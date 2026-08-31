"""
Authoritative list of test series to scrape.

Source: user-provided dashboard bookmark list (52 entries).
ONLY these series will be scraped — no others.

Each entry has:
    platform: "tb" | "tb-pro" | "gd"
    slug: series slug (used in URL)
    name: human-readable name (for display)
    icon: CDN icon URL (kept for reference, not used by scraper)

URL pattern: https://repeatermock.com/{platform}/test-series/{slug}
"""
TARGET_SERIES = [
    {"platform": "tb",       "slug": "ssc-cgl",                                       "name": "SSC CGL Mock Test Series 2026 (Tier I & Tier II) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-cgl",                                       "name": "SSC CGL Mock Test Series 2026 (Tier I & Tier II)"},
    {"platform": "gd",       "slug": "ssc-selection-post",                            "name": "SSC Selection Post"},
    {"platform": "gd",       "slug": "sbi-po",                                        "name": "SBI PO"},
    {"platform": "gd",       "slug": "ssc-cgl",                                       "name": "SSC CGL Free"},
    {"platform": "tb",       "slug": "rrb-group-d",                                   "name": "RRB Group D Mock Test Series 2025-26 (New) PYQs"},
    {"platform": "tb-pro",   "slug": "rrb-group-d",                                   "name": "RRB Group D Mock Test Series 2025-26 (New)"},
    {"platform": "tb",       "slug": "ssc-maths-previous-year-questions",             "name": "SSC Maths PYP Mock Test Series (20k+ Questions) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-maths-previous-year-questions",             "name": "SSC Maths PYP Mock Test Series (20k+ Questions)"},
    {"platform": "tb",       "slug": "ssc-reasoning-previous-year-questions",         "name": "SSC Reasoning PYP Mock Test Series (20k+ Questions) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-reasoning-previous-year-questions",         "name": "SSC Reasoning PYP Mock Test Series (20k+ Questions)"},
    {"platform": "gd",       "slug": "ssc-cpo",                                       "name": "SSC CPO"},
    {"platform": "tb",       "slug": "ssc-chsl",                                      "name": "SSC CHSL Mock Test Series 2026 (Tier I & Tier II) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-chsl",                                      "name": "SSC CHSL Mock Test Series 2026 (Tier I & Tier II)"},
    {"platform": "gd",       "slug": "ssc-cgl-previous-year-paper",                   "name": "SSC CGL Previous Year Paper"},
    {"platform": "tb",       "slug": "ssc-english-previous-year-questions",           "name": "SSC English PYP Mock Test Series (20k+ Questions) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-english-previous-year-questions",           "name": "SSC English PYP Mock Test Series (20k+ Questions)"},
    {"platform": "tb",       "slug": "ssc-mts",                                       "name": "SSC MTS & Havaldar Mock Test Series 2026 PYQs"},
    {"platform": "gd",       "slug": "ssc-mts",                                       "name": "SSC MTS"},
    {"platform": "tb-pro",   "slug": "ssc-mts",                                       "name": "SSC MTS & Havaldar Mock Test Series 2026"},
    {"platform": "gd",       "slug": "ssc-chsl",                                      "name": "SSC CHSL"},
    {"platform": "tb",       "slug": "ssc-gk-previous-year-questions",                "name": "SSC GK PYP Mock Test Series (20k+ Questions) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-gk-previous-year-questions",                "name": "SSC GK PYP Mock Test Series (20k+ Questions)"},
    {"platform": "gd",       "slug": "ssc-gd",                                        "name": "SSC GD"},
    {"platform": "tb-pro",   "slug": "ssc-stenographer",                              "name": "SSC Stenographer Grade C & D Mock Test 2026 (New Pattern)"},
    {"platform": "gd",       "slug": "ssc-delhi-head-constable",                      "name": "SSC Delhi Head Constable"},
    {"platform": "tb",       "slug": "ssc-stenographer",                              "name": "SSC Stenographer Grade C & D Mock Test 2026 (New Pattern) PYQs"},
    {"platform": "tb",       "slug": "ssc-selection-post",                            "name": "SSC Selection Post (Phase 14) 2026 Mock Test Series PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-cpo-ranker",                                "name": "SSC CPO Rankers Test Series 2025"},
    {"platform": "tb",       "slug": "ssc-gd-constable",                              "name": "SSC GD Constable 2026 Mock Test Series PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-selection-post",                            "name": "SSC Selection Post (Phase 14) 2026 Mock Test Series"},
    {"platform": "tb",       "slug": "ssc-cpo",                                       "name": "SSC CPO Mock Test Series 2026 (Tier I & II) PYQs"},
    {"platform": "tb",       "slug": "ssc-chsl-previous",                             "name": "SSC CHSL Mock Test Series 2025 (Tier I & Tier II) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-cpo",                                       "name": "SSC CPO Mock Test Series 2026 (Tier I & II)"},
    {"platform": "tb",       "slug": "ssc-cpo-previous",                              "name": "SSC CPO Mock Test Series 2025 (Tier I & II) (DP SI & CAPF) (New Pattern) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-chsl-previous",                             "name": "SSC CHSL Mock Test Series 2025 (Tier I & Tier II)"},
    {"platform": "tb",       "slug": "ssc-je-ce",                                     "name": "SSC JE Civil 2026 Mock Test (Paper 1 & Paper 2) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-cpo-previous",                              "name": "SSC CPO Mock Test Series 2025 (Tier I & II) (DP SI & CAPF) (New Pattern)"},
    {"platform": "tb",       "slug": "ssc-mts-previous",                              "name": "SSC MTS & Havaldar Mock Test Series 2025 PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-je-ce",                                     "name": "SSC JE Civil 2026 Mock Test (Paper 1 & Paper 2)"},
    {"platform": "tb",       "slug": "ssc-je-ee",                                     "name": "SSC JE Electrical 2026 Mock Test (Paper 1 & Paper 2) PYQs"},
    {"platform": "tb-pro",   "slug": "ssc-mts-previous",                              "name": "SSC MTS & Havaldar Mock Test Series 2025"},
    {"platform": "tb",       "slug": "west-bengal-group-c",                           "name": "WB SSC Group C & D Combined Mock Test Series 2025 PYQs"},
    {"platform": "tb-pro",   "slug": "west-bengal-group-c",                           "name": "WB SSC Group C & D Combined Mock Test Series 2025"},
    {"platform": "tb-pro",   "slug": "rrb-maths-previous-year-questions",             "name": "Mathematics for All Railway Exams Previous Year Paper Mock Test"},
    {"platform": "tb",       "slug": "rrb-gk-previous-year-questions",                "name": "General Knowledge for All Railway Exams Previous Year Paper Mock Test PYQs"},
    {"platform": "tb-pro",   "slug": "rrb-reasoning-previous-year-questions",         "name": "Reasoning for All Railway Exams Previous Year Paper Mock Test"},
    {"platform": "tb",       "slug": "rrb-general-science-previous-year-questions",   "name": "General Science for All Railway Exams Previous Year Paper Mock Test PYQs"},
    {"platform": "tb-pro",   "slug": "rrb-gk-previous-year-questions",                "name": "General Knowledge for All Railway Exams Previous Year Paper Mock Test"},
    {"platform": "tb-pro",   "slug": "rrb-general-science-previous-year-questions",   "name": "General Science for All Railway Exams Previous Year Paper Mock Test"},
    {"platform": "tb-pro",   "slug": "general-knowledge-ssc-railways-competitive-exams", "name": "Ace General Knowledge - For All Railway, SSC & Other Competitive Exams"},
    {"platform": "tb-pro",   "slug": "ssc-railways-polity",                           "name": "Polity Master Pack for SSC / Railways / State Exams"},
    {"platform": "tb",       "slug": "general-knowledge-ssc-railways-competitive-exams", "name": "Ace General Knowledge - For All Railway, SSC & Other Competitive Exams"},
]


def get_all_series_urls() -> list[str]:
    """Return list of full series URLs."""
    return [f"https://repeatermock.com/{s['platform']}/test-series/{s['slug']}" for s in TARGET_SERIES]


def get_series_metadata(series_url: str) -> dict | None:
    """Look up series metadata by URL."""
    for s in TARGET_SERIES:
        url = f"https://repeatermock.com/{s['platform']}/test-series/{s['slug']}"
        if url == series_url:
            return s
    return None
