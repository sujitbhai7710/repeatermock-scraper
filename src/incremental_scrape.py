"""
Incremental scraper — scrapes tests across multiple series with:
- Progress tracking (data/progress.json)
- Time limit (stops at 50 minutes, saves state)
- Cookie auto-refresh + persistence
- Caches test lists so Phase 1 is instant on subsequent runs
- Interleaves listing + scraping (scrapes as soon as first series is fetched)

Usage:
    python -m src.incremental_scrape [--time-limit-minutes 50] [--max-tests 0]
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Configure logging to stdout (critical for CI debugging)
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%H:%M:%S',
    stream=sys.stdout,
)

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.cookie_manager import load_cookies, save_cookies
from src.full_scraper import scrape_test_full
from src.image_downloader import download_images_for_test
from src.scraper import (
    create_browser_session,
    refresh_cookies_if_needed,
    fetch_series_details,
    fetch_all_tests_for_series,
    scrape_test,
    parse_series_url,
    COOKIES_FILE,
    TESTS_DIR,
    SERIES_DIR,
)

# ─── Config ────────────────────────────────────────────────────────────────

PROGRESS_FILE = Path(__file__).parent.parent / "data" / "progress.json"
DEFAULT_TIME_LIMIT_MINUTES = 50
DEFAULT_RATE_LIMIT_SECONDS = 2

ALL_SERIES_URLS = [
    "https://repeatermock.com/tb/test-series/bank-of-baroda-lbo",
    "https://repeatermock.com/tb/test-series/bssc-cgl",
    "https://repeatermock.com/tb/test-series/bssc-inter-level",
    "https://repeatermock.com/tb/test-series/cbi-zbo",
    "https://repeatermock.com/tb/test-series/cds-previous",
    "https://repeatermock.com/tb/test-series/cisf-head-constable",
    "https://repeatermock.com/tb/test-series/general-knowledge-ssc-railways-competitive-exams",
    "https://repeatermock.com/tb/test-series/general-science",
    "https://repeatermock.com/tb/test-series/ibps-clerk",
    "https://repeatermock.com/tb/test-series/ibps-clerk-previous",
    "https://repeatermock.com/tb/test-series/ibps-po",
    "https://repeatermock.com/tb/test-series/ibps-rrb-clerk",
    "https://repeatermock.com/tb/test-series/ibps-rrb-hindi",
    "https://repeatermock.com/tb/test-series/ibps-rrb-office-assistant",
    "https://repeatermock.com/tb/test-series/ibps-rrb-po",
    "https://repeatermock.com/tb/test-series/ibps-rrb-po-previous",
    "https://repeatermock.com/tb/test-series/ibps-so",
    "https://repeatermock.com/tb/test-series/indian-army-gd",
    "https://repeatermock.com/tb/test-series/iob-lbo",
    "https://repeatermock.com/tb/test-series/jammu-and-kashmir-panchayat-secretary",
    "https://repeatermock.com/tb/test-series/jammu-and-kashmir-patwari",
    "https://repeatermock.com/tb/test-series/jammu-and-kashmir-si",
    "https://repeatermock.com/tb/test-series/jk-bank",
    "https://repeatermock.com/tb/test-series/karnataka-bank",
    "https://repeatermock.com/tb/test-series/lic-hfl",
    "https://repeatermock.com/tb/test-series/mp-police-si",
    "https://repeatermock.com/tb/test-series/nabard-develop-assistant",
    "https://repeatermock.com/tb/test-series/nabard-grade-a",
    "https://repeatermock.com/tb/test-series/oicl-ao",
    "https://repeatermock.com/tb/test-series/psb-lbo",
    "https://repeatermock.com/tb/test-series/rajasthan-police-si",
    "https://repeatermock.com/tb/test-series/rpf-constable",
    "https://repeatermock.com/tb/test-series/rrb-alp",
    "https://repeatermock.com/tb/test-series/rrb-alp-previous",
    "https://repeatermock.com/tb/test-series/rrb-general-science-previous-year-questions",
    "https://repeatermock.com/tb/test-series/rrb-gk-previous-year-questions",
    "https://repeatermock.com/tb/test-series/rrb-group-d",
    "https://repeatermock.com/tb/test-series/rrb-je-previous",
    "https://repeatermock.com/tb/test-series/rrb-junior-translator",
    "https://repeatermock.com/tb/test-series/rrb-maths-previous-year-questions",
    "https://repeatermock.com/tb/test-series/rrb-ntpc",
    "https://repeatermock.com/tb/test-series/rrb-ntpc-memory-based",
    "https://repeatermock.com/tb/test-series/rrb-ntpc-ug",
    "https://repeatermock.com/tb/test-series/rrb-reasoning-previous-year-questions",
    "https://repeatermock.com/tb/test-series/rrb-section-controller",
    "https://repeatermock.com/tb/test-series/rrb-technician-previous",
    "https://repeatermock.com/tb/test-series/sbi-apprentice",
    "https://repeatermock.com/tb/test-series/sbi-clerk",
    "https://repeatermock.com/tb/test-series/sbi-po",
    "https://repeatermock.com/tb/test-series/ssc-cgl",
    "https://repeatermock.com/tb/test-series/ssc-cgl-exam",
    "https://repeatermock.com/tb/test-series/ssc-cgl-previous-year-paper",
    "https://repeatermock.com/tb/test-series/ssc-cpo",
    "https://repeatermock.com/tb/test-series/ssc-english-previous-year-questions",
    "https://repeatermock.com/tb/test-series/ssc-maths-previous-year-questions",
    "https://repeatermock.com/tb/test-series/ssc-mts",
    "https://repeatermock.com/tb/test-series/ssc-railways-current-affairs",
    "https://repeatermock.com/tb/test-series/ssc-railways-polity",
    "https://repeatermock.com/tb/test-series/ssc-railways-reasoning",
    "https://repeatermock.com/tb/test-series/ssc-reasoning-previous-year-questions",
    "https://repeatermock.com/tb/test-series/ssc-selection-post",
    "https://repeatermock.com/tb/test-series/static-gk",
    "https://repeatermock.com/tb/test-series/ugc-net-set-jrf-previous-year-papers",
    "https://repeatermock.com/tb/test-series/union-bank-of-india-apprentice",
    "https://repeatermock.com/tb/test-series/up-lekhpal",
    "https://repeatermock.com/tb/test-series/up-police-constable",
]


# ─── Progress tracking ─────────────────────────────────────────────────────

def load_progress() -> dict[str, Any]:
    if PROGRESS_FILE.exists():
        return json.loads(PROGRESS_FILE.read_text())
    return {
        "scraped_test_ids": [],
        "failed_test_ids": [],
        "series_cache": {},      # Cached test lists: {series_url: {tests: [...], fetched_at: ts}}
        "series_progress": {},
        "last_run_start": None,
        "last_run_end": None,
        "total_scraped": 0,
        "run_history": [],
    }


def save_progress(progress: dict[str, Any]):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2, ensure_ascii=False))


# ─── Main ──────────────────────────────────────────────────────────────────

async def run_incremental_scrape(
    time_limit_minutes: int = DEFAULT_TIME_LIMIT_MINUTES,
    max_tests: int = 0,
):
    start_time = time.time()
    time_limit_seconds = time_limit_minutes * 60
    progress = load_progress()
    scraped_ids = set(progress["scraped_test_ids"])
    failed_ids = set(progress["failed_test_ids"])
    series_cache = progress.get("series_cache", {})

    print(f"\n{'='*60}")
    print(f"INCREMENTAL SCRAPE RUN")
    print(f"{'='*60}")
    print(f"  Time limit: {time_limit_minutes} minutes")
    print(f"  Max tests this run: {max_tests if max_tests > 0 else 'unlimited'}")
    print(f"  Previously scraped: {len(scraped_ids)} tests")
    print(f"  Start time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    # Load cookies from cookies/ directory (JSON files committed to repo)
    import os
    cookie_sets = []
    cookies_dir = Path(__file__).parent.parent / "cookies"
    
    # Read all account*.json files from cookies/ directory
    if cookies_dir.exists():
        for cookie_file in sorted(cookies_dir.glob("account*.json")):
            try:
                account_cookies = json.loads(cookie_file.read_text())
                if account_cookies and len(account_cookies) > 0:
                    cookie_sets.append(account_cookies)
                    has_refresh = any(c["name"] == "refreshToken" for c in account_cookies)
                    print(f"  Found {cookie_file.name} ({len(account_cookies)} cookies, has refreshToken: {has_refresh})")
            except Exception as e:
                print(f"  Error reading {cookie_file.name}: {e}")
    
    # Also try cached cookies from previous run (data/cookies.json)
    if COOKIES_FILE.exists():
        try:
            cached = json.loads(COOKIES_FILE.read_text())
            if cached.get("cookies"):
                # Only add if not already in cookie_sets
                if not any(cs[0].get("value") == cached["cookies"][0].get("value") for cs in cookie_sets if cs):
                    cookie_sets.append(cached["cookies"])
                    print(f"  Found cached cookies ({len(cached['cookies'])} cookies)")
        except:
            pass

    if not cookie_sets:
        print("✗ No cookies found anywhere. Exiting.")
        return

    print(f"  Total cookie sets to try: {len(cookie_sets)}")

    # Try each cookie set until one works
    p = browser = context = page = None
    authed = False
    
    for i, cookies in enumerate(cookie_sets):
        print(f"\n  Trying cookie set {i+1}/{len(cookie_sets)}...")
        try:
            if p:
                await browser.close()
                await p.stop()
            p, browser, context = await create_browser_session(cookies)
            page = await context.new_page()
            
            result = await refresh_cookies_if_needed(context, page, original_cookies=cookies)
            if result is not None:
                print(f"  ✓ Cookie set {i+1} authenticated!")
                authed = True
                break
            else:
                print(f"  ✗ Cookie set {i+1} failed")
        except Exception as e:
            print(f"  ✗ Cookie set {i+1} error: {e}")
            if p:
                try:
                    await browser.close()
                    await p.stop()
                except:
                    pass
                p = None

    if not authed:
        print("\n✗ All cookie sets failed. Exiting gracefully.")
        print("  Update GitHub secrets with fresh cookies.")
        return

    tests_scraped_this_run = 0
    questions_scraped_this_run = 0

    try:
        # Process each series — interleave listing + scraping
        for series_url in ALL_SERIES_URLS:
            # Check time limit
            elapsed = time.time() - start_time
            if elapsed >= time_limit_seconds:
                print(f"\n  ⏰ Time limit reached ({elapsed/60:.1f} min)")
                break

            config = parse_series_url(series_url)
            variant = config["variant"]
            slug = config["slug"]
            api_version = config["api_version"]

            # Get cached test list or fetch fresh
            cached = series_cache.get(series_url)
            cache_age = time.time() - cached.get("fetched_at", 0) if cached else float('inf')

            if cached and cache_age < 3600:  # Cache for 1 hour
                all_tests = cached["tests"]
                series_name = cached.get("name", "")
                print(f"\n  [{series_name[:50]}] Using cached test list ({len(all_tests)} tests, {cache_age/60:.0f} min old)")
            else:
                print(f"\n  Fetching test list: {series_url}")
                try:
                    details = await fetch_series_details(context, slug, variant, api_version)
                    series_name = details.get("name", "")
                    all_tests = await fetch_all_tests_for_series(context, details, variant, api_version)

                    # Cache it
                    series_cache[series_url] = {
                        "name": series_name,
                        "tests": all_tests,
                        "fetched_at": time.time(),
                    }
                    progress["series_cache"] = series_cache
                    save_progress(progress)

                    print(f"  ✓ [{series_name[:50]}] {len(all_tests)} tests fetched")
                except Exception as e:
                    print(f"  ✗ Error fetching {series_url}: {e}")
                    continue

            # Filter to pending
            pending = [t for t in all_tests if t["id"] not in scraped_ids and t["id"] not in failed_ids]
            total = len(all_tests)
            already_scraped = len([t for t in all_tests if t["id"] in scraped_ids])

            progress["series_progress"][series_url] = {
                "name": series_name,
                "total": total,
                "scraped": already_scraped,
                "pending": len(pending),
            }

            if not pending:
                print(f"  ✓ All {total} tests already scraped — skipping")
                continue

            print(f"  Scraping {len(pending)} pending tests ({already_scraped}/{total} done)...")

            # Scrape pending tests in this series
            for i, test in enumerate(pending):
                # Check time limit
                elapsed = time.time() - start_time
                if elapsed >= time_limit_seconds:
                    print(f"\n  ⏰ Time limit reached ({elapsed/60:.1f} min)")
                    break

                if max_tests > 0 and tests_scraped_this_run >= max_tests:
                    print(f"\n  Max tests limit reached ({max_tests})")
                    break

                # Refresh cookies every 20 tests
                if tests_scraped_this_run > 0 and tests_scraped_this_run % 20 == 0:
                    print(f"\n  Refreshing cookies ({tests_scraped_this_run} tests done)...")
                    cookies = await refresh_cookies_if_needed(context, page)
                    if cookies:
                        save_cookies(cookies, COOKIES_FILE)
                    else:
                        print("\n  ⚠ Cookie refresh failed — continuing with existing cookies")

                time_remaining = time_limit_seconds - elapsed
                mins_left = int(time_remaining / 60)

                test_id = test["id"]
                test_title = test.get("title", "Unknown")[:60]
                print(f"  [{tests_scraped_this_run+1}] ({mins_left}m left) {test_title}")

                try:
                    result = await scrape_test_full(context, page, test, variant, slug)
                    if result:
                        # Download images and replace CDN URLs with local paths
                        result = await download_images_for_test(context, result, slug)
                        # Re-save with local image paths
                        out_file = TESTS_DIR / f"{test_id}.json"
                        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
                        tests_scraped_this_run += 1
                        questions_scraped_this_run += len(result.get("questions", []))
                        scraped_ids.add(test_id)
                        progress["scraped_test_ids"] = list(scraped_ids)
                    else:
                        failed_ids.add(test_id)
                        progress["failed_test_ids"] = list(failed_ids)
                except Exception as e:
                    print(f"    ✗ Error: {e}")
                    failed_ids.add(test_id)
                    progress["failed_test_ids"] = list(failed_ids)

                # Save progress after each test
                progress["total_scraped"] = len(scraped_ids)
                save_progress(progress)

                await asyncio.sleep(DEFAULT_RATE_LIMIT_SECONDS)

            # Check if we hit time limit
            elapsed = time.time() - start_time
            if elapsed >= time_limit_seconds:
                break

        # Summary
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"RUN SUMMARY")
        print(f"{'='*60}")
        print(f"  Tests scraped this run: {tests_scraped_this_run}")
        print(f"  Questions scraped this run: {questions_scraped_this_run}")
        print(f"  Time elapsed: {elapsed/60:.1f} minutes")
        print(f"  Total scraped (all runs): {len(scraped_ids)}")
        print(f"  Total failed: {len(failed_ids)}")
        print(f"\n  Series progress:")
        for url, sp in progress["series_progress"].items():
            print(f"    {sp['name'][:40]}: {sp['scraped']}/{sp['total']} scraped, {sp['pending']} pending")

    finally:
        progress["last_run_end"] = time.time()
        progress["run_history"].append({
            "start": start_time,
            "end": progress["last_run_end"],
            "tests_scraped": tests_scraped_this_run,
            "questions_scraped": questions_scraped_this_run,
            "time_minutes": (progress["last_run_end"] - start_time) / 60,
        })
        progress["run_history"] = progress["run_history"][-20:]
        save_progress(progress)

        final_cookies = await context.cookies()
        save_cookies(final_cookies, COOKIES_FILE)

        await browser.close()
        await p.stop()

    print(f"\n✓ Run complete. Progress saved.")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Incremental RepeaterMock scraper")
    parser.add_argument("--time-limit-minutes", type=int, default=DEFAULT_TIME_LIMIT_MINUTES)
    parser.add_argument("--max-tests", type=int, default=0)
    args = parser.parse_args()
    asyncio.run(run_incremental_scrape(args.time_limit_minutes, args.max_tests))


if __name__ == "__main__":
    main()
