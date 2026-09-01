"""
Diagnose why tb-pro /attempt pages don't create an active attempt while tb
pages do. Captures every API call the page's JS makes after loading.

    python scripts/diag_attempt.py tb-pro
    python scripts/diag_attempt.py tb
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.scraper import create_browser_session  # noqa: E402

ROOT = Path(__file__).parent.parent
VARIANT = sys.argv[1] if len(sys.argv) > 1 else "tb-pro"
TEST_ID = "6a43aac2f6c489960bb113e5" if VARIANT == "tb-pro" else "6a0f3e5a33a6a35112cededf"
URL = f"https://repeatermock.com/{VARIANT}/test-series/ssc-cgl/test/{TEST_ID}/attempt"


async def main():
    cookies = json.loads((ROOT / "cookies" / "account4.json").read_text(encoding="utf-8"))
    p, browser, context = await create_browser_session(cookies)
    page = await context.new_page()

    reqs, resps = [], []
    page.on("request", lambda r: reqs.append(f"{r.method} {r.url}")
            if "repeatermock" in r.url else None)
    page.on("response", lambda r: resps.append(f"{r.status} {r.url}")
            if "repeatermock" in r.url else None)

    print(f"=== Diagnosing [{VARIANT}] {URL}\n")
    try:
        await page.goto(URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"goto error: {e}")
    await asyncio.sleep(20)

    print(f"Final URL : {page.url}")
    try:
        print(f"Title     : {await page.title()}")
        body = await page.inner_text("body")
        print(f"Body text : {body[:400].replace(chr(10), ' | ')}")
    except Exception as e:
        print(f"page eval error: {e}")

    print(f"\n--- Requests to repeatermock ({len(reqs)}):")
    for r in reqs:
        print("  ", r)
    print(f"\n--- Responses ({len(resps)}):")
    for r in resps:
        print("  ", r)

    # Context cookie state after the visit
    names = sorted(c["name"] for c in await context.cookies() if "repeatermock" in c.get("domain", ""))
    print(f"\n--- Context cookies: {names}")

    await browser.close()
    await p.stop()


if __name__ == "__main__":
    asyncio.run(main())
