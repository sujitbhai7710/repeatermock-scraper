"""
Test scraping the geometry test (CT 46: Congruence and Similarity) and
try to get answer keys + solutions via the /analysis and /solution pages.
"""
import asyncio
import json
import re
from pathlib import Path
from playwright.async_api import async_playwright
from dotenv import load_dotenv
import sys

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
load_dotenv(PROJECT_ROOT / ".env")

from src.cookie_manager import load_cookies, save_cookies
from src.scraper import create_browser_session, refresh_cookies_if_needed, COOKIES_FILE
from src.question_parser import extract_flight_payload, parse_question_objects, clean_question

DUMP = PROJECT_ROOT / "data" / "test_scrape"
DUMP.mkdir(parents=True, exist_ok=True)

TEST_ID = "6a0f3ce8f886fe6323e12634"
VARIANT = "tb-pro"
SLUG = "ssc-cgl"

async def main():
    print("=== Geometry Test Scraper + Answer Key Test ===\n", flush=True)
    cookies = load_cookies(COOKIES_FILE)
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    try:
        cookies = await refresh_cookies_if_needed(context, page)
        print("✓ Authenticated\n", flush=True)

        # 1. Scrape /attempt page for questions
        print("=== 1. Fetching /attempt page ===", flush=True)
        resp = await context.request.get(
            f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}/attempt",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        html = await resp.text()
        print(f"  Status: {resp.status}, Size: {len(html)}", flush=True)
        (DUMP / f"attempt_{TEST_ID}.html").write_text(html, encoding="utf-8")

        payload = extract_flight_payload(html)
        raw_qs = parse_question_objects(payload)
        cleaned = [clean_question(q) for q in raw_qs]
        print(f"  Found {len(cleaned)} questions\n", flush=True)

        # 2. Check for images and math
        print("=== 2. Images and math in questions ===", flush=True)
        for i, q in enumerate(cleaned[:5]):
            en = q.get("languages", {}).get("en", {})
            qt = en.get("question", "")
            opts = en.get("options", [])
            has_img = "<img" in qt.lower() or "src=" in qt.lower()
            has_math = "math-tex" in qt or "\\(" in qt or "\\frac" in qt
            print(f"\n  Q{i+1}: img={has_img} math={has_math}", flush=True)
            print(f"    {qt[:250]}", flush=True)
            imgs = re.findall(r'src="([^"]+)"', qt)
            if imgs:
                print(f"    IMAGES: {imgs}", flush=True)
            for j, o in enumerate(opts[:4]):
                v = o.get("value", "")
                om = "math-tex" in v or "\\(" in v
                oi = "<img" in v.lower()
                print(f"    {chr(65+j)}) {v[:80]}{' [M]' if om else ''}{' [I]' if oi else ''}", flush=True)

        # 3. Fetch /solution page
        print(f"\n=== 3. Fetching /solution page ===", flush=True)
        resp2 = await context.request.get(
            f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}/solution",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        sol_html = await resp2.text()
        print(f"  Status: {resp2.status}, Size: {len(sol_html)}", flush=True)
        (DUMP / f"solution_{TEST_ID}.html").write_text(sol_html, encoding="utf-8")

        sol_payload = extract_flight_payload(sol_html)
        print(f"  Payload: {len(sol_payload)} chars", flush=True)

        # Search for answer patterns
        for pat, name in [
            (r'"ans"\s*:\s*"?(\w+)"?', "ans"),
            (r'"correctAns"\s*:\s*"?(\w+)"?', "correctAns"),
            (r'"correctOption"\s*:\s*"?(\w+)"?', "correctOption"),
            (r'"answer"\s*:\s*"?(\w+)"?', "answer"),
            (r'"isCorrect"\s*:\s*(?:true|false)', "isCorrect"),
            (r'"solution"\s*:\s*"([^"]{5,})"', "solution"),
        ]:
            ms = re.findall(pat, sol_payload)
            if ms:
                print(f"  '{name}': {len(ms)} matches — {ms[:5]}", flush=True)

        # 4. Fetch /analysis page
        print(f"\n=== 4. Fetching /analysis page ===", flush=True)
        resp3 = await context.request.get(
            f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{TEST_ID}/analysis",
            headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"}
        )
        ana_html = await resp3.text()
        print(f"  Status: {resp3.status}, Size: {len(ana_html)}", flush=True)
        (DUMP / f"analysis_{TEST_ID}.html").write_text(ana_html, encoding="utf-8")

        # 5. Try POST submit
        print(f"\n=== 5. POST submit ===", flush=True)
        for url in [f"https://api.repeatermock.com/api/v1/attempts/{TEST_ID}/submit"]:
            try:
                resp4 = await context.request.post(url, headers={
                    "Accept": "application/json", "Content-Type": "application/json",
                }, data=json.dumps({"answers": [], "timeTaken": 0, "language": "en"}))
                b4 = await resp4.text()
                print(f"  [{resp4.status}] {url}: {b4[:300]}", flush=True)
            except Exception as e:
                print(f"  Error: {e}", flush=True)

        # 6. Save questions
        out = {"test_id": TEST_ID, "title": "CT 46: Congruence and Similarity - 01",
               "duration_minutes": 6, "total_marks": 20, "question_count": 10, "questions": cleaned}
        (DUMP / f"questions_{TEST_ID}.json").write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
        print(f"\n✓ Saved {len(cleaned)} questions", flush=True)

    finally:
        save_cookies(await context.cookies(), COOKIES_FILE)
        await browser.close()
        await p.stop()

asyncio.run(main())
