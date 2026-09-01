#!/usr/bin/env bash
# Deploy the Cloudflare Worker + set secrets.
# Run AFTER setup_cloudflare.py has configured D1.
#
# Usage:
#   bash scripts/deploy_worker.sh
set -euo pipefail
cd "$(dirname "$0")/.."

ADMIN_PASSWORD="${ADMIN_PASSWORD:-BloggingTest@7}"
GH_REPO="${GH_REPO:-sujitbhai7710/repeatermock-scraper}"

if [ -z "${CLOUDFLARE_API_TOKEN:-}" ]; then
  echo "✗ CLOUDFLARE_API_TOKEN env not set"
  exit 1
fi
if [ -z "${CLOUDFLARE_ACCOUNT_ID:-}" ]; then
  echo "✗ CLOUDFLARE_ACCOUNT_ID env not set"
  exit 1
fi

export CLOUDFLARE_API_TOKEN
export CLOUDFLARE_ACCOUNT_ID

echo "→ Setting worker secrets..."
cd worker
echo "$ADMIN_PASSWORD" | npx wrangler secret put ADMIN_PASSWORD 2>&1 | tail -3
echo "$GH_REPO" | npx wrangler secret put GH_REPO 2>&1 | tail -3
if [ -n "${GH_TOKEN:-}" ]; then
  echo "$GH_TOKEN" | npx wrangler secret put GH_TOKEN 2>&1 | tail -3
fi
echo "  ✓ Secrets set"

echo ""
echo "→ Deploying worker..."
npx wrangler deploy 2>&1 | tail -15

echo ""
echo "✓ Worker deployed"
