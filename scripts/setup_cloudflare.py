"""
One-shot Cloudflare setup via REST API.

Creates:
1. D1 database "repeatermock-scraper" (idempotent)
2. Applies db/schema.sql
3. Writes database_id to worker/wrangler.toml + worker/.env

Then prints next steps for the user (worker deploy + secrets).

Usage:
    python3 scripts/setup_cloudflare.py

Env vars:
    CLOUDFLARE_API_TOKEN  (required)
    CLOUDFLARE_ACCOUNT_ID (required)
"""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).parent.parent
SCHEMA_FILE = ROOT / "db" / "schema.sql"
WRANGLER_TOML = ROOT / "worker" / "wrangler.toml"
WORKER_ENV = ROOT / "worker" / ".env"

DB_NAME = "repeatermock-scraper"


def cf_request(method, url, token, body=None):
    """Make an authenticated Cloudflare API request."""
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        err_body = e.read().decode("utf-8", errors="replace")
        try:
            err_json = json.loads(err_body)
        except Exception:
            err_json = {"raw": err_body}
        return e.code, err_json
    except Exception as e:
        return 0, {"error": str(e)}


def find_or_create_db(account_id, token):
    """Find existing D1 database by name, or create a new one."""
    # List existing databases (paginated)
    page = 1
    while True:
        url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database?per_page=100&page={page}"
        status, body = cf_request("GET", url, token)
        if status == 401:
            print("✗ Authentication error — your CLOUDFLARE_API_TOKEN doesn't have D1 permission.")
            print()
            print("  To fix: create a new API token at https://dash.cloudflare.com/profile/api-tokens")
            print("  with these permissions:")
            print("    • Account > D1 > Edit")
            print("    • Account > Workers Scripts > Edit")
            print("    • Account > Cloudflare Pages > Edit")
            print("    • Account > Account Settings > Read")
            print()
            print("  Then update the CLOUDFLARE_API_TOKEN GitHub secret and re-run this workflow.")
            sys.exit(1)
        if status != 200:
            print(f"✗ Failed to list D1 databases: HTTP {status}")
            print(f"  Response: {json.dumps(body, indent=2)[:500]}")
            sys.exit(1)

        for db in body.get("result", []) or []:
            if db.get("name") == DB_NAME:
                print(f"  ✓ Found existing database: {db['uuid']}")
                return db["uuid"]

        # Check if there are more pages
        info = body.get("result_info", {})
        if info.get("page") * info.get("per_page", 100) >= info.get("count", 0):
            break
        page += 1
        if page > 50:  # safety
            break

    # Create new database
    print(f"  Creating database '{DB_NAME}'...")
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database"
    status, body = cf_request("POST", url, token, body={"name": DB_NAME})
    if status == 401:
        print("✗ Authentication error — your CLOUDFLARE_API_TOKEN doesn't have D1 permission.")
        sys.exit(1)
    if status != 200 or not body.get("success"):
        print(f"✗ Failed to create D1 database: HTTP {status}")
        print(f"  Response: {json.dumps(body, indent=2)[:500]}")
        sys.exit(1)

    db_id = body["result"]["uuid"]
    print(f"  ✓ Created database: {db_id}")
    return db_id


def apply_schema(account_id, db_id, token):
    """Apply schema.sql to the D1 database."""
    if not SCHEMA_FILE.exists():
        print(f"✗ Schema file not found: {SCHEMA_FILE}")
        sys.exit(1)

    schema_sql = SCHEMA_FILE.read_text()
    # Split on semicolons (simple split — D1 batch API handles each statement)
    statements = [s.strip() for s in schema_sql.split(";") if s.strip() and not s.strip().startswith("--")]
    print(f"  Applying {len(statements)} statements from schema.sql...")

    # D1 batch endpoint
    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_id}/batch"
    body = {"statements": [{"sql": s, "params": []} for s in statements]}
    status, resp = cf_request("POST", url, token, body=body)
    if status != 200 or not resp.get("success"):
        print(f"✗ Schema apply failed: HTTP {status}")
        print(f"  Response: {json.dumps(resp, indent=2)[:1000]}")
        # Try statements one by one for better error messages
        print("  Retrying statement-by-statement...")
        for i, s in enumerate(statements):
            single_url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/d1/database/{db_id}/query"
            single_body = {"sql": s, "params": []}
            s_status, s_resp = cf_request("POST", single_url, token, body=single_body)
            if s_status != 200 or not s_resp.get("success"):
                first_word = s.split()[0] if s.split() else "?"
                if "already exists" in str(s_resp).lower():
                    print(f"    [{i+1}] {first_word}... — already exists (skipping)")
                else:
                    print(f"    [{i+1}] {first_word}... — FAILED: {str(s_resp)[:200]}")
            else:
                first_word = s.split()[0] if s.split() else "?"
                print(f"    [{i+1}] {first_word}... — OK")
    else:
        print(f"  ✓ Schema applied ({len(statements)} statements)")


def update_wrangler_config(db_id, account_id):
    """Update worker/wrangler.toml with database_id and account_id."""
    if not WRANGLER_TOML.exists():
        print(f"✗ wrangler.toml not found: {WRANGLER_TOML}")
        return

    content = WRANGLER_TOML.read_text()
    content = re.sub(r'account_id = ".*?"', f'account_id = "{account_id}"', content)
    content = re.sub(r'database_id = ".*?"', f'database_id = "{db_id}"', content)
    WRANGLER_TOML.write_text(content)
    print(f"  ✓ Updated {WRANGLER_TOML.relative_to(ROOT)}")

    # Also write worker/.env (for update_d1.py fallback)
    WORKER_ENV.parent.mkdir(exist_ok=True)
    WORKER_ENV.write_text(
        f"DATABASE_ID={db_id}\n"
        f"ACCOUNT_ID={account_id}\n"
    )
    print(f"  ✓ Updated {WORKER_ENV.relative_to(ROOT)}")


def main():
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")

    if not token:
        print("✗ CLOUDFLARE_API_TOKEN env not set")
        sys.exit(1)
    if not account_id:
        print("✗ CLOUDFLARE_ACCOUNT_ID env not set")
        sys.exit(1)

    print("=" * 60)
    print("Cloudflare D1 Setup")
    print("=" * 60)
    print(f"  DB name: {DB_NAME}")
    print(f"  Account: {account_id}")
    print()

    print("→ Step 1: Find or create D1 database...")
    db_id = find_or_create_db(account_id, token)

    print()
    print("→ Step 2: Apply schema...")
    apply_schema(account_id, db_id, token)

    print()
    print("→ Step 3: Update wrangler.toml + worker/.env...")
    update_wrangler_config(db_id, account_id)

    print()
    print("=" * 60)
    print("✓ D1 SETUP COMPLETE")
    print("=" * 60)
    print(f"  Database ID: {db_id}")
    print(f"  Database name: {DB_NAME}")
    print()
    print("Next steps (run from worker/ directory):")
    print("  cd worker")
    print('  echo "BloggingTest@7" | npx wrangler secret put ADMIN_PASSWORD')
    print('  echo "sujitbhai7710/repeatermock-scraper" | npx wrangler secret put GH_REPO')
    print('  # Optional: echo "<github-pat>" | npx wrangler secret put GH_TOKEN')
    print("  npx wrangler deploy")
    print()
    print("Or run scripts/deploy_worker.sh to do all of the above.")


if __name__ == "__main__":
    main()
