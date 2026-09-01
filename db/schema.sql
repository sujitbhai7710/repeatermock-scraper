-- ============================================================
-- RepeaterMock Scraper — D1 Database Schema
-- ============================================================
-- Tables:
--   series        : one row per target series (52 total)
--   tests         : one row per scraped test, with granular status
--   runs          : one row per scraper run (history)
--   refresh_log   : cookie refresh events (for debugging token expiry)
-- ============================================================

-- Drop existing tables (clean install)
DROP TABLE IF EXISTS tests;
DROP TABLE IF EXISTS series;
DROP TABLE IF EXISTS runs;
DROP TABLE IF EXISTS refresh_log;

-- ────────────── Series table ──────────────
CREATE TABLE series (
    platform           TEXT NOT NULL,         -- "tb" | "tb-pro" | "gd"
    slug               TEXT NOT NULL,
    name               TEXT NOT NULL,
    icon               TEXT,
    series_url         TEXT NOT NULL UNIQUE,  -- https://repeatermock.com/{platform}/test-series/{slug}
    total_tests        INTEGER DEFAULT 0,
    scraped_count      INTEGER DEFAULT 0,     -- fully scraped (Q + A + sol + analysis)
    partial_count      INTEGER DEFAULT 0,     -- questions only, missing answers/analysis
    failed_count       INTEGER DEFAULT 0,
    pending_count      INTEGER DEFAULT 0,
    last_fetched_at    INTEGER,               -- when test list was last fetched
    last_scraped_at    INTEGER,               -- when last test in series was scraped
    created_at         INTEGER DEFAULT (unixepoch()),
    updated_at         INTEGER DEFAULT (unixepoch()),
    PRIMARY KEY (platform, slug)
);

-- ────────────── Tests table ──────────────
CREATE TABLE tests (
    test_id            TEXT PRIMARY KEY,      -- RepeaterMock's test ObjectId
    series_url         TEXT NOT NULL,
    series_name        TEXT,
    title              TEXT,
    section            TEXT,
    subsection         TEXT,
    duration_minutes   INTEGER,
    total_marks        INTEGER,
    question_count     INTEGER,
    is_free            INTEGER DEFAULT 0,
    status             TEXT NOT NULL DEFAULT 'pending',  -- "scraped" | "partial" | "failed" | "pending"
    has_questions      INTEGER DEFAULT 0,
    has_answers        INTEGER DEFAULT 0,
    has_solutions      INTEGER DEFAULT 0,
    has_analysis       INTEGER DEFAULT 0,
    has_images         INTEGER DEFAULT 0,
    actual_questions   INTEGER DEFAULT 0,     -- number of questions actually scraped
    error_message      TEXT,
    last_attempted_at  INTEGER,               -- when scraper last tried this test
    scraped_at         INTEGER,               -- when test was fully scraped
    file_path          TEXT,                  -- relative path to JSON file in repo
    file_size_bytes    INTEGER,
    created_at         INTEGER DEFAULT (unixepoch()),
    updated_at         INTEGER DEFAULT (unixepoch()),
    FOREIGN KEY (series_url) REFERENCES series(series_url)
);

CREATE INDEX idx_tests_series ON tests(series_url);
CREATE INDEX idx_tests_status ON tests(status);
CREATE INDEX idx_tests_partial ON tests(status) WHERE status = 'partial';

-- ────────────── Runs table ──────────────
CREATE TABLE runs (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at         INTEGER NOT NULL,
    ended_at           INTEGER,
    time_minutes       REAL,
    account_used      INTEGER,                -- 1, 2, or 3
    tests_scraped      INTEGER DEFAULT 0,     -- fully scraped this run
    tests_partial      INTEGER DEFAULT 0,
    tests_failed       INTEGER DEFAULT 0,
    questions_scraped  INTEGER DEFAULT 0,
    status             TEXT DEFAULT 'running', -- "running" | "completed" | "aborted"
    notes              TEXT
);

-- ────────────── Refresh log table (for debugging token expiry) ──────────────
CREATE TABLE refresh_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp          INTEGER NOT NULL,
    account_idx        INTEGER,               -- 0, 1, 2
    trigger            TEXT,                  -- "proactive" | "submit_401" | "initial"
    auth_me_status     INTEGER,
    refresh_status     INTEGER,
    new_access_token   INTEGER,               -- 1 if new accessToken captured
    new_refresh_token  INTEGER,               -- 1 if new refreshToken captured
    notes              TEXT
);
