"""Download ALL JS bundles from a RepeaterMock page to find the submit payload format."""
import asyncio, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")
from src.cookie_manager import load_cookies, save_cookies
from src.scraper import create_browser_session, refresh_cookies_if_needed, COOKIES_FILE

OUT = Path(__file__).parent.parent / "data" / "all_js"
OUT.mkdir(parents=True, exist_ok=True)

async def main():
    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()
    
    js_urls = set()
    async def on_resp(resp):
        if "javascript" in resp.headers.get("content-type", "") and "repeatermock.com" in resp.url:
            js_urls.add(resp.url)
    page.on("response", on_resp)
    
    try:
        cookies = await refresh_cookies_if_needed(context, page)
        if cookies is None:
            print("✗ Auth failed", flush=True)
            return
        
        # Visit a test page to trigger all JS loading
        test_id = "6a0f3ef125f9d428c136a83a"
        print(f"Visiting /attempt page to collect JS URLs...", flush=True)
        try:
            await page.goto(f"https://repeatermock.com/tb/test-series/ssc-cgl/test/{test_id}/attempt",
                          timeout=15000, wait_until="domcontentloaded")
        except: pass
        await asyncio.sleep(5)
        
        print(f"Found {len(js_urls)} JS URLs", flush=True)
        
        # Download each JS file
        for url in sorted(js_urls):
            try:
                resp = await context.request.get(url)
                body = await resp.text()
                fname = url.split("/")[-1].split("?")[0]
                if not fname.endswith(".js"): fname += ".js"
                (OUT / fname).write_text(body, encoding="utf-8")
                print(f"  [{resp.status}] {fname} ({len(body)} bytes)", flush=True)
            except Exception as e:
                print(f"  ERROR {url}: {e}", flush=True)
        
        # Now search ALL downloaded JS for the submit payload
        print(f"\n=== Searching all JS for submit payload ===", flush=True)
        import re
        all_content = ""
        for f in OUT.glob("*.js"):
            all_content += f.read_text() + "\n"
        
        # Search for payload construction near "enqueueSubmit" or "submit"
        for pat in [
            r'enqueueSubmit\([^)]{0,500}',
            r'payload\s*[:=]\s*\{[^}]{0,500}testId[^}]{0,500}\}',
            r'\{[^{}]*answers[^{}]*timeTaken[^{}]*\}',
            r'\{[^{}]*testId[^{}]*answers[^{}]*\}',
            r'JSON\.stringify\(\{[^}]{0,300}\}',
        ]:
            matches = re.findall(pat, all_content)
            if matches:
                print(f"\n  Pattern '{pat[:50]}': {len(matches)} matches")
                for m in matches[:3]:
                    print(f"    {m[:300]}")
        
    finally:
        save_cookies(await context.cookies(), COOKIES_FILE)
        await browser.close()
        await p.stop()

asyncio.run(main())
