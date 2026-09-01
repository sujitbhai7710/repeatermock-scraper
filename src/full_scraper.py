"""
Enhanced scraper that captures questions + answer keys + solutions + analysis
from RepeaterMock in a single pass.

For each test, it fetches 3 pages:
1. /attempt → questions (100 questions with multilingual text + options)
2. /solution → answersData (correctOption + multilingual solutions + images)
3. /analysis → analysisData (rank, percentile, cutoffs, average, marks distribution)

The solution and analysis pages only return data if the test has been attempted.
For tests without attempts, only questions are available.
"""
import asyncio
import json
import re
import time
from pathlib import Path
from typing import Any

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.cookie_manager import load_cookies, save_cookies
from src.scraper import (
    create_browser_session, refresh_cookies_if_needed, COOKIES_FILE,
    TESTS_DIR, parse_series_url, fetch_series_details, fetch_all_tests_for_series,
)
from src.question_parser import extract_flight_payload, parse_question_objects, clean_question, thorough_unescape
from src.submit_attempt import submit_attempt


def extract_json_object(payload: str, key: str) -> dict | None:
    """Extract a JSON object by its key from the RSC payload using brace matching."""
    search = f'"{key}":{{'
    idx = payload.find(search)
    if idx < 0:
        return None

    start = payload.find('{', idx + len(key) + 2)
    depth = 0
    in_str = False
    esc = False

    for j in range(start, len(payload)):
        c = payload[j]
        if esc:
            esc = False
            continue
        if c == '\\':
            esc = True
            continue
        if c == '"':
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(payload[start:j+1])
                except json.JSONDecodeError:
                    return None
    return None


async def fetch_with_auto_refresh(context, url, original_cookies, on_refresh=None, method="GET", body=None, max_retries=2):
    """Fetch a URL with auto-refresh on 401.

    Uses original_cookies (manually set as Cookie header) instead of context cookies
    (which may be wiped by page.goto). If the response is 401, calls on_refresh()
    to get new cookies, updates original_cookies in place, and retries.

    Returns: (status, text) tuple
    """
    for attempt in range(max_retries + 1):
        # Build Cookie header from original_cookies (includes httpOnly)
        cookie_str = "; ".join(
            f'{c["name"]}={c["value"]}' for c in original_cookies
            if "repeatermock" in c.get("domain", "")
        )
        headers = {
            "Accept": "text/html,application/xhtml+xml,*/*",
            "Cookie": cookie_str,
            "Origin": "https://repeatermock.com",
            "Referer": "https://repeatermock.com/",
        }
        if method == "POST":
            headers["Content-Type"] = "application/json"

        try:
            if method == "GET":
                resp = await context.request.get(url, headers=headers)
            else:
                resp = await context.request.post(url, headers=headers, data=body or "{}")
            text = await resp.text()

            # If 401 and we haven't exhausted retries, refresh and retry
            if resp.status == 401 and attempt < max_retries and on_refresh is not None:
                print(f"    ↻ 401 received — auto-refreshing cookies (attempt {attempt+1}/{max_retries})...", flush=True)
                new_cookies = await on_refresh()
                if new_cookies:
                    # Update original_cookies IN PLACE so caller sees new tokens
                    for i, c in enumerate(original_cookies):
                        for nc in new_cookies:
                            if c.get("name") == nc.get("name") and c.get("domain") == nc.get("domain"):
                                original_cookies[i] = nc
                                break
                    continue  # Retry with new cookies
                else:
                    print(f"    ⚠ Refresh failed — returning 401 response", flush=True)

            return resp.status, text
        except Exception as e:
            if attempt < max_retries:
                print(f"    ⚠ Fetch error (attempt {attempt+1}): {e} — retrying...", flush=True)
                await asyncio.sleep(1)
                continue
            return 0, f"ERROR: {e}"

    return 0, "ERROR: max retries exceeded"


async def scrape_test_full(context, page, test: dict, variant: str, slug: str, original_cookies: list[dict] = None, on_submit_401=None) -> dict | None:
    """Scrape a single test: questions + answers + solutions + analysis.

    Args:
        on_submit_401: async callable that refreshes cookies and returns the new
                       cookies list. Called when submit returns 401 session_expired.
                       The new cookies are then used for subsequent requests.
    """
    test_id = test["id"]
    title = test.get("title", "Unknown")
    base_url = f"https://repeatermock.com/{variant}/test-series/{slug}/test/{test_id}"

    print(f"  Scraping: {title[:60]} (id={test_id})", flush=True)

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
        "platform": variant,
        "slug": slug,
        "series_url": f"https://repeatermock.com/{variant}/test-series/{slug}",
        "scraped_at": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "questions": [],
        "answers": {},
        "analysis": {},
        "has_answers": False,
        "has_analysis": False,
    }

    # If original_cookies not provided, use page context (fallback)
    if original_cookies is None:
        original_cookies = await context.cookies()

    # 1. Fetch /attempt page → questions (with auto-refresh on 401)
    try:
        status, html = await fetch_with_auto_refresh(
            context, f"{base_url}/attempt", original_cookies, on_refresh=on_submit_401
        )
        if status == 200 and len(html) > 5000:
            payload = extract_flight_payload(html)
            raw_qs = parse_question_objects(payload)
            result["questions"] = [clean_question(q) for q in raw_qs]
            print(f"    ✓ {len(result['questions'])} questions", flush=True)
        else:
            print(f"    ✗ /attempt returned {status} ({len(html)} bytes)", flush=True)
            return None
    except Exception as e:
        print(f"    ✗ /attempt error: {e}", flush=True)
        return None

    # 1b. Submit dummy attempt (so /solution and /analysis return data)
    if result["questions"]:
        print(f"    Submitting dummy attempt...", flush=True)
        # Try submit. If 401, refresh cookies via callback and retry once.
        submitted = await submit_attempt(
            context, page, test_id, result["questions"], variant, slug,
            original_cookies=original_cookies,
        )
        if not submitted and on_submit_401 is not None and original_cookies is not None:
            print(f"    ⚠ Submit failed — refreshing cookies and retrying once...", flush=True)
            try:
                new_cookies = await on_submit_401()
                if new_cookies:
                    # Update the original_cookies list IN PLACE so submit_attempt sees new tokens
                    for i, c in enumerate(original_cookies):
                        for nc in new_cookies:
                            if c.get("name") == nc.get("name") and c.get("domain") == nc.get("domain"):
                                original_cookies[i] = nc
                                break
                    submitted = await submit_attempt(
                        context, page, test_id, result["questions"], variant, slug,
                        original_cookies=original_cookies,
                    )
            except Exception as e:
                print(f"    ⚠ Refresh callback error: {e}", flush=True)

        if submitted:
            print(f"    ✓ Attempt submitted — solutions/analysis will have data", flush=True)
            await asyncio.sleep(2)  # Wait for server to process
        else:
            print(f"    ⚠ Submit failed — will try /solution anyway", flush=True)

    # 2. Fetch /solution page → answer keys + solutions (with auto-refresh on 401)
    try:
        sol_status, sol_html = await fetch_with_auto_refresh(
            context, f"{base_url}/solution", original_cookies, on_refresh=on_submit_401
        )
        if sol_status == 200 and len(sol_html) > 30000:
            sol_payload = extract_flight_payload(sol_html)
            # Extract answersData
            answers_data = extract_json_object(sol_payload, "answersData")
            if answers_data and len(answers_data) > 5:
                # Thoroughly unescape all solution values (they're double-escaped HTML)
                for qid, ans in answers_data.items():
                    sol = ans.get("sol", {})
                    for lang_code, lang_data in sol.items():
                        if isinstance(lang_data, dict) and lang_data.get("value"):
                            lang_data["value"] = thorough_unescape(lang_data["value"])
                result["answers"] = answers_data
                result["has_answers"] = True
                print(f"    ✓ {len(answers_data)} answer keys + solutions", flush=True)
            else:
                print(f"    ⚠ No answersData in solution page (test not attempted)", flush=True)
        else:
            print(f"    ⚠ /solution returned {sol_status} ({len(sol_html)} bytes) — no attempt data", flush=True)
    except Exception as e:
        print(f"    ⚠ /solution error: {e}", flush=True)

    # 3. Fetch /analysis page → rank, cutoffs, percentile (with auto-refresh on 401)
    try:
        ana_status, ana_html = await fetch_with_auto_refresh(
            context, f"{base_url}/analysis", original_cookies, on_refresh=on_submit_401
        )
        if ana_status == 200 and len(ana_html) > 30000:
            ana_payload = extract_flight_payload(ana_html)
            # Extract analysisData
            analysis_data = extract_json_object(ana_payload, "analysisData")
            if analysis_data:
                result["analysis"] = analysis_data
                result["has_analysis"] = True
                # Extract cutoffs from the raw payload
                ts = analysis_data.get("ts", {})
                analysis = analysis_data.get("analysis", {})
                rank = ts.get("rank", "N/A")
                percentile = ts.get("percentile", "N/A")
                avg = analysis.get("avgMarks", "N/A")
                total = analysis.get("totalStudents", "N/A")
                print(f"    ✓ Analysis: rank={rank}, percentile={percentile:.1f}%, avg={avg}, students={total}", flush=True)
            else:
                print(f"    ⚠ No analysisData (test not attempted)", flush=True)
        else:
            print(f"    ⚠ /analysis returned {ana_status} — no attempt data", flush=True)
    except Exception as e:
        print(f"    ⚠ /analysis error: {e}", flush=True)

    # Save to file — ONLY if fully scraped (has Q + A + analysis)
    # Partial scrapes are NOT saved as JSON files (they'd be useless to users)
    # The status is still tracked in progress.json so the next run can retry
    TESTS_DIR.mkdir(parents=True, exist_ok=True)
    out_file = TESTS_DIR / f"{test_id}.json"

    has_q = bool(result.get("questions"))
    has_a = result.get("has_answers", False)
    has_ana = result.get("has_analysis", False)

    if has_q and has_a and has_ana:
        out_file.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"    ✓ Saved to {out_file.name} (FULL — Q+A+Sol+Ana)", flush=True)
    else:
        # Remove any stale file from a previous successful scrape
        if out_file.exists():
            out_file.unlink()
        missing = []
        if not has_q:
            missing.append("Q")
        if not has_a:
            missing.append("A")
        if not has_ana:
            missing.append("Ana")
        print(f"    ⚠ NOT saved (missing: {','.join(missing)}) — will retry next run", flush=True)

    return result


async def scrape_series_full(series_url: str, max_tests: int = 0, time_limit_minutes: int = 45):
    """Scrape a series with full data (questions + answers + analysis)."""
    config = parse_series_url(series_url)
    variant = config["variant"]
    slug = config["slug"]
    api_version = config["api_version"]

    print(f"\n{'='*60}", flush=True)
    print(f"FULL SCRAPE: {series_url}", flush=True)
    print(f"  Variant: {variant}, Time limit: {time_limit_minutes} min", flush=True)
    print(f"{'='*60}", flush=True)

    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    start_time = time.time()
    tests_scraped = 0

    try:
        cookies = await refresh_cookies_if_needed(context, page)
        if cookies is None:
            print("✗ Authentication failed. Update cookies and retry.", flush=True)
            return
        print(f"✓ Authenticated\n", flush=True)

        # Fetch series details + all tests
        details = await fetch_series_details(context, slug, variant, api_version)
        all_tests = await fetch_all_tests_for_series(context, details, variant, api_version)
        free_tests = [t for t in all_tests if t.get("isFree")]
        print(f"  Total tests: {len(all_tests)}, Free: {len(free_tests)}\n", flush=True)

        if max_tests > 0:
            free_tests = free_tests[:max_tests]

        for i, test in enumerate(free_tests):
            elapsed = time.time() - start_time
            if elapsed >= time_limit_minutes * 60:
                print(f"\n⏰ Time limit reached ({elapsed/60:.1f} min)", flush=True)
                break

            print(f"[{i+1}/{len(free_tests)}] ({int((time_limit_minutes*60-elapsed)/60)}m left)", flush=True)

            try:
                await scrape_test_full(context, test, variant, slug)
                tests_scraped += 1
            except Exception as e:
                print(f"  ✗ Error: {e}", flush=True)

            # Refresh cookies every 10 tests
            if tests_scraped > 0 and tests_scraped % 10 == 0:
                cookies = await refresh_cookies_if_needed(context, page)
                if cookies:
                    save_cookies(cookies, COOKIES_FILE)

            await asyncio.sleep(1.5)

        print(f"\n{'='*60}", flush=True)
        print(f"SUMMARY: Scraped {tests_scraped}/{len(free_tests)} tests in {(time.time()-start_time)/60:.1f} min", flush=True)

    finally:
        save_cookies(await context.cookies(), COOKIES_FILE)
        await browser.close()
        await p.stop()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Series URL")
    parser.add_argument("--max-tests", type=int, default=0)
    parser.add_argument("--time-limit", type=int, default=45)
    args = parser.parse_args()
    asyncio.run(scrape_series_full(args.url, args.max_tests, args.time_limit))
