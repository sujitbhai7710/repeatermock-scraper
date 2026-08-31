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
import os
import sys
import time
from pathlib import Path
from typing import Any

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
    "https://repeatermock.com/tb/test-series/ssc-cgl",
    "https://repeatermock.com/tb-pro/test-series/ssc-cgl",
    "https://repeatermock.com/tb/test-series/ssc-maths-previous-year-questions",
    "https://repeatermock.com/tb-pro/test-series/ssc-maths-previous-year-questions",
    "https://repeatermock.com/tb/test-series/ssc-chsl",
    "https://repeatermock.com/gd/test-series/ssc-cgl",
    "https://repeatermock.com/tb-pro/test-series/ssc-english-previous-year-questions",
    "https://repeatermock.com/tb/test-series/ssc-english-previous-year-questions",
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

    # Load cookies — try cached first, then env vars (multiple accounts)
    import os
    cookie_sets = []
    
    # Try cached cookies first (from previous run)
    if COOKIES_FILE.exists():
        try:
            cached = json.loads(COOKIES_FILE.read_text())
            if cached.get("cookies"):
                cookie_sets.append(cached["cookies"])
                print(f"  Found cached cookies ({len(cached['cookies'])} cookies)")
        except:
            pass
    
    # Try env var cookies (from GitHub secrets)
    for env_var in ["REPEATERMOCK_COOKIES_JSON", "REPEATERMOCK_COOKIES_JSON_1", "REPEATERMOCK_COOKIES_JSON_2"]:
        raw = os.environ.get(env_var, "")
        if raw:
            try:
                cookies_env = json.loads(raw)
                if cookies_env and len(cookies_env) > 0:
                    cookie_sets.append(cookies_env)
                    print(f"  Found {env_var} ({len(cookies_env)} cookies)")
            except:
                pass
    
    # Also try .env file and cookie_accounts.json
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except:
        pass
    
    # Read from cookie_accounts.json (written by GitHub Actions)
    accounts_file = Path(__file__).parent.parent / "data" / "cookie_accounts.json"
    if accounts_file.exists():
        try:
            accounts = json.loads(accounts_file.read_text())
            for key, val in accounts.items():
                try:
                    cookies_env = json.loads(val)
                    if cookies_env and len(cookies_env) > 0:
                        if not any(c[0].get("value") == cookies_env[0].get("value") for c in cookie_sets if c):
                            cookie_sets.append(cookies_env)
                            print(f"  Found {key} from cookie_accounts.json ({len(cookies_env)} cookies)")
                except:
                    pass
        except:
            pass
    
    # Also check env vars directly
    for env_var in ["REPEATERMOCK_COOKIES_JSON", "REPEATERMOCK_COOKIES_JSON_1", "REPEATERMOCK_COOKIES_JSON_2"]:
        raw = os.environ.get(env_var, "")
        if raw:
            try:
                cookies_env = json.loads(raw)
                if cookies_env and len(cookies_env) > 0:
                    if not any(c[0].get("value") == cookies_env[0].get("value") for c in cookie_sets if c):
                        cookie_sets.append(cookies_env)
                        print(f"  Found {env_var} from env ({len(cookies_env)} cookies)")
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
            
            result = await refresh_cookies_if_needed(context, page)
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
                    result = await scrape_test_full(context, test, variant, slug)
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
