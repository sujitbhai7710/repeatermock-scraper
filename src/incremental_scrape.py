"""
Incremental scraper — scrapes tests across the 52 target series with:
- Granular per-test progress (scraped / partial / failed)
- Proactive access-token refresh (every 5 tests, not 20)
- Immediate refresh + retry on 401 from submit
- Cookie rotation persisted to cookies/account*.json
- Per-test status tracking with failure reason

Usage:
    python -m src.incremental_scrape [--time-limit-minutes 45] [--max-tests 0]
"""
import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

# Never let a print() crash the scraper: force UTF-8 on stdout/stderr with
# "replace" so Unicode symbols (✓ ✗ →) survive any console or redirect.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Configure logging to stdout (critical for CI debugging)
logging.basicConfig(
    level=logging.INFO,
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
    force_refresh_cookies,
    fetch_series_details,
    fetch_all_tests_for_series,
    parse_series_url,
    COOKIES_FILE,
    TESTS_DIR,
    SERIES_DIR,
)
from src.series_config import TARGET_SERIES, get_all_series_urls, get_series_metadata

# ─── Config ────────────────────────────────────────────────────────────────

PROGRESS_FILE = Path(__file__).parent.parent / "data" / "progress.json"
DEFAULT_TIME_LIMIT_MINUTES = 0  # 0 = no time limit (run until all tests scraped)
DEFAULT_RATE_LIMIT_SECONDS = 1
# Access tokens last ~15 min. Refresh after 12 min of use (time-based, not
# test-count-based). Fewer rotations = safer, because the refresh token is
# SINGLE-USE and rotates on every /auth/refresh — every extra rotation is a
# chance to lose the chain if anything else touches the account.
REFRESH_AFTER_SECONDS = 12 * 60


# ─── Progress tracking (granular) ──────────────────────────────────────────

def load_progress() -> dict[str, Any]:
    if PROGRESS_FILE.exists():
        p = json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        # Migrate old format if needed
        if "tests_status" not in p:
            p["tests_status"] = {}
        if "partial_test_ids" not in p:
            p["partial_test_ids"] = []
        return p
    return {
        "scraped_test_ids": [],         # fully scraped (questions + answers + solutions + analysis)
        "partial_test_ids": [],         # questions only (no answers/solutions)
        "failed_test_ids": [],          # couldn't fetch even questions
        "tests_status": {},             # test_id → {status, has_questions, has_answers, has_solutions, has_analysis, has_images, error, last_attempted_at}
        "series_cache": {},             # {series_url: {name, tests, fetched_at}}
        "series_progress": {},          # {series_url: {name, total, scraped, partial, failed, pending}}
        "last_run_start": None,
        "last_run_end": None,
        "total_scraped": 0,
        "run_history": [],
    }


def save_progress(progress: dict[str, Any]):
    PROGRESS_FILE.parent.mkdir(parents=True, exist_ok=True)
    PROGRESS_FILE.write_text(json.dumps(progress, indent=2, ensure_ascii=False), encoding="utf-8")


def load_d1_env() -> dict | None:
    """Load Cloudflare creds from environment or .env. Returns None if token missing."""
    env = dict(os.environ)
    env_file = Path(__file__).parent.parent / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if not env.get("CLOUDFLARE_API_TOKEN"):
        return None
    return env


def sync_d1_if_configured(progress: dict[str, Any] | None = None,
                          only_test_ids: set | None = None) -> bool:
    """Push data/progress.json to Cloudflare D1 (the dashboard's database).

    Non-fatal: never raises. Returns True if the sync succeeded.
    only_test_ids: if given, only sync those tests (cheap incremental sync);
    None = sync everything.
    """
    env = load_d1_env()
    if env is None:
        print("\n  ⚠ D1 sync skipped — CLOUDFLARE_API_TOKEN not set in .env")
        print("    (local progress is saved in data/progress.json; to mirror it to the")
        print("     Cloudflare D1 dashboard, add a D1-capable API token to .env)")
        return False

    if progress is None:
        progress = load_progress()

    try:
        from src.update_d1 import sync_series_table, sync_tests_table, sync_runs_table
        scope = f"{len(only_test_ids)} changed tests" if only_test_ids is not None else "all tests"
        print(f"\n  → Syncing progress to Cloudflare D1 ({scope})...")
        sync_series_table(env, progress)
        sync_tests_table(env, progress, only_test_ids=only_test_ids)
        sync_runs_table(env, progress)
        print("  ✓ D1 sync complete — dashboard is up to date")
        return True
    except Exception as e:
        print(f"  ⚠ D1 sync failed (non-fatal — local progress is safe): {e}")
        return False


def update_series_progress(progress: dict, series_url: str, series_name: str, all_tests: list[dict]):
    """Recompute series_progress for a single series based on current state."""
    scraped_set = set(progress["scraped_test_ids"])
    partial_set = set(progress["partial_test_ids"])
    failed_set = set(progress["failed_test_ids"])

    total = len(all_tests)
    scraped = sum(1 for t in all_tests if t["id"] in scraped_set)
    partial = sum(1 for t in all_tests if t["id"] in partial_set)
    failed = sum(1 for t in all_tests if t["id"] in failed_set)
    pending = total - scraped - partial - failed

    progress["series_progress"][series_url] = {
        "name": series_name,
        "total": total,
        "scraped": scraped,
        "partial": partial,
        "failed": failed,
        "pending": pending,
        "updated_at": time.time(),
    }


def record_test_status(progress: dict, test_id: str, status: str, **kwargs):
    """Record granular status for a test."""
    progress["tests_status"][test_id] = {
        "status": status,  # "scraped" | "partial" | "failed"
        "last_attempted_at": time.time(),
        **kwargs,
    }


# ─── Cookie file persistence (for multi-account rotation) ──────────────────

def save_account_cookies(account_idx: int, cookies: list[dict]):
    """Save updated cookies back to cookies/account{N}.json (for git commit).
    If account_idx is -1 (env-var cookies), don't write to file."""
    if account_idx < 0:
        # Env-var mode — don't write to file, just print
        print(f"  ✓ Cookies rotated in-memory (env-var mode — not persisted to file)")
        return
    cookies_dir = Path(__file__).parent.parent / "cookies"
    cookies_dir.mkdir(exist_ok=True)
    account_file = cookies_dir / f"account{account_idx+1}.json"
    account_file.write_text(json.dumps(cookies, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ✓ Updated {account_file.name}")


# ─── Main ──────────────────────────────────────────────────────────────────

async def run_incremental_scrape(
    time_limit_minutes: int = DEFAULT_TIME_LIMIT_MINUTES,
    max_tests: int = 0,
):
    start_time = time.time()
    time_limit_seconds = time_limit_minutes * 60 if time_limit_minutes > 0 else 0  # 0 = no limit
    progress = load_progress()
    scraped_ids = set(progress["scraped_test_ids"])
    partial_ids = set(progress["partial_test_ids"])
    failed_ids = set(progress["failed_test_ids"])
    series_cache = progress.get("series_cache", {})

    # The "active cookie set" we're using this run — gets updated when refresh rotates tokens
    active_account_idx = -1
    active_cookies = None

    print(f"\n{'='*60}")
    print(f"INCREMENTAL SCRAPE RUN")
    print(f"{'='*60}")
    print(f"  Time limit: {time_limit_minutes} minutes")
    print(f"  Max tests this run: {max_tests if max_tests > 0 else 'unlimited'}")
    print(f"  Previously scraped: {len(scraped_ids)} (full), {len(partial_ids)} (partial), {len(failed_ids)} (failed)")
    print(f"  Target series: {len(TARGET_SERIES)}")
    print(f"  Start time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}")

    # Load cookies — priority: REPEATERMOCK_COOKIES env var > cookies/account*.json files
    cookie_sets = []
    cookies_dir = Path(__file__).parent.parent / "cookies"

    # 1. Try env var first (for local runs — set REPEATERMOCK_COOKIES='[{"name":"accessToken",...}]')
    env_cookies = os.environ.get("REPEATERMOCK_COOKIES")
    if env_cookies:
        try:
            parsed = json.loads(env_cookies)
            if isinstance(parsed, list) and len(parsed) > 0:
                cookie_sets.append(parsed)
                has_refresh = any(c.get("name") == "refreshToken" for c in parsed)
                print(f"  Found REPEATERMOCK_COOKIES env var ({len(parsed)} cookies, has refreshToken: {has_refresh})")
        except Exception as e:
            print(f"  Error parsing REPEATERMOCK_COOKIES env var: {e}")

    # 2. Also try cookies/account*.json files
    if cookies_dir.exists():
        for cookie_file in sorted(cookies_dir.glob("account*.json")):
            try:
                account_cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
                if account_cookies and len(account_cookies) > 0:
                    # Skip if already in cookie_sets (avoid dupes)
                    if not any(cs[0].get("value") == account_cookies[0].get("value") for cs in cookie_sets if cs):
                        cookie_sets.append(account_cookies)
                        has_refresh = any(c["name"] == "refreshToken" for c in account_cookies)
                        print(f"  Found {cookie_file.name} ({len(account_cookies)} cookies, has refreshToken: {has_refresh})")
            except Exception as e:
                print(f"  Error reading {cookie_file.name}: {e}")

    if not cookie_sets:
        print("✗ No cookies found. Exiting.")
        print("  Option 1: set REPEATERMOCK_COOKIES env var to a JSON array of cookies")
        print("  Option 2: create cookies/account1.json with a JSON array of cookies")
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

            # Step 1: Check if access token is valid via /auth/me
            result = await refresh_cookies_if_needed(context, page, original_cookies=cookies)
            if result is not None:
                print(f"  ✓ Cookie set {i+1} authenticated!")
                active_account_idx = i
                active_cookies = result

                # Step 2: ALWAYS force-refresh to get a FRESH access token (full 15-min window).
                # The provided access token may be close to expiry (user exported cookies minutes ago).
                # This also rotates the refresh token — capture + save it immediately.
                print(f"  → Force-refreshing to get fresh access token (full 15-min window)...")
                refreshed = await force_refresh_cookies(context, page, original_cookies=active_cookies)
                if refreshed is not None:
                    active_cookies = refreshed
                    save_account_cookies(i, refreshed)
                    print(f"  ✓ Fresh access token obtained — ready to scrape for ~15 minutes")
                else:
                    # Refresh failed — but access token might still be valid for a few minutes.
                    # Continue with existing tokens; proactive refresh will retry later.
                    print(f"  ⚠ Force-refresh failed — continuing with existing access token")
                    print(f"    (may expire soon — proactive refresh will retry at test {REFRESH_EVERY_N_TESTS})")
                    save_account_cookies(i, result)

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
        print("\n✗ All cookie sets failed. Exiting — NO partial/guest scraping.")
        print("  Only fully-scraped tests (Q + A + Sol + Ana) are saved.")
        print("  The refresh tokens in cookies/account*.json are expired or already consumed")
        print("  (RepeaterMock rotates the refresh token on every /auth/refresh call).")
        print("  FIX:")
        print("    1. Log in to https://repeatermock.com in your browser (Google Authenticator)")
        print("    2. Install the 'Cookie-Editor' extension → Export (JSON)")
        print("    3. Paste the JSON array into cookies/account1.json")
        print("    4. Verify first with:  python scripts/check_cookies.py")
        print("    5. DO NOT reuse the same cookies in GitHub Secrets AND locally —")
        print("       whichever uses them first rotates the refresh token and breaks the other.")
        # Clean up Playwright before returning — otherwise the driver subprocess
        # is left unclosed and you get "unclosed transport" ResourceWarnings
        # ("ValueError: I/O operation on closed pipe") at interpreter shutdown.
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
        if p:
            try:
                await p.stop()
            except Exception:
                pass
        return

    # ─── Cloudflare D1 sync: at startup, every 15 min, and at end of run ──────
    # Interval is configurable: set D1_SYNC_MINUTES env var (default 15).
    d1_sync_interval = max(1, int(os.environ.get("D1_SYNC_MINUTES", "15"))) * 60
    d1_last_sync = 0.0
    d1_changed_tests: set[str] = set()  # test_ids changed since last D1 push
    d1_disabled = False                 # set once if token missing — no retry spam

    def d1_periodic_sync(force: bool = False, full: bool = False):
        """Push progress to D1, throttled to once per interval (unless forced).
        full=True syncs every test in the cache; otherwise only changed ones."""
        nonlocal d1_last_sync, d1_disabled
        if d1_disabled:
            return
        if load_d1_env() is None:
            d1_disabled = True
            print("\n  ⚠ D1 sync disabled for this run — CLOUDFLARE_API_TOKEN not set in .env")
            return
        now = time.time()
        if not force and (now - d1_last_sync) < d1_sync_interval:
            return
        d1_last_sync = now
        ids = None if full else set(d1_changed_tests)
        d1_changed_tests.clear()
        sync_d1_if_configured(progress, only_test_ids=ids)

    # Push existing progress to D1 right away, so the dashboard starts current
    d1_periodic_sync(force=True, full=True)

    # Track when the current access token was issued (time-based refresh)
    last_refresh_time = time.time()

    async def switch_to_next_account(dead_idx: int) -> bool:
        """Mid-run fallback: the current account's refresh token died (it was
        rotated elsewhere or expired). Try every OTHER cookie set and take
        over with the first that authenticates, WITHOUT ending the run.
        Returns True if we have a working session again."""
        nonlocal p, browser, context, page, active_account_idx, active_cookies
        for offset in range(1, len(cookie_sets)):
            idx = (dead_idx + offset) % len(cookie_sets)
            print(f"\n  ↻ Account {dead_idx + 1}'s refresh token is dead — switching to account {idx + 1}...")
            try:
                if p:
                    try:
                        await browser.close()
                        await p.stop()
                    except Exception:
                        pass
                    p = browser = None
                p, browser, context = await create_browser_session(cookie_sets[idx])
                page = await context.new_page()
                result = await refresh_cookies_if_needed(context, page, original_cookies=cookie_sets[idx])
                if result is None:
                    print(f"  ✗ Account {idx + 1} is also dead")
                    continue
                active_account_idx = idx
                active_cookies = result
                refreshed = await force_refresh_cookies(context, page, original_cookies=active_cookies)
                if refreshed is not None:
                    active_cookies = refreshed
                save_account_cookies(idx, active_cookies)
                print(f"  ✓ Switched to account {idx + 1} — continuing scrape")
                return True
            except Exception as e:
                print(f"  ✗ Switch to account {idx + 1} failed: {e}")
        print("  ✗ No other account could authenticate")
        return False

    tests_scraped_this_run = 0
    tests_partial_this_run = 0
    tests_failed_this_run = 0
    questions_scraped_this_run = 0
    consecutive_auth_failures = 0

    async def refresh_active_cookies_callback():
        """Called by scrape_test_full when submit returns 401.
        Force-refreshes cookies, persists them, and returns the new list.
        Note: failure here doesn't abort the run — the test may still scrape
        fully if it was previously attempted (solution/analysis pages return
        data for previously-attempted tests regardless of auth)."""
        nonlocal active_cookies, context, page, p, browser, active_account_idx, last_refresh_time
        print("    ↻ Force-refreshing cookies due to 401 from submit...")
        refreshed = await force_refresh_cookies(context, page, original_cookies=active_cookies)
        if refreshed is not None:
            active_cookies = refreshed
            save_account_cookies(active_account_idx, refreshed)
            last_refresh_time = time.time()
            return refreshed
        # Refresh token dead — take over with another account before giving up
        if await switch_to_next_account(active_account_idx):
            last_refresh_time = time.time()
            return active_cookies
        print("    ⚠ All accounts failed — continuing with current cookies (GETs may still work)")
        return None

    try:
        for series_url in get_all_series_urls():
            # Check time limit (0 = no limit, run until all tests scraped)
            if time_limit_seconds > 0:
                elapsed = time.time() - start_time
                if elapsed >= time_limit_seconds:
                    print(f"\n  ⏰ Time limit reached ({elapsed/60:.1f} min)")
                    break

            # Max tests reached — don't waste time fetching test lists for remaining series
            if max_tests > 0 and (tests_scraped_this_run + tests_partial_this_run + tests_failed_this_run) >= max_tests:
                print(f"\n  Max tests limit reached ({max_tests}) — stopping run")
                break

            config = parse_series_url(series_url)
            variant = config["variant"]
            slug = config["slug"]
            api_version = config["api_version"]
            meta = get_series_metadata(series_url) or {}

            # Get cached test list or fetch fresh
            cached = series_cache.get(series_url)
            cache_age = time.time() - cached.get("fetched_at", 0) if cached else float('inf')

            if cached and cache_age < 86400:  # Cache for 24 hours
                all_tests = cached["tests"]
                series_name = cached.get("name", meta.get("name", ""))
                print(f"\n  [{series_name[:50]}] Using cached test list ({len(all_tests)} tests, {cache_age/60:.0f} min old)")
            else:
                print(f"\n  Fetching test list: {series_url}")
                try:
                    details = await fetch_series_details(context, slug, variant, api_version)
                    series_name = details.get("name", "") or meta.get("name", "")
                    all_tests = await fetch_all_tests_for_series(context, details, variant, api_version)

                    # Cache it
                    series_cache[series_url] = {
                        "name": series_name,
                        "tests": all_tests,
                        "fetched_at": time.time(),
                        "platform": variant,
                        "slug": slug,
                    }
                    progress["series_cache"] = series_cache
                    save_progress(progress)

                    print(f"  ✓ [{series_name[:50]}] {len(all_tests)} tests fetched")
                except Exception as e:
                    print(f"  ✗ Error fetching {series_url}: {e}")
                    continue

            # Filter to pending (not fully scraped)
            pending = [t for t in all_tests
                       if t["id"] not in scraped_ids
                       or t["id"] in partial_ids   # retry partials
                       or t["id"] in failed_ids]   # retry failures
            total = len(all_tests)
            already_scraped = len([t for t in all_tests if t["id"] in scraped_ids])

            update_series_progress(progress, series_url, series_name, all_tests)
            save_progress(progress)

            if not pending:
                print(f"  ✓ All {total} tests fully scraped — skipping")
                continue

            print(f"  Scraping {len(pending)} pending tests ({already_scraped}/{total} done)...")

            for i, test in enumerate(pending):
                if time_limit_seconds > 0:
                    elapsed = time.time() - start_time
                    if elapsed >= time_limit_seconds:
                        print(f"\n  ⏰ Time limit reached ({elapsed/60:.1f} min)")
                        break

                if max_tests > 0 and (tests_scraped_this_run + tests_partial_this_run + tests_failed_this_run) >= max_tests:
                    print(f"\n  Max tests limit reached ({max_tests})")
                    break

                # Time-based proactive refresh: access tokens last ~15 min, so
                # refresh after 12 min of scraping. (Fewer rotations = safer —
                # the refresh token is single-use and rotates on each refresh.)
                if (tests_scraped_this_run + tests_partial_this_run + tests_failed_this_run) > 0 and \
                   (time.time() - last_refresh_time) >= REFRESH_AFTER_SECONDS:
                    token_age_min = (time.time() - last_refresh_time) / 60
                    print(f"\n  Proactive token refresh (access token {token_age_min:.0f} min old)...")
                    refreshed = await force_refresh_cookies(context, page, original_cookies=active_cookies)
                    if refreshed is not None:
                        active_cookies = refreshed
                        save_account_cookies(active_account_idx, refreshed)
                        last_refresh_time = time.time()
                        consecutive_auth_failures = 0
                        print(f"  ✓ Token refreshed proactively")
                    else:
                        # Refresh token consumed/invalidated — take over with another account
                        if await switch_to_next_account(active_account_idx):
                            last_refresh_time = time.time()
                            consecutive_auth_failures = 0
                        else:
                            consecutive_auth_failures += 1
                            print(f"  ⚠ All accounts failed refresh (attempt {consecutive_auth_failures})")
                            # DON'T abort immediately — GETs may still work:
                            # 1. GET /attempt returns questions regardless of auth (public page)
                            # 2. GET /solution + /analysis return data if previously attempted
                            # Abort only after repeated total failures with no successful scrapes.
                            if consecutive_auth_failures >= 3:
                                print("  ✗ 3 total auth-failure cycles — aborting run")
                                break

                if time_limit_seconds > 0:
                    time_remaining = time_limit_seconds - elapsed
                    mins_left = int(time_remaining / 60)
                else:
                    mins_left = "∞"

                test_id = test["id"]
                test_title = test.get("title", "Unknown")[:60]
                test_num = tests_scraped_this_run + tests_partial_this_run + tests_failed_this_run + 1
                print(f"  [{test_num}] ({mins_left}m left) {test_title}")

                try:
                    result = await scrape_test_full(
                        context, page, test, variant, slug,
                        original_cookies=active_cookies,
                        on_submit_401=refresh_active_cookies_callback,
                    )

                    if result is None:
                        # Couldn't even fetch questions
                        failed_ids.add(test_id)
                        progress["failed_test_ids"] = list(failed_ids)
                        record_test_status(progress, test_id, "failed",
                                          has_questions=False, error="Could not fetch /attempt page")
                        tests_failed_this_run += 1
                        print(f"    ✗ FAILED: no questions fetched")
                    else:
                        # Check what we got
                        has_q = bool(result.get("questions"))
                        has_a = result.get("has_answers", False)
                        has_ana = result.get("has_analysis", False)

                        if has_q and has_a and has_ana:
                            # Fully scraped
                            scraped_ids.add(test_id)
                            partial_ids.discard(test_id)
                            failed_ids.discard(test_id)
                            progress["scraped_test_ids"] = list(scraped_ids)
                            progress["partial_test_ids"] = list(partial_ids)
                            progress["failed_test_ids"] = list(failed_ids)
                            record_test_status(progress, test_id, "scraped",
                                              has_questions=True, has_answers=True,
                                              has_solutions=True, has_analysis=True,
                                              has_images=True, question_count=len(result["questions"]))
                            tests_scraped_this_run += 1
                            questions_scraped_this_run += len(result["questions"])
                            consecutive_auth_failures = 0  # Reset — test scraped fine, access token still works for GETs
                            print(f"    ✓ FULLY SCRAPED ({len(result['questions'])} questions)")
                        elif has_q:
                            # Partial — got questions but no answers/analysis
                            partial_ids.add(test_id)
                            failed_ids.discard(test_id)
                            progress["partial_test_ids"] = list(partial_ids)
                            progress["failed_test_ids"] = list(failed_ids)
                            missing = []
                            if not has_a:
                                missing.append("answers")
                            if not has_ana:
                                missing.append("analysis")
                            record_test_status(progress, test_id, "partial",
                                              has_questions=True, has_answers=has_a,
                                              has_analysis=has_ana,
                                              error=f"Missing: {','.join(missing)}")
                            tests_partial_this_run += 1
                            questions_scraped_this_run += len(result["questions"])
                            print(f"    ⚠ PARTIAL (missing: {','.join(missing)})")
                        else:
                            failed_ids.add(test_id)
                            progress["failed_test_ids"] = list(failed_ids)
                            record_test_status(progress, test_id, "failed",
                                              has_questions=False, error="No questions in /attempt response")
                            tests_failed_this_run += 1
                            print(f"    ✗ FAILED: no questions in response")

                except Exception as e:
                    print(f"    ✗ Error: {e}")
                    failed_ids.add(test_id)
                    progress["failed_test_ids"] = list(failed_ids)
                    record_test_status(progress, test_id, "failed", error=str(e))
                    tests_failed_this_run += 1

                # Update series progress after each test
                update_series_progress(progress, series_url, series_name, all_tests)
                progress["total_scraped"] = len(scraped_ids)
                save_progress(progress)

                # Mark this test for the next D1 push (fires every 15 minutes)
                d1_changed_tests.add(test_id)
                d1_periodic_sync()

                await asyncio.sleep(DEFAULT_RATE_LIMIT_SECONDS)

            # Check if we hit time limit
            if time_limit_seconds > 0:
                elapsed = time.time() - start_time
                if elapsed >= time_limit_seconds:
                    break

            # Check if we hit auth failure limit (10 consecutive failures with no successful scrapes)
            if consecutive_auth_failures >= 10:
                print(f"\n  ✗ {consecutive_auth_failures} consecutive auth failures — aborting run")
                break

        # Summary
        elapsed = time.time() - start_time
        print(f"\n{'='*60}")
        print(f"RUN SUMMARY")
        print(f"{'='*60}")
        print(f"  Tests fully scraped this run: {tests_scraped_this_run}")
        print(f"  Tests partial this run: {tests_partial_this_run}")
        print(f"  Tests failed this run: {tests_failed_this_run}")
        print(f"  Questions scraped this run: {questions_scraped_this_run}")
        print(f"  Time elapsed: {elapsed/60:.1f} minutes")
        print(f"  Total fully scraped (all runs): {len(scraped_ids)}")
        print(f"  Total partial (all runs): {len(partial_ids)}")
        print(f"  Total failed (all runs): {len(failed_ids)}")
        print(f"\n  Series progress:")
        for url, sp in progress["series_progress"].items():
            print(f"    {sp['name'][:50]}: {sp['scraped']}/{sp['total']} scraped, {sp.get('partial', 0)} partial, {sp.get('pending', 0)} pending")

    finally:
        progress["last_run_end"] = time.time()
        progress["run_history"].append({
            "start": start_time,
            "end": progress["last_run_end"],
            "tests_scraped": tests_scraped_this_run,
            "tests_partial": tests_partial_this_run,
            "tests_failed": tests_failed_this_run,
            "questions_scraped": questions_scraped_this_run,
            "time_minutes": (progress["last_run_end"] - start_time) / 60,
            "account_used": active_account_idx + 1,
        })
        progress["run_history"] = progress["run_history"][-20:]
        save_progress(progress)

        # Persist final cookies
        if active_cookies:
            save_account_cookies(active_account_idx, active_cookies)
            save_cookies(active_cookies, COOKIES_FILE)

        # Mirror final progress to Cloudflare D1 (dashboard) — full sync, non-fatal
        d1_periodic_sync(force=True, full=True)

        if browser:
            await browser.close()
        if p:
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
