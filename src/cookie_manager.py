"""
Cookie management for RepeaterMock scraper.

Handles:
- Loading cookies from env vars, .env file, or JSON file
- Saving rotated cookies (refresh token rotates on each /auth/refresh)
- Converting between cookie formats (Playwright, browser JSON, string)
"""
import json
import os
import time
from pathlib import Path
from typing import Any


# All cookies RepeaterMock uses
COOKIE_NAMES = [
    "accessToken",
    "refreshToken",
    "totpVerified",
    "guestId",
    "rm_fe",
    "g_state",
    "cf_clearance",
    "_ga",
    "_ga_5ZXVX6K05R",
]


def load_cookies_from_env() -> list[dict[str, Any]]:
    """
    Load cookies from environment variables.

    Supports two formats:
    1. Individual env vars: REPEATERMOCK_ACCESS_TOKEN, REPEATERMOCK_REFRESH_TOKEN, etc.
    2. Single JSON string: REPEATERMOCK_COOKIES_JSON='[{"name":"accessToken","value":"...","domain":".repeatermock.com","path":"/"},...]'
    3. Cookie string: REPEATERMOCK_COOKIE_STRING='accessToken=xxx; refreshToken=yyy; ...'
    """
    cookies = []

    # Format 2: Full JSON
    json_str = os.environ.get("REPEATERMOCK_COOKIES_JSON")
    if json_str:
        try:
            parsed = json.loads(json_str)
            for c in parsed:
                cookies.append({
                    "name": c["name"],
                    "value": c["value"],
                    "domain": c.get("domain", ".repeatermock.com"),
                    "path": c.get("path", "/"),
                })
            return cookies
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Warning: REPEATERMOCK_COOKIES_JSON parse error: {e}")

    # Format 3: Cookie string
    cookie_str = os.environ.get("REPEATERMOCK_COOKIE_STRING")
    if cookie_str:
        for pair in cookie_str.split(";"):
            pair = pair.strip()
            if "=" in pair:
                name, value = pair.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".repeatermock.com",
                    "path": "/",
                })
        if cookies:
            return cookies

    # Format 1: Individual env vars
    env_map = {
        "accessToken": "REPEATERMOCK_ACCESS_TOKEN",
        "refreshToken": "REPEATERMOCK_REFRESH_TOKEN",
        "totpVerified": "REPEATERMOCK_TOTP_VERIFIED",
        "guestId": "REPEATERMOCK_GUEST_ID",
        "rm_fe": "REPEATERMOCK_RM_FE",
        "g_state": "REPEATERMOCK_G_STATE",
        "cf_clearance": "REPEATERMOCK_CF_CLEARANCE",
    }
    for name, env_key in env_map.items():
        value = os.environ.get(env_key)
        if value:
            domain = "repeatermock.com" if name == "rm_fe" else ".repeatermock.com"
            cookies.append({"name": name, "value": value, "domain": domain, "path": "/"})

    return cookies


def load_cookies_from_file(path: Path) -> list[dict[str, Any]]:
    """Load cookies from a JSON file (Playwright storage_state format)."""
    if not path.exists():
        return []
    data = json.loads(path.read_text())
    if isinstance(data, list):
        return data
    return data.get("cookies", [])


def load_cookies(path: Path | None = None) -> list[dict[str, Any]]:
    """
    Load cookies from env vars first, then from file.

    Priority:
    1. Environment variables (for CI/GitHub Actions)
    2. Cookie file (for local dev — stores rotated tokens)
    """
    env_cookies = load_cookies_from_env()
    if env_cookies:
        print(f"Loaded {len(env_cookies)} cookies from environment")
        return env_cookies

    if path:
        file_cookies = load_cookies_from_file(path)
        if file_cookies:
            print(f"Loaded {len(file_cookies)} cookies from {path}")
            return file_cookies

    raise RuntimeError(
        "No cookies found. Set REPEATERMOCK_COOKIES_JSON env var, "
        "individual REPEATERMOCK_* env vars, or provide a cookie file path."
    )


def save_cookies(cookies: list[dict[str, Any]], path: Path):
    """Save cookies to a JSON file (for reuse — refresh token rotates)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    simple = {c["name"]: c["value"] for c in cookies if "repeatermock" in c.get("domain", "")}
    path.write_text(json.dumps({
        "cookies": cookies,
        "simple": simple,
        "saved_at": time.time(),
        "saved_at_human": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
    }, indent=2))


def cookies_to_string(cookies: list[dict[str, Any]]) -> str:
    """Convert cookies to a 'name=value; name=value' string."""
    return "; ".join(f'{c["name"]}={c["value"]}' for c in cookies)


def get_cookie_value(cookies: list[dict[str, Any]], name: str) -> str | None:
    """Get a specific cookie value by name."""
    for c in cookies:
        if c["name"] == name:
            return c["value"]
    return None
