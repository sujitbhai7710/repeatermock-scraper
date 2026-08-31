# RepeaterMock Scraper & Frontend

A complete system for scraping real test questions from [RepeaterMock](https://repeatermock.com) and serving them via a static website deployed on Cloudflare Pages.

## Repository structure

```
repeatermock-scraper/
├── src/                        # Python scraper
│   ├── scraper.py              # Main scraper CLI
│   ├── cookie_manager.py       # Cookie loading/saving/rotation
│   └── question_parser.py      # RSC flight payload parser
├── frontend/                   # Static website (Cloudflare Pages)
│   ├── index.html              # SPA entry point
│   ├── data.js                 # Series catalog (2,157 tests)
│   ├── assets/
│   │   ├── styles.css          # RepeaterMock-style UI
│   │   └── router.js           # SPA router + test runner
│   ├── tests/                  # Scraped question JSON files
│   │   └── parsed_questions_*.json
│   └── _redirects              # SPA fallback for Cloudflare Pages
├── data/                       # Scraper output (gitignored)
│   ├── tests/                  # Scraped test JSON files
│   ├── series/                 # Series metadata
│   └── cookies.json            # Auto-saved rotated cookies
├── .github/workflows/
│   └── scrape.yml              # GitHub Actions workflow
├── .env.example                # Cookie template
├── requirements.txt
└── README.md
```

## Quick start

### 1. Scraper (local)

```bash
# Install
pip install -r requirements.txt
playwright install chromium

# Set up cookies
cp .env.example .env
# Edit .env — paste your RepeaterMock cookies

# Test if a series is scrapable
python -m src.scraper test-series https://repeatermock.com/tb/test-series/ssc-cgl

# Scrape 5 tests
python -m src.scraper scrape-series https://repeatermock.com/tb/test-series/ssc-cgl --max-tests 5

# Copy scraped tests to frontend
cp data/tests/*.json frontend/tests/
```

### 2. Frontend (local)

```bash
cd frontend
python3 -m http.server 8000
# Open http://localhost:8000
```

### 3. Deploy frontend to Cloudflare Pages

```bash
cd frontend
npx wrangler pages deploy . --project-name=pwthor-mock-tests --branch=main
```

### 4. GitHub Actions (automated)

Set the `REPEATERMOCK_COOKIES_JSON` secret in your GitHub repo settings, then the workflow runs daily and on push.

See [README.md](README.md) for full documentation.
