"""
Targeted test: verify that PLAIN PLAYWRIGHT COOKIES (no login during scraping)
can fully scrape tests from https://repeatermock.com/tb-pro/test-series/ssc-cgl
— questions + submit + solutions + analysis.

Flow: mint cookies (disk files, else CDP re-login via real Chrome) → then scrape
using ONLY those cookies in a plain browser context.

    python scripts/test_tbpro_cgl.py [num_tests]
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.scraper import (
    create_browser_session, fetch_series_details, fetch_all_tests_for_series,
    refresh_cookies_if_needed,
)
from src.full_scraper import scrape_test_full
from src.auto_login import cdp_relogin

SERIES_URL = "https://repeatermock.com/tb-pro/test-series/ssc-cgl"
VARIANT, SLUG = "tb-pro", "ssc-cgl"
ROOT = Path(__file__).parent.parent


async def get_working_session():
    """Mint FRESH cookies via CDP (real Chrome) first — freshest possible.
    Falls back to account files if Chrome isn't running.
    Returns (playwright, browser, context, page, cookies, source) or None."""
    print("  Minting fresh cookies via CDP (real Chrome)...")
    fresh = await cdp_relogin()
    if fresh:
        p, browser, context = await create_browser_session(fresh)
        page = await context.new_page()
        check = await refresh_cookies_if_needed(context, page, original_cookies=fresh)
        if check is not None:
            print("  ✓ Fresh CDP cookies authenticated")
            return p, browser, context, page, check, "CDP"

    cookies_dir = ROOT / "cookies"
    for f in sorted(cookies_dir.glob("account*.json")):
        try:
            cookies = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        print(f"  Trying {f.name}...")
        p, browser, context = await create_browser_session(cookies)
        page = await context.new_page()
        result = await refresh_cookies_if_needed(context, page, original_cookies=cookies)
        if result is not None:
            print(f"  ✓ {f.name} authenticated")
            return p, browser, context, page, result, f.name
        print(f"  ✗ {f.name} dead")
        try:
            await browser.close()
            await p.stop()
        except Exception:
            pass
    return None


async def main(num_tests: int):
    print("=" * 60)
    print(f"TEST: plain-cookie scrape of {SERIES_URL}")
    print("=" * 60)

    session = await get_working_session()
    if not session:
        print("\n✗ RESULT: FAILED — no working session (run scripts\\start_scrape_chrome.bat)")
        return 1
    p, browser, context, page, cookies, source = session

    # Fetch the target series
    details = await fetch_series_details(context, SLUG, VARIANT, "v1")
    tests = await fetch_all_tests_for_series(context, details, VARIANT, "v1")
    name = details.get("name", "")
    print(f"\n  Series: {name} — {len(tests)} tests total")

    # Skip already-scraped (from progress.json)
    scraped = set()
    pf = ROOT / "data" / "progress.json"
    if pf.exists():
        scraped = set(json.loads(pf.read_text(encoding="utf-8")).get("scraped_test_ids", []))
    pending = [t for t in tests if t["id"] not in scraped][:num_tests]
    print(f"  Testing {len(pending)} pending tests with PLAIN COOKIES only...\n")

    full = 0
    for t in pending:
        r = await scrape_test_full(context, page, t, VARIANT, SLUG, original_cookies=cookies)
        if r and r.get("questions") and r.get("has_answers") and r.get("has_analysis"):
            full += 1
            print(f"  → ✓ FULL (Q+A+Sol+Ana): {t.get('title', '')[:55]}\n")
        else:
            print(f"  → ✗ INCOMPLETE: {t.get('title', '')[:55]}\n")

    try:
        await browser.close()
        await p.stop()
    except Exception:
        pass

    print("=" * 60)
    print(f"RESULT: {full}/{len(pending)} tests FULLY scraped with plain Playwright cookies")
    print(f"(login source: {source} — used only to MINT cookies, not during scraping)")
    print("=" * 60)
    return 0 if full == len(pending) else 1


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    raise SystemExit(asyncio.run(main(n)))
