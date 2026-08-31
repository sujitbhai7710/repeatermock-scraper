"""
Scrape the analysis + solution pages for a test that's already been attempted.
Test 6a0f3f2c0b97114ca22cf188 has a submitted attempt, so its analysis/solution
pages should contain real answer keys, solutions, rank, cutoffs, etc.

This script:
1. Fetches /attempt page → extracts questions
2. Fetches /solution page → extracts answer keys + explanations + images
3. Fetches /analysis page → extracts rank, cutoff, percentile, sectional summary
4. Saves everything in a combined JSON
"""
import asyncio
import json
import re
import html as html_module
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.cookie_manager import load_cookies, save_cookies
from src.scraper import create_browser_session, refresh_cookies_if_needed, COOKIES_FILE
from src.question_parser import extract_flight_payload, parse_question_objects, clean_question, thorough_unescape

DUMP = PROJECT_ROOT / "data" / "full_scrape"
DUMP.mkdir(parents=True, exist_ok=True)

# The test that already has a submitted attempt
TEST_ID = "6a0f3f2c0b97114ca22cf188"
VARIANT = "tb"
SLUG = "ssc-cgl"


def extract_all_json_objects(payload: str) -> list:
    """Extract ALL JSON objects from the RSC payload using brace matching."""
    objects = []
    i = 0
    while i < len(payload):
        if payload[i] == '{':
            depth = 0
            in_str = False
            esc = False
            start = i
            for j in range(i, len(payload)):
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
                        obj_str = payload[start:j+1]
                        try:
                            obj = json.loads(obj_str)
                            objects.append(obj)
                        except:
                            pass
                        i = j + 1
                        break
            else:
                break
        else:
            i += 1
    return objects


async def main():
    print("=== Full Scrape: Questions + Answers + Solutions + Analysis ===\n", flush=True)
    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        cookies = await refresh_cookies_if_needed(context, page)
        print("✓ Authenticated\n", flush=True)

        # ─── 1. Fetch /attempt page (questions) ────────────────────────
        print("=== 1. /attempt page ===", flush=True)
        resp = await context.request.get(
            f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}/attempt",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        attempt_html = await resp.text()
        print(f"  Status: {resp.status}, Size: {len(attempt_html)}", flush=True)
        (DUMP / f"attempt.html").write_text(attempt_html, encoding="utf-8")

        attempt_payload = extract_flight_payload(attempt_html)
        raw_questions = parse_question_objects(attempt_payload)
        questions = [clean_question(q) for q in raw_questions]
        print(f"  Questions found: {len(questions)}", flush=True)

        # ─── 2. Fetch /solution page (answer keys + explanations) ──────
        print(f"\n=== 2. /solution page ===", flush=True)
        resp2 = await context.request.get(
            f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}/solution",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        solution_html = await resp2.text()
        print(f"  Status: {resp2.status}, Size: {len(solution_html)}", flush=True)
        (DUMP / f"solution.html").write_text(solution_html, encoding="utf-8")

        solution_payload = extract_flight_payload(solution_html)
        print(f"  Solution payload: {len(solution_payload)} chars", flush=True)
        (DUMP / "solution_payload.txt").write_text(solution_payload, encoding="utf-8")

        # Check if solution page has real data (not "no attempt" page)
        has_solution_data = "No submitted attempt" not in solution_payload and len(solution_payload) > 30000
        print(f"  Has real solution data: {has_solution_data}", flush=True)

        if has_solution_data:
            # Extract ALL JSON objects from the solution payload
            print(f"  Extracting JSON objects from solution payload...", flush=True)
            all_objects = extract_all_json_objects(solution_payload)
            print(f"  Found {len(all_objects)} JSON objects", flush=True)

            # Look for objects with answer/solution fields
            answer_objects = []
            for obj in all_objects:
                if not isinstance(obj, dict):
                    continue
                # Check for answer-related fields
                keys = set(obj.keys())
                if any(k in keys for k in ['ans', 'correctAns', 'correctOption', 'answer', 'isCorrect', 'solution', 'explanation', 'correctAnswer']):
                    answer_objects.append(obj)
                # Also check for objects with _id and numeric answer
                if '_id' in obj and any(k in obj for k in ['ans', 'correct', 'answer']):
                    answer_objects.append(obj)

            print(f"  Objects with answer fields: {len(answer_objects)}", flush=True)
            for obj in answer_objects[:5]:
                print(f"    Keys: {list(obj.keys())[:15]}", flush=True)
                for k, v in obj.items():
                    if k in ['ans', 'correctAns', 'correctOption', 'answer', 'isCorrect', 'solution', 'explanation', 'correctAnswer', '_id']:
                        vstr = str(v)[:200]
                        print(f"      {k}: {vstr}", flush=True)

            # Also search for specific patterns in the raw payload
            print(f"\n  Searching payload for answer patterns...", flush=True)
            for pat in [
                r'"ans"\s*:\s*"?(\w+)"?',
                r'"correctAns"\s*:\s*"?(\w+)"?',
                r'"correctOption"\s*:\s*"?(\w+)"?',
                r'"answer"\s*:\s*"?(\w+)"?',
                r'"isCorrect"\s*:\s*(true|false)',
                r'"solution"\s*:\s*"([^"]{10,})"',
                r'"explanation"\s*:\s*"([^"]{10,})"',
                r'"correctAnswer"\s*:\s*"?(\w+)"?',
            ]:
                matches = re.findall(pat, solution_payload)
                if matches:
                    print(f"    {pat[:40]}: {len(matches)} matches — first: {matches[:3]}", flush=True)

            # Look for question _id → answer mapping
            print(f"\n  Looking for _id → answer mappings...", flush=True)
            id_pattern = r'"_id":"([a-f0-9]{24})"[^}]{0,300}"(?:ans|correct|answer)"\s*:\s*"?(\w+)"?'
            id_matches = re.findall(id_pattern, solution_payload)
            print(f"    Direct _id→answer: {len(id_matches)} matches", flush=True)
            for m in id_matches[:5]:
                print(f"      {m[0]} → {m[1]}", flush=True)

        # ─── 3. Fetch /analysis page (rank, cutoff, percentile) ────────
        print(f"\n=== 3. /analysis page ===", flush=True)
        resp3 = await context.request.get(
            f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}/analysis",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        analysis_html = await resp3.text()
        print(f"  Status: {resp3.status}, Size: {len(analysis_html)}", flush=True)
        (DUMP / f"analysis.html").write_text(analysis_html, encoding="utf-8")

        analysis_payload = extract_flight_payload(analysis_html)
        print(f"  Analysis payload: {len(analysis_payload)} chars", flush=True)
        (DUMP / "analysis_payload.txt").write_text(analysis_payload, encoding="utf-8")

        has_analysis_data = "No submitted attempt" not in analysis_payload and len(analysis_payload) > 30000
        print(f"  Has real analysis data: {has_analysis_data}", flush=True)

        if has_analysis_data:
            # Extract ALL JSON objects from analysis payload
            analysis_objects = extract_all_json_objects(analysis_payload)
            print(f"  Found {len(analysis_objects)} JSON objects", flush=True)

            # Look for rank, cutoff, percentile, etc.
            for obj in analysis_objects:
                if not isinstance(obj, dict):
                    continue
                keys = set(obj.keys())
                if any(k in keys for k in ['rank', 'cutoff', 'percentile', 'score', 'accuracy', 'attempted', 'average', 'median', 'topperMarks']):
                    print(f"\n  Analysis object: keys={list(obj.keys())[:20]}", flush=True)
                    for k, v in obj.items():
                        print(f"    {k}: {str(v)[:150]}", flush=True)

            # Search for specific patterns
            print(f"\n  Searching for analysis patterns...", flush=True)
            for pat, name in [
                (r'"rank"\s*:\s*"?(\w+)"?', "rank"),
                (r'"percentile"\s*:\s*"?([\d.]+)"?', "percentile"),
                (r'"score"\s*:\s*"?(-?[\d.]+)"?', "score"),
                (r'"accuracy"\s*:\s*"?([\d.]+)"?', "accuracy"),
                (r'"attempted"\s*:\s*"?(\d+)"?', "attempted"),
                (r'"average"\s*:\s*"?([\d.]+)"?', "average"),
                (r'"median"\s*:\s*"?([\d.]+)"?', "median"),
                (r'"cutoff[^"]*"\s*:', "cutoff"),
                (r'"General"\s*:\s*"?([\d-]+)"?', "General cutoff"),
                (r'"OBC"\s*:\s*"?([\d-]+)"?', "OBC cutoff"),
                (r'"SC"\s*:\s*"?([\d-]+)"?', "SC cutoff"),
                (r'"ST"\s*:\s*"?([\d-]+)"?', "ST cutoff"),
                (r'"EWS"\s*:\s*"?([\d-]+)"?', "EWS cutoff"),
            ]:
                matches = re.findall(pat, analysis_payload)
                if matches:
                    print(f"    {name}: {matches[:5]}", flush=True)

        # ─── 4. Save combined result ───────────────────────────────────
        print(f"\n=== 4. Saving combined result ===", flush=True)
        result = {
            "test_id": TEST_ID,
            "questions": questions,
            "has_solution_data": has_solution_data,
            "has_analysis_data": has_analysis_data,
        }
        (DUMP / f"full_test_{TEST_ID}.json").write_text(
            json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"  Saved {len(questions)} questions", flush=True)

    finally:
        save_cookies(await context.cookies(), COOKIES_FILE)
        await browser.close()
        await p.stop()

asyncio.run(main())
