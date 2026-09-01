"""
Try different payload formats for POST /api/v1/attempts/{testId}/submit
to find the correct format that RepeaterMock accepts.

We'll try submitting to a test that HASN'T been attempted yet (so we can
verify the submit worked by checking if /solution returns data afterwards).

Test ID: 6a0f3ef125f9d428c136a83a (SSC CGL 2025 Shift 1 — not attempted by polturaja7)
"""
import asyncio
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
load_dotenv(PROJECT_ROOT / ".env")

from src.cookie_manager import load_cookies, save_cookies
from src.scraper import create_browser_session, refresh_cookies_if_needed, COOKIES_FILE, fetch_via_context

API_BASE = "https://api.repeatermock.com"
TEST_ID = "6a0f3ef125f9d428c136a83a"  # SSC CGL 2025 Shift 1 (not attempted by polturaja7)

# Different payload formats to try
PAYLOAD_FORMATS = [
    # Format 1: Empty answers, minimal fields
    {
        "name": "minimal_empty",
        "payload": {
            "answers": [],
            "timeTaken": 0,
            "language": "en",
        }
    },
    # Format 2: With interface field
    {
        "name": "with_interface",
        "payload": {
            "answers": [],
            "timeTaken": 0,
            "language": "en",
            "interface": "classic",
        }
    },
    # Format 3: With attemptNo
    {
        "name": "with_attemptNo",
        "payload": {
            "answers": [],
            "timeTaken": 0,
            "language": "en",
            "attemptNo": 1,
        }
    },
    # Format 4: answers as object (not array)
    {
        "name": "answers_object",
        "payload": {
            "answers": {},
            "timeTaken": 0,
            "language": "en",
        }
    },
    # Format 5: With markedQuestions and bookmarkedQuestions
    {
        "name": "with_marked_bookmarked",
        "payload": {
            "answers": [],
            "timeTaken": 0,
            "language": "en",
            "markedQuestions": [],
            "bookmarkedQuestions": [],
        }
    },
    # Format 6: Minimal — just testId
    {
        "name": "just_testId",
        "payload": {
            "testId": TEST_ID,
        }
    },
    # Format 7: With section-wise data
    {
        "name": "section_wise",
        "payload": {
            "answers": [],
            "timeTaken": 0,
            "language": "en",
            "interface": "classic",
            "sectionWiseData": [],
        }
    },
]


async def main():
    print("=== Submit API Payload Format Discovery ===\n", flush=True)

    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        cookies = await refresh_cookies_if_needed(context, page)
        if cookies is None:
            print("✗ Auth failed — cookies may be expired", flush=True)
            return
        print("✓ Authenticated\n", flush=True)

        # First, check if this test already has an attempt
        print(f"Checking if test {TEST_ID} already has an attempt...", flush=True)
        s, b = await fetch_via_context(context, f"{API_BASE}/api/v1/attempts/{TEST_ID}/submit")
        # This will likely 404 since we haven't started an attempt

        # Try each payload format
        for fmt in PAYLOAD_FORMATS:
            print(f"\n--- Trying format: {fmt['name']} ---", flush=True)
            print(f"  Payload: {json.dumps(fmt['payload'])[:200]}", flush=True)

            submit_url = f"{API_BASE}/api/v1/attempts/{TEST_ID}/submit"
            s, b = await fetch_via_context(context, submit_url, method="POST", body=json.dumps(fmt["payload"]))
            print(f"  Status: {s}", flush=True)
            print(f"  Response: {b[:500]}", flush=True)

            if s == 200:
                print(f"  ✓✓✓ SUCCESS! This payload format works!", flush=True)

                # Verify by fetching /solution
                print(f"\n  Verifying: fetching /solution page...", flush=True)
                resp2 = await context.request.get(
                    f"https://repeatermock.com/tb/test-series/ssc-cgl/test/{TEST_ID}/solution",
                    headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
                )
                sol_html = await resp2.text()
                print(f"  /solution status: {resp2.status}, size: {len(sol_html)}", flush=True)

                if len(sol_html) > 50000:
                    print(f"  ✓✓✓ SOLUTION PAGE HAS DATA! Submit worked!", flush=True)
                    # Save the solution page for parsing
                    (PROJECT_ROOT / "data" / "submit_verified_solution.html").write_text(sol_html, encoding="utf-8")
                else:
                    print(f"  ⚠ Solution page still small — submit may not have worked", flush=True)

                break
            elif s == 404:
                print(f"  ✗ 404 — endpoint not found or no active attempt", flush=True)
            elif s == 400:
                print(f"  ✗ 400 — bad request (payload format wrong)", flush=True)
            elif s == 401:
                print(f"  ✗ 401 — auth issue", flush=True)
            elif s == 429:
                print(f"  ⚠ 429 — rate limited, waiting 10s...", flush=True)
                await asyncio.sleep(10)

        # Also try the /api/v1/attempts/in-progress endpoint to see if there's an active attempt
        print(f"\n=== Checking in-progress attempts ===", flush=True)
        s, b = await fetch_via_context(context, f"{API_BASE}/api/v1/attempts/in-progress")
        print(f"  Status: {s}", flush=True)
        print(f"  Response: {b[:300]}", flush=True)

        # Try a "start attempt" pattern — maybe we need to POST to create an attempt first
        print(f"\n=== Trying to start an attempt ===", flush=True)
        start_urls = [
            (f"{API_BASE}/api/v1/attempts/{TEST_ID}/start", "POST"),
            (f"{API_BASE}/api/v1/attempts/start", "POST"),
            (f"{API_BASE}/api/v1/test-series/6960d60ab4975a8fe9557df7/sections/6960ef002ba086d1322b9893/tests/{TEST_ID}/start", "POST"),
            (f"{API_BASE}/api/v1/attempts", "POST"),
        ]
        start_payloads = [
            json.dumps({"testId": TEST_ID, "language": "en", "interface": "classic"}),
            json.dumps({"testId": TEST_ID}),
            json.dumps({}),
        ]

        for url, method in start_urls:
            for payload in start_payloads:
                s, b = await fetch_via_context(context, url, method=method, body=payload)
                if s != 404:
                    print(f"  [{s}] {method} {url}", flush=True)
                    print(f"    payload: {payload[:100]}", flush=True)
                    print(f"    response: {b[:300]}", flush=True)
                    if s == 200:
                        print(f"    ✓✓✓ Found start endpoint!", flush=True)
                        break
            if s == 200:
                break

    finally:
        save_cookies(await context.cookies(), COOKIES_FILE)
        await browser.close()
        await p.stop()

asyncio.run(main())
