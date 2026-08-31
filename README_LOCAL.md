# RepeaterMock Scraper — Local & GitHub Actions

Scrape real test questions, answer keys, solutions, and analysis from RepeaterMock.com.
Works both locally and in GitHub Actions. Self-sustaining token rotation (no manual
cookie updates after the first one).

## Quick Start (Local)

### Prerequisites

```bash
pip install -r requirements.txt
playwright install chromium
```

### Option 1: Env var (recommended for local)

Set `REPEATERMOCK_COOKIES` to a JSON array of cookies (copied from your browser's
cookie editor extension, e.g. "Cookie-Editor"):

```bash
export REPEATERMOCK_COOKIES='[
  {
    "domain": ".repeatermock.com",
    "httpOnly": true,
    "name": "accessToken",
    "path": "/",
    "sameSite": "lax",
    "secure": true,
    "value": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
  },
  {
    "domain": ".repeatermock.com",
    "httpOnly": true,
    "name": "refreshToken",
    "path": "/",
    "sameSite": "lax",
    "secure": true,
    "value": "c0dd4ce83b91f095786c357491da88ed89f80574d0a033f1b9e129e5b3128b42..."
  },
  {
    "domain": ".repeatermock.com",
    "httpOnly": true,
    "name": "totpVerified",
    "path": "/",
    "sameSite": "lax",
    "secure": true,
    "value": "1"
  }
]'
```

Then run:

```bash
python -m src.incremental_scrape
```

This runs with NO time limit — it will keep scraping until ALL tests across all 53 series are fully scraped (questions + answers + solutions + analysis). Only stops if:
- All tests are scraped (success!)
- 10 consecutive auth failures (refresh token exhausted — re-login and update cookies)
- You press Ctrl+C

### Option 2: Cookie file

Save the JSON array to `cookies/account1.json`:

```bash
# Paste the cookie JSON array into:
cookies/account1.json
```

Then run:

```bash
python -m src.incremental_scrape
```

## How to get cookies from your browser

1. Login to https://repeatermock.com (use Google Authenticator)
2. Install the "Cookie-Editor" browser extension
3. Visit https://repeatermock.com
4. Click the Cookie-Editor icon → "Export" (JSON format)
5. Copy the JSON array
6. Paste it into `cookies/account1.json` OR set as `REPEATERMOCK_COOKIES` env var

## Command-line options

```bash
# Default: no time limit, scrape everything
python -m src.incremental_scrape

# With a time limit (optional — stops after N minutes)
python -m src.incremental_scrape --time-limit-minutes 120

# Limit to N tests (optional — useful for testing)
python -m src.incremental_scrape --max-tests 10
```

| Option | Default | Description |
|--------|---------|-------------|
| `--time-limit-minutes` | 0 (no limit) | Stop after N minutes. 0 = run until all tests scraped |
| `--max-tests` | 0 (unlimited) | Stop after N tests scraped. 0 = no limit |

## What gets scraped

For each test, the scraper fetches:
1. `/attempt` page → 100 questions (with multilingual text + options)
2. **Submits a dummy attempt** (so /solution and /analysis return data)
3. `/solution` page → 100 answer keys + multilingual solutions + images
4. `/analysis` page → rank, percentile, cutoffs, average marks, marks distribution

**Only fully-scraped tests (Q + A + Sol + Ana) are saved** as JSON files in
`data/tests/{test_id}.json`. Partial scrapes are NOT saved — they're retried
on the next run.

## Self-sustaining token rotation

RepeaterMock's access token expires every 15 minutes. The refresh token rotates
on every `/auth/refresh` call. The scraper handles this:

1. **At startup**: always force-refreshes to get a fresh 15-min access token
   (the provided access token may be close to expiry if you exported cookies
   a few minutes ago)
2. **Proactive refresh every 8 tests** (~3 min) — keeps access token fresh
3. **Captures rotated refresh token** from `Set-Cookie` response header
4. **Saves rotated token** to `cookies/account1.json` immediately
5. **Next run uses the rotated token** — self-sustaining loop

After the first successful run, you never need to manually update cookies again.

**IMPORTANT**: Only run ONE instance of the scraper at a time. If two instances
try to use the same refresh token, one will fail (the token rotates on every use).
The GitHub Actions workflow uses `cancel-in-progress: true` to prevent this.

## Cloudflare D1 + Worker Dashboard

The scraper syncs progress to a Cloudflare D1 database every 15 minutes
(via `.github/workflows/d1-sync.yml`). The dashboard is at:

- **Dashboard**: https://repeatermock-dashboard.walletxapi.workers.dev
- **Admin**: https://repeatermock-dashboard.walletxapi.workers.dev/admin
- **Admin password**: `BloggingTest@7`

### What the dashboard shows

- **Overview**: total series, total tests, scraped, partial, failed, pending, questions, progress %
- **Series progress table**: per-series scraped/partial/failed/pending counts + progress bars
- **Recent runs**: last 20 runs with duration, account used, tests scraped/partial/failed
- **Recent failures**: last 50 partial/failed tests with what's missing (Q/A/Sol/Ana/Img) + error message

### D1 sync (15-min)

Every 15 minutes, the `d1-sync.yml` workflow:
1. Restores the cached `data/progress.json`
2. Calls `python -m src.update_d1` to sync to D1
3. The dashboard reads from D1 and shows live progress

## GitHub Actions workflows

| Workflow | Schedule | Purpose |
|----------|----------|---------|
| `scrape.yml` | Every hour at :10 | Scrape tests, save JSON, deploy frontend, commit cookies |
| `d1-sync.yml` | Every 15 min | Sync `progress.json` to D1 (updates dashboard) |

### Concurrency

- `scrape.yml` uses `concurrency: cancel-in-progress: true` — only one scrape run at a time
  (prevents two runs from consuming the same refresh token)
- `d1-sync.yml` uses `concurrency: cancel-in-progress: true` — only one sync at a time

## Output files

```
data/
├── tests/
│   ├── 6a0f3ef125f9d428c136a83a.json    # Fully-scraped test (Q + A + Sol + Ana)
│   ├── 6a0f3ef35a73de9e21cdf098.json
│   └── ...
├── progress.json                         # Scrape progress (scraped/partial/failed IDs)
└── submit_format.json                    # Saved working submit payload format

frontend/
├── tests/
│   ├── 6a0f3ef125f9d428c136a83a.json    # Copies for Cloudflare Pages deployment
│   └── index.json                        # List of all fully-scraped tests (for frontend)

cookies/
└── account1.json                         # Login cookies (auto-updated by token rotation)
```

## Test JSON format

Each `data/tests/{test_id}.json` contains:

```json
{
  "test_id": "6a0f3ef125f9d428c136a83a",
  "title": "SSC CGL 2025 (Held On: 12 Sept, 2025 Shift 1)",
  "duration_minutes": 60,
  "total_marks": 200,
  "question_count": 100,
  "platform": "tb-pro",
  "slug": "ssc-cgl",
  "series_url": "https://repeatermock.com/tb-pro/test-series/ssc-cgl",
  "scraped_at": "2026-08-31 22:30:00 UTC",
  "questions": [...],          // 100 questions with multilingual text + options
  "answers": {...},            // 100 answer keys + multilingual solutions
  "analysis": {...},           // rank, percentile, cutoffs, marks distribution
  "has_answers": true,
  "has_analysis": true
}
```

## Troubleshooting

### "All cookie sets failed. Exiting"

Your refresh token has expired or been consumed. Get fresh cookies from your browser
(see "How to get cookies" above) and update `cookies/account1.json` or the
`REPEATERMOCK_COOKIES` env var.

### "Force refresh failed: HTTP 401"

The refresh token has been used by a concurrent run. Make sure only one scrape
runs at a time (the GitHub Actions concurrency group handles this automatically).

### "No active attempt found" on submit

The `/attempt` page didn't create an attempt server-side. The scraper retries
`page.goto()` automatically. If it persists, the test is marked as failed.

### Tests marked as "partial" (missing answers/analysis)

The submit failed, so `/solution` and `/analysis` didn't return data. The test
is NOT saved as a JSON file (only fully-scraped tests are saved). It's retried
on the next run.

## Target series (53 total)

See `src/series_config.py` for the full list. Includes SSC CGL/CHSL/MTS/CPO/GD,
RRB Group D, RRB NTPC, SBI PO, and more — across tb (free), tb-pro (pro), and
gd (guidely) platforms.
