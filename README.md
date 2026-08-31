# RepeaterMock Scraper

A Python scraper that extracts **real test questions** (and optionally answer keys) from [RepeaterMock](https://repeatermock.com) using Playwright with human-like browser simulation to bypass Cloudflare's bot detection.

## What it does

1. **Authenticates** with your RepeaterMock cookies (access token + refresh token)
2. **Fetches series details** via the official API (`api.repeatermock.com`)
3. **Lists all tests** across all sections and subsections
4. **Scrapes questions** for each free test by parsing the RSC (React Server Component) flight payload from the `/attempt` page
5. **Saves** structured JSON files per test with: question text (English + Hindi + other languages), options, marks, section info, and (when available) answer keys

## Quick start

```bash
# 1. Install dependencies
pip install -r requirements.txt
playwright install chromium

# 2. Set up cookies
cp .env.example .env
# Edit .env and paste your RepeaterMock cookies

# 3. Test if a series is scrapable
python -m src.scraper test-series https://repeatermock.com/tb/test-series/ssc-cgl

# 4. List all tests in a series
python -m src.scraper list-series https://repeatermock.com/tb/test-series/ssc-cgl

# 5. Scrape all free tests (questions + answers)
python -m src.scraper scrape-series https://repeatermock.com/tb/test-series/ssc-cgl

# 6. Scrape just 5 tests (for testing)
python -m src.scraper scrape-series https://repeatermock.com/tb/test-series/ssc-cgl --max-tests 5

# 7. Scrape a single test by ID
python -m src.scraper scrape-test 6a0f3ef125f9d428c136a83a --variant tb --slug ssc-cgl
```

## How to get cookies

1. Log into [repeatermock.com](https://repeatermock.com) in your browser
2. Open **DevTools** → **Application** → **Cookies** → `https://repeatermock.com`
3. Copy the values of:
   - `accessToken`
   - `refreshToken`
   - `totpVerified` (should be `1`)
   - `guestId`
   - `rm_fe`
4. Paste them into `.env` (Option A — individual cookies)

**Note:** `accessToken` expires in 15 minutes. The scraper auto-refreshes it using your `refreshToken` and saves the new cookies to `data/cookies.json` for reuse. The refresh token **rotates** on each refresh — don't reuse old refresh tokens.

## Commands

### `test-series` — Check if a series is scrapable
```bash
python -m src.scraper test-series <url>
```
Fetches series details + first free test's questions. Exits with code 0 if scrapable, 1 if not.

### `list-series` — List all tests
```bash
python -m src.scraper list-series <url>
```
Lists all tests in a series (free + locked) without scraping questions. Saves to `data/series/{variant}_{slug}_test_list.json`.

### `scrape-series` — Scrape all tests
```bash
python -m src.scraper scrape-series <url> [--max-tests N] [--no-answers]
```
Scrapes questions for all free tests in a series. Each test is saved to `data/tests/{testId}.json`.

### `scrape-test` — Scrape a single test
```bash
python -m src.scraper scrape-test <testId> --variant <tb|tb-pro|gd> --slug <slug>
```

## Output format

Each test is saved as `data/tests/{testId}.json`:

```json
{
  "test_id": "6a0f3ef125f9d428c136a83a",
  "title": "SSC CGL 2025 (Held On: 12 Sept, 2025 Shift 1)",
  "duration_minutes": 60,
  "total_marks": 200,
  "question_count": 100,
  "languages": ["English", "Hindi"],
  "is_free": true,
  "section": "Previous Year Paper (Tier I) (New Pattern)",
  "subsection": "2025",
  "has_answers": false,
  "scraped_at": "2025-08-31 10:00:00 UTC",
  "questions": [
    {
      "id": "6901f8b14d79a5a4a1ddefd0",
      "type": "mcq",
      "isNumerical": false,
      "posMarks": 2,
      "negMarks": 0.5,
      "section": 1,
      "questionNo": 1,
      "languages": {
        "en": {
          "question": "<p>In the following question, select the related word...</p>",
          "options": [
            {"prompt": "1", "value": "Energy"},
            {"prompt": "2", "value": "Temperature"},
            {"prompt": "3", "value": "Pressure"},
            {"prompt": "4", "value": "Force"}
          ]
        },
        "hi": {
          "question": "<p>निम्नलिखित प्रश्न में दिए गए विकल्पों में से...</p>",
          "options": [...]
        }
      }
    }
  ]
}
```

## How it works

### Bypassing Cloudflare
RepeaterMock uses Cloudflare's bot detection. Direct HTTP requests get `403 bot_blocked`. The scraper uses **Playwright** (headless Chromium) with:
- `navigator.webdriver` set to `undefined`
- `window.chrome.runtime` polyfill
- `console.clear` no-op (RepeaterMock's anti-debug code spams this)
- Real browser User-Agent + viewport
- Cookies loaded via `storage_state` (includes `cf_clearance`)

### Extracting questions
The `/attempt` page (e.g. `repeatermock.com/tb/test-series/ssc-cgl/test/{testId}/attempt`) returns a 400KB HTML page. The page contains a **React Server Component (RSC) flight payload** — a series of `self.__next_f.push([1,"..."])` script tags. When combined and unescaped, this payload contains all 100 question objects as JSON, embedded in the React tree.

The scraper:
1. Fetches the `/attempt` page HTML via `context.request.get()` (bypasses anti-debug JS)
2. Extracts all RSC flight chunks and concatenates them
3. Finds all `{"isNum":false,"type":"mcq"...}` objects using a brace-counting parser
4. Cleans each question into a structured format (multilingual text + options + marks)

### Answer keys
Answer keys are **not** in the `/attempt` page payload. They're only returned by `POST /api/v1/attempts/{testId}/submit` after a real test submission. The scraper attempts this with empty answers, but RepeaterMock may reject it. If the answer key is unavailable, `has_answers` is set to `false` in the output.

To get answer keys reliably, you'd need to:
1. Submit the test with real (or random) answers via the API
2. Capture the response which contains the answer key
3. Or visit the `/solution` page after submitting

## Series URLs

The scraper supports these URL patterns:

| URL | Variant | API | Description |
|-----|---------|-----|-------------|
| `repeatermock.com/tb/test-series/{slug}` | `tb` | v1 | Free test series |
| `repeatermock.com/tb-pro/test-series/{slug}` | `tb-pro` | v1 | Pro (paid) test series |
| `repeatermock.com/gd/test-series/{slug}` | `gd` | v2 | Guidely-sourced test series |

### Tested series
- ✅ `tb/test-series/ssc-cgl` — 1,313 free tests, fully scrapable
- ✅ `tb-pro/test-series/ssc-cgl` — 795 tests (first of each section is free)
- ✅ `gd/test-series/ssc-selection-post` — 49 free tests
- ⚠ `tb/test-series/ssc-maths-previous-year-questions` — see test results
- ⚠ `tb-pro/test-series/ssc-english-previous-year-questions` — see test results

Run `test-series` on any URL to check.

## GitHub Actions

A workflow is included in `.github/workflows/scrape.yml`. It:
1. Loads cookies from the `REPEATERMOCK_COOKIES_JSON` secret
2. Tests scrapability of all configured series
3. Scrapes up to 3 tests per series (to stay within Actions timeout)
4. Uploads results as artifacts

To set up:
1. Push this repo to GitHub
2. Go to **Settings → Secrets and variables → Actions → New repository secret**
3. Name: `REPEATERMOCK_COOKIES_JSON`
4. Value: the full JSON cookie array (Option C from `.env.example`)
5. Trigger the workflow manually or wait for the daily schedule

## Rate limiting

The scraper:
- Waits 1.5 seconds between tests
- Refreshes the access token every 20 tests (token expires in 15 min)
- Saves rotated cookies after each refresh

For 1,000+ tests, expect the scrape to take 30+ minutes. Use `--max-tests` for testing.

## Legal

This scraper is for personal educational use. RepeaterMock's `robots.txt` disallows scraping `/tb/test-series/*/test$` paths. Questions are aggregated from publicly available previous-year exam papers. Respect their terms of service and don't redistribute scraped content commercially.
