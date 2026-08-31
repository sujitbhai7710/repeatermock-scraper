"""
Push scrape progress into Cloudflare D1.

Reads:
  - data/progress.json     (scraped/partial/failed test IDs, series_cache, run_history)
  - data/tests/*.json      (individual scraped test files)

Writes to D1 tables: series, tests, runs

Usage:
    python -m src.update_d1

Requires env vars:
    CLOUDFLARE_API_TOKEN
    CLOUDFLARE_ACCOUNT_ID
    D1_DATABASE_ID

Or reads from .env file.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
PROGRESS_FILE = ROOT / "data" / "progress.json"
TESTS_DIR = ROOT / "data" / "tests"

# ─── Config ──────────────────────────────────────────────────────────────────

# Import target series list
sys.path.insert(0, str(ROOT))
from src.series_config import TARGET_SERIES


def get_env():
    """Load env vars from environment or .env file or wrangler.toml."""
    env = dict(os.environ)
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    # Also try worker/.env (created by setup_cloudflare.sh)
    worker_env = ROOT / "worker" / ".env"
    if worker_env.exists():
        for line in worker_env.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env.setdefault(k.strip(), v.strip().strip('"').strip("'"))

    # Also extract D1_DATABASE_ID from worker/wrangler.toml as fallback
    if not env.get("D1_DATABASE_ID"):
        wrangler_toml = ROOT / "worker" / "wrangler.toml"
        if wrangler_toml.exists():
            import re
            content = wrangler_toml.read_text()
            m = re.search(r'database_id\s*=\s*"([^"]+)"', content)
            if m:
                env["D1_DATABASE_ID"] = m.group(1)

    return env


def d1_query(env, sql, params=None):
    """Execute a SQL query against D1 via REST API. Returns parsed JSON response."""
    api_token = env.get("CLOUDFLARE_API_TOKEN")
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID")
    db_id = env.get("D1_DATABASE_ID")

    if not all([api_token, account_id, db_id]):
        raise RuntimeError(
            "Missing required env vars. Need CLOUDFLARE_API_TOKEN, "
            "CLOUDFLARE_ACCOUNT_ID, D1_DATABASE_ID"
        )

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_id}/query"
    body = json.dumps({"sql": sql, "params": params or []}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"D1 query HTTP {e.code}: {err_body}\nSQL: {sql}\nParams: {params}")
    except Exception as e:
        raise RuntimeError(f"D1 query error: {e}\nSQL: {sql}")


def d1_exec_batch(env, statements):
    """Execute a batch of SQL statements (each is {sql, params})."""
    api_token = env.get("CLOUDFLARE_API_TOKEN")
    account_id = env.get("CLOUDFLARE_ACCOUNT_ID")
    db_id = env.get("D1_DATABASE_ID")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_id}/batch"

    body = json.dumps({"statements": statements}).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {api_token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"D1 batch HTTP {e.code}: {err_body}")
    except Exception as e:
        raise RuntimeError(f"D1 batch error: {e}")


# ─── Sync logic ──────────────────────────────────────────────────────────────

def sync_series_table(env, progress):
    """Upsert all 52 target series into D1."""
    series_cache = progress.get("series_cache", {})
    series_progress = progress.get("series_progress", {})

    statements = []
    for s in TARGET_SERIES:
        url = f"https://repeatermock.com/{s['platform']}/test-series/{s['slug']}"
        cached = series_cache.get(url, {})
        sp = series_progress.get(url, {})

        total = sp.get("total", len(cached.get("tests", [])))
        scraped = sp.get("scraped", 0)
        partial = sp.get("partial", 0)
        failed = sp.get("failed", 0)
        pending = sp.get("pending", 0)
        last_fetched = int(cached.get("fetched_at", 0)) if cached else None
        last_scraped = int(sp.get("updated_at", 0)) if sp else None

        sql = """
            INSERT INTO series
                (platform, slug, name, series_url, total_tests, scraped_count,
                 partial_count, failed_count, pending_count, last_fetched_at,
                 last_scraped_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(platform, slug) DO UPDATE SET
                name = excluded.name,
                total_tests = excluded.total_tests,
                scraped_count = excluded.scraped_count,
                partial_count = excluded.partial_count,
                failed_count = excluded.failed_count,
                pending_count = excluded.pending_count,
                last_fetched_at = excluded.last_fetched_at,
                last_scraped_at = excluded.last_scraped_at,
                updated_at = excluded.updated_at
        """
        params = [s["platform"], s["slug"], s["name"], url, total, scraped,
                  partial, failed, pending, last_fetched, last_scraped, int(time.time())]
        statements.append({"sql": sql, "params": params})

    # D1 batch limit is ~1000 statements per call — we have 52, fine
    result = d1_exec_batch(env, statements)
    print(f"  ✓ Synced {len(statements)} series to D1")
    return result


def sync_tests_table(env, progress):
    """Upsert each test's status into D1."""
    series_cache = progress.get("series_cache", {})
    tests_status = progress.get("tests_status", {})
    scraped_ids = set(progress.get("scraped_test_ids", []))
    partial_ids = set(progress.get("partial_test_ids", []))
    failed_ids = set(progress.get("failed_test_ids", []))

    # Build a map of test_id → series_url, test meta from cache
    test_to_series = {}
    for series_url, cache in series_cache.items():
        for t in cache.get("tests", []):
            test_to_series[t["id"]] = {
                "series_url": series_url,
                "series_name": cache.get("name", ""),
                "title": t.get("title", ""),
                "section": t.get("_section", ""),
                "subsection": t.get("_subsection", ""),
                "duration": t.get("duration", 60),
                "total_mark": t.get("totalMark", 200),
                "question_count": t.get("questionCount", 100),
                "is_free": 1 if t.get("isFree") else 0,
            }

    statements = []
    # Iterate over all tests in caches (covers pending, scraped, partial, failed)
    seen_test_ids = set()
    for series_url, cache in series_cache.items():
        for t in cache.get("tests", []):
            tid = t["id"]
            if tid in seen_test_ids:
                continue
            seen_test_ids.add(tid)

            meta = test_to_series.get(tid, {})
            status = tests_status.get(tid, {})
            st = status.get("status", "pending")
            if tid in scraped_ids and st != "scraped":
                st = "scraped"
            if tid in partial_ids and st not in ("partial", "scraped"):
                st = "partial"
            if tid in failed_ids and st not in ("failed", "scraped", "partial"):
                st = "failed"

            # Check if the JSON file actually exists
            file_path = TESTS_DIR / f"{tid}.json"
            file_size = file_path.stat().st_size if file_path.exists() else None

            sql = """
                INSERT INTO tests
                    (test_id, series_url, series_name, title, section, subsection,
                     duration_minutes, total_marks, question_count, is_free,
                     status, has_questions, has_answers, has_solutions, has_analysis,
                     has_images, actual_questions, error_message, last_attempted_at,
                     scraped_at, file_path, file_size_bytes, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(test_id) DO UPDATE SET
                    series_url = excluded.series_url,
                    series_name = excluded.series_name,
                    title = excluded.title,
                    section = excluded.section,
                    subsection = excluded.subsection,
                    duration_minutes = excluded.duration_minutes,
                    total_marks = excluded.total_marks,
                    question_count = excluded.question_count,
                    is_free = excluded.is_free,
                    status = excluded.status,
                    has_questions = excluded.has_questions,
                    has_answers = excluded.has_answers,
                    has_solutions = excluded.has_solutions,
                    has_analysis = excluded.has_analysis,
                    has_images = excluded.has_images,
                    actual_questions = excluded.actual_questions,
                    error_message = excluded.error_message,
                    last_attempted_at = excluded.last_attempted_at,
                    scraped_at = excluded.scraped_at,
                    file_path = excluded.file_path,
                    file_size_bytes = excluded.file_size_bytes,
                    updated_at = excluded.updated_at
            """
            params = [
                tid, meta.get("series_url", series_url),
                meta.get("series_name", ""), meta.get("title", ""),
                meta.get("section", ""), meta.get("subsection", ""),
                meta.get("duration", 60), meta.get("total_mark", 200),
                meta.get("question_count", 100), meta.get("is_free", 0),
                st,
                1 if status.get("has_questions") else (1 if file_path.exists() else 0),
                1 if status.get("has_answers") else 0,
                1 if status.get("has_solutions") else 0,
                1 if status.get("has_analysis") else 0,
                1 if status.get("has_images") else 0,
                status.get("question_count", 0),
                status.get("error"),
                int(status.get("last_attempted_at", 0)) if status.get("last_attempted_at") else None,
                int(status.get("last_attempted_at", 0)) if st == "scraped" else None,
                str(file_path.relative_to(ROOT)) if file_path.exists() else None,
                file_size,
                int(time.time()),
            ]
            statements.append({"sql": sql, "params": params})

            # Batch in groups of 200 (D1 batch limit ~1000)
            if len(statements) >= 200:
                d1_exec_batch(env, statements)
                print(f"  ✓ Synced {len(seen_test_ids)} tests so far...")
                statements = []

    if statements:
        d1_exec_batch(env, statements)

    print(f"  ✓ Synced {len(seen_test_ids)} tests to D1")


def sync_runs_table(env, progress):
    """Insert the latest run into D1."""
    run_history = progress.get("run_history", [])
    if not run_history:
        print("  ⚠ No run history to sync")
        return

    # Sync last 10 runs
    statements = []
    for r in run_history[-10:]:
        # Check if already exists
        check = d1_query(env, "SELECT id FROM runs WHERE started_at = ? AND ended_at = ?",
                         [int(r.get("start", 0)), int(r.get("end", 0))])
        existing = check.get("result", [{}])[0].get("results", [])
        if existing:
            continue

        sql = """
            INSERT INTO runs
                (started_at, ended_at, time_minutes, account_used,
                 tests_scraped, tests_partial, tests_failed,
                 questions_scraped, status, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = [
            int(r.get("start", 0)), int(r.get("end", 0)),
            r.get("time_minutes", 0), r.get("account_used"),
            r.get("tests_scraped", 0), r.get("tests_partial", 0),
            r.get("tests_failed", 0), r.get("questions_scraped", 0),
            "completed", ""
        ]
        statements.append({"sql": sql, "params": params})

    if statements:
        d1_exec_batch(env, statements)
        print(f"  ✓ Synced {len(statements)} runs to D1")
    else:
        print(f"  ✓ All runs already in D1")


def main():
    if not PROGRESS_FILE.exists():
        print(f"✗ No progress file at {PROGRESS_FILE}")
        sys.exit(1)

    progress = json.loads(PROGRESS_FILE.read_text())
    env = get_env()

    print("=" * 60)
    print("D1 SYNC")
    print("=" * 60)
    print(f"  Series: {len(TARGET_SERIES)}")
    print(f"  Scraped: {len(progress.get('scraped_test_ids', []))}")
    print(f"  Partial: {len(progress.get('partial_test_ids', []))}")
    print(f"  Failed: {len(progress.get('failed_test_ids', []))}")
    print(f"  Test files: {len(list(TESTS_DIR.glob('*.json'))) if TESTS_DIR.exists() else 0}")

    try:
        sync_series_table(env, progress)
        sync_tests_table(env, progress)
        sync_runs_table(env, progress)
        print("\n✓ D1 sync complete")
    except Exception as e:
        print(f"\n✗ D1 sync failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
