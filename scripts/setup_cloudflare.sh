#!/usr/bin/env bash
# One-shot setup for Cloudflare D1 + Worker deployment.
#
# Prereqs:
#   - CLOUDFLARE_API_TOKEN env (already in GitHub secret)
#   - CLOUDFLARE_ACCOUNT_ID env
#   - npx wrangler available
#
# This script:
#   1. Creates the D1 database "repeatermock-scraper" (idempotent)
#   2. Saves database_id to worker/.env
#   3. Applies db/schema.sql
#   4. Sets worker secrets (ADMIN_PASSWORD, GH_TOKEN, GH_REPO)
#   5. Deploys the worker with cron trigger
#
# Usage:
#   ./scripts/setup_cloudflare.sh
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "✗ CLOUDFLARE_API_TOKEN env not set"
  exit 1
fi
if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "✗ CLOUDFLARE_ACCOUNT_ID env not set"
  exit 1
fi
# GH_TOKEN is optional — cron triggers will skip if not set
if [ -z "${GH_TOKEN:-}" ]; then
  echo "⚠ GH_TOKEN env not set — cron triggers will be no-ops"
  echo "  Create a GitHub PAT with repo:workflow scope and add as secret GH_PAT"
fi

DB_NAME="repeatermock-scraper"
WORKER_NAME="repeatermock-dashboard"
ADMIN_PASSWORD="BloggingTest@7"
GH_REPO="sujitbhai7710/repeatermock-scraper"

echo "============================================================"
echo "Cloudflare Setup — D1 + Worker"
echo "============================================================"
echo "  DB name:      $DB_NAME"
echo "  Worker name:  $WORKER_NAME"
echo "  GH repo:      $GH_REPO"
echo ""

# Step 1: Create D1 database (idempotent — list first, create if missing)
echo "→ Step 1: Check/create D1 database..."
DB_ID=$(npx wrangler d1 list --json 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for d in data:
    if d.get('name') == '$DB_NAME':
        print(d.get('uuid'))
        break
" 2>/dev/null || echo "")

if [ -z "$DB_ID" ]; then
  echo "  Creating database..."
  CREATE_OUT=$(npx wrangler d1 create "$DB_NAME" 2>&1 || true)
  DB_ID=$(echo "$CREATE_OUT" | grep -oE 'database_id = "[^"]+"' | head -1 | cut -d'"' -f2)
  if [ -z "$DB_ID" ]; then
    DB_ID=$(echo "$CREATE_OUT" | grep -oE '[a-f0-9-]{36}' | head -1)
  fi
  if [ -z "$DB_ID" ]; then
    echo "✗ Could not create D1 database. Output:"
    echo "$CREATE_OUT"
    exit 1
  fi
  echo "  ✓ Created database: $DB_ID"
else
  echo "  ✓ Existing database: $DB_ID"
fi

# Save for later steps
echo "DATABASE_ID=$DB_ID" > worker/.env
echo "ACCOUNT_ID=$CLOUDFLARE_ACCOUNT_ID" >> worker/.env

# Step 2: Apply schema
echo ""
echo "→ Step 2: Apply schema..."
npx wrangler d1 execute "$DB_NAME" --remote --file=db/schema.sql 2>&1 | tail -5
echo "  ✓ Schema applied"

# Step 3: Update wrangler.toml with database_id and account_id
echo ""
echo "→ Step 3: Update wrangler.toml..."
python3 << EOF
import re
with open('worker/wrangler.toml', 'r') as f:
    content = f.read()
content = re.sub(r'account_id = ".*"', f'account_id = "$CLOUDFLARE_ACCOUNT_ID"', content)
content = re.sub(r'database_id = ".*"', f'database_id = "$DB_ID"', content)
with open('worker/wrangler.toml', 'w') as f:
    f.write(content)
print("  ✓ wrangler.toml updated")
EOF

# Step 4: Set worker secrets
echo ""
echo "→ Step 4: Set worker secrets..."
cd worker
echo "$ADMIN_PASSWORD" | npx wrangler secret put ADMIN_PASSWORD 2>&1 | tail -3
if [ -n "${GH_TOKEN:-}" ]; then
  echo "$GH_TOKEN" | npx wrangler secret put GH_TOKEN 2>&1 | tail -3
fi
echo "$GH_REPO" | npx wrangler secret put GH_REPO 2>&1 | tail -3
echo "  ✓ Secrets set"

# Step 5: Deploy worker
echo ""
echo "→ Step 5: Deploy worker..."
npx wrangler deploy 2>&1 | tail -15

echo ""
echo "============================================================"
echo "✓ SETUP COMPLETE"
echo "============================================================"
echo "  Dashboard URL: https://$WORKER_NAME.<your-subdomain>.workers.dev"
echo "  Admin URL:     https://$WORKER_NAME.<your-subdomain>.workers.dev/admin"
echo "  Admin password: $ADMIN_PASSWORD"
echo "  D1 database:   $DB_ID"
echo ""
echo "Next: add these as GitHub secrets:"
echo "  D1_DATABASE_ID = $DB_ID"
echo "  WORKER_URL     = https://$WORKER_NAME.<your-subdomain>.workers.dev"
