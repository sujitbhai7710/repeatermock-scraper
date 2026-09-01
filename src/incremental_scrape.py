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
# line_buffering=True also makes logs stream in real time when redirected.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
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
from src.full_scraper import scrape_test_full, SessionReplaced
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
# Access tokens last ~15 min. Refresh after 10 min of use (time-based, not
# test-count-based) — comfortably inside the 15-min window so a token is
# NEVER allowed to expire. Fewer rotations = safer, because the refresh token
# is SINGLE-USE and rotates on every /auth/refresh — every extra rotation is
# a chance to lose the chain if anything else touches the account. With the
# Set-Cookie capture fixed, this chain is self-sustaining: refresh every
# 10 min → new 15-min access token + rotated refresh token (30-day life) →
# no login ever needed.
REFRESH_AFTER_SECONDS = 10 * 60


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


def load_cookie_sets_from_disk() -> list[tuple[int, list[dict]]]:
    """Load cookie sets fresh from disk: REPEATERMOCK_COOKIES env var first,
    then cookies/account*.json. Returns (account_idx, cookies) pairs —
    account_idx is -1 for env cookies, else N-1 for accountN.json.

    Called at startup AND on every auth-recovery retry, so fresh cookies
    pasted into the files while the scraper waits are picked up automatically.
    """
    import re as _re
    sets: list[tuple[int, list[dict]]] = []
    cookies_dir = Path(__file__).parent.parent / "cookies"

    env_cookies = os.environ.get("REPEATERMOCK_COOKIES")
    if env_cookies:
        try:
            parsed = json.loads(env_cookies)
            if isinstance(parsed, list) and len(parsed) > 0:
                sets.append((-1, parsed))
        except Exception as e:
            print(f"  Error parsing REPEATERMOCK_COOKIES env var: {e}")

    if cookies_dir.exists():
        for cookie_file in sorted(cookies_dir.glob("account*.json")):
            try:
                account_cookies = json.loads(cookie_file.read_text(encoding="utf-8"))
                if account_cookies and len(account_cookies) > 0:
                    m = _re.search(r"account(\d+)", cookie_file.name)
                    account_idx = int(m.group(1)) - 1 if m else len(sets)
                    # Skip exact duplicates (same first cookie value)
                    if not any(cs and cs[0].get("value") == account_cookies[0].get("value")
                               for _, cs in sets):
                        sets.append((account_idx, account_cookies))
            except Exception as e:
                print(f"  Error reading {cookie_file.name}: {e}")
    return sets


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
    cookie_sets = load_cookie_sets_from_disk()

    for acct_idx, cs in cookie_sets:
        label = "REPEATERMOCK_COOKIES env var" if acct_idx < 0 else f"account{acct_idx+1}.json"
        has_refresh = any(c.get("name") == "refreshToken" for c in cs)
        print(f"  Found {label} ({len(cs)} cookies, has refreshToken: {has_refresh})")

    if not cookie_sets:
        print("✗ No cookies found. Exiting.")
        print("  Option 1: set REPEATERMOCK_COOKIES env var to a JSON array of cookies")
        print("  Option 2: create cookies/account1.json with a JSON array of cookies")
        return

    print(f"  Total cookie sets to try: {len(cookie_sets)}")
    active_account_idx = -1
    active_cookies: list[dict[str, Any]] = []
    session_generation = [0]     # bumped whenever cookies are refreshed/replaced
    guest_mode = [False]         # True when scraping as guest (free 'tb' tests only)

    # Try each cookie set until one works
    async def wait_for_live_account():
        """All cookie sets are dead (refresh tokens consumed/invalidated elsewhere).
        Recovery order, retried every 90 seconds until one works:
          1. Try every cookie set fresh from disk (picks up cookies you paste
             into cookies/account*.json while the run waits)
          2. If REPEATERMOCK_EMAIL/PASSWORD (+TOTP secret) are set in .env,
             log in automatically and mint a brand-new session
        NEVER gives up on its own; Ctrl+C stops. On success, the browser
        session and active cookies are replaced."""
        nonlocal p, browser, context, page, active_account_idx, active_cookies, last_refresh_time
        attempt = 0
        dead_refresh_tokens: set[str] = set()  # tokens already proven dead this run
        fallback_session: tuple[int, list[dict]] | None = None  # auth-me OK, refresh dead
        while True:
            attempt += 1
            sets = load_cookie_sets_from_disk()
            if not sets:
                print("  ⚠ No cookie files found — save fresh cookies into cookies/account1.json")
            for acct_idx, cs in sets:
                label = f"account{acct_idx+1}" if acct_idx >= 0 else "env-var cookies"
                rt = next((c.get("value") for c in cs if c.get("name") == "refreshToken"), None)
                if rt and rt in dead_refresh_tokens:
                    print(f"  ⏭ {label}: refresh token already known dead — skipping")
                    continue
                try:
                    print(f"  ↻ Recovery attempt {attempt}: trying {label}...")
                    if p:
                        try:
                            await browser.close()
                            await p.stop()
                        except Exception:
                            pass
                        p = browser = None
                    p, browser, context = await create_browser_session(cs)
                    page = await context.new_page()
                    result = await refresh_cookies_if_needed(context, page, original_cookies=cs)
                    if result is None:
                        print(f"  ✗ {label} is dead")
                        if rt:
                            dead_refresh_tokens.add(rt)
                        continue
                    refreshed = await force_refresh_cookies(context, page, original_cookies=result)
                    if refreshed is not None:
                        # FULL session — refresh token works. Perfect, use it.
                        active_account_idx = acct_idx
                        active_cookies = refreshed
                        save_account_cookies(acct_idx, active_cookies)
                        last_refresh_time = time.time()
                        print(f"  ✓ Back online with {label} — continuing scrape")
                        return True
                    # Refresh token dead but access token still works — remember as
                    # a LAST-RESORT fallback and keep looking for a refreshable
                    # session (Google auto-login) before settling for this.
                    if rt:
                        # dead — remember it so future recovery cycles skip this
                        # account instantly instead of relaunching a browser every time
                        dead_refresh_tokens.add(rt)
                    fallback_session = (acct_idx, result)
                    print(f"  ⚠ {label}: access token works but refresh token is dead — kept as fallback")
                except Exception as e:
                    print(f"  ✗ Recovery with {label} failed: {e}")

            # 2. CDP re-login via the user's REAL Chrome (best for Google-only
            #    accounts — Google never blocks the user's actual browser)
            try:
                from src.auto_login import cdp_relogin
                print("  🤖 Trying auto-login via your real Chrome (CDP port 9222)...")
                print("     (If Chrome isn't open yet, run:  scripts\\start_scrape_chrome.bat )")
                fresh = await cdp_relogin()
                if fresh:
                    p, browser, context = await create_browser_session(fresh)
                    page = await context.new_page()
                    active_account_idx = 3  # cookies/account4.json
                    active_cookies = fresh
                    save_account_cookies(3, fresh)
                    last_refresh_time = time.time()
                    print("  ✓ Back online via CHROME (CDP) AUTO-LOGIN — continuing scrape")
                    return True
            except Exception as e:
                print(f"  ✗ CDP auto-login attempt failed: {e}")

            # 3. Google-profile auto-login (fallback if CDP Chrome isn't set up)
            try:
                from src.auto_login import google_profile_exists, google_profile_relogin
                if google_profile_exists():
                    print("  🤖 Attempting Google auto-login via saved profile...")
                    if p:
                        try:
                            await browser.close()
                            await p.stop()
                        except Exception:
                            pass
                        p = browser = None
                    fresh = await google_profile_relogin()
                    if fresh:
                        p, browser, context = await create_browser_session(fresh)
                        page = await context.new_page()
                        active_account_idx = 3  # cookies/account4.json
                        active_cookies = fresh
                        save_account_cookies(3, fresh)
                        last_refresh_time = time.time()
                        print("  ✓ Back online via GOOGLE AUTO-LOGIN — continuing scrape")
                        return True
                else:
                    print("  💡 Google-only account? Run  python scripts/setup_google_login.py")
                    print("     once — then the scraper re-logins via Google automatically, forever.")
            except Exception as e:
                print(f"  ✗ Google auto-login attempt failed: {e}")

            # 3. Password auto-login (only for accounts with a site password)
            try:
                from src.auto_login import try_auto_login, load_login_credentials
                if load_login_credentials() is not None:
                    fresh = try_auto_login()
                    if fresh:
                        login_account = max(0, (load_login_credentials().get("account", 1) or 1) - 1)
                        p, browser, context = await create_browser_session(fresh)
                        page = await context.new_page()
                        active_account_idx = login_account
                        active_cookies = fresh
                        save_account_cookies(login_account, fresh)
                        last_refresh_time = time.time()
                        print(f"  ✓ Back online via AUTO-LOGIN (account{login_account+1}) — continuing scrape")
                        return True
                else:
                    print("  💡 Tip: set REPEATERMOCK_EMAIL + REPEATERMOCK_PASSWORD + REPEATERMOCK_TOTP_SECRET")
                    print("     in .env and the scraper will log itself back in automatically — never waiting for you.")
            except Exception as e:
                print(f"  ✗ Auto-login attempt failed: {e}")

            # 4. Nothing refreshable — use the best fallback we found
            #    (access token still works for GETs, but expires in minutes)
            if fallback_session:
                acct_idx, fb = fallback_session
                p, browser, context = await create_browser_session(fb)
                page = await context.new_page()
                active_account_idx = acct_idx
                active_cookies = fb
                save_account_cookies(acct_idx, fb)
                last_refresh_time = time.time()
                print(f"  ⚠ No refreshable session — using access-token-only session "
                      f"(account{acct_idx+1}); will re-recover when it expires")
                return True

            # 5. GUEST MODE — DISABLED BY DEFAULT (ALLOW_GUEST=0).
            #    Guest sessions can only fetch QUESTIONS — never submit, never
            #    get answers/solutions/analysis — so guest "scrapes" can never
            #    complete. Worse: the submit-404 chaos triggered recovery loops
            #    that clobbered other workers' sessions and marked tests as
            #    FAILED, poisoning progress.json. The authed refresh chain
            #    (10-min proactive refresh) is self-sustaining, so guest mode
            #    is never needed. Opt back in ONLY for diagnostics with
            #    ALLOW_GUEST=1.
            if os.environ.get("ALLOW_GUEST", "0") == "1":
                print("  👤 ALLOW_GUEST=1 — falling back to GUEST MODE (questions only, never completes)")
                p, browser, context = await create_browser_session([])
                page = await context.new_page()
                await page.goto("https://repeatermock.com", wait_until="domcontentloaded")
                await asyncio.sleep(4)
                active_cookies = await context.cookies()
                guest_mode[0] = True
                last_refresh_time = time.time()
                print("  ✓ Guest session ready — scraping FREE tests as guest")
                return True

            print("  ⏳ Still no working session. Paste fresh cookies into cookies/account*.json "
                  "or add credentials to .env — retrying in 90s (Ctrl+C to stop)")
            await asyncio.sleep(90)

    p = browser = context = page = None
    authed = False

    for acct_idx, cookies in cookie_sets:
        print(f"\n  Trying cookie set {acct_idx+1}/{max(c[0] for c in cookie_sets)+1}...")
        try:
            if p:
                await browser.close()
                await p.stop()
            p, browser, context = await create_browser_session(cookies)
            page = await context.new_page()

            # Step 1: Check if access token is valid via /auth/me
            result = await refresh_cookies_if_needed(context, page, original_cookies=cookies)
            if result is not None:
                print(f"  ✓ Cookie set {acct_idx+1} authenticated!")
                active_account_idx = acct_idx
                active_cookies = result

                # Step 2: ALWAYS force-refresh to get a FRESH access token (full 15-min window).
                # The provided access token may be close to expiry (user exported cookies minutes ago).
                # This also rotates the refresh token — capture + save it immediately.
                print(f"  → Force-refreshing to get fresh access token (full 15-min window)...")
                refreshed = await force_refresh_cookies(context, page, original_cookies=active_cookies)
                if refreshed is not None:
                    active_cookies = refreshed
                    save_account_cookies(acct_idx, refreshed)
                    print(f"  ✓ Fresh access token obtained — ready to scrape for ~15 minutes")
                else:
                    # Refresh failed — but access token might still be valid for a few minutes.
                    # Continue with existing tokens; proactive refresh will retry later.
                    print(f"  ⚠ Force-refresh failed — continuing with existing access token")
                    print(f"    (may expire soon — the time-based proactive refresh will retry in ~12 min)")
                    save_account_cookies(acct_idx, result)

                authed = True
                break
            else:
                print(f"  ✗ Cookie set {acct_idx+1} failed")
        except Exception as e:
            print(f"  ✗ Cookie set {acct_idx+1} error: {e}")
            if p:
                try:
                    await browser.close()
                    await p.stop()
                except:
                    pass
                p = None

    if not authed:
        # Don't exit — enter recovery mode: wait for fresh cookies (hot-reload)
        print("\n✗ All cookie sets failed on startup — entering RECOVERY MODE:")
        print("  the run stays alive and retries every 90s. Log in to repeatermock.com,")
        print("  export fresh cookies (Cookie-Editor extension) and save them into")
        print("  cookies/account1.json — the run picks them up automatically.")
        print("  Press Ctrl+C to stop the run.")
        await wait_for_live_account()

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

    # Light D1 sync at startup (series + runs only). The full test-row sync
    # happens at the END of the run — re-uploading all 6600+ rows at startup
    # wastes minutes and spams the log every single run.
    d1_periodic_sync(force=True, full=False)

    # Track when the current access token was issued (time-based refresh)
    last_refresh_time = time.time()

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
        # Refresh token dead — reload cookies from disk and wait until one works
        # (hot-reloads fresh cookies the user pastes into cookies/account*.json,
        #  or auto-logins via Google profile / saved credentials).
        await wait_for_live_account()
        # The recovery replaced the browser session — this test's context/page
        # references are stale. Signal the caller to retry with the new session.
        raise SessionReplaced("browser session was replaced by auth recovery")

    # ─── Parallel workers ─────────────────────────────────────────────────────
    # N workers scrape different tests at the same time, each with its own
    # browser context on the shared browser. Set PARALLEL_WORKERS env var to
    # change the count (default 3). Recovery is single-flight: one worker
    # recovers, the rest automatically rebuild from the fresh session.
    NUM_WORKERS = max(1, int(os.environ.get("PARALLEL_WORKERS", "3")))
    session_lock = asyncio.Lock()
    progress_lock = asyncio.Lock()
    worker_contexts: dict = {}
    worker_pages: dict = {}
    worker_gen: dict = {}
    series_meta: dict = {}       # series_url -> (series_name, all_tests)

    async def build_worker_session(wid: int):
        """(Re)create worker wid's context+page on the current browser with the
        current active_cookies. Falls back to full recovery if the browser died."""
        try:
            old = worker_contexts.get(wid)
            if old:
                try:
                    await old.close()
                except Exception:
                    pass
            if browser is None:
                await wait_for_live_account()
            context = await browser.new_context(
                viewport={"width": 1366, "height": 768},
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
                locale="en-IN",
                timezone_id="Asia/Kolkata",
            )
            clean = []
            for c in active_cookies:
                cc = {"name": c["name"], "value": c["value"],
                      "domain": c.get("domain", ".repeatermock.com"), "path": c.get("path", "/")}
                ss = c.get("sameSite", "Lax")
                cc["sameSite"] = ss if ss in ("Strict", "Lax", "None") else "Lax"
                if c.get("secure"):
                    cc["secure"] = True
                if c.get("httpOnly"):
                    cc["httpOnly"] = True
                clean.append(cc)
            await context.add_cookies(clean)
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                window.chrome = { runtime: {} };
                console.clear = function() {};
                window.close = function() {};
            """)
            worker_contexts[wid] = context
            worker_pages[wid] = await context.new_page()
            worker_gen[wid] = session_generation[0]
        except Exception as e:
            print(f"  [W{wid}] worker session build failed: {e}")
            await wait_for_live_account()

    def make_submit_callback(wid: int):
        async def on_submit_401():
            nonlocal active_cookies, last_refresh_time
            async with session_lock:
                # Another worker may have already refreshed/recovered
                if worker_gen.get(wid) != session_generation[0]:
                    raise SessionReplaced("session already updated by another worker")
                refreshed = await force_refresh_cookies(
                    worker_contexts[wid], worker_pages[wid], original_cookies=active_cookies)
                if refreshed is not None:
                    active_cookies = refreshed
                    save_account_cookies(active_account_idx, refreshed)
                    last_refresh_time = time.time()
                    session_generation[0] += 1
                    worker_gen[wid] = session_generation[0]
                    return refreshed
                # Refresh token dead — full recovery (single-flight via session_lock)
                await wait_for_live_account()
                session_generation[0] += 1
                worker_gen[wid] = session_generation[0]
        return on_submit_401

    async def worker_loop(wid: int, work_queue: asyncio.Queue):
        nonlocal tests_scraped_this_run, tests_partial_this_run, tests_failed_this_run
        nonlocal questions_scraped_this_run, active_cookies, last_refresh_time
        await asyncio.sleep(wid * 4)  # stagger workers to desynchronize attempts
        while True:
            if time_limit_seconds > 0 and time.time() - start_time >= time_limit_seconds:
                break
            if max_tests > 0 and (tests_scraped_this_run + tests_partial_this_run + tests_failed_this_run) >= max_tests:
                break
            # Adopt a refreshed/recovered session if another worker bumped it
            if worker_gen.get(wid) != session_generation[0] or wid not in worker_contexts:
                await build_worker_session(wid)

            try:
                test, variant, slug, s_url, s_name = work_queue.get_nowait()
            except asyncio.QueueEmpty:
                break

            test_id = test["id"]
            print(f"  [W{wid}] {test.get('title', 'Unknown')[:60]}")

            # Proactive refresh (single-flight — one worker per 12-min window)
            if (time.time() - last_refresh_time) >= REFRESH_AFTER_SECONDS:
                async with session_lock:
                    if (time.time() - last_refresh_time) >= REFRESH_AFTER_SECONDS:
                        refreshed = await force_refresh_cookies(
                            worker_contexts[wid], worker_pages[wid],
                            original_cookies=active_cookies)
                        if refreshed is not None:
                            active_cookies = refreshed
                            save_account_cookies(active_account_idx, refreshed)
                            session_generation[0] += 1
                            worker_gen[wid] = session_generation[0]
                            print(f"  [W{wid}] ✓ Token refreshed proactively")
                        # On failure: don't recover here — the submit 401 path
                        # triggers full recovery with Google auto-login.
                        last_refresh_time = time.time()

            result = None
            for sess_attempt in range(3):
                try:
                    result = await scrape_test_full(
                        worker_contexts[wid], worker_pages[wid], test, variant, slug,
                        original_cookies=active_cookies,
                        on_submit_401=make_submit_callback(wid),
                    )
                    break
                except SessionReplaced:
                    if sess_attempt == 2:
                        print(f"  [W{wid}] ⚠ Session replaced 3 times — recording partial (will retry next pass)")
                        result = {"questions": [{"id": "pending-retry"}],
                                  "has_answers": False, "has_analysis": False}
                        break
                    print(f"  [W{wid}] ↻ Session replaced by recovery — rebuilding and retrying")
                    await build_worker_session(wid)

            async with progress_lock:
                if result is None:
                    failed_ids.add(test_id)
                    progress["failed_test_ids"] = list(failed_ids)
                    record_test_status(progress, test_id, "failed",
                                      has_questions=False, error="Could not fetch /attempt page")
                    tests_failed_this_run += 1
                    print(f"  [W{wid}] ✗ FAILED: no questions fetched")
                else:
                    has_q = bool(result.get("questions"))
                    has_a = result.get("has_answers", False)
                    has_ana = result.get("has_analysis", False)
                    if has_q and has_a and has_ana:
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
                        print(f"  [W{wid}] ✓ FULLY SCRAPED ({len(result['questions'])} questions)")
                    elif has_q:
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
                        print(f"  [W{wid}] ⚠ PARTIAL (missing: {','.join(missing)})")
                    else:
                        failed_ids.add(test_id)
                        progress["failed_test_ids"] = list(failed_ids)
                        record_test_status(progress, test_id, "failed",
                                          has_questions=False, error="No questions in /attempt response")
                        tests_failed_this_run += 1
                        print(f"  [W{wid}] ✗ FAILED: no questions in response")

                s_name2, all_tests2 = series_meta.get(s_url, (s_name, []))
                update_series_progress(progress, s_url, s_name2, all_tests2)
                progress["total_scraped"] = len(scraped_ids)
                save_progress(progress)
                d1_changed_tests.add(test_id)
                if wid == 0:
                    d1_periodic_sync()

            await asyncio.sleep(DEFAULT_RATE_LIMIT_SECONDS)
    try:
        # ── Keep making passes over ALL series until every test is fully scraped ──
        # Failed and partial tests are automatically retried on the next pass.
        # The run NEVER stops on auth failures — it waits (hot-reloading fresh
        # cookies you paste into cookies/account*.json) until it can continue.
        pass_num = 0
        while True:
            pass_num += 1
            if pass_num > 1:
                print(f"\n{'='*60}")
                print(f"  PASS {pass_num}: retrying tests not fully scraped yet "
                      f"({len(scraped_ids)} done, {len(partial_ids)} partial, {len(failed_ids)} failed)")
                print(f"{'='*60}")
            work_items = []

            # Prefetch stale/missing series test lists in PARALLEL (makes
            # queueing ~6x faster instead of one-by-one)
            stale = []
            for surl in get_all_series_urls():
                c = series_cache.get(surl)
                age = time.time() - c.get("fetched_at", 0) if c else float("inf")
                if not c or age >= 86400:
                    stale.append(surl)
            if stale:
                print(f"  ⏳ Prefetching test lists for {len(stale)} series in parallel...")
                sem = asyncio.Semaphore(6)

                async def prefetch(surl):
                    async with sem:
                        try:
                            cfg = parse_series_url(surl)
                            meta = get_series_metadata(surl) or {}
                            details = await fetch_series_details(
                                context, cfg["slug"], cfg["variant"], cfg["api_version"])
                            name = details.get("name", "") or meta.get("name", "")
                            tests = await fetch_all_tests_for_series(
                                context, details, cfg["variant"], cfg["api_version"])
                            series_cache[surl] = {"name": name, "tests": tests,
                                                  "fetched_at": time.time(),
                                                  "platform": cfg["variant"], "slug": cfg["slug"]}
                            print(f"  ✓ Prefetched [{name[:50]}] {len(tests)} tests")
                        except Exception as e:
                            print(f"  ✗ Prefetch failed {surl}: {e}")

                await asyncio.gather(*[prefetch(s) for s in stale])
                progress["series_cache"] = series_cache
                save_progress(progress)

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

                if guest_mode[0] and variant != "tb":
                    print(f"  ⏭ [{series_name[:50]}] '{variant}' series needs an active plan — skipped in guest mode")
                    continue

                # Queue all pending tests for the parallel workers
                series_meta[series_url] = (series_name, all_tests)
                for _t in pending:
                    work_items.append((_t, variant, slug, series_url, series_name))
                print(f"  + Queued {len(pending)} tests from [{series_name[:50]}] "
                      f"({already_scraped}/{total} already done)")

                # Check if we hit time limit
                if time_limit_seconds > 0:
                    elapsed = time.time() - start_time
                    if elapsed >= time_limit_seconds:
                        break

                # NOTE: no auth-failure abort here anymore — when all refresh
                # tokens die, wait_for_live_account() blocks (hot-reloading
                # cookies/account*.json) until one works, and the pass loop
                # retries failed/partial tests until everything is scraped.

            # Run this pass's queue with parallel workers
            if work_items:
                n = min(NUM_WORKERS, len(work_items))
                print(f"\n  ▶ Scraping {len(work_items)} pending tests with {n} parallel workers...")
                work_queue: asyncio.Queue = asyncio.Queue()
                for _it in work_items:
                    work_queue.put_nowait(_it)
                await asyncio.gather(*[asyncio.create_task(worker_loop(i, work_queue))
                                       for i in range(n)])

            # Pass finished — if anything is left (failed/partial), do another pass
            pending_total = 0
            for _surl, _cache in progress.get("series_cache", {}).items():
                for _t in _cache.get("tests", []):
                    if _t["id"] not in scraped_ids:
                        pending_total += 1
            if pending_total == 0:
                print("\n  ✓✓✓ ALL TESTS FULLY SCRAPED — every test has Q + A + solutions + analysis!")
                break
            # Respect --time-limit / --max-tests between passes
            if time_limit_seconds > 0 and (time.time() - start_time) >= time_limit_seconds:
                print("\n  ⏰ Time limit reached — progress saved, run again anytime to resume")
                break
            if max_tests > 0 and (tests_scraped_this_run + tests_partial_this_run + tests_failed_this_run) >= max_tests:
                print("\n  Max tests limit reached — progress saved, run again anytime to resume")
                break
            print(f"\n  ↻ Pass {pass_num} finished — {pending_total} tests still need work. "
                  f"Starting next pass (retries included)...")
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

    # Signal auth failure to the workflow: the run ended with a guest or
    # never-authenticated session AND scraped absolutely nothing — this means
    # every cookie set is dead. Exit code 2 → the workflow turns this into a
    # red ❌ run so dead cookies are visible immediately (instead of a green
    # run that scraped 0 tests silently, which is how the chain death went
    # unnoticed before).
    if tests_scraped_this_run == 0 and tests_partial_this_run == 0:
        if guest_mode[0] or not authed:
            print("\n✗ RUN FAILED: 0 tests scraped and no authenticated account session "
                  "(all cookie sets dead). Export fresh cookies from repeatermock.com "
                  "and update cookies/account*.json.")
            sys.exit(2)

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
