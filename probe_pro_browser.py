"""Probe the paid test with a real logged-in browser (Playwright), capturing
every API response — the HTML shell alone never contains the question data."""
import asyncio
import json

TEST_ID = "6a0f3cc4076c0c0843115e2f"
BASE = f"https://repeatermock.com/tb-pro/test-series/ssc-cgl/test/{TEST_ID}"

COOKIES = [
    {"name": "accessToken", "value": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJ1c2VySWQiOiI2YTk1ZDZlNjljNDk1OGE2NzEyNzkzMTciLCJlbWFpbCI6ImRpYmFrYXJzZHNlbnNlQGdtYWlsLmNvbSIsImlhdCI6MTc4ODI5MDIwMSwiZXhwIjoxNzg4MjkxMTAxfQ.nnn4SsHPgWL9dHRVPumW96hYJKaBdH2U49JXv4kMxMA", "domain": ".repeatermock.com", "path": "/"},
    {"name": "refreshToken", "value": "a416764efa4b322966408b4f6eca48c2985d859459dc686a81b7ed5d2815c77c21a1c596b35c54611c63e958ee5674c6ac8f91ead19e3e371df8c821c51b2bfd", "domain": ".repeatermock.com", "path": "/"},
    {"name": "totpVerified", "value": "1", "domain": ".repeatermock.com", "path": "/"},
    {"name": "rm_fe", "value": "2f6631856d3362ec", "domain": "repeatermock.com", "path": "/"},
]


async def main():
    from playwright.async_api import async_playwright
    p = await async_playwright().start()
    browser = await p.chromium.launch(headless=True, args=[
        "--no-sandbox", "--disable-blink-features=AutomationControlled"])
    ctx = await browser.new_context(
        viewport={"width": 1366, "height": 768},
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36",
        locale="en-IN", timezone_id="Asia/Kolkata")
    await ctx.add_cookies(COOKIES)
    await ctx.add_init_script("""
        Object.defineProperty(navigator,'webdriver',{get:()=>undefined});
        window.chrome={runtime:{}};
        console.clear=function(){};
        window.close=function(){};
    """)
    page = await ctx.new_page()
    await page.route("**/swiper.js", lambda r: r.fulfill(
        status=200, content_type="application/javascript", body="/*blocked*/"))

    api_calls = []

    async def on_resp(r):
        if "api.repeatermock.com" in r.url:
            try:
                body = await r.text()
            except Exception:
                body = ""
            api_calls.append({"url": r.url, "status": r.status, "len": len(body),
                              "body": body[:400]})
    page.on("response", lambda r: asyncio.create_task(on_resp(r)))

    for label, url in (("attempt", f"{BASE}/attempt"),
                       ("solution", f"{BASE}/solution"),
                       ("analysis", f"{BASE}/analysis")):
        print(f"\n=== {label} ===")
        api_calls.clear()
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        except Exception as e:
            print("  goto:", type(e).__name__)
        await page.wait_for_timeout(9000)
        print("  final url:", page.url)
        txt = (await page.inner_text("body"))[:400].replace("\n", " | ")
        print("  visible text:", txt[:300])
        for c in api_calls:
            print(f"  [api] {c['status']} {c['len']:>6}b {c['url'].split('api.repeatermock.com')[1][:70]}")
            if c["status"] >= 400:
                print(f"        {c['body'][:150]}")
        await page.screenshot(path=f"pro_{label}.png")

    await browser.close()
    await p.stop()


if __name__ == "__main__":
    asyncio.run(main())
