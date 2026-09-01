"""
Automatic re-login for RepeaterMock.

When the scraper's refresh token dies (it is single-use and gets invalidated
whenever the same account refreshes elsewhere — e.g. an open browser tab),
this module logs in again over plain HTTP:

  1. POST /auth/login        {email, password}        → pre-TOTP session cookie
  2. POST /auth/totp/verify  {token, code}            → final session cookies
     where `code` is a TOTP generated from the account's secret
     (pure stdlib — HMAC-SHA1, same algorithm as Google Authenticator)

Credentials come from .env:
    REPEATERMOCK_EMAIL=you@example.com
    REPEATERMOCK_PASSWORD=yourpassword
    REPEATERMOCK_TOTP_SECRET=BASE32SECRET   # from re-enrolling TOTP in account settings
    REPEATERMOCK_LOGIN_ACCOUNT=1            # which cookies/accountN.json to persist to (default 1)
"""
import base64
import hashlib
import hmac
import json
import os
import struct
import time
import urllib.error
import urllib.request
from pathlib import Path

API_BASE = "https://api.repeatermock.com"
ROOT = Path(__file__).parent.parent
ENV_PATH = ROOT / ".env"

_HEADERS = {
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://repeatermock.com",
    "Referer": "https://repeatermock.com/login",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def load_login_credentials() -> dict | None:
    """Read credentials from environment or .env. Returns None if not configured."""
    env = dict(os.environ)
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    email = env.get("REPEATERMOCK_EMAIL", "").strip()
    password = env.get("REPEATERMOCK_PASSWORD", "").strip()
    totp_secret = env.get("REPEATERMOCK_TOTP_SECRET", "").strip()
    if not email or not password:
        return None
    return {
        "email": email,
        "password": password,
        "totp_secret": totp_secret,
        "account": int(env.get("REPEATERMOCK_LOGIN_ACCOUNT", "1") or 1),
    }


def totp_now(secret: str, period: int = 30, digits: int = 6) -> str:
    """Generate the current TOTP code (RFC 6238, SHA-1) from a base32 secret."""
    clean = secret.strip().replace(" ", "").upper()
    padding = "=" * ((8 - len(clean) % 8) % 8)
    key = base64.b32decode(clean + padding)
    counter = int(time.time()) // period
    msg = struct.pack(">Q", counter)
    digest = hmac.new(key, msg, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = (struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def _post(path: str, payload: dict) -> tuple[int, dict, list[str]]:
    """POST JSON, return (status, parsed_body, set_cookie_headers)."""
    req = urllib.request.Request(
        f"{API_BASE}{path}",
        data=json.dumps(payload).encode("utf-8"),
        headers=_HEADERS,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8", "replace")
            set_cookies = resp.headers.get_all("Set-Cookie") or []
            try:
                return resp.status, json.loads(raw), set_cookies
            except json.JSONDecodeError:
                return resp.status, {"raw": raw[:300]}, set_cookies
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(body), e.headers.get_all("Set-Cookie") or []
        except json.JSONDecodeError:
            return e.code, {"raw": body[:300]}, []


def try_auto_login() -> list[dict] | None:
    """Log in with configured credentials and return a fresh cookie list
    (RepeaterMock cookie dicts, ready for the scraper), or None on failure.
    Never raises — all failures are printed and return None.
    """
    creds = load_login_credentials()
    if not creds:
        return None

    print(f"  🤖 Auto-login as {creds['email']}...")

    # Step 1: email + password
    status, body, set_cookies = _post("/auth/login", {
        "email": creds["email"],
        "password": creds["password"],
    })
    print(f"    /auth/login → {status}: {json.dumps(body)[:100]}")
    if status != 200:
        print("    ✗ Auto-login failed — check REPEATERMOCK_EMAIL / REPEATERMOCK_PASSWORD in .env")
        return None

    cookies: dict[str, str] = {}
    _capture_cookies(set_cookies, cookies)

    # The login response usually carries the pre-TOTP session token
    token = None
    if isinstance(body, dict):
        token = (body.get("token") or body.get("accessToken")
                 or (body.get("data") or {}).get("token"))
    if not token:
        token = cookies.get("accessToken")

    # Step 2: TOTP verification (needed whenever totpVerified isn't already "1")
    if cookies.get("totpVerified") != "1":
        if not creds["totp_secret"]:
            print("    ✗ TOTP verification required but REPEATERMOCK_TOTP_SECRET is not set in .env")
            print("      (Account settings → re-enroll Google Authenticator → copy the secret code)")
            return None
        code = totp_now(creds["totp_secret"])
        verify_payload = {"code": code}
        if token:
            verify_payload["token"] = token
        status2, body2, set_cookies2 = _post("/auth/totp/verify", verify_payload)
        print(f"    /auth/totp/verify → {status2}: {json.dumps(body2)[:100]}")
        if status2 != 200:
            print("    ✗ TOTP verification failed — check REPEATERMOCK_TOTP_SECRET in .env")
            return None
        _capture_cookies(set_cookies2, cookies)

    if "refreshToken" not in cookies or "accessToken" not in cookies:
        print(f"    ✗ Login succeeded but session cookies are missing — got: {sorted(cookies)}")
        return None

    # Build the scraper's cookie list
    result = []
    for name in ("accessToken", "refreshToken", "totpVerified", "guestId", "rm_fe"):
        if name in cookies:
            domain = "repeatermock.com" if name == "rm_fe" else ".repeatermock.com"
            result.append({"name": name, "value": cookies[name], "domain": domain, "path": "/"})

    print(f"    ✓ Auto-login OK — fresh session cookies obtained ({len(result)} cookies)")
    return result


# ── Google OAuth auto-recovery (for Google-sign-in-only accounts) ──────────
# A dedicated browser profile ("browser_profile/") keeps the Google session.
# One-time setup:  python scripts/setup_google_login.py   (log in manually once)
# After that, the scraper can re-login through Google by itself, forever.

import asyncio

GOOGLE_PROFILE_DIR = ROOT / "browser_profile"
LOGIN_URL = "https://repeatermock.com/login"

_GOOGLE_BUTTON_SELECTORS = [
    'button:has-text("Google")',
    'a:has-text("Google")',
    'button:has-text("Continue with Google")',
    'a:has-text("Continue with Google")',
    '[aria-label*="Google"]',
    '[class*="google" i]',
    'text=/sign in with google/i',
]


def google_profile_exists() -> bool:
    """True once the bootstrap script has created the profile."""
    return (GOOGLE_PROFILE_DIR / "Default").exists() or GOOGLE_PROFILE_DIR.exists() and any(
        GOOGLE_PROFILE_DIR.iterdir())


def _cookie_dicts_from(context_cookies: list[dict]) -> list[dict] | None:
    """Convert Playwright cookies into the scraper's cookie format.
    Returns None until both accessToken and refreshToken are present."""
    names = {}
    for c in context_cookies:
        if "repeatermock" in c.get("domain", ""):
            names[c["name"]] = c["value"]
    if "refreshToken" not in names or "accessToken" not in names:
        return None
    result = []
    for name in ("accessToken", "refreshToken", "totpVerified", "guestId", "rm_fe"):
        if name in names:
            domain = "repeatermock.com" if name == "rm_fe" else ".repeatermock.com"
            result.append({"name": name, "value": names[name], "domain": domain, "path": "/"})
    return result


async def _launch_profile_context(pw, headless: bool):
    """Launch the persistent profile context — prefer real Chrome (Google
    trusts it more), fall back to Playwright's Chromium."""
    launch_kwargs = dict(user_data_dir=str(GOOGLE_PROFILE_DIR), headless=headless,
                         args=["--disable-blink-features=AutomationControlled",
                               "--no-first-run", "--no-default-browser-check"])
    try:
        return await pw.chromium.launch_persistent_context(channel="chrome", **launch_kwargs)
    except Exception:
        return await pw.chromium.launch_persistent_context(**launch_kwargs)


async def _drive_google_login(context, timeout_s: float = 150.0) -> list[dict] | None:
    """Click the Google button, handle the account chooser, and wait until
    repeatermock session cookies appear. Returns cookie dicts or None."""
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
    except Exception as e:
        print(f"    ✗ Could not open {LOGIN_URL}: {e}")
        return None

    clicked = False
    for sel in _GOOGLE_BUTTON_SELECTORS:
        try:
            await page.locator(sel).first.click(timeout=3000)
            clicked = True
            break
        except Exception:
            continue
    if not clicked:
        print("    ✗ Couldn't find the Google sign-in button on /login")
        return None
    print("    → Clicked Google sign-in — completing OAuth...")

    deadline = time.time() + timeout_s
    chooser_clicked = False
    result = None
    while time.time() < deadline and result is None:
        # If Google shows the account chooser, click the first account
        if not chooser_clicked:
            for pg in context.pages:
                if "accounts.google.com" in pg.url:
                    try:
                        for sel in ['div[role="link"]', 'div[data-identifier] button',
                                    'li div[role="link"]']:
                            loc = pg.locator(sel).first
                            if await loc.count() > 0:
                                await loc.click(timeout=2000)
                                chooser_clicked = True
                                break
                    except Exception:
                        pass
                    if chooser_clicked:
                        break

        result = _cookie_dicts_from(await context.cookies())
        if not result:
            await asyncio.sleep(2)
    if not result:
        print("    ✗ Timed out waiting for the Google login to complete")
        return None

    # CRITICAL: the site's own JS rotates the refresh token right after login,
    # so freshly-captured cookies may already be stale. Close the page (stops
    # the site JS), then VERIFY the cookies work with one /auth/refresh —
    # retry-capturing until we hold a verified-working token set.
    try:
        await page.close()
    except Exception:
        pass

    verify_deadline = time.time() + 45
    last_err = ""
    while time.time() < verify_deadline:
        result = _cookie_dicts_from(await context.cookies()) or result
        cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in result)
        try:
            resp = await context.request.post(
                "https://api.repeatermock.com/auth/refresh",
                headers={"Accept": "application/json", "Content-Type": "application/json",
                         "Cookie": cookie_str, "Origin": "https://repeatermock.com",
                         "Referer": "https://repeatermock.com/"},
                data="{}")
            if resp.status == 200:
                final = _cookie_dicts_from(await context.cookies()) or result
                print("    ✓ Refresh verified — captured final working cookies")
                return final
            last_err = f"HTTP {resp.status}"
        except Exception as e:
            last_err = str(e)[:100]
        await asyncio.sleep(3)
    print(f"    ⚠ Could not verify refresh token ({last_err}) — returning captured cookies anyway")
    return result


async def google_profile_relogin(headless: bool | None = None) -> list[dict] | None:
    """Re-login to RepeaterMock using the saved Google session in the profile.
    Returns fresh cookie dicts (saved to account4.json by the caller), or None."""
    if not google_profile_exists():
        return None
    if headless is None:
        headless = os.environ.get("REPEATERMOCK_GOOGLE_HEADLESS", "0") == "1"

    from playwright.async_api import async_playwright
    print("  🤖 Auto-login via saved Google profile...")
    print("  ⚠ A Chrome window will open — if a Google/RepeaterMock login page appears,")
    print("     complete the login ONCE in that window; the scraper continues by itself.")
    pw = await async_playwright().start()
    try:
        context = await _launch_profile_context(pw, headless=headless)
        try:
            return await _drive_google_login(context)
        finally:
            try:
                await context.close()
            except Exception:
                pass
    except Exception as e:
        print(f"    ✗ Google profile re-login failed: {e}")
        return None
    finally:
        try:
            await pw.stop()
        except Exception:
            pass


# ── CDP re-login (MOST RELIABLE for Google-only accounts) ──────────────────
# Uses your REAL Chrome browser via remote debugging. Google never blocks
# your actual browser, so OAuth completes automatically every time.
#
# One-time setup: start Chrome with a dedicated profile:
#   chrome.exe --remote-debugging-port=9222 --user-data-dir="%USERPROFILE%\repeatermock-chrome"
# (or just run:  scripts\start_scrape_chrome.bat )
# Log into Google + repeatermock.com in that window ONCE, then leave it open.
# The scraper connects to it whenever tokens die and re-logins by itself.

CDP_URL = os.environ.get("REPEATERMOCK_CDP_URL", "http://127.0.0.1:9222")


async def cdp_relogin(timeout_s: float = 240.0) -> list[dict] | None:
    """Re-login to RepeaterMock through the user's real Chrome (CDP port 9222).
    Returns fresh cookie dicts, or None if Chrome isn't running / login fails.
    Never raises. The user's browser is NOT closed — only the tab we opened."""
    from playwright.async_api import async_playwright
    pw = await async_playwright().start()
    try:
        try:
            browser = await pw.chromium.connect_over_cdp(CDP_URL)
        except Exception:
            return None  # Chrome with debug port not running — caller handles it

        print(f"    ✓ Connected to your real Chrome via CDP")
        context = browser.contexts[0] if browser.contexts else None
        if context is None:
            print("    ✗ No browser context found in Chrome")
            return None

        page = await context.new_page()
        try:
            await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            print(f"    ⚠ goto /login: {e}")

        # Click the Google sign-in button (same selectors as the profile flow)
        clicked = False
        for sel in _GOOGLE_BUTTON_SELECTORS:
            try:
                await page.locator(sel).first.click(timeout=3000)
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            # Maybe already logged in — check cookies before failing
            result = _cookie_dicts_from(await context.cookies())
            if result:
                print("    ✓ Already logged in — captured session cookies")
                return result
            print("    ✗ Couldn't find the Google sign-in button")
            try:
                await page.close()
            except Exception:
                pass
            return None
        print("    → Clicked Google sign-in in your real Chrome — completing OAuth...")

        # Poll for repeatermock session cookies (handle Google account chooser)
        deadline = time.time() + timeout_s
        chooser_clicked = False
        result = None
        while time.time() < deadline and result is None:
            if not chooser_clicked:
                for pg in context.pages:
                    if "accounts.google.com" in pg.url:
                        try:
                            for sel in ['div[role="link"]', 'div[data-identifier] button']:
                                loc = pg.locator(sel).first
                                if await loc.count() > 0:
                                    await loc.click(timeout=2000)
                                    chooser_clicked = True
                                    break
                        except Exception:
                            pass
                        if chooser_clicked:
                            break
            result = _cookie_dicts_from(await context.cookies())
            if not result:
                await asyncio.sleep(2)
        if not result:
            print("    ✗ Timed out waiting for the login to complete in Chrome")
            try:
                await page.close()
            except Exception:
                pass
            return None

        # Verify the cookies work (same settle+verify as the profile flow)
        verify_deadline = time.time() + 45
        last_err = ""
        while time.time() < verify_deadline:
            cookie_str = "; ".join(f'{c["name"]}={c["value"]}' for c in result)
            try:
                req = urllib.request.Request(
                    f"{API_BASE}/auth/refresh", data=b"{}", method="POST",
                    headers={"Accept": "application/json", "Content-Type": "application/json",
                             "Cookie": cookie_str, "Origin": "https://repeatermock.com",
                             "Referer": "https://repeatermock.com/",
                             "User-Agent": _HEADERS["User-Agent"]})
                with urllib.request.urlopen(req, timeout=30) as r:
                    if r.status == 200:
                        print("    ✓ Refresh verified — captured working session cookies")
                        return result
                    last_err = f"HTTP {r.status}"
            except urllib.error.HTTPError as e:
                last_err = f"HTTP {e.code}"
            except Exception as e:
                last_err = str(e)[:100]
            await asyncio.sleep(3)
            result = _cookie_dicts_from(await context.cookies()) or result
        print(f"    ⚠ Could not verify refresh token ({last_err}) — returning captured cookies anyway")
        try:
            await page.close()
        except Exception:
            pass
        return result
    finally:
        try:
            await pw.stop()
        except Exception:
            pass


if __name__ == "__main__":
    result = try_auto_login()
    if result:
        print("\n✓ Auto-login works — the scraper can now recover from expired tokens by itself")
        raise SystemExit(0)
    print("\n✗ Auto-login failed — fix the .env values above and re-run: python -m src.auto_login")
    raise SystemExit(1)
