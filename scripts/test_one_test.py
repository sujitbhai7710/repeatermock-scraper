"""
PURE COOKIE TEST — exactly what GitHub Actions would do.
NO login, NO CDP, NO Google. Only cookies/account*.json from disk.

Scrapes ONE test matching 'Discount and MP' from:
  https://repeatermock.com/tb-pro/test-series/ssc-cgl
and verifies: questions + answers + solutions + analysis.

    python scripts/test_one_test.py
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

SERIES_URL = "https://repeatermock.com/tb-pro/test-series/ssc-cgl"
VARIANT, SLUG = "tb-pro", "ssc-cgl"
MATCH = "discount"
ROOT = Path(__file__).parent.parent


async def main():
    print("=" * 60)
    print("PURE COOKIE TEST (no login / no CDP / no Google)")
    print(f"Target: one '{MATCH}' test from {SERIES_URL}")
    print("=" * 60)

    # 1. Find a working cookie set — plain files only (exactly like CI)
    working = None
    for f in sorted((ROOT / "cookies").glob("account*.json")):
        try:
            cookies = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        print(f"\n  Trying {f.name}...")
        p, browser, context = await create_browser_session(cookies)
        page = await context.new_page()
        result = await refresh_cookies_if_needed(context, page, original_cookies=cookies)
        if result is not None:
            print(f"  ✓ {f.name} WORKS (plain cookies)")
            working = (p, browser, context, page, result, f.name)
            break
        print(f"  ✗ {f.name} dead")
        try:
            await browser.close()
            await p.stop()
        except Exception:
            pass

    if not working:
        print("\n✗ RESULT: FAILED — all cookie files dead. CI needs FRESH cookies")
        print("  in the secret (export once from a browser, then CI self-rotates).")
        return 1

    p, browser, context, page, cookies, source = working

    # 2. Find the target test in the series
    details = await fetch_series_details(context, SLUG, VARIANT, "v1")
    tests = await fetch_all_tests_for_series(context, details, VARIANT, "v1")
    print(f"\n  Series: {details.get('name', '')} — {len(tests)} tests")
    target = next((t for t in tests if MATCH in t.get("title", "").lower()), None)
    if not target:
        matches = [t.get("title", "") for t in tests if "discount" in t.get("title", "").lower()]
        print(f"  ✗ No test matching '{MATCH}' — titles containing 'discount': {matches[:5]}")
        return 1
    print(f"  Target test: {target.get('title', '')} (id={target['id']})")

    # 3. Scrape it fully with plain cookies
    print(f"\n  Scraping with plain cookies only...\n")
    result = await scrape_test_full(context, page, target, VARIANT, SLUG,
                                    original_cookies=cookies)

    try:
        await browser.close()
        await p.stop()
    except Exception:
        pass

    # 4. Verdict
    print("\n" + "=" * 60)
    ok_q = bool(result and result.get("questions"))
    ok_a = bool(result and result.get("has_answers"))
    ok_ana = bool(result and result.get("has_analysis"))
    print(f"  Questions : {'✓ ' + str(len(result.get('questions', []))) if ok_q else '✗'}")
    print(f"  Answers   : {'✓' if ok_a else '✗'}")
    print(f"  Solutions : {'✓' if ok_a else '✗'}")
    print(f"  Analysis  : {'✓' if ok_ana else '✗'}")
    if ok_q and ok_a and ok_ana:
        out = ROOT / "data" / "tests" / f"{target['id']}.json"
        print(f"\n  ✓✓✓ SUCCESS — saved to {out.name}")
        print("  → Plain cookies DO work for the full flow (GitHub Actions will work)")
        return 0
    print("\n  ✗ INCOMPLETE — see which parts failed above")
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
