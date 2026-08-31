# RepeaterMock Scraper — Learnings & Documentation for AI Agents

> **Purpose**: This document captures everything learned during development so a new AI agent can understand the project, avoid past mistakes, and continue the work.

---

## Table of Contents
1. [Project Overview](#project-overview)
2. [Architecture](#architecture)
3. [How RepeaterMock Works (Technical)](#how-repeatermock-works-technical)
4. [Scraping Strategy](#scraping-strategy)
5. [Mistakes Made & Lessons Learned](#mistakes-made--lessons-learned)
6. [Known Issues & Limitations](#known-issues--limitations)
7. [Cookie Management](#cookie-management)
8. [GitHub Actions Setup](#github-actions-setup)
9. [Frontend Deployment](#frontend-deployment)
10. [Future Work](#future-work)

---

## Project Overview

**Goal**: Scrape real SSC exam questions, answer keys, solutions, and analysis data from RepeaterMock.com and serve them via a static website on Cloudflare Pages.

**GitHub Repo**: https://github.com/sujitbhai7710/repeatermock-scraper
**Live Site**: https://pwthor-mock-tests.pages.dev/

### What's been achieved:
- ✅ 2,157+ test IDs cataloged across 8 series (SSC CGL, CHSL, MTS, GD, Selection Post, Maths PYP, English PYP)
- ✅ Real questions scraped from /attempt pages (100 questions per full test)
- ✅ Answer keys + solutions scraped from /solution pages (correctOption + multilingual explanations)
- ✅ Analysis data scraped from /analysis pages (rank, percentile, cutoffs, average marks, marks distribution)
- ✅ MathJax rendering for LaTeX math (fractions, angles, etc.)
- ✅ Solution images from cdn.repeatermock.com rendering properly
- ✅ Rank predictor (calculates rank for any score using rankMarksData)
- ✅ Frontend test runner with timer, question palette, section navigation

---

## Architecture

```
repeatermock-scraper/
├── src/
│   ├── scraper.py              # Base scraper: test-series, list-series, scrape-series, scrape-test
│   ├── full_scraper.py         # Full scraper: questions + answers + solutions + analysis
│   ├── incremental_scrape.py   # Incremental scraper with time limit + progress tracking
│   ├── cookie_manager.py       # Cookie loading/saving/rotation
│   ├── question_parser.py      # RSC flight payload parser (extracts questions from HTML)
│   └── logging_config.py       # Python logging setup
├── frontend/                   # Static website (deployed to Cloudflare Pages)
│   ├── index.html              # SPA entry point (includes MathJax)
│   ├── data.js                 # Series catalog (2,157 tests with real IDs)
│   ├── assets/
│   │   ├── styles.css          # RepeaterMock-style UI
│   │   └── router.js           # SPA router + test runner + result page + rank predictor
│   ├── tests/                  # Scraped question JSON files
│   └── _redirects              # SPA fallback for Cloudflare Pages
├── scripts/                    # Test/debug scripts
├── data/                       # Scraper output (gitignored)
│   ├── tests/                  # Scraped test JSON files
│   ├── series/                 # Series metadata
│   ├── cookies.json            # Auto-saved rotated cookies
│   └── progress.json           # Incremental scrape progress
├── .github/workflows/scrape.yml
└── .env.example
```

---

## How RepeaterMock Works (Technical)

### Tech Stack
- **Frontend**: Next.js 15 (App Router) with React Server Components (RSC)
- **API**: `api.repeatermock.com` (separate subdomain)
- **Bot Protection**: Cloudflare WAF + custom anti-debug JavaScript
- **Auth**: JWT access token (15-min expiry) + rotating refresh token

### API Endpoints (Discovered)
| Endpoint | Method | Purpose |
|----------|--------|---------|
| `api.repeatermock.com/auth/me` | GET | Check auth status |
| `api.repeatermock.com/auth/refresh` | POST | Refresh access token (rotates refresh token!) |
| `api.repeatermock.com/api/v1/test-series/{slug}?variant={tb\|tb-pro}` | GET | Series details (sections, subsections, test counts) |
| `api.repeatermock.com/api/v1/test-series/{id}/sections/{sectionId}/tests?limit=500&offset=0&variant={v}&subSectionId={subId}` | GET | List tests in a subsection |
| `api.repeatermock.com/api/v2/test-series/{slug}` | GET | Same for "gd" variant (Guidely-sourced) |
| `api.repeatermock.com/api/v2/test-series/{id}/sections/{secId}/tests?limit=500&offset=0` | GET | List tests (v2 API) |
| `repeatermock.com/{variant}/test-series/{slug}/test/{testId}/attempt` | GET (HTML) | Test questions page (RSC payload) |
| `repeatermock.com/{variant}/test-series/{slug}/test/{testId}/solution` | GET (HTML) | Answer keys + solutions (RSC payload) |
| `repeatermock.com/{variant}/test-series/{slug}/test/{testId}/analysis` | GET (HTML) | Rank, cutoffs, percentile (RSC payload) |
| `api.repeatermock.com/api/v1/attempts/{testId}/submit` | POST | Submit test attempt (returns answer key) |

### RSC Flight Payload
RepeaterMock uses Next.js RSC. The page HTML contains `<script>` tags with `self.__next_f.push([1,"..."])` calls. Each chunk is a JSON-escaped string. Combined and unescaped, they form the RSC flight payload — a text-based serialization of the React component tree.

**Questions** are embedded as JSON objects in the payload:
```json
{"isNum":false,"type":"mcq","negMarks":0.5,"posMarks":2,"_id":"6901f8b14d79a5a4a1ddefd0","en":{"value":"<p>Question text...</p>","options":[{"prompt":"1","value":"Option A"},...]}}
```

**Answer keys** are in the `answersData` object:
```json
"answersData":{"690b34473f7e30afba7292a8":{"correctOption":"1","sol":{"en":{"value":"<p>Solution text with <img src='cdn.repeatermock.com/...'> images</p>"}}}}
```

**Analysis data** is in the `analysisData` object:
```json
"analysisData":{"ts":{"rank":1912,"percentile":6.42,"marks":0},"analysis":{"title":"...","maxMarks":200,"avgMarks":108.18,"totalStudents":2042,"rankMarksData":[{"marks":188.5,"rank":1,"per":100},...]}}
```

### Anti-Debug Mechanism
RepeaterMock's JS includes anti-debug code that:
1. Spams `console.clear()` in a loop
2. Calls `window.close()`
3. Navigates to `about:blank` via `window.location`

**Bypass**: Add `console.clear = function(){};` and `window.close = function(){};` via `context.add_init_script()`. The navigation to `about:blank` is harder to block — but using `context.request.get()` instead of `page.goto()` avoids triggering it entirely.

---

## Scraping Strategy

### Phase 1: Fetch Test List (Fast — API calls only)
1. Call `/api/v1/test-series/{slug}?variant={variant}` → get series ID + sections + subsections
2. For each subsection, call `/api/v1/test-series/{id}/sections/{secId}/tests?limit=500` → get all test IDs + metadata

### Phase 2: Scrape Each Test (3 HTTP requests per test)
1. `GET /{variant}/test-series/{slug}/test/{testId}/attempt` → parse questions from RSC payload
2. `GET /{variant}/test-series/{slug}/test/{testId}/solution` → parse answersData (answer keys + solutions)
3. `GET /{variant}/test-series/{slug}/test/{testId}/analysis` → parse analysisData (rank, cutoffs, etc.)

**Note**: Steps 2 and 3 only return data if the test has been previously attempted by the authenticated user. For tests without attempts, only questions are available.

### Phase 3: Parse RSC Payload
1. Extract all `self.__next_f.push([1,"..."])` chunks from HTML
2. Unescape each chunk (JSON string unescaping)
3. Concatenate into full payload
4. Find JSON objects using brace-matching parser
5. Extract `answersData` and `analysisData` by key name

---

## Mistakes Made & Lessons Learned

### 1. Refresh Token Rotation
**Mistake**: Used the same refresh token for both local testing and GitHub Actions.
**Result**: The refresh token was consumed by local testing, making it invalid for CI.
**Lesson**: RepeaterMock **rotates the refresh token on every `/auth/refresh` call**. The old token becomes invalid immediately. Never use the same session in two places simultaneously.
**Fix**: The scraper saves rotated cookies to `data/cookies.json` and the GitHub Actions cache persists them between runs.

### 2. Double-Escaped HTML Entities
**Mistake**: Used `html.unescape()` once on solution text.
**Result**: Solutions showed `&lt;p&gt;&lt;img src=&quot;...&quot;&gt;` instead of `<p><img src="...">`.
**Lesson**: RepeaterMock double-escapes HTML entities in option values and solution text.
**Fix**: Created `thorough_unescape()` that unescapes up to 3 times until stable.

### 3. Cloudflare Bot Detection
**Mistake**: Tried to scrape with direct HTTP requests (curl/requests).
**Result**: All requests returned `403 bot_blocked` or `cf-mitigated: challenge`.
**Lesson**: RepeaterMock uses Cloudflare WAF that blocks non-browser requests.
**Fix**: Use Playwright with headless Chromium + anti-detection measures (`navigator.webdriver = undefined`, real User-Agent, etc.).

### 4. Anti-Debug Code
**Mistake**: Used `page.goto()` to load the /attempt page.
**Result**: The page's anti-debug JS detected the automation and navigated to `about:blank`, destroying the page.
**Lesson**: RepeaterMock's anti-debug code runs on page load and detects automation.
**Fix**: Use `context.request.get()` instead of `page.goto()` — this fetches the HTML directly without executing JavaScript, bypassing the anti-debug entirely.

### 5. Inline Python in GitHub Actions
**Mistake**: Used heredoc-style Python in workflow YAML with improper indentation.
**Result**: `IndentationError: unexpected indent` in CI.
**Lesson**: Python's indentation is significant — inline Python in bash heredocs can break.
**Fix**: Use `python3 << 'EOF'` (quoted delimiter to prevent variable expansion) and ensure proper indentation.

### 6. SPA Fallback Returns 200 with HTML
**Mistake**: Checked only `resp.ok` (status 200) to determine if JSON file exists.
**Result**: The Cloudflare Pages SPA fallback (`/* /index.html 200`) returns 200 with HTML for missing JSON files.
**Lesson**: Always check `content-type` header, not just status code.
**Fix**: Check `resp.headers.get("content-type").includes("json")`.

### 7. MathJax Not Rendering
**Mistake**: Expected MathJax to auto-render after setting `innerHTML`.
**Result**: LaTeX like `\(\frac{1}{4}\)` showed as raw text.
**Lesson**: MathJax needs explicit `typeset()` call after dynamic content insertion.
**Fix**: Call `window.MathJax.typesetPromise([element])` after rendering each question.

### 8. Solution HTML Not Rendering
**Mistake**: Used `exDiv.innerHTML = "<strong>Solution:</strong> " + solText` where `solText` contained escaped HTML.
**Result**: Solutions showed raw HTML tags as text.
**Lesson**: When mixing static HTML with dynamic HTML, create separate DOM elements.
**Fix**: Create a `<strong>` label element, then a separate `<div>` for the solution content with `innerHTML`.

### 9. "Loading..." Indicator Never Cleared
**Mistake**: Added "Loading result..." at the start of `renderResult()` but never removed it.
**Result**: "Loading..." text stayed visible above the actual content.
**Fix**: Remove `.rm-loading` element after content is rendered.

### 10. Cookie Expiry During Long Scraping Sessions
**Mistake**: Didn't refresh cookies during long scraping runs.
**Result**: Access token expired (15-min lifespan) mid-scrape, causing 401 errors.
**Fix**: Refresh cookies every 20 tests (well within the 15-min window).

---

## Known Issues & Limitations

### 1. Answer Keys Require Previous Attempts
The `/solution` and `/analysis` pages only return data if the authenticated user has previously submitted an attempt for that test. For tests without attempts, only questions are available (no answer keys).

**Workaround**: Submit a dummy attempt (all questions skipped, 0 time) via `POST /api/v1/attempts/{testId}/submit` before fetching solutions. This requires reverse-engineering the submit payload format.

### 2. Refresh Token Cannot Be Shared
The refresh token rotates on every use. If you run the scraper locally AND in GitHub Actions, one will invalidate the other.

**Solution**: Use separate RepeaterMock accounts for local and CI. Or only run in one place at a time.

### 3. Cloudflare Rate Limiting
Making too many requests too quickly may trigger Cloudflare's rate limiter. The scraper adds a 1.5-second delay between tests.

### 4. Image Hosting
Solution images are hosted on `cdn.repeatermock.com`. They currently load directly from there. If RepeaterMock blocks hotlinking, images will break.

**Future fix**: Download images and re-host on GitHub or Cloudflare R2.

### 5. No Answer Key for Pro Tests Without Attempt
Pro (locked) tests can be scraped for questions (the /attempt page works), but answer keys require a submitted attempt. Pro tests can't be attempted without a paid plan.

---

## Cookie Management

### How Cookies Work
- `accessToken`: JWT, expires in 15 minutes
- `refreshToken`: Long-lived, but **rotates on every refresh** (old token invalidated)
- `totpVerified`: Must be `"1"` (user completed TOTP verification)
- `cf_clearance`: Cloudflare clearance cookie (needed for bot protection bypass)
- `rm_fe`: Frontend session ID

### Cookie Lifecycle in the Scraper
1. Load cookies from env vars / `.env` file / `data/cookies.json`
2. Visit `repeatermock.com/` to establish session + get `cf_clearance`
3. Call `/auth/me` → if 401, call `/auth/refresh` (POST)
4. Refresh rotates the token → save new cookies to `data/cookies.json`
5. Use cookies for all subsequent API calls
6. Every 20 tests, repeat step 3-4 to refresh before token expires

### Setting Up Cookies
1. Log into `repeatermock.com` in your browser
2. Open DevTools → Application → Cookies → `https://repeatermock.com`
3. Copy `accessToken`, `refreshToken`, `totpVerified`, `rm_fe`
4. Set as GitHub secret `REPEATERMOCK_COOKIES_JSON` (JSON array format)

---

## GitHub Actions Setup

### Required Secrets
| Secret Name | Value |
|-------------|-------|
| `REPEATERMOCK_COOKIES_JSON` | JSON array of cookie objects |

### Workflow Features
- **Concurrency control**: Only one run at a time (`concurrency: scrape-repeatermock`)
- **15-minute gap**: Skips if last run ended < 15 minutes ago
- **45-minute time limit**: Stops gracefully, saves progress
- **Cookie caching**: `actions/cache` persists cookies + progress between runs
- **Logging**: Detailed Python logging for debugging
- **Graceful auth failure**: Returns `None` instead of crashing, with helpful error message

### Common CI Failures & Solutions

| Error | Cause | Solution |
|-------|-------|----------|
| `Invalid or expired refresh token` | Token consumed by another run | Update `REPEATERMOCK_COOKIES_JSON` secret with fresh cookies |
| `IndentationError: unexpected indent` | Inline Python in YAML | Use `python3 << 'EOF'` with proper indentation |
| `[: too many arguments` | Shell test with special chars in secret | Use `printf` instead of `echo` for writing .env |
| `Process completed with exit code 1` | Scraper crashed on auth | Fixed: now returns `None` gracefully |

---

## Frontend Deployment

### Cloudflare Pages
- **Project name**: `pwthor-mock-tests`
- **Account ID**: `YOUR_CLOUDFLARE_ACCOUNT_ID`
- **API Token**: `YOUR_CLOUDFLARE_API_TOKEN`
- **Deploy command**: `npx wrangler pages deploy . --project-name=pwthor-mock-tests --branch=main --commit-dirty=true`

### Key Frontend Features
- MathJax 4.1.0 for LaTeX rendering
- SPA router with 6 routes: `/`, `/series/{id}`, `/instructions/{id}/{sec}/{test}`, `/test/{id}`, `/result/{id}`, `/pricing`, `/faq`, `/about`
- Test runner: timer, question palette, section tabs, navigation
- Result page: score calculation, answer key with correct/wrong highlighting, solution explanations, rank predictor
- `_redirects` file for SPA fallback: `/* /index.html 200`

---

## Future Work

### High Priority
1. **Image downloading**: Download images from `cdn.repeatermock.com`, re-host on GitHub/Cloudflare R2
2. **Dummy attempt submission**: Reverse-engineer `POST /api/v1/attempts/{testId}/submit` payload to get answer keys for un-attempted tests
3. **Cloudflare Worker**: Cron trigger to call GitHub Actions (replaces `schedule:` cron)
4. **D1 database**: Track scrape progress, failures, timing
5. **Password-protected dashboard**: Public progress page (password: `BloggingTest@7`)

### Medium Priority
6. **Bookmark scraping**: Fetch user's bookmarked series from `/dashboard`
7. **West Bengal exams**: Include WB-related test series
8. **Frontend attractiveness**: Improve test series cards, add icons, better color scheme
9. **Auto-deploy**: GitHub Action deploys frontend to Cloudflare Pages after scraping
10. **14-second token refresh**: Proactively refresh token every 14 seconds (before 15-min expiry)

### Low Priority
11. **Offline mode**: Cache test data in browser for offline access
12. **PDF export**: Generate PDF of test + solutions
13. **Multi-language UI**: Hindi/Bengali UI for the test runner
14. **Performance analytics**: Track which questions take longest, which topics are weakest

---

## Quick Reference for New AI Agents

### To scrape a single test:
```bash
cd repeatermock-scraper
python -m src.scraper scrape-test <testId> --variant tb --slug ssc-cgl
```

### To scrape a full test (questions + answers + analysis):
```bash
python -m src.full_scraper <series_url> --max-tests 1
```

### To run incremental scraping:
```bash
python -m src.incremental_scrape --time-limit-minutes 45 --max-tests 0
```

### To deploy frontend:
```bash
cd frontend
CLOUDFLARE_API_TOKEN=YOUR_CLOUDFLARE_API_TOKEN \
CLOUDFLARE_ACCOUNT_ID=YOUR_CLOUDFLARE_ACCOUNT_ID \
npx wrangler pages deploy . --project-name=pwthor-mock-tests --branch=main --commit-dirty=true
```

### To update GitHub secret:
```python
import json, base64
from nacl.public import PublicKey, SealedBox
import urllib.request

TOKEN = "YOUR_GITHUB_TOKEN"
REPO = "sujitbhai7710/repeatermock-scraper"

# Get public key
req = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/actions/secrets/public-key",
    headers={"Authorization": f"token {TOKEN}"}
)
pubkey_data = json.loads(urllib.request.urlopen(req).read())
public_key = PublicKey(base64.b64decode(pubkey_data["key"]))
sealed_box = SealedBox(public_key)

cookies = [...]  # Your cookie array
encrypted = sealed_box.encrypt(json.dumps(cookies).encode())
payload = json.dumps({
    "encrypted_value": base64.b64encode(encrypted).decode(),
    "key_id": pubkey_data["key_id"]
})

req2 = urllib.request.Request(
    f"https://api.github.com/repos/{REPO}/actions/secrets/REPEATERMOCK_COOKIES_JSON",
    data=payload.encode(),
    headers={"Authorization": f"token {TOKEN}", "Content-Type": "application/json"},
    method="PUT"
)
urllib.request.urlopen(req2)
```

### To trigger GitHub Actions workflow:
```bash
curl -X POST "https://api.github.com/repos/sujitbhai7710/repeatermock-scraper/actions/workflows/scrape.yml/dispatches" \
  -H "Authorization: token YOUR_GITHUB_TOKEN" \
  -H "Accept: application/vnd.github.v3+json" \
  -d '{"ref":"main","inputs":{"time_limit_minutes":"45","max_tests":"0"}}'
```

---

## Update: Submit API + Image Downloader + Two Workflows

### Submit API Discovery (Added 2025-08-31)
- The submit endpoint is `POST /api/v1/attempts/{testId}/submit`
- The payload format is being discovered by trying multiple formats (see `src/submit_attempt.py`)
- Once a working format is found, it's saved to `data/submit_format.json` for reuse
- After submitting a dummy attempt (all questions skipped, 1 second time), `/solution` and `/analysis` pages return real data

### Image Downloader (Added 2025-08-31)
- `src/image_downloader.py` downloads images from `cdn.repeatermock.com`
- Images are saved to `frontend/img/{series_slug}/{test_id}/{filename}`
- CDN URLs in JSON are replaced with local paths (e.g., `/img/ssc-cgl/{testId}/hash.png`)
- This ensures images work even if RepeaterMock blocks hotlinking

### Two GitHub Actions Workflows (Added 2025-08-31)
1. **scrape.yml** — Runs every 15 min (gap logic: 15-min gap, 45-min time limit)
   - Scrapes questions + submits dummy attempt + fetches answers/solutions/analysis + downloads images
   - Auto-deploys frontend to Cloudflare Pages after each run
   - Checks if all tests are done → skips if complete
2. **daily-update.yml** — Runs once daily at 3 AM UTC
   - Refreshes analysis data (rank, average, cutoffs) for all scraped tests
   - Checks for new tests added to any series
   - Deploys updated frontend

### Cloudflare Secrets (Added 2025-08-31)
- `CLOUDFLARE_API_TOKEN` — For auto-deploy from GitHub Actions
- `CLOUDFLARE_ACCOUNT_ID` — For auto-deploy
- `REPEATERMOCK_COOKIES_JSON` — Auth cookies (must be fresh!)

### Important: Cookie Management
- NEVER use cookies locally if they're also in the GitHub secret
- The refresh token rotates on every use — using it locally invalidates it for CI
- If CI fails with "Invalid or expired refresh token", the user must:
  1. Log into RepeaterMock (fresh login)
  2. Export cookies immediately
  3. Update the `REPEATERMOCK_COOKIES_JSON` secret
  4. DO NOT use those cookies locally
