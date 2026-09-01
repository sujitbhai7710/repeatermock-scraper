"""
One-time setup for Google auto-login (for Google-sign-in-only accounts).

Opens a real browser window with a dedicated profile. You log in to
repeatermock.com via Google ONCE — the Google session is saved inside
browser_profile/ so the scraper can re-login automatically, forever.

    python scripts/setup_google_login.py
"""
import asyncio
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.auto_login import (  # noqa: E402
    _cookie_dicts_from,
    _launch_profile_context,
    google_profile_exists,
    GOOGLE_PROFILE_DIR,
)


async def main():
    print("=" * 60)
    print("GOOGLE LOGIN SETUP — one time only")
    print("=" * 60)
    if google_profile_exists():
        print("Profile already exists — running again lets you re-login if")
        print("the saved Google session ever expires.")
    print(f"\nA browser window will open. Log in to repeatermock.com with Google")
    print(f"(complete TOTP etc.). This script saves the session into:")
    print(f"  {GOOGLE_PROFILE_DIR}")
    input("\nPress Enter to open the browser...")

    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    try:
        context = await _launch_profile_context(pw, headless=False)
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto("https://repeatermock.com/login", wait_until="domcontentloaded")
        print("\n⏳ Waiting for you to complete the Google login (up to 5 minutes)...")
        print("   The script finishes automatically once you're logged in.\n")

        deadline = time.time() + 300
        result = None
        while time.time() < deadline:
            cookies = await context.cookies()
            result = _cookie_dicts_from(cookies)
            if result:
                break
            await asyncio.sleep(2)

        if not result:
            print("✗ Timed out — login wasn't completed in 5 minutes. Run again.")
            return 1

        out = Path(__file__).parent.parent / "cookies" / "account4.json"
        out.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n✓ SUCCESS! Google session saved in browser_profile/")
        print(f"✓ Fresh cookies saved to cookies/account4.json")
        print(f"  (account used: {next((c['value'][:40] for c in result if c['name'] == 'accessToken'), '?')}...)")
        print("\nThe scraper can now auto-login via Google whenever tokens die.")
        print("Start scraping:  python -m src.incremental_scrape")
        return 0
    finally:
        try:
            await context.close()
        except Exception:
            pass
        try:
            await pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()) or 0)
