#!/usr/bin/env python3
"""Reset everything: D1 database + local data files. Clean slate for fresh run.

Usage:
    CLOUDFLARE_API_TOKEN=xxx CLOUDFLARE_ACCOUNT_ID=xxx D1_DATABASE_ID=xxx python3 scripts/reset_all.py
"""
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

TOKEN = os.environ.get("CLOUDFLARE_API_TOKEN")
ACCOUNT_ID = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
DB_ID = os.environ.get("D1_DATABASE_ID")

if not all([TOKEN, ACCOUNT_ID, DB_ID]):
    print("✗ Missing env vars. Set:")
    print("  CLOUDFLARE_API_TOKEN=xxx CLOUDFLARE_ACCOUNT_ID=xxx D1_DATABASE_ID=xxx python3 scripts/reset_all.py")
    sys.exit(1)

ROOT = Path(__file__).parent.parent


def cf(method, url, body=None):
    headers = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        err = e.read().decode()
        try:
            return e.code, json.loads(err)
        except Exception:
            return e.code, {"raw": err}


def query(sql, params=None):
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/d1/database/{DB_ID}/query"
    s, b = cf("POST", url, body={"sql": sql, "params": params or []})
    if s != 200 or not b.get("success"):
        print(f"  ✗ Query failed: HTTP {s}")
        print(f"    SQL: {sql[:100]}")
        print(f"    Response: {json.dumps(b, indent=2)[:300]}")
        return None
    return b.get("result", [])


def main():
    print("=" * 60)
    print("FULL RESET — D1 + local files")
    print("=" * 60)

    # ─── Part 1: Reset D1 ────────────────────────────────────────────────────
    print("\n→ Resetting D1 database...")
    statements = [
        "DELETE FROM tests",
        "DELETE FROM runs",
        "DELETE FROM refresh_log",
        "UPDATE series SET total_tests = 0, scraped_count = 0, partial_count = 0, failed_count = 0, pending_count = 0, last_fetched_at = NULL, last_scraped_at = NULL",
    ]
    for sql in statements:
        first_word = sql.split()[0]
        r = query(sql)
        if r is not None:
            print(f"  ✓ {first_word}...")

    # Verify
    r = query("SELECT COUNT(*) as c FROM tests")
    if r:
        print(f"  Tests in D1: {r[0]['results'][0]['c']}")
    r = query("SELECT COUNT(*) as c FROM runs")
    if r:
        print(f"  Runs in D1: {r[0]['results'][0]['c']}")
    r = query("SELECT COUNT(*) as c, SUM(scraped_count) as s, SUM(partial_count) as p FROM series")
    if r:
        row = r[0]['results'][0]
        print(f"  Series in D1: {row['c']} (scraped: {row['s']}, partial: {row['p']})")

    # ─── Part 2: Reset local files ──────────────────────────────────────────
    print("\n→ Resetting local files...")

    # Delete data/tests/*.json
    tests_dir = ROOT / "data" / "tests"
    if tests_dir.exists():
        count = 0
        for f in tests_dir.glob("*.json"):
            f.unlink()
            count += 1
        print(f"  ✓ Deleted {count} files from data/tests/")

    # Delete data/progress.json
    progress_file = ROOT / "data" / "progress.json"
    if progress_file.exists():
        progress_file.unlink()
        print(f"  ✓ Deleted data/progress.json")

    # Delete data/submit_format.json (so scraper rediscovers the working format)
    submit_fmt = ROOT / "data" / "submit_format.json"
    if submit_fmt.exists():
        submit_fmt.unlink()
        print(f"  ✓ Deleted data/submit_format.json")

    # Delete data/cookies.json (cached cookies from old runs)
    cookies_cache = ROOT / "data" / "cookies.json"
    if cookies_cache.exists():
        cookies_cache.unlink()
        print(f"  ✓ Deleted data/cookies.json")

    # Delete frontend/tests/*.json + index.json
    fe_tests = ROOT / "frontend" / "tests"
    if fe_tests.exists():
        count = 0
        for f in fe_tests.glob("*.json"):
            f.unlink()
            count += 1
        print(f"  ✓ Deleted {count} files from frontend/tests/")

    # Delete frontend/img/* (downloaded images)
    fe_img = ROOT / "frontend" / "img"
    if fe_img.exists():
        import shutil
        shutil.rmtree(fe_img)
        print(f"  ✓ Deleted frontend/img/")

    # Delete data/img/* (downloaded images)
    data_img = ROOT / "data" / "img"
    if data_img.exists():
        import shutil
        shutil.rmtree(data_img)
        print(f"  ✓ Deleted data/img/")

    # Delete data/series/* (cached series test lists)
    series_dir = ROOT / "data" / "series"
    if series_dir.exists():
        count = 0
        for f in series_dir.glob("*.json"):
            f.unlink()
            count += 1
        print(f"  ✓ Deleted {count} files from data/series/")

    # ─── Part 3: Summary ────────────────────────────────────────────────────
    print()
    print("=" * 60)
    print("✓ RESET COMPLETE — clean slate")
    print("=" * 60)
    print()
    print("What was reset:")
    print("  • D1 database: all tests, runs, refresh_log cleared; series counts zeroed")
    print("  • data/tests/*.json: all scraped test files deleted")
    print("  • data/progress.json: deleted (will be recreated on next run)")
    print("  • data/submit_format.json: deleted (will be rediscovered)")
    print("  • data/cookies.json: deleted (cached cookies)")
    print("  • data/series/*.json: deleted (cached series test lists)")
    print("  • data/img/: deleted (downloaded images)")
    print("  • frontend/tests/*.json: deleted (copies for Pages deployment)")
    print("  • frontend/img/: deleted (copies for Pages deployment)")
    print()
    print("What was KEPT:")
    print("  • cookies/account1.json, account2.json, account3.json (your login cookies)")
    print("  • All source code (src/, worker/, etc.)")
    print("  • D1 schema (tables still exist, just empty)")
    print("  • Worker deployment (still live)")
    print()
    print("Ready for fresh local run:")
    print("  python -m src.incremental_scrape")


if __name__ == "__main__":
    main()
