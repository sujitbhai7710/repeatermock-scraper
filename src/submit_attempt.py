"""
Submit a dummy test attempt to RepeaterMock.

This is needed because /solution and /analysis pages only return data
(answer keys, solutions, rank, cutoffs) if the user has a submitted attempt.

The submit API endpoint is:
  POST https://api.repeatermock.com/api/v1/attempts/{testId}/submit

The payload format is discovered by trying multiple formats.
Once a working format is found, it's saved for reuse.

For a dummy attempt:
- All questions are skipped (selectedOption: null)
- Time taken is 1 second (minimum)
- Language is "en"
- Interface is "classic"
"""
import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.cookie_manager import load_cookies, save_cookies
from src.scraper import create_browser_session, refresh_cookies_if_needed, COOKIES_FILE, fetch_via_context

API_BASE = "https://api.repeatermock.com"
WORKING_FORMAT_FILE = Path(__file__).parent.parent / "data" / "submit_format.json"

# Global pacing for attempt starts — the server 429s ("starting tests
# unusually fast") if starts come too quickly. One lock for ALL parallel
# workers enforces a minimum interval between starts.
_start_lock = asyncio.Lock()
_last_start = [0.0]
MIN_START_INTERVAL = float(__import__("os").environ.get("START_MIN_INTERVAL", "10"))


async def _start_attempt(context, start_url: str, cookie_str: str):
    """POST /attempts/{id}/start with global pacing. Returns (status, body)."""
    async with _start_lock:
        wait = _last_start[0] + MIN_START_INTERVAL - time.time()
        if wait > 0:
            await asyncio.sleep(wait)
        status, body = await fetch_via_context_with_cookies(
            context, start_url, method="POST", body="{}", cookie_str=cookie_str)
        _last_start[0] = time.time()
        return status, body


async def fetch_via_context_with_cookies(context, url, method="POST", body=None, cookie_str=""):
    """Fetch using context.request but with explicit Cookie header (includes httpOnly)."""
    headers = {
        "Accept": "application/json",
        "Origin": "https://repeatermock.com",
        "Referer": "https://repeatermock.com/",
    }
    if cookie_str:
        headers["Cookie"] = cookie_str
    if method == "POST":
        headers["Content-Type"] = "application/json"
    try:
        if method == "POST":
            resp = await context.request.post(url, headers=headers, data=body or "{}")
        else:
            resp = await context.request.get(url, headers=headers)
        return resp.status, await resp.text()
    except Exception as e:
        return 0, f"ERROR: {e}"


def load_working_format() -> dict | None:
    """Load the last known working submit format."""
    if WORKING_FORMAT_FILE.exists():
        return json.loads(WORKING_FORMAT_FILE.read_text(encoding="utf-8"))
    return None


def save_working_format(fmt: dict):
    """Save the working submit format for future runs."""
    WORKING_FORMAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKING_FORMAT_FILE.write_text(json.dumps(fmt, indent=2), encoding="utf-8")


def build_payloads(test_id: str, questions: list[dict]) -> list[dict]:
    """Build multiple candidate payloads to try."""
    # Build answer entries for all questions (all skipped)
    answer_entries = []
    for q in questions:
        qid = q.get("id") or q.get("_id", "")
        answer_entries.append({
            "questionId": qid,
            "selectedOption": None,
            "markedForReview": False,
            "timeSpent": 0,
        })

    return [
        # Format 1: Empty answers array
        {
            "name": "empty_answers",
            "payload": {
                "answers": [],
                "timeTaken": 1,
                "language": "en",
                "interface": "classic",
            }
        },
        # Format 2: Answers with all questions skipped
        {
            "name": "all_skipped",
            "payload": {
                "answers": answer_entries,
                "timeTaken": 1,
                "language": "en",
                "interface": "classic",
            }
        },
        # Format 3: Minimal — just testId
        {
            "name": "minimal",
            "payload": {
                "testId": test_id,
                "answers": [],
                "timeTaken": 1,
                "language": "en",
            }
        },
        # Format 4: With attemptNo
        {
            "name": "with_attemptNo",
            "payload": {
                "answers": [],
                "timeTaken": 1,
                "language": "en",
                "attemptNo": 1,
                "interface": "classic",
            }
        },
        # Format 5: Answers as object keyed by questionId
        {
            "name": "answers_object",
            "payload": {
                "answers": {q.get("id", ""): None for q in questions},
                "timeTaken": 1,
                "language": "en",
                "interface": "classic",
            }
        },
        # Format 6: With sectionWiseData
        {
            "name": "section_wise",
            "payload": {
                "answers": [],
                "timeTaken": 1,
                "language": "en",
                "interface": "classic",
                "sectionWiseData": [],
                "markedQuestions": [],
                "bookmarkedQuestions": [],
            }
        },
    ]


async def submit_attempt(context, page, test_id: str, questions: list[dict], variant: str = "tb", slug: str = "ssc-cgl", original_cookies: list[dict] = None) -> bool:
    """
    Submit a dummy attempt for a test.
    
    KEY FIX: The /attempt page must be visited via page.goto() to create an
    active attempt on the server. But page.goto() wipes httpOnly cookies,
    so we need to pass original_cookies for the Cookie header in the submit
    API call.
    
    Also: RepeaterMock rate-limits attempt creation. After submitting a test,
    the server blocks new attempt creation for a few seconds. We add a delay
    between tests to avoid this.
    """
    api_prefix = "/api/v1" if variant in ("tb", "tb-pro") else "/api/v2"
    submit_url = f"{API_BASE}{api_prefix}/attempts/{test_id}/submit"
    attempt_url = f"https://repeatermock.com/{variant}/test-series/{slug}/test/{test_id}/attempt"
    
    # Build cookie string from original cookies (httpOnly ones included)
    if original_cookies:
        cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in original_cookies if "repeatermock" in c.get("domain", ""))
    else:
        cookie_str = ""
    
    # Step 1: Start the attempt via the API. The /attempt page's JS does exactly
    # this call (POST /attempts/{id}/start); calling it directly is much faster
    # and avoids the site's anti-debug page, which detects automated browsers
    # and WIPES the session cookies on browser page loads ("you-idiot.html").
    print(f"  Starting attempt via API...", flush=True)
    start_url = f"{API_BASE}{api_prefix}/attempts/{test_id}/start"
    started = False
    for wait_s in (0, 30, 120, 300):
        if wait_s:
            print(f"  ⚠ Start rate-limited (429) — waiting {wait_s}s...", flush=True)
            await asyncio.sleep(wait_s)
        status, body = await _start_attempt(context, start_url, cookie_str)
        if status in (200, 201, 204):
            started = True
            print(f"  ✓ Attempt started ({status})", flush=True)
            break
        if status == 429:
            continue
        print(f"  ⚠ start → {status}: {body[:80]}", flush=True)
        # Unexpected status (404/401/auth) — fall back to the legacy page load
        try:
            await page.goto(attempt_url, timeout=30000, wait_until="domcontentloaded")
            await asyncio.sleep(8)
        except Exception as e:
            print(f"  ⚠ page.goto failed: {e}", flush=True)
        break
    if not started:
        print(f"  ⚠ Attempt start not confirmed — will try submit anyway", flush=True)
    
    # Step 2: Now try to submit using the original cookies (not context.cookies which got wiped)
    # Check if we already have a working format
    working = load_working_format()
    if working:
        print(f"  Using saved submit format: {working['name']}", flush=True)
        payload = working["payload"].copy()
        if "testId" in payload:
            payload["testId"] = test_id

        s, b = await fetch_via_context_with_cookies(context, submit_url, method="POST", body=json.dumps(payload), cookie_str=cookie_str)
        if s == 200:
            print(f"  ✓ Submit succeeded with saved format", flush=True)
            return True
        elif s == 401 or "session_expired" in b:
            # Access token dead — bail out so caller refreshes + retries
            print(f"  ✗ 401 session_expired from saved format — aborting (caller will refresh)", flush=True)
            return False
        else:
            print(f"  ⚠ Saved format failed ({s}), trying others...", flush=True)

    # Try all payload formats
    payloads = build_payloads(test_id, questions)
    for fmt in payloads:
        print(f"  Trying format: {fmt['name']}...", flush=True)
        s, b = await fetch_via_context_with_cookies(context, submit_url, method="POST", body=json.dumps(fmt["payload"]), cookie_str=cookie_str)
        print(f"    Status: {s}, Response: {b[:200]}", flush=True)

        if s == 200:
            print(f"  ✓✓✓ SUCCESS with format: {fmt['name']}!", flush=True)
            save_working_format(fmt)
            return True
        elif s == 401 or "session_expired" in b:
            # Access token expired — bail out IMMEDIATELY so caller can refresh + retry
            # (don't waste time trying all 6 formats with a dead token)
            print(f"  ✗ 401 session_expired — access token dead, aborting (caller will refresh)", flush=True)
            return False
        elif s == 429:
            print(f"  ⚠ Rate limited, waiting 10s...", flush=True)
            await asyncio.sleep(10)
            # Retry after rate limit
            s2, b2 = await fetch_via_context_with_cookies(context, submit_url, method="POST", body=json.dumps(fmt["payload"]), cookie_str=cookie_str)
            if s2 == 200:
                print(f"  ✓✓✓ SUCCESS after rate limit wait!", flush=True)
                save_working_format(fmt)
                return True
        elif s == 409:
            # Conflict — attempt already exists
            print(f"  ✓ Attempt already exists (409) — treating as success", flush=True)
            return True
        elif s == 404:
            # No active attempt — try the START endpoint directly (the legacy
            # page.goto triggers the site's anti-debug and wipes cookies)
            print(f"  ⚠ No active attempt — calling start endpoint...", flush=True)
            s3, b3 = await _start_attempt(
                context, start_url, cookie_str)
            print(f"    start → {s3}: {b3[:100]}", flush=True)
            if s3 == 429:
                await asyncio.sleep(120)
                s3, b3 = await _start_attempt(
                    context, start_url, cookie_str)
                print(f"    start retry → {s3}: {b3[:100]}", flush=True)
            # Retry submit
            s2, b2 = await fetch_via_context_with_cookies(context, submit_url, method="POST", body=json.dumps(fmt["payload"]), cookie_str=cookie_str)
            if s2 == 200:
                print(f"  ✓✓✓ SUCCESS after retry!", flush=True)
                save_working_format(fmt)
                return True

    print(f"  ✗ All payload formats failed", flush=True)
    return False


async def main():
    """Test the submit function with a single test."""
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("test_id", help="Test ID to submit attempt for")
    parser.add_argument("--variant", default="tb", choices=["tb", "tb-pro", "gd"])
    parser.add_argument("--slug", default="ssc-cgl")
    args = parser.parse_args()

    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        cookies = await refresh_cookies_if_needed(context, page)
        if cookies is None:
            print("✗ Auth failed", flush=True)
            return

        # Fetch questions first (needed for payload)
        from src.question_parser import extract_flight_payload, parse_question_objects, clean_question
        resp = await context.request.get(
            f"https://repeatermock.com/{args.variant}/test-series/{args.slug}/test/{args.test_id}/attempt",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        html = await resp.text()
        payload = extract_flight_payload(html)
        raw_qs = parse_question_objects(payload)
        questions = [clean_question(q) for q in raw_qs]
        print(f"Found {len(questions)} questions", flush=True)

        # Submit attempt
        success = await submit_attempt(context, args.test_id, questions, args.variant)
        if success:
            print(f"\n✓ Attempt submitted! Now /solution and /analysis should have data.", flush=True)
        else:
            print(f"\n✗ Submit failed.", flush=True)

    finally:
        save_cookies(await context.cookies(), COOKIES_FILE)
        await browser.close()
        await p.stop()


if __name__ == "__main__":
    asyncio.run(main())
