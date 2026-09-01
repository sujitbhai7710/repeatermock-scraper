"""
GUEST MODE TEST — headless browser with ZERO login cookies.
Exactly what GitHub Actions could regenerate automatically.

Tests whether an anonymous guest can do the FULL flow on one tb-pro test:
  questions → start attempt → submit → solutions → analysis

    python scripts/test_guest.py
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.scraper import create_browser_session, fetch_via_context  # noqa: E402
from src.question_parser import (  # noqa: E402
    extract_flight_payload, parse_question_objects, clean_question,
)

API_BASE = "https://api.repeatermock.com"
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "tb"
SLUG = sys.argv[2] if len(sys.argv) > 2 else "ssc-cgl"
SERIES_URL = f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}"
MATCH = sys.argv[3].lower() if len(sys.argv) > 3 else ""


async def main():
    print("=" * 60)
    print("GUEST MODE TEST — headless, ZERO login cookies")
    print("=" * 60)

    # 1. Fresh headless context with NO cookies
    p, browser, context = await create_browser_session([])
    page = await context.new_page()
    await page.goto("https://repeatermock.com", wait_until="domcontentloaded")
    await asyncio.sleep(4)
    names = [c["name"] for c in await context.cookies() if "repeatermock" in c.get("domain", "")]
    print(f"\n[1] Cookies after visiting homepage (guest): {names}")

    # 2. Series + find the target test
    s, body = await fetch_via_context(context, f"{API_BASE}/api/v1/test-series/{SLUG}?variant={VARIANT}")
    print(f"[2] Series details: {s}")
    if s != 200:
        print("    ✗ Guest cannot fetch series — guest mode FAILS here")
        return 1
    details = json.loads(body).get("data", {}).get("details", {})
    tests = []
    for sec in details.get("sections", []):
        for sub in sec.get("subsections", []) or [{}]:
            url = (f"{API_BASE}/api/v1/test-series/{details.get('id')}/sections/{sec['id']}"
                   f"/tests?limit=500&offset=0&variant={VARIANT}")
            if sub.get("id"):
                url += f"&subSectionId={sub['id']}"
            st, tb = await fetch_via_context(context, url)
            if st == 200:
                tests += json.loads(tb).get("data", [])
    print(f"    {len(tests)} tests visible to guest")
    target = next((t for t in tests if MATCH in t.get("title", "").lower()), None)
    if not target:
        print(f"    ✗ No test matching '{MATCH}'")
        return 1
    tid = target["id"]
    print(f"    Target: {target.get('title', '')} (id={tid})")

    # 3. Questions (guest GET /attempt)
    req = await context.request.get(
        f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{tid}/attempt",
        headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"})
    s, html = req.status, await req.text()
    qs = []
    if s == 200 and len(html) > 5000:
        payload = extract_flight_payload(html)
        qs = [clean_question(q) for q in parse_question_objects(payload)]
    print(f"[3] Questions as guest: {s}, {len(qs)} questions")

    # 4. Start attempt as guest
    s, body = await fetch_via_context(
        context, f"{API_BASE}/api/v1/attempts/{tid}/start", method="POST", body="{}")
    print(f"[4] START attempt as guest: {s} — {body[:120]}")

    # 5. Submit as guest (simple skipped-answers payload)
    payload = {"testId": tid, "answers": [], "timeTaken": 1, "language": "en", "interface": "classic"}
    s, body = await fetch_via_context(
        context, f"{API_BASE}/api/v1/attempts/{tid}/submit", method="POST",
        body=json.dumps(payload))
    print(f"[5] SUBMIT as guest: {s} — {body[:120]}")

    # 6. Solutions as guest
    req = await context.request.get(
        f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{tid}/solution",
        headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"})
    s, sol = req.status, await req.text()
    has_sol = s == 200 and "answersData" in sol
    print(f"[6] SOLUTION page as guest: {s}, answersData present: {has_sol}, size={len(sol)}")

    # 7. Analysis as guest
    req = await context.request.get(
        f"https://repeatermock.com/{VARIANT}/test-series/{SLUG}/test/{tid}/analysis",
        headers={"Accept": "text/html", "Referer": "https://repeatermock.com/"})
    s, ana = req.status, await req.text()
    has_ana = s == 200 and "analysisData" in ana
    print(f"[7] ANALYSIS page as guest: {s}, analysisData present: {has_ana}, size={len(ana)}")

    print("\n" + "=" * 60)
    verdict = []
    verdict.append(("questions", len(qs) > 0))
    verdict.append(("start attempt", "[4]" is not None and "401" not in body))
    verdict.append(("submit", "s == 200 or 409"))
    verdict.append(("solutions", has_sol))
    verdict.append(("analysis", has_ana))
    for name, ok in verdict:
        print(f"  {name:15} : {'✓' if ok else '✗'}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
