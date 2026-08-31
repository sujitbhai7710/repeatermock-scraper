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


def load_working_format() -> dict | None:
    """Load the last known working submit format."""
    if WORKING_FORMAT_FILE.exists():
        return json.loads(WORKING_FORMAT_FILE.read_text())
    return None


def save_working_format(fmt: dict):
    """Save the working submit format for future runs."""
    WORKING_FORMAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    WORKING_FORMAT_FILE.write_text(json.dumps(fmt, indent=2))


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


async def submit_attempt(context, test_id: str, questions: list[dict], variant: str = "tb") -> bool:
    """
    Submit a dummy attempt for a test.
    
    Returns True if the submit succeeded, False otherwise.
    """
    api_prefix = "/api/v1" if variant in ("tb", "tb-pro") else "/api/v2"
    submit_url = f"{API_BASE}{api_prefix}/attempts/{test_id}/submit"

    # Check if we already have a working format
    working = load_working_format()
    if working:
        print(f"  Using saved submit format: {working['name']}", flush=True)
        payload = working["payload"].copy()
        # Update testId-specific fields if needed
        if "testId" in payload:
            payload["testId"] = test_id

        s, b = await fetch_via_context(context, submit_url, method="POST", body=json.dumps(payload))
        if s == 200:
            print(f"  ✓ Submit succeeded with saved format", flush=True)
            return True
        else:
            print(f"  ⚠ Saved format failed ({s}), trying others...", flush=True)

    # Try all payload formats
    payloads = build_payloads(test_id, questions)
    for fmt in payloads:
        print(f"  Trying format: {fmt['name']}...", flush=True)
        s, b = await fetch_via_context(context, submit_url, method="POST", body=json.dumps(fmt["payload"]))
        print(f"    Status: {s}, Response: {b[:200]}", flush=True)

        if s == 200:
            print(f"  ✓✓✓ SUCCESS with format: {fmt['name']}!", flush=True)
            save_working_format(fmt)
            return True
        elif s == 429:
            print(f"  ⚠ Rate limited, waiting 10s...", flush=True)
            await asyncio.sleep(10)
        elif s == 409:
            # Conflict — attempt already exists
            print(f"  ✓ Attempt already exists (409) — treating as success", flush=True)
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
