# Remaining Tasks & Current Status

> **Last updated**: 2025-08-31 16:00 UTC

---

## Current Status Summary

### What's Working ✅
1. **Question scraping** — 100 real questions per test from /attempt page (RSC payload parsing)
2. **Answer keys** — correctOption (1-4) for each question from /solution page answersData
3. **Solutions** — 15 out of 100 have real HTML explanations (85 have placeholder `$N` values)
4. **Analysis data** — rank, percentile, topper score, average, total students, cutoffs (from /analysis page)
5. **Rank predictor** — uses 313 real data points from rankMarksData to predict rank for any score
6. **MathJax rendering** — LaTeX fractions, angles, etc. render properly
7. **Solution images** — images from cdn.repeatermock.com load correctly
8. **Frontend** — test runner, result page, answer key, rank predictor all live on Cloudflare Pages

### What's NOT Working ❌
1. **GitHub Actions** — all runs fail because refresh token is expired/consumed
2. **Only 15/100 solutions** — 85 have placeholder `$N` values (RepeaterMock internal references)
3. **Analysis data is static** — doesn't update when more students attempt the test
4. **No Cloudflare Worker** — not built yet
5. **No D1 database** — not built yet
6. **No password dashboard** — not built yet
7. **No image downloading** — images still load from cdn.repeatermock.com (not re-hosted)

---

## GitHub Actions Failure — Root Cause

### The Problem
All GitHub Action runs fail with:
```
RuntimeError: Authentication failed. /auth/me returned 401: {"success":false,"message":"Invalid or expired refresh token"}
```

### Root Cause
RepeaterMock **rotates the refresh token on every `/auth/refresh` call**. The old refresh token becomes invalid immediately. Here's what happened:

1. User provided fresh cookies for `polturaja7@gmail.com` account
2. I set those cookies as the GitHub secret `REPEATERMOCK_COOKIES_JSON`
3. I also used those same cookies **locally** for testing (scraping the geometry test, re-scraping the SSC CGL test)
4. My local testing consumed the refresh token → rotated to a new one
5. The new token was saved to my local `data/cookies.json` but NOT to the GitHub secret
6. When GitHub Actions runs, it uses the OLD (now-invalid) refresh token from the secret
7. `/auth/refresh` returns 401 "Invalid or expired refresh token"

### The Fix (Two Options)

**Option A: Fresh cookies each time (current approach)**
- User logs into RepeaterMock, exports fresh cookies
- Updates the GitHub secret
- This works but requires manual intervention every time the token expires

**Option B: Cookie persistence via cache (implemented but needs first successful run)**
- The workflow uses `actions/cache` to persist `data/cookies.json` between runs
- On the first successful run, the rotated refresh token is saved to the cache
- Subsequent runs load cookies from cache (which has the latest refresh token)
- This should work IF the first run succeeds (chicken-and-egg problem)

**Option C: Don't use cookies locally**
- Never run the scraper locally with the same cookies as CI
- Use a separate RepeaterMock account for local testing
- This prevents token rotation conflicts

### What Needs to Happen
1. User logs into `polturaja7@gmail.com` on RepeaterMock
2. Exports FRESH cookies (immediately, don't use them locally)
3. Updates the `REPEATERMOCK_COOKIES_JSON` GitHub secret
4. Triggers the workflow manually
5. If it succeeds, the cache will save the rotated token for future runs
6. DO NOT use those cookies locally after updating the secret

---

## Why Only 15/100 Solutions (Not 100)?

### The Data
- **15 solutions** have real HTML content (paragraphs, images, logic explanations)
- **85 solutions** have placeholder values like `$35`, `$36`, `$37`, `$3a`, `$3b`

### What the Placeholders Mean
The `$N` values are **RepeaterMock internal references** — they're not actual solution text. They're likely:
- Image IDs or asset references that RepeaterMock's frontend resolves client-side
- Template references that get expanded by their React components
- Or simply empty/placeholder solutions that RepeaterMock hasn't filled in

### Why This Happens
The `/solution` page RSC payload contains the `answersData` object. Each answer has:
```json
{
  "correctOption": "1",
  "sol": {
    "en": { "value": "$35" }  // Placeholder — no real solution text
  }
}
```

For 15 questions, the `value` contains real HTML:
```json
{
  "correctOption": "1",
  "sol": {
    "en": { "value": "<p>The logic followed here is:</p><p><img src='...'></p>" }
  }
}
```

### Can We Get All 100 Solutions?
**Maybe.** The `$N` placeholders might be:
1. **Image-only solutions** — the explanation is in an image that we need to download separately
2. **Client-side rendered** — RepeaterMock's JS expands them into full solutions
3. **Genuinely empty** — RepeaterMock hasn't added text solutions for those questions

To investigate, we'd need to:
1. Visit the actual `/solution` page in a browser (with anti-debug bypass)
2. Check if the React app renders full solutions for the `$N` questions
3. If yes, find where the expanded content comes from (another API call? client-side template?)

---

## Analysis Data — Static vs Dynamic

### Current State
The analysis data (rank, percentile, topper score, average, cutoffs) was scraped ONCE from RepeaterMock's `/analysis` page. It's stored as static JSON in the test file.

### Why It's Static
- The `/analysis` page only returns data if the authenticated user has a submitted attempt
- The `polturaja7@gmail.com` account hasn't attempted most tests
- The `finnolim7@gmail.com` account attempted test `6a0f3f2c0b97114ca22cf188` — that's why we have its analysis data
- To get fresh analysis data, we'd need to:
  1. Submit a dummy attempt (all questions skipped, 0 time) via the API
  2. Then fetch `/analysis` — it would return data based on ALL students' attempts
  3. Re-scrape periodically to keep it fresh

### What Needs to Happen for Dynamic Data
1. **Reverse-engineer the submit API** — find the correct payload format for `POST /api/v1/attempts/{testId}/submit`
2. **Submit a dummy attempt** — all questions skipped, 0 time taken
3. **Fetch /analysis** — now it returns real data (rank based on all students, not just our score)
4. **Schedule periodic re-scraping** — via Cloudflare Worker cron

---

## Rank Predictor — How It Works

### The Data Source
The `rankMarksData` array contains 313 entries, scraped from RepeaterMock's `/analysis` page. Each entry maps a marks value to a rank:

```json
{"marks": 188.5, "count": 1, "per": 100, "rank": 1}      // 188.5 marks → rank 1
{"marks": 183, "count": 2, "per": 99.95, "rank": 2}       // 183 marks → rank 2
{"marks": 60, "count": 5, "per": 14.6, "rank": 1744}      // 60 marks → rank 1744
{"marks": 0, "count": 130, "per": 6.42, "rank": 1912}     // 0 marks → rank 1912
```

### The Algorithm
```javascript
function predictRank(score) {
    // rankMarksData is sorted by marks descending (highest first)
    for (let i = 0; i < rankMarksData.length; i++) {
        if (rankMarksData[i].marks <= score) {
            return {
                rank: rankMarksData[i].rank,
                percentile: rankMarksData[i].per
            };
        }
    }
    // If score is higher than topper, rank = 1
    if (score >= rankMarksData[0].marks) {
        return { rank: 1, percentile: 100 };
    }
    // Default: last place
    return { rank: totalStudents, percentile: 0 };
}
```

### Is This Accurate?
**Yes, for the data we have.** The `rankMarksData` is the same data RepeaterMock uses for their own rank predictor. Our prediction matches their data exactly.

**But**: The data is static (cached from scrape time). If 100 more students attempt the test tomorrow, the ranks would shift. Our predictor won't reflect that until we re-scrape.

---

## Remaining Tasks

### HIGH PRIORITY

#### 1. Fix GitHub Actions (BLOCKED — needs fresh cookies)
- **Status**: All runs fail with "Invalid or expired refresh token"
- **Root cause**: Refresh token consumed by local testing
- **Fix**: User provides fresh cookies → update secret → trigger workflow → cache saves rotated token
- **Blocker**: User needs to log in and export cookies WITHOUT me using them locally first

#### 2. Submit Dummy Attempts for Answer Keys
- **Status**: Not started
- **Problem**: `/solution` and `/analysis` pages only return data if user has a submitted attempt
- **Approach**: Reverse-engineer `POST /api/v1/attempts/{testId}/submit` payload format
- **Benefit**: Would unlock answer keys + analysis for ALL tests, not just pre-attempted ones
- **Estimated effort**: 2-3 hours of JS bundle analysis

#### 3. Cloudflare Worker (Cron Trigger)
- **Status**: Not started
- **Purpose**: Replace GitHub Actions cron with Cloudflare Worker
- **Features**: 
  - Triggers GitHub Actions via API every 70 minutes
  - 15-minute gap between runs
  - More reliable than GitHub Actions cron (which can be delayed)
- **Estimated effort**: 1-2 hours

#### 4. D1 Database (Progress Tracking)
- **Status**: Not started
- **Purpose**: Track scrape progress, failures, timing in Cloudflare D1
- **Tables**: 
  - `scrape_runs` (run_id, start, end, tests_scraped, status)
  - `tests` (test_id, title, series, questions_count, has_answers, has_analysis, scraped_at)
  - `failures` (test_id, error, timestamp)
- **Estimated effort**: 2-3 hours

#### 5. Password-Protected Dashboard
- **Status**: Not started
- **Purpose**: Public progress page (password: `BloggingTest@7`)
- **Features**:
  - Shows which tests are scraped, which are pending
  - Per-series progress bars
  - Failure logs
  - Timing data
- **Tech**: Cloudflare Pages function or Worker + D1
- **Estimated effort**: 3-4 hours

### MEDIUM PRIORITY

#### 6. Download Images from cdn.repeatermock.com
- **Status**: Not started
- **Problem**: Solution images load from `cdn.repeatermock.com` — if they block hotlinking, images break
- **Approach**: 
  1. During scraping, find all `<img src="cdn.repeatermock.com/...">` in solutions
  2. Download each image
  3. Upload to GitHub repo or Cloudflare R2
  4. Replace URLs in JSON
- **Estimated effort**: 2-3 hours

#### 7. Bookmark Scraping from /dashboard
- **Status**: Not started
- **Problem**: User has bookmarked multiple test series on RepeaterMock's /dashboard page
- **Approach**: 
  1. Fetch `/dashboard` page with authenticated cookies
  2. Parse RSC payload for bookmarked series URLs
  3. Add those URLs to the scraper's series list
- **Includes**: SSC series + 2-3 West Bengal-related series
- **Estimated effort**: 1-2 hours

#### 8. Auto-Deploy Frontend from GitHub Actions
- **Status**: Not started
- **Purpose**: After scraping, automatically deploy updated frontend to Cloudflare Pages
- **Approach**: 
  1. Copy `data/tests/*.json` to `frontend/tests/`
  2. Run `npx wrangler pages deploy frontend/`
  3. Use Cloudflare API token from GitHub secret
- **Estimated effort**: 1 hour

#### 9. Fix 85 Placeholder Solutions
- **Status**: Not started
- **Problem**: 85/100 solutions have `$N` placeholder values instead of real text
- **Investigation needed**: 
  1. Visit `/solution` page in real browser (bypass anti-debug)
  2. Check if React app expands `$N` into full solutions
  3. If yes, find the expansion source (API call? client-side template?)
- **Estimated effort**: 3-4 hours

### LOW PRIORITY

#### 10. Frontend Attractiveness
- Improve test series cards with icons, better colors
- Add search/filter for tests
- Show progress indicators on series pages

#### 11. 14-Second Token Refresh
- Proactively refresh access token every 14 seconds (before 15-min expiry)
- Currently refreshes every 20 tests (roughly every 30-40 seconds)
- Not critical — current approach works

#### 12. Multi-Language UI
- Hindi/Bengali UI for the test runner
- Currently questions support 28 languages but UI is English-only

---

## Architecture Diagram

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  RepeaterMock   │     │  GitHub Actions  │     │  Cloudflare     │
│  (Source)       │     │  (Scraper CI)    │     │  Pages (Frontend)│
│                 │     │                  │     │                 │
│  api.repeater   │◄────│  Playwright      │     │  Test Runner    │
│  mock.com       │     │  + Python        │     │  Result Page    │
│                 │     │                  │     │  Rank Predictor │
│  /attempt       │     │  data/tests/     │────►│  /tests/*.json  │
│  /solution      │     │  *.json          │     │                 │
│  /analysis      │     │                  │     │  MathJax        │
│                 │     │  actions/cache   │     │  Images         │
└─────────────────┘     │  (cookies +      │     └─────────────────┘
                        │   progress)      │
                        └──────────────────┘
                                 │
                                 ▼
                        ┌──────────────────┐
                        │  Cloudflare D1   │  ← NOT BUILT YET
                        │  (Progress DB)   │
                        └──────────────────┘
                                 │
                        ┌──────────────────┐
                        │  Cloudflare      │  ← NOT BUILT YET
                        │  Worker (Cron)   │
                        └──────────────────┘
                                 │
                        ┌──────────────────┐
                        │  Dashboard       │  ← NOT BUILT YET
                        │  (Password:      │
                        │   BloggingTest@7)│
                        └──────────────────┘
```
