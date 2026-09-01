"""
Quick cookie validator — checks cookies/account*.json (and optional env vars)
against RepeaterMock's /auth/me and /auth/refresh endpoints WITHOUT launching
a browser or starting a scrape.

Use this BEFORE running the scraper to confirm your cookies are fresh:

    python scripts/check_cookies.py

Exit code: 0 if at least one cookie set authenticates, 1 otherwise.

WARNING: /auth/refresh ROTATES the refresh token. On success, the new token is
saved back to the account file automatically (same behavior as the scraper).
Do not run this concurrently with the scraper or GitHub Actions, or the two
runs will invalidate each other's tokens.
"""
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

# Never let a print() crash: force UTF-8 on stdout/stderr.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

API_BASE = "https://api.repeatermock.com"
PROJECT_ROOT = Path(__file__).parent.parent
COOKIES_DIR = PROJECT_ROOT / "cookies"
ENV_PATH = PROJECT_ROOT / ".env"

HEADERS = {
    "Accept": "application/json",
    "Origin": "https://repeatermock.com",
    "Referer": "https://repeatermock.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
}


def cookie_string(cookies: list[dict]) -> str:
    return "; ".join(f'{c["name"]}={c["value"]}' for c in cookies
                     if "repeatermock" in c.get("domain", ""))


def load_env_cookies() -> list[dict] | None:
    """Manually parse a single-line REPEATERMOCK_COOKIES from .env (no dotenv dep)."""
    if not ENV_PATH.exists():
        return None
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line.startswith("REPEATERMOCK_COOKIES="):
            value = line.split("=", 1)[1].strip().strip("'\"")
            try:
                parsed = json.loads(value)
                if isinstance(parsed, list) and parsed:
                    return parsed
            except json.JSONDecodeError as e:
                print(f"  ! REPEATERMOCK_COOKIES in .env is not valid JSON: {e}")
    return None


def http(url: str, method: str = "GET", cookie_str: str = "") -> tuple[int, str, dict]:
    headers = dict(HEADERS)
    if cookie_str:
        headers["Cookie"] = cookie_str
    if method == "POST":
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=b"{}" if method == "POST" else None,
                                 headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)


def check_and_rotate(cookies: list[dict], label: str, persist_path: Path | None) -> bool:
    """Check auth; on refresh success, update cookies in place and persist."""
    cs = cookie_string(cookies)
    print(f"\n  Checking {label} ({len(cookies)} cookies)...")

    status, body, _ = http(f"{API_BASE}/auth/me", cookie_str=cs)
    print(f"    /auth/me     → {status}: {body[:70]}")
    if status == 200 and '"success":true' in body:
        print("    ✓ Access token still valid — cookies are FRESH, ready to scrape")
        return True

    status, body, headers = http(f"{API_BASE}/auth/refresh", method="POST", cookie_str=cs)
    print(f"    /auth/refresh→ {status}: {body[:70]}")
    if status != 200:
        print("    ✗ Refresh token is dead — log in again and export fresh cookies")
        return False

    # Capture rotated tokens from Set-Cookie
    set_cookie = headers.get("Set-Cookie", "")
    for name in ("accessToken", "refreshToken", "totpVerified"):
        m = re.search(rf'{name}=([^;]+)', set_cookie)
        if m:
            for c in cookies:
                if c["name"] == name:
                    c["value"] = m.group(1)
                    print(f"    ✓ Rotated {name} captured")

    # Confirm the new access token works
    status2, body2, _ = http(f"{API_BASE}/auth/me", cookie_str=cookie_string(cookies))
    if status2 == 200 and '"success":true' in body2:
        print("    ✓ Authenticated via refresh!")
        if persist_path:
            persist_path.write_text(json.dumps(cookies, indent=2, ensure_ascii=False))
            print(f"    ✓ Saved rotated tokens to {persist_path.name}")
        return True

    print(f"    ✗ Refresh succeeded but /auth/me still fails ({status2})")
    return False


def main():
    # Load .env only for the optional REPEATERMOCK_COOKIES line
    try:
        from dotenv import load_dotenv
        if ENV_PATH.exists():
            load_dotenv(ENV_PATH)
    except ImportError:
        pass

    import os
    sets: list[tuple[str, list[dict], Path | None]] = []

    env_raw = os.environ.get("REPEATERMOCK_COOKIES")
    if env_raw:
        try:
            parsed = json.loads(env_raw)
            if isinstance(parsed, list) and parsed:
                sets.append(("REPEATERMOCK_COOKIES env var", parsed, None))
        except json.JSONDecodeError as e:
            print(f"  ! Could not parse REPEATERMOCK_COOKIES env var: {e}")

    env_file_cookies = load_env_cookies()
    if env_file_cookies:
        sets.append(("REPEATERMOCK_COOKIES in .env", env_file_cookies, None))

    if COOKIES_DIR.exists():
        for f in sorted(COOKIES_DIR.glob("account*.json")):
            try:
                cookies = json.loads(f.read_text(encoding="utf-8"))
                if cookies:
                    sets.append((f.name, cookies, f))
            except Exception as e:
                print(f"  ! Could not read {f.name}: {e}")

    if not sets:
        print("✗ No cookies found. Export fresh cookies from your browser and save")
        print("  the JSON array to cookies/account1.json (see cookies/README.md).")
        return 1

    print(f"Found {len(sets)} cookie set(s) to check.")
    for label, cookies, path in sets:
        if check_and_rotate(cookies, label, path):
            print("\n✓ At least one cookie set works — you can run: python -m src.incremental_scrape")
            return 0

    print("\n✗ ALL cookie sets are dead.")
    print("  How to fix:")
    print("    1. Log in to https://repeatermock.com in your browser (Google Authenticator)")
    print("    2. Install the 'Cookie-Editor' extension → Export (JSON)")
    print("    3. Paste the JSON array into cookies/account1.json")
    print("    4. Re-run this script to verify, then run: python -m src.incremental_scrape")
    return 1


if __name__ == "__main__":
    started = time.time()
    code = main()
    print(f"\nDone in {time.time() - started:.1f}s")
    sys.exit(code)
