"""
Main RepeaterMock scraper.

Usage:
    python -m src.scraper scrape-series <series_url> [--max-tests N]
    python -m src.scraper scrape-test <test_id> [--variant tb|tb-pro|gd]
    python -m src.scraper test-series <series_url>   # test if scrapable
    python -m src.scraper list-series <series_url>   # list all tests without scraping questions

Examples:
    # Scrape all free tests from SSC CGL free series
    python -m src.scraper scrape-series https://repeatermock.com/tb/test-series/ssc-cgl

    # Scrape just 5 tests (for testing)
    python -m src.scraper scrape-series https://repeatermock.com/tb/test-series/ssc-cgl --max-tests 5

    # Scrape a single test by ID
    python -m src.scraper scrape-test 6a0f3ef125f9d428c136a83a --variant tb

    # Test if a series is scrapable (fetch series details + first test's questions)
    python -m src.scraper test-series https://repeatermock.com/tb-pro/test-series/ssc-maths-previous-year-questions

Environment variables (set in .env or GitHub Secrets):
    REPEATERMOCK_COOKIES_JSON    — Full cookie JSON array
    REPEATERMOCK_COOKIE_STRING   — Cookie string: "name=val; name=val; ..."
    REPEATERMOCK_ACCESS_TOKEN    — Individual cookie
    REPEATERMOCK_REFRESH_TOKEN   — Individual cookie
    REPEATERMOCK_TOTP_VERIFIED   — Individual cookie (should be "1")
    REPEATERMOCK_GUEST_ID        — Individual cookie
    REPEATERMOCK_RM_FE           — Individual cookie
"""
import argparse
import asyncio
import json
import re
import sys
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

# Load .env file if it exists (for local dev)
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
except ImportError:
    pass  # python-dotenv not installed — rely on env vars directly

from playwright.async_api import async_playwright

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.cookie_manager import load_cookies, save_cookies, get_cookie_value
from src.question_parser import parse_attempt_page


# ─── Constants ─────────────────────────────────────────────────────────────

API_BASE = "https://api.repeatermock.com"
DATA_DIR = Path(__file__).parent.parent / "data"
TESTS_DIR = DATA_DIR / "tests"
COOKIES_FILE = DATA_DIR / "cookies.json"
SERIES_DIR = DATA_DIR / "series"

# Known series configurations
SERIES_CONFIG = {
    # slug → (variant, api_version, label)
    # variant: "tb" (free), "tb-pro" (paid), "gd" (guidely)
    # api_version: "v1" or "v2"
}


# ─── URL parsing ───────────────────────────────────────────────────────────

def parse_series_url(url: str) -> dict[str, str]:
    """
    Parse a RepeaterMock series URL into its components.

    Examples:
        https://repeatermock.com/tb/test-series/ssc-cgl
            → {"variant": "tb", "slug": "ssc-cgl", "api_version": "v1"}

        https://repeatermock.com/tb-pro/test-series/ssc-cgl
            → {"variant": "tb-pro", "slug": "ssc-cgl", "api_version": "v1"}

        https://repeatermock.com/gd/test-series/ssc-selection-post
            → {"variant": "gd", "slug": "ssc-selection-post", "api_version": "v2"}
    """
    parsed = urlparse(url)
    path = parsed.path

    # Pattern: /{variant}/test-series/{slug}
    m = re.match(r'^/(tb-pro|tb|gd)/test-series/([\w-]+)', path)
    if not m:
        raise ValueError(f"Invalid series URL: {url}")

    variant = m.group(1)
    slug = m.group(2)
    api_version = "v2" if variant == "gd" else "v1"

    return {"variant": variant, "slug": slug, "api_version": api_version}


# ─── Browser session ───────────────────────────────────────────────────────

async def create_browser_session(cookies: list[dict[str, Any]]):
    """
    Create a Playwright browser session with:
    - User's authenticated cookies
    - Anti-bot-detection measures (webdriver flag, chrome runtime, console.clear no-op)
    - Cookie rotation handling (saves new cookies after /auth/refresh)
    """
    p = await async_playwright().start()
    browser = await p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--disable-blink-features=AutomationControlled",
        ],
    )
    # Normalize cookies for Playwright (fix sameSite, remove extra fields)
    clean_cookies = []
    for c in cookies:
        cc = {
            "name": c["name"],
            "value": c["value"],
            "domain": c.get("domain", ".repeatermock.com"),
            "path": c.get("path", "/"),
        }
        ss = c.get("sameSite", "Lax")
        if ss in ("Strict", "Lax", "None"):
            cc["sameSite"] = ss
        else:
            cc["sameSite"] = "Lax"
        if c.get("secure"):
            cc["secure"] = True
        if c.get("httpOnly"):
            cc["httpOnly"] = True
        clean_cookies.append(cc)

    # Create context WITHOUT storage_state, then add cookies via add_cookies
    # (storage_state sometimes drops httpOnly cookies; add_cookies is more reliable)
    context = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        locale="en-IN",
        timezone_id="Asia/Kolkata",
    )

    # Add cookies via add_cookies (more reliable for httpOnly cookies)
    await context.add_cookies(clean_cookies)

    # Anti-detection + anti-anti-debug
    await context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
        window.chrome = { runtime: {} };
        // RepeaterMock's anti-debug code spams console.clear then navigates to about:blank
        console.clear = function() {};
        window.close = function() {};
    """)

    return p, browser, context


async def fetch_via_context(context, url: str, method: str = "GET", body: str | None = None) -> tuple[int, str]:
    """Fetch a URL using the browser context. Manually adds Cookie header from context cookies."""
    # Get all cookies from the context (includes httpOnly ones)
    cookies = await context.cookies()
    cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in cookies if "repeatermock" in c.get("domain", ""))
    
    headers = {
        "Accept": "application/json",
        "Referer": "https://repeatermock.com/",
        "Origin": "https://repeatermock.com",
        "Cookie": cookie_str,
    }
    if method == "POST":
        headers["Content-Type"] = "application/json"

    try:
        if method == "GET":
            resp = await context.request.get(url, headers=headers)
        elif method == "POST":
            resp = await context.request.post(url, headers=headers, data=body or "{}")
        else:
            raise ValueError(f"Unsupported method: {method}")
        return resp.status, await resp.text()
    except Exception as e:
        return 0, f"ERROR: {e}"


async def fetch_via_page(page, url: str, method: str = "GET", body: str | None = None) -> tuple[int, str]:
    """
    Fetch a URL from within the browser page using page.evaluate().
    This ensures httpOnly cookies (refreshToken, accessToken) are sent with the request,
    because the fetch() call runs in the page's context which has access to all cookies.
    """
    try:
        result = await page.evaluate("""
            async ({url, method, body}) => {
                try {
                    const opts = {
                        method: method,
                        credentials: 'include',
                        headers: {
                            'Accept': 'application/json',
                        },
                    };
                    if (method === 'POST') {
                        opts.headers['Content-Type'] = 'application/json';
                        opts.body = body || '{}';
                    }
                    const resp = await fetch(url, opts);
                    const text = await resp.text();
                    return { status: resp.status, body: text };
                } catch (e) {
                    return { status: 0, body: 'ERROR: ' + String(e) };
                }
            }
        """, {"url": url, "method": method, "body": body})
        return result.get("status", 0), result.get("body", "")
    except Exception as e:
        return 0, f"ERROR: {e}"


async def refresh_cookies_if_needed(context, page, max_retries: int = 3) -> list[dict[str, Any]] | None:
    """
    Check if auth is working; if not, refresh. Save rotated cookies.
    
    KEY INSIGHT: RepeaterMock's client-side JS auto-refreshes the access token
    when the page loads. We must use page.goto() (which runs JS) to trigger
    the refresh, NOT just context.request.get() (which doesn't run JS).
    
    Returns None on failure (caller should handle gracefully).
    """
    import logging
    logger = logging.getLogger("repeatermock_scraper")

    for attempt in range(max_retries):
        logger.info(f"Auth attempt {attempt+1}/{max_retries}")
        
        # Step 1: Load the home page in the browser — this runs RepeaterMock's
        # JS which automatically refreshes the access token if expired.
        # The JS calls /auth/refresh internally and sets new cookies.
        try:
            logger.info("  Loading repeatermock.com (triggers JS token refresh)...")
            await page.goto("https://repeatermock.com/", timeout=45000, wait_until="networkidle")
        except Exception as e:
            logger.warning(f"  Page load failed (trying domcontentloaded): {e}")
            try:
                await page.goto("https://repeatermock.com/", timeout=30000, wait_until="domcontentloaded")
            except Exception as e2:
                logger.warning(f"  domcontentloaded also failed: {e2}")
        
        # Wait for JS to finish token refresh
        logger.info("  Waiting for JS token refresh...")
        await asyncio.sleep(8)
        
        # Step 2: Check if the page loaded as authenticated user
        # The home page shows different content for logged-in vs logged-out users
        try:
            body_text = await page.evaluate("document.body ? document.body.innerText.substring(0, 500) : ''")
            logger.info(f"  Page content preview: {body_text[:100]}")
            
            # Check for logged-in indicators
            if "Dashboard" in body_text or "My Batches" in body_text or "Sign Out" in body_text or "Logout" in body_text:
                logger.info("  ✓ User is logged in (found Dashboard/menu indicators)")
                cookies = await context.cookies()
                save_cookies(cookies, COOKIES_FILE)
                return cookies
        except Exception as e:
            logger.warning(f"  Could not read page content: {e}")
        
        # Step 3: Try direct API check using fetch_via_context (now includes Cookie header manually)
        logger.info("  Checking /auth/me (with manually added Cookie header)...")
        # Debug: log what cookies we have
        all_cookies = await context.cookies()
        cookie_names = [c["name"] for c in all_cookies if "repeatermock" in c.get("domain", "")]
        logger.info(f"  Available cookies: {cookie_names}")
        has_refresh = any(c["name"] == "refreshToken" for c in all_cookies)
        logger.info(f"  Has refreshToken in context: {has_refresh}")
        if has_refresh:
            refresh_val = next(c["value"][:30] for c in all_cookies if c["name"] == "refreshToken")
            logger.info(f"  refreshToken value (first 30): {refresh_val}...")
        
        status, body = await fetch_via_context(context, f"{API_BASE}/auth/me")
        logger.info(f"  /auth/me → {status}: {body[:80]}")

        if status == 200 and '"success":true' in body:
            cookies = await context.cookies()
            save_cookies(cookies, COOKIES_FILE)
            logger.info("  ✓ Authenticated via API check")
            return cookies

        # Step 4: Try manual /auth/refresh via fetch_via_context
        logger.info("  Trying /auth/refresh (with Cookie header)...")
        status, body = await fetch_via_context(context, f"{API_BASE}/auth/refresh", method="POST")
        logger.info(f"  /auth/refresh → {status}: {body[:80]}")

        if status == 200:
            await asyncio.sleep(2)
            # The refresh response sets new cookies via Set-Cookie headers
            # We need to re-read cookies from the context (they may have been updated)
            cookies = await context.cookies()
            save_cookies(cookies, COOKIES_FILE)
            # Re-check auth with updated cookies
            status2, body2 = await fetch_via_context(context, f"{API_BASE}/auth/me")
            if status2 == 200 and '"success":true' in body2:
                logger.info("  ✓ Authenticated via manual refresh")
                return cookies

        # Step 5: Try navigating to dashboard (forces redirect if logged in)
        if attempt == 1:
            try:
                logger.info("  Trying /dashboard navigation...")
                await page.goto("https://repeatermock.com/dashboard", timeout=30000, wait_until="domcontentloaded")
                await asyncio.sleep(5)
                url_after = page.url
                logger.info(f"  Dashboard redirect URL: {url_after}")
                # If we're still on /dashboard (not redirected to login), we're authed
                if "/dashboard" in url_after and "login" not in url_after:
                    cookies = await context.cookies()
                    save_cookies(cookies, COOKIES_FILE)
                    logger.info("  ✓ Authenticated via dashboard check")
                    return cookies
            except Exception as e:
                logger.warning(f"  Dashboard check failed: {e}")

        if attempt < max_retries - 1:
            logger.info(f"  Waiting 5s before retry...")
            await asyncio.sleep(5)

    logger.error(f"✗ Auth failed after {max_retries} attempts")
    logger.error(f"  The refresh token may be consumed/expired.")
    cookies = await context.cookies()
    save_cookies(cookies, COOKIES_FILE)
    return None


async def try_auth_with_fallback(cookies_list: list[list[dict]], page_factory) -> tuple[Any, Any, Any, list[dict]] | None:
    """
    Try multiple cookie sets (accounts). Return first that works.
    page_factory: async callable that returns (playwright, browser, context, page)
    """
    import logging
    logger = logging.getLogger("repeatermock_scraper")

    for i, cookies in enumerate(cookies_list):
        account_name = f"Account {i+1}"
        logger.info(f"\nTrying {account_name}...")
        p, browser, context, page = await page_factory(cookies)
        result = await refresh_cookies_if_needed(context, page)
        if result is not None:
            logger.info(f"✓ {account_name} authenticated successfully!")
            return p, browser, context, page
        logger.warning(f"✗ {account_name} failed, trying next...")
        await browser.close()
        await p.stop()

    logger.error("✗ All accounts failed!")
    return None


# ─── Series scraping ───────────────────────────────────────────────────────

async def fetch_series_details(context, slug: str, variant: str, api_version: str) -> dict[str, Any]:
    """Fetch series details (name, sections, subsections, test counts)."""
    if api_version == "v2":
        url = f"{API_BASE}/api/v2/test-series/{slug}"
    else:
        url = f"{API_BASE}/api/v1/test-series/{slug}?variant={variant}"

    status, body = await fetch_via_context(context, url)
    if status != 200:
        raise RuntimeError(f"Failed to fetch series details: {status} {body[:200]}")

    data = json.loads(body)
    return data.get("data", {}).get("details", {})


async def fetch_section_tests(
    context,
    series_id: str,
    section_id: str,
    subsection_id: str | None,
    variant: str,
    api_version: str,
    limit: int = 500,
) -> list[dict[str, Any]]:
    """Fetch all tests in a subsection."""
    if api_version == "v2":
        url = f"{API_BASE}/api/v2/test-series/{series_id}/sections/{section_id}/tests?limit={limit}&offset=0"
        if subsection_id:
            url += f"&subSectionId={subsection_id}"
    else:
        url = f"{API_BASE}/api/v1/test-series/{series_id}/sections/{section_id}/tests?limit={limit}&offset=0&variant={variant}"
        if subsection_id:
            url += f"&subSectionId={subsection_id}"

    status, body = await fetch_via_context(context, url)
    if status != 200:
        print(f"    Warning: Failed to fetch tests: {status}")
        return []

    data = json.loads(body)
    return data.get("data", [])


async def fetch_all_tests_for_series(
    context,
    series_details: dict[str, Any],
    variant: str,
    api_version: str,
) -> list[dict[str, Any]]:
    """Fetch all tests across all sections and subsections of a series."""
    series_id = series_details["id"]
    sections = series_details.get("sections", [])
    all_tests = []

    for sec in sections:
        sec_id = sec["id"]
        sec_name = sec.get("name", "Unknown")
        subsections = sec.get("subsections", [])

        if not subsections:
            # No subsections — fetch all tests for this section
            tests = await fetch_section_tests(context, series_id, sec_id, None, variant, api_version)
            for t in tests:
                t["_section"] = sec_name
            all_tests.extend(tests)
            print(f"  [{sec_name}] {len(tests)} tests")
        else:
            for sub in subsections:
                sub_id = sub["id"]
                sub_name = sub.get("name", "Unknown")
                tests = await fetch_section_tests(context, series_id, sec_id, sub_id, variant, api_version)
                for t in tests:
                    t["_section"] = sec_name
                    t["_subsection"] = sub_name
                all_tests.extend(tests)
                print(f"  [{sec_name} / {sub_name}] {len(tests)} tests")

        await asyncio.sleep(0.3)  # rate limit

    return all_tests


# ─── Question scraping ────────────────────────────────────────────────────

async def fetch_test_questions(context, test_id: str, variant: str, slug: str) -> dict[str, Any] | None:
    """
    Fetch a test's questions by loading the /attempt page and parsing the RSC payload.

    Returns the parsed question data, or None if the test couldn't be scraped.
    """
    # The /attempt page URL pattern
    # For tb/tb-pro: /{variant}/test-series/{slug}/test/{testId}/attempt
    # For gd: /gd/test-series/{slug}/test/{testId}/attempt
    attempt_url = f"https://repeatermock.com/{variant}/test-series/{slug}/test/{test_id}/attempt"

    # Fetch the page HTML via context.request (bypasses anti-debug JS)
    resp = await context.request.get(attempt_url, headers={
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Referer": "https://repeatermock.com/",
    })
    if resp.status != 200:
        print(f"    /attempt returned {resp.status}")
        return None

    html = await resp.text()
    if len(html) < 1000:
        print(f"    /attempt page too small ({len(html)} chars) — possibly 404 or redirect")
        return None

    # Parse questions from the RSC flight payload
    result = parse_attempt_page(html)
    if not result["questions"]:
        print(f"    No questions found in /attempt page (payload: {result['payload_size']} chars)")
        return None

    return {
        "questions": result["questions"],
        "raw_count": result["raw_count"],
        "payload_size": result["payload_size"],
    }


async def fetch_test_answers(context, test_id: str, variant: str) -> dict[str, Any] | None:
    """
    Try to fetch the answer key for a test.

    Attempts multiple approaches:
    1. POST /api/v1/attempts/{testId}/submit with empty answers
       → The response should contain the answer key after "submission"
    2. GET /api/tests/{testId}/answers (from JS bundle analysis)
    3. Fetch /solution page and parse RSC payload

    Returns the answer data, or None if not available.
    """
    api_prefix = "/api/v1" if variant in ("tb", "tb-pro") else "/api/v2"

    # Approach 1: POST /submit with empty answers
    submit_url = f"{API_BASE}{api_prefix}/attempts/{test_id}/submit"
    # Build a minimal empty submission payload
    # The payload format is unknown, but we can try common patterns
    empty_payload = json.dumps({
        "answers": [],
        "timeTaken": 0,
        "language": "en",
    })
    status, body = await fetch_via_context(context, submit_url, method="POST", body=empty_payload)
    if status == 200 and len(body) > 100:
        try:
            data = json.loads(body)
            if data.get("success") or data.get("data"):
                return {"method": "submit", "data": data}
        except json.JSONDecodeError:
            pass

    # If submit didn't work, return None — answers not available without real submission
    return None


# ─── Main scraping logic ──────────────────────────────────────────────────

async def scrape_test(context, test: dict[str, Any], variant: str, slug: str) -> dict[str, Any] | None:
    """Scrape a single test: questions + answers (if available)."""
    test_id = test["id"]
    title = test.get("title", "Unknown")

    print(f"\n  Scraping test: {title} (id={test_id})")

    # Fetch questions
    q_data = await fetch_test_questions(context, test_id, variant, slug)
    if not q_data:
        return None

    # Try to fetch answers
    a_data = await fetch_test_answers(context, test_id, variant)
    has_answers = a_data is not None

    # Build the output
    result = {
        "test_id": test_id,
        "title": title,
        "duration_minutes": test.get("duration", 60),
        "total_marks": test.get("totalMark", 200),
        "question_count": test.get("questionCount", 100),
        "languages": test.get("languages", ["English", "Hindi"]),
        "is_free": test.get("isFree", False),
        "section": test.get("_section", ""),
        "subsection": test.get("_subsection", ""),
        "has_answers": has_answers,
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "questions": q_data["questions"],
    }

    if has_answers:
        result["answers"] = a_data["data"]

    # Save to file
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = TESTS_DIR / f"{test_id}.json"
    out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False))

    print(f"    ✓ Saved {len(q_data['questions'])} questions to {out_file.name}" +
          (f" (+ answers)" if has_answers else " (no answers)"))

    return result


async def scrape_series(series_url: str, max_tests: int | None = None, scrape_answers: bool = True):
    """
    Scrape all tests in a series.

    Args:
        series_url: The RepeaterMock series URL (e.g. https://repeatermock.com/tb/test-series/ssc-cgl)
        max_tests: Limit number of tests to scrape (for testing). None = all.
        scrape_answers: Whether to attempt scraping answer keys.
    """
    config = parse_series_url(series_url)
    variant = config["variant"]
    slug = config["slug"]
    api_version = config["api_version"]

    print(f"\n{'='*60}")
    print(f"Scraping series: {series_url}")
    print(f"  Variant: {variant}, Slug: {slug}, API: {api_version}")
    print(f"{'='*60}")

    # Load cookies
    cookies = load_cookies(COOKIES_FILE)

    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        # Refresh cookies if needed
        cookies = await refresh_cookies_if_needed(context, page)
        print(f"  ✓ Authenticated as: {get_cookie_value(cookies, 'accessToken', )[:20] if get_cookie_value(cookies, 'accessToken') else 'unknown'}...")

        # Fetch series details
        print(f"\n  Fetching series details...")
        series_details = await fetch_series_details(context, slug, variant, api_version)
        series_id = series_details.get("id", "")
        series_name = series_details.get("name", "")
        sections = series_details.get("sections", [])
        print(f"  ✓ Series: {series_name}")
        print(f"  ✓ Series ID: {series_id}")
        print(f"  ✓ Sections: {len(sections)}")

        # Save series details
        SERIES_DIR.mkdir(parents=True, exist_ok=True)
        series_file = SERIES_DIR / f"{variant}_{slug}.json"
        series_file.write_text(json.dumps({
            "url": series_url,
            "variant": variant,
            "slug": slug,
            "api_version": api_version,
            "details": series_details,
            "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        }, indent=2, ensure_ascii=False))

        # Fetch all tests
        print(f"\n  Fetching all tests...")
        all_tests = await fetch_all_tests_for_series(context, series_details, variant, api_version)
        print(f"\n  ✓ Total tests found: {len(all_tests)}")

        # Filter to free tests only (can't scrape locked tests)
        free_tests = [t for t in all_tests if t.get("isFree")]
        locked_tests = [t for t in all_tests if not t.get("isFree")]
        print(f"  ✓ Free tests: {len(free_tests)}")
        print(f"  ✓ Locked tests: {len(locked_tests)} (cannot scrape questions)")

        if max_tests:
            free_tests = free_tests[:max_tests]
            print(f"  ⚠ Limiting to first {max_tests} free tests")

        # Scrape each test
        print(f"\n  Scraping {len(free_tests)} tests...")
        scraped = 0
        failed = 0
        for i, test in enumerate(free_tests):
            print(f"\n  [{i+1}/{len(free_tests)}]", end="")
            try:
                result = await scrape_test(context, test, variant, slug)
                if result:
                    scraped += 1
                else:
                    failed += 1
            except Exception as e:
                print(f"    ✗ Error: {e}")
                failed += 1

            # Rate limit
            await asyncio.sleep(1.5)

            # Refresh cookies every 20 tests (access token expires in 15 min)
            if scraped > 0 and scraped % 20 == 0:
                print(f"\n  Refreshing cookies...")
                cookies = await refresh_cookies_if_needed(context, page)

        # Summary
        print(f"\n{'='*60}")
        print(f"SERIES SUMMARY: {series_name}")
        print(f"  Total tests in series: {len(all_tests)}")
        print(f"  Free tests: {len(free_tests)}")
        print(f"  Scraped successfully: {scraped}")
        print(f"  Failed: {failed}")
        print(f"  Output: {TESTS_DIR}/")
        print(f"{'='*60}")

    finally:
        # Save final cookies
        final_cookies = await context.cookies()
        save_cookies(final_cookies, COOKIES_FILE)
        await browser.close()
        await p.stop()


async def test_series_scrapable(series_url: str) -> bool:
    """
    Test if a series is scrapable. Fetches series details + first free test's questions.

    Returns True if scrapable, False otherwise.
    """
    config = parse_series_url(series_url)
    variant = config["variant"]
    slug = config["slug"]
    api_version = config["api_version"]

    print(f"\n{'='*60}")
    print(f"Testing scrapability: {series_url}")
    print(f"{'='*60}")

    try:
        cookies = load_cookies(COOKIES_FILE)
    except RuntimeError as e:
        print(f"  ✗ {e}")
        return False

    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        # Check auth
        cookies = await refresh_cookies_if_needed(context, page)

        # Fetch series details
        print(f"  Fetching series details...")
        series_details = await fetch_series_details(context, slug, variant, api_version)
        series_name = series_details.get("name", "")
        sections = series_details.get("sections", [])
        print(f"  ✓ Series: {series_name}")
        print(f"  ✓ Sections: {len(sections)}")

        # Fetch first section's tests
        if not sections:
            print(f"  ✗ No sections found")
            return False

        first_sec = sections[0]
        subsections = first_sec.get("subsections", [])

        if subsections:
            tests = await fetch_section_tests(
                context, series_details["id"], first_sec["id"],
                subsections[0]["id"], variant, api_version, limit=5
            )
        else:
            tests = await fetch_section_tests(
                context, series_details["id"], first_sec["id"],
                None, variant, api_version, limit=5
            )

        if not tests:
            print(f"  ✗ No tests found in first section")
            return False

        # Find first free test
        free_test = next((t for t in tests if t.get("isFree")), None)
        if not free_test:
            print(f"  ✗ No free tests found (all locked)")
            print(f"  Found {len(tests)} tests but none are free")
            return False

        print(f"  ✓ First free test: {free_test.get('title', 'Unknown')}")

        # Try to scrape its questions
        print(f"  Attempting to scrape questions...")
        q_data = await fetch_test_questions(context, free_test["id"], variant, slug)
        if q_data and q_data["questions"]:
            print(f"  ✓ SUCCESS! Scraped {len(q_data['questions'])} questions")
            print(f"  ✓ Series is SCRAPABLE")
            return True
        else:
            print(f"  ✗ Failed to scrape questions")
            return False

    except Exception as e:
        print(f"  ✗ Error: {e}")
        return False
    finally:
        final_cookies = await context.cookies()
        save_cookies(final_cookies, COOKIES_FILE)
        await browser.close()
        await p.stop()


async def list_series_tests(series_url: str):
    """List all tests in a series without scraping questions."""
    config = parse_series_url(series_url)
    variant = config["variant"]
    slug = config["slug"]
    api_version = config["api_version"]

    print(f"\n{'='*60}")
    print(f"Listing tests: {series_url}")
    print(f"{'='*60}")

    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        cookies = await refresh_cookies_if_needed(context, page)
        series_details = await fetch_series_details(context, slug, variant, api_version)
        all_tests = await fetch_all_tests_for_series(context, series_details, variant, api_version)

        free = [t for t in all_tests if t.get("isFree")]
        locked = [t for t in all_tests if not t.get("isFree")]

        print(f"\n  Series: {series_details.get('name', '')}")
        print(f"  Total tests: {len(all_tests)}")
        print(f"  Free: {len(free)}")
        print(f"  Locked: {len(locked)}")

        print(f"\n  First 10 free tests:")
        for t in free[:10]:
            print(f"    - {t.get('title', 'Unknown')} (id={t['id']})")

        # Save test list
        SERIES_DIR.mkdir(parents=True, exist_ok=True)
        list_file = SERIES_DIR / f"{variant}_{slug}_test_list.json"
        list_file.write_text(json.dumps({
            "series_url": series_url,
            "series_name": series_details.get("name", ""),
            "total_tests": len(all_tests),
            "free_tests": len(free),
            "locked_tests": len(locked),
            "tests": all_tests,
        }, indent=2, ensure_ascii=False))
        print(f"\n  Saved test list to {list_file}")

    finally:
        final_cookies = await context.cookies()
        save_cookies(final_cookies, COOKIES_FILE)
        await browser.close()
        await p.stop()


# ─── CLI ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="RepeaterMock Scraper")
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # scrape-series
    sp = subparsers.add_parser("scrape-series", help="Scrape all tests from a series")
    sp.add_argument("url", help="Series URL (e.g. https://repeatermock.com/tb/test-series/ssc-cgl)")
    sp.add_argument("--max-tests", type=int, default=None, help="Max tests to scrape (for testing)")
    sp.add_argument("--no-answers", action="store_true", help="Skip answer key scraping")

    # scrape-test
    sp = subparsers.add_parser("scrape-test", help="Scrape a single test by ID")
    sp.add_argument("test_id", help="Test ID (24-char hex)")
    sp.add_argument("--variant", default="tb", choices=["tb", "tb-pro", "gd"])
    sp.add_argument("--slug", default="ssc-cgl", help="Series slug (e.g. ssc-cgl)")

    # test-series
    sp = subparsers.add_parser("test-series", help="Test if a series is scrapable")
    sp.add_argument("url", help="Series URL")

    # list-series
    sp = subparsers.add_parser("list-series", help="List all tests in a series")
    sp.add_argument("url", help="Series URL")

    args = parser.parse_args()

    if args.command == "scrape-series":
        asyncio.run(scrape_series(args.url, args.max_tests, not args.no_answers))
    elif args.command == "scrape-test":
        # Build a fake test object
        test = {"id": args.test_id, "title": f"Test {args.test_id}", "duration": 60, "totalMark": 200, "questionCount": 100, "languages": ["English", "Hindi"], "isFree": True}
        async def _run():
            cookies = load_cookies(COOKIES_FILE)
            p, browser, context = await create_browser_session(cookies)
            page = await context.new_page()
            try:
                await refresh_cookies_if_needed(context, page)
                await scrape_test(context, test, args.variant, args.slug)
            finally:
                save_cookies(await context.cookies(), COOKIES_FILE)
                await browser.close()
                await p.stop()
        asyncio.run(_run())
    elif args.command == "test-series":
        result = asyncio.run(test_series_scrapable(args.url))
        sys.exit(0 if result else 1)
    elif args.command == "list-series":
        asyncio.run(list_series_tests(args.url))
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
