"""
Download images from cdn.repeatermock.com and save them locally.
Replaces cdn.repeatermock.com URLs in scraped JSON with local paths.

Images are organized by: frontend/img/{series_slug}/{test_id}/{hash}.png
"""
import asyncio
import hashlib
import json
import re
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))


CDN_BASE = "https://cdn.repeatermock.com"
IMG_DIR = Path(__file__).parent.parent / "frontend" / "img"


def find_all_images(data: Any) -> list[str]:
    """Recursively find all cdn.repeatermock.com image URLs in a data structure."""
    urls = set()
    
    if isinstance(data, str):
        for m in re.finditer(r'https://cdn\.repeatermock\.com/[^"\'<>\s]+', data):
            urls.add(m.group(0))
    elif isinstance(data, dict):
        for v in data.values():
            urls.update(find_all_images(v))
    elif isinstance(data, list):
        for item in data:
            urls.update(find_all_images(item))
    
    return list(urls)


def get_image_filename(url: str) -> str:
    """Get the filename from a CDN URL."""
    # URL format: https://cdn.repeatermock.com/tb/{hash}.png
    return url.split("/")[-1]


async def download_image(context, url: str, save_path: Path) -> bool:
    """Download a single image."""
    try:
        resp = await context.request.get(url, headers={
            "Accept": "image/*",
            "Referer": "https://repeatermock.com/",
        })
        if resp.status == 200:
            body = await resp.body()
            save_path.parent.mkdir(parents=True, exist_ok=True)
            save_path.write_bytes(body)
            return True
    except Exception as e:
        print(f"    Error downloading {url}: {e}", flush=True)
    return False


def replace_cdn_urls(data: Any, series_slug: str, test_id: str) -> Any:
    """Replace cdn.repeatermock.com URLs with local paths in a data structure."""
    local_prefix = f"/img/{series_slug}/{test_id}"
    
    if isinstance(data, str):
        def replacer(m):
            url = m.group(0)
            filename = get_image_filename(url)
            return f"{local_prefix}/{filename}"
        return re.sub(r'https://cdn\.repeatermock\.com/[^"\'<>\s]+', replacer, data)
    elif isinstance(data, dict):
        return {k: replace_cdn_urls(v, series_slug, test_id) for k, v in data.items()}
    elif isinstance(data, list):
        return [replace_cdn_urls(item, series_slug, test_id) for item in data]
    return data


async def download_images_for_test(context, test_data: dict, series_slug: str) -> dict:
    """
    Download all images for a test and replace CDN URLs with local paths.
    
    Returns the updated test_data with local image paths.
    """
    test_id = test_data.get("test_id", "unknown")
    
    # Find all image URLs
    image_urls = find_all_images(test_data)
    if not image_urls:
        return test_data
    
    print(f"    Found {len(image_urls)} images to download", flush=True)
    
    # Download each image
    downloaded = 0
    test_img_dir = IMG_DIR / series_slug / test_id
    
    for url in image_urls:
        filename = get_image_filename(url)
        save_path = test_img_dir / filename
        
        if save_path.exists():
            downloaded += 1
            continue
        
        success = await download_image(context, url, save_path)
        if success:
            downloaded += 1
    
    print(f"    ✓ Downloaded {downloaded}/{len(image_urls)} images", flush=True)
    
    # Replace CDN URLs with local paths in the test data
    updated_data = replace_cdn_urls(test_data, series_slug, test_id)
    
    return updated_data


if __name__ == "__main__":
    # Test with an existing scraped test
    import sys
    sys.path.insert(0, str(Path(__file__).parent.parent))
    from src.cookie_manager import load_cookies, save_cookies
    from src.scraper import create_browser_session, refresh_cookies_if_needed, COOKIES_FILE, TESTS_DIR
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    
    async def main():
        test_file = TESTS_DIR / "6a0f3f2c0b97114ca22cf188.json"
        if not test_file.exists():
            print("Test file not found")
            return
        
        test_data = json.loads(test_file.read_text())
        
        cookies = load_cookies(COOKIES_FILE)
        p, browser, context = await create_browser_session(cookies)
        page = await context.new_page()
        
        try:
            cookies = await refresh_cookies_if_needed(context, page)
            if cookies is None:
                print("Auth failed")
                return
            
            updated = await download_images_for_test(context, test_data, "ssc-cgl")
            
            # Save updated test data
            test_file.write_text(json.dumps(updated, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"✓ Updated test file with local image paths")
            
        finally:
            save_cookies(await context.cookies(), COOKIES_FILE)
            await browser.close()
            await p.stop()
    
    asyncio.run(main())
