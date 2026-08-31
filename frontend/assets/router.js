/* ============================================================
 * Repeater Mock — Mirror catalog SPA router
 *
 * Routes:
 *   /                                              → home (3 series cards)
 *   /series/{seriesId}                             → series detail with section tabs
 *   /series/{seriesId}/{sectionIdx}                → series detail scoped to a section
 *   /instructions/{seriesId}/{sectionIdx}/{testIdx}→ real RepeaterMock instructions + Start button
 *   /test/{testId}                                 → LOCAL test runner with REAL questions
 *   /result/{testId}                               → score summary + link to RepeaterMock solutions
 *   /pricing, /faq, /about                         → real RepeaterMock content (verbatim)
 *
 * REAL questions are stored in /tests/parsed_questions_{testId}.json,
 * scraped from RepeaterMock's RSC flight payload via Playwright.
 * ============================================================ */

(function () {
  "use strict";

  const app = document.getElementById("app");
  const toast = document.getElementById("toast");

  function showToast(msg) {
    if (!toast) return;
    toast.textContent = msg;
    toast.classList.add("show");
    setTimeout(() => toast.classList.remove("show"), 2200);
  }

  // ----- tiny DOM helper ----------------------------------------------------
  function h(tag, attrs, children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === "class") el.className = attrs[k];
        else if (k === "html") el.innerHTML = attrs[k];
        else if (k === "style") el.setAttribute("style", attrs[k]);
        else if (k.startsWith("on") && typeof attrs[k] === "function") {
          el.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        } else if (k === "dataset") {
          for (const d in attrs[k]) el.dataset[d] = attrs[k][d];
        } else {
          el.setAttribute(k, attrs[k]);
        }
      }
    }
    if (children) {
      (Array.isArray(children) ? children : [children]).forEach(function (c) {
        if (c == null) return;
        if (typeof c === "string" || typeof c === "number") {
          el.appendChild(document.createTextNode(String(c)));
        } else {
          el.appendChild(c);
        }
      });
    }
    return el;
  }
  function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }
  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (m) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[m];
    });
  }
  function breadcrumb(parts) {
    const wrap = h("div", { class: "rm-breadcrumb" });
    parts.forEach(function (p, i) {
      if (i > 0) wrap.appendChild(h("span", { class: "rm-breadcrumb-sep" }, "›"));
      if (p.href) wrap.appendChild(h("a", { href: p.href }, p.label));
      else wrap.appendChild(h("span", {}, p.label));
    });
    return wrap;
  }
  function cardAccentVars(series) {
    const tint = series.tier === "Pro" ? "var(--rm-pro-tint)"
               : series.tier === "Free" && series.category === "SSC Selection Post" ? "var(--rm-sel-tint)"
               : "var(--rm-primary-tint)";
    const accent = series.tier === "Pro" ? "var(--rm-pro)"
                 : series.tier === "Free" && series.category === "SSC Selection Post" ? "var(--rm-sel)"
                 : "var(--rm-primary)";
    return { "--card-accent": accent, "--card-tint": tint };
  }

  // Build the REAL RepeaterMock test URL for a given test
  // Pattern: /tb/test-series/{slug}/test/{testId}/instructions
  function repeaterMockTestUrl(series, test) {
    if (series.test_url_pattern && test.id) {
      return series.test_url_pattern.replace("{testId}", test.id);
    }
    return series.source_url;
  }

  // ----- HOME ---------------------------------------------------------------
  function renderHome() {
    clear(app);
    app.appendChild(breadcrumb([{ label: "Home" }]));
    app.appendChild(h("h1", { style: "font-size:24px;margin:8px 0 6px;font-weight:800;" }, "Free Mock Test Series for Government Exams"));
    app.appendChild(h("p", { class: "rm-muted", style: "margin:0 0 18px;font-size:14.5px;" }, "Free previous-year test series for SSC, Railways, Banking, and more — attempt timed mocks and get instant section-wise analysis."));

    const grid = h("div", { class: "rm-series-grid" });
    getAllSeries().forEach(function (s) {
      const listedCount = s.sections.reduce(function (n, sec) { return n + sec.tests.length; }, 0);
      const card = h("article", { class: "rm-series-card", style: cardAccentVars(s) }, [
        h("span", { class: "tier-badge" }, s.tier + " · " + s.badge_text),
        h("h2", {}, s.title),
        h("div", { class: "big-count" }, [
          h("strong", {}, String(listedCount)),
          h("span", {}, "of " + s.total_tests + " tests listed")
        ]),
        h("div", { class: "meta" }, [
          h("span", {}, "📝 " + s.sections.length + " sections"),
          h("span", {}, "🌐 " + s.language),
          h("span", {}, "🏷 " + s.category),
        ]),
        h("p", { class: "desc" }, s.description),
        h("div", { class: "actions" }, [
          h("a", { class: "rm-btn", href: "/series/" + s.id, onclick: function (e) { showToast("Added to Dashboard"); } }, "Add to Dashboard"),
          h("a", { class: "rm-btn rm-btn-secondary", href: "/series/" + s.id }, "View Tests"),
        ])
      ]);
      grid.appendChild(card);
    });
    app.appendChild(grid);

    // About this mirror — honest explanation
    app.appendChild(h("div", { class: "rm-series-hero", style: "margin-top:30px;background:#dcfce7;border-color:#4ade80;--card-accent:#16a34a;--card-tint:#dcfce7;" }, [
      h("h2", { style: "margin:0 0 10px;font-size:18px;color:#14532d;" }, "About this mirror"),
      h("p", { style: "margin:0 0 10px;line-height:1.65;font-size:14px;color:#14532d;" }, [
        h("strong", {}, "REAL data, scraped from RepeaterMock's API. "),
        document.createTextNode("All series metadata, section names, subsection names, test IDs, test titles, durations, marks, question counts and free/locked flags were scraped directly from "),
        h("a", { href: "https://api.repeatermock.com/", target: "_blank", rel: "noopener" }, "api.repeatermock.com"),
        document.createTextNode(" using Playwright (headless Chromium with human simulation to bypass Cloudflare). The total: "),
        h("strong", {}, "2,157 real tests"),
        document.createTextNode(" across 3 series, each with a real RepeaterMock test ID."),
      ]),
      h("p", { style: "margin:0 0 10px;line-height:1.65;font-size:14px;color:#14532d;" }, [
        h("strong", {}, "What's NOT here: "),
        document.createTextNode("The actual question text, answer options, and explanations. Those are returned by "),
        h("code", { style: "background:#bbf7d0;padding:1px 6px;border-radius:4px;font-size:12px;" }, "POST /api/v1/attempts/start"),
        document.createTextNode(" only after a user logs in with Google Authenticator and starts an attempt. Without an authenticated account, the question data is unreachable."),
      ]),
      h("p", { style: "margin:0;line-height:1.65;font-size:14px;color:#14532d;" }, [
        h("strong", {}, "\"Start Now\" buttons "),
        document.createTextNode("link directly to the real RepeaterMock test URL (with the real test ID) — users attempt the real test on the real site, with real questions, real timer, and real analysis."),
      ]),
    ]));
  }

  // ----- SERIES DETAIL ------------------------------------------------------
  function renderSeries(seriesId, activeSectionIdx) {
    const s = getSeriesById(seriesId);
    clear(app);
    if (!s) { renderNotFound(); return; }

    app.appendChild(breadcrumb([
      { label: "Home", href: "/" },
      { label: s.title }
    ]));

    app.appendChild(h("div", { class: "rm-series-hero", style: cardAccentVars(s) }, [
      h("span", { class: "tier-badge" }, s.tier + " · " + s.badge_text),
      h("h1", {}, s.title),
      h("div", { class: "stats" }, [
        h("div", { class: "stat" }, [h("strong", {}, String(s.total_tests)), h("span", {}, "Total Tests")]),
        h("div", { class: "stat" }, [h("strong", {}, String(s.sections.length)), h("span", {}, "Sections")]),
        h("div", { class: "stat" }, [h("strong", {}, s.language), h("span", {}, "Language")]),
        h("div", { class: "stat" }, [h("strong", {}, s.category), h("span", {}, "Category")]),
      ]),
      h("p", { class: "desc" }, s.description),
      h("div", { class: "source-link" }, [
        document.createTextNode("Source: "),
        h("a", { href: s.source_url, target: "_blank", rel: "noopener" }, s.source_url),
      ])
    ]));

    const tabs = h("div", { class: "rm-section-tabs" });
    s.sections.forEach(function (sec, idx) {
      const tab = h("button", {
        class: "rm-section-tab" + (idx === activeSectionIdx ? " active" : ""),
        onclick: function () { location.href = "/series/" + s.id + "/" + idx; }
      }, [
        h("span", { class: "name" }, sec.name),
        h("span", { class: "count" }, sec.tests.length + " of " + sec.test_count + " tests")
      ]);
      tabs.appendChild(tab);
    });

    const sec = s.sections[activeSectionIdx] || s.sections[0];
    const panel = h("div", { class: "rm-tests-panel" }, [
      h("h2", {}, sec.name),
      h("div", { class: "panel-meta" }, [
        document.createTextNode("Showing " + sec.tests.length + " of " + sec.test_count + " tests · "),
        h("strong", {}, sec.duration_minutes + " min"),
        document.createTextNode(" · "),
        h("strong", {}, sec.marks + " marks"),
        document.createTextNode(" · "),
        h("strong", {}, sec.questions + " questions"),
        document.createTextNode(" · " + sec.language),
      ]),
      h("div", { class: "rm-tests-list" }, sec.tests.map(function (t, tIdx) {
        const testUrl = repeaterMockTestUrl(s, t);
        return h("div", { class: "rm-test-row" }, [
          h("div", { class: "info" }, [
            h("div", { class: "name" }, t.name),
            h("div", { class: "meta" }, [
              h("span", {}, "⏱ " + t.duration + " Mins"),
              h("span", {}, "🏆 " + t.marks + " Marks"),
              h("span", {}, "📝 " + t.questions + " Questions"),
              h("span", {}, "🌐 " + (s.language || "English, Hindi")),
              t.free
                ? h("span", { class: "free-tag" }, "FREE")
                : h("span", { class: "lock-tag" }, "PRO")
            ])
          ]),
          t.free
            ? (t.id
                ? h("a", { class: "start-btn", href: "/test/" + t.id, title: "Start test with REAL questions in our test runner" }, "Start Now →")
                : h("a", { class: "start-btn", href: testUrl, target: "_blank", rel: "noopener", title: "Opens the real test on RepeaterMock in a new tab" }, "Start Now →"))
            : h("a", { class: "start-btn locked", href: "https://repeatermock.com/pricing", target: "_blank", rel: "noopener", title: "Unlock on RepeaterMock (plans from ₹19)" }, "🔒 Unlock")
        ]);
      }))
    ]);

    app.appendChild(h("div", { class: "rm-sections-wrap" }, [tabs, panel]));
  }

  // ----- INSTRUCTIONS (REAL RepeaterMock text, verbatim) --------------------
  function renderInstructions(seriesId, secIdx, testIdx) {
    const found = findTest(seriesId, Number(secIdx), Number(testIdx));
    clear(app);
    if (!found) { renderNotFound(); return; }
    const { series, section, test } = found;
    const testUrl = repeaterMockTestUrl(series, test);

    app.appendChild(breadcrumb([
      { label: "Home", href: "/" },
      { label: series.title, href: "/series/" + series.id },
      { label: "Instructions" }
    ]));

    app.appendChild(h("div", { class: "rm-instructions", style: cardAccentVars(series) }, [
      h("h1", {}, test.name),
      h("div", { class: "meta-row" }, [
        h("span", {}, "⏱ " + test.duration + " Mins"),
        h("span", {}, "🏆 " + test.marks + " Marks"),
        h("span", {}, "📝 " + test.questions + " Questions"),
        h("span", {}, "🌐 " + (series.language || "English, Hindi")),
        h("span", {}, "📚 " + section.name),
        test.free ? h("span", { class: "free-tag" }, "FREE") : h("span", { class: "lock-tag" }, "PRO")
      ]),

      h("h2", { style: "margin:18px 0 8px;font-size:17px;" }, "General Instructions:"),
      h("ol", { class: "rm-instructions-list" }, REPEATERMOCK_INSTRUCTIONS.general.map(function (i) { return h("li", {}, i); })),

      h("h3", { style: "margin:18px 0 6px;font-size:15px;" }, "Navigating to a Question:"),
      h("ol", { class: "rm-instructions-list" }, REPEATERMOCK_INSTRUCTIONS.navigating.map(function (i) { return h("li", {}, i); })),
      h("p", { class: "rm-muted", style: "font-size:13.5px;margin:0 0 14px;" }, REPEATERMOCK_INSTRUCTIONS.navigatingNote),

      h("h3", { style: "margin:18px 0 6px;font-size:15px;" }, "Answering a Question:"),
      h("ol", { class: "rm-instructions-list" }, REPEATERMOCK_INSTRUCTIONS.answering.map(function (i) { return h("li", {}, i); })),

      h("div", { class: "rm-agree", style: "margin-top:22px;" }, [
        h("p", { style: "margin:0 0 10px;font-size:14px;" }, [
          h("strong", {}, "Ready to attempt the test? "),
          test.id
            ? document.createTextNode("This test has REAL questions loaded — click below to start the test right here on our site. The full test runner with timer, question palette, and all 100 real SSC CGL 2025 questions runs in your browser.")
            : document.createTextNode("Click below to open the real test on RepeaterMock. The questions, timer, scoring, and section-wise analysis all run on the original platform."),
        ])
      ]),
      h("div", { class: "rm-instructions-actions" }, [
        h("a", { class: "rm-btn rm-btn-secondary", href: "/series/" + series.id + "/" + secIdx }, "← Back to tests"),
        test.id
          ? h("a", { class: "rm-btn rm-btn-lg", href: "/test/" + test.id }, "Start Test →")
          : test.free
            ? h("a", { class: "rm-btn rm-btn-lg", href: testUrl, target: "_blank", rel: "noopener" }, "Start Test on RepeaterMock →")
            : h("a", { class: "rm-btn rm-btn-lg", href: "https://repeatermock.com/pricing", target: "_blank", rel: "noopener" }, "🔒 Unlock on RepeaterMock (from ₹19)")
      ]),
    ]));
  }

  // ----- PRICING (verbatim from RepeaterMock) -------------------------------
  function renderPricing() {
    clear(app);
    app.appendChild(breadcrumb([
      { label: "Home", href: "/" },
      { label: "Pricing" }
    ]));
    const P = REPEATERMOCK_PRICING;
    app.appendChild(h("div", { class: "rm-series-hero" }, [
      h("h1", { style: "margin:0 0 8px;" }, "Clear prices. Nothing renews on its own."),
      h("p", { class: "desc" }, "Two separate upgrades. Take one, take both, or take neither. Trusted by 25,000+ students who've already paid for premium access."),
    ]));

    // Ad-free plans
    app.appendChild(h("h2", { style: "margin:24px 0 10px;font-size:20px;" }, "Remove the banners"));
    app.appendChild(h("p", { class: "rm-muted", style: "margin:0 0 14px;font-size:14px;" }, "Takes the promo banners off the home page, your analysis pages and the test-series pages. One payment — no auto-renewal, and no card is saved."));
    const adGrid = h("div", { class: "rm-series-grid" });
    P.ad_free_plans.forEach(function (plan) {
      adGrid.appendChild(h("article", { class: "rm-series-card", style: "--card-accent:#16a34a;--card-tint:#dcfce7;" }, [
        h("span", { class: "tier-badge" }, plan.name),
        h("div", { class: "big-count" }, [h("strong", {}, plan.price), h("span", {}, plan.regular ? "Regular " + plan.regular + " (" + plan.discount + ")" : "")]),
        plan.per_month ? h("p", { class: "rm-muted", style: "margin:0 0 12px;font-size:13px;" }, plan.per_month) : null,
        h("ul", { style: "margin:0;padding-left:18px;font-size:13.5px;color:#475569;" }, plan.features.map(function (f) { return h("li", {}, f); })),
      ]));
    });
    app.appendChild(adGrid);

    // Mock test plans
    app.appendChild(h("h2", { style: "margin:30px 0 10px;font-size:20px;" }, "Open the locked test series"));
    app.appendChild(h("p", { class: "rm-muted", style: "margin:0 0 14px;font-size:14px;" }, "Most test series here are free. A few are locked — you'll see a lock on them. The first test of every subsection is always free to try, so you can check the quality before paying. A mock test plan opens all the rest. This is separate from ad-free above. Buying one does not give you the other."));
    const mockGrid = h("div", { class: "rm-series-grid" });
    P.mock_test_plans.forEach(function (plan) {
      mockGrid.appendChild(h("article", { class: "rm-series-card", style: "--card-accent:#9333ea;--card-tint:#f3e8ff;" }, [
        h("span", { class: "tier-badge" }, plan.name.split(" (")[0]),
        h("div", { class: "big-count" }, [h("strong", {}, plan.price), h("span", {}, plan.regular ? "Regular " + plan.regular + " (" + plan.discount + ")" : "")]),
        h("ul", { style: "margin:8px 0 0;padding-left:18px;font-size:13.5px;color:#475569;" }, plan.features.map(function (f) { return h("li", {}, f); })),
      ]));
    });
    app.appendChild(mockGrid);

    // Free vs paid comparison
    app.appendChild(h("h2", { style: "margin:30px 0 10px;font-size:20px;" }, "What you get without paying"));
    app.appendChild(h("p", { class: "rm-muted", style: "margin:0 0 14px;font-size:14px;" }, "Quite a lot, honestly. Here's the real difference."));
    const cmpGrid = h("div", { class: "rm-series-grid" });
    cmpGrid.appendChild(h("article", { class: "rm-series-card", style: "--card-accent:#16a34a;--card-tint:#dcfce7;" }, [
      h("span", { class: "tier-badge" }, "Free account"),
      h("div", { class: "big-count" }, [h("strong", {}, "₹0"), h("span", {}, "forever")]),
      h("ul", { style: "margin:8px 0 0;padding-left:18px;font-size:13.5px;color:#475569;" }, P.free_account_features.map(function (f) { return h("li", {}, f); })),
    ]));
    cmpGrid.appendChild(h("article", { class: "rm-series-card", style: "--card-accent:#9333ea;--card-tint:#f3e8ff;" }, [
      h("span", { class: "tier-badge" }, "With a mock test plan"),
      h("div", { class: "big-count" }, [h("strong", {}, "from ₹19"), h("span", {}, "one payment")]),
      h("ul", { style: "margin:8px 0 0;padding-left:18px;font-size:13.5px;color:#475569;" }, P.paid_account_extra_features.map(function (f) { return h("li", {}, f); })),
    ]));
    app.appendChild(cmpGrid);

    app.appendChild(h("div", { class: "rm-instructions-actions", style: "margin-top:24px;justify-content:center;" }, [
      h("a", { class: "rm-btn rm-btn-lg", href: "https://repeatermock.com/pricing", target: "_blank", rel: "noopener" }, "Pay on RepeaterMock →"),
    ]));
  }

  // ----- FAQ (verbatim from RepeaterMock) ----------------------------------
  function renderFaq() {
    clear(app);
    app.appendChild(breadcrumb([
      { label: "Home", href: "/" },
      { label: "FAQ" }
    ]));
    app.appendChild(h("div", { class: "rm-series-hero" }, [
      h("h1", { style: "margin:0 0 8px;" }, "Frequently Asked Questions"),
      h("p", { class: "desc" }, "Quick answers to questions we hear most often."),
    ]));
    const faqList = h("div", { class: "rm-tests-panel" });
    REPEATERMOCK_PRICING.faq.forEach(function (item) {
      faqList.appendChild(h("div", { class: "rm-test-row", style: "flex-direction:column;align-items:flex-start;gap:6px;" }, [
        h("div", { class: "name", style: "font-weight:700;color:#0f172a;" }, item.q),
        h("div", { class: "meta", style: "font-size:14px;color:#475569;line-height:1.55;white-space:normal;" }, item.a)
      ]));
    });
    app.appendChild(faqList);
  }

  // ----- ABOUT (verbatim from RepeaterMock) --------------------------------
  function renderAbout() {
    clear(app);
    app.appendChild(breadcrumb([
      { label: "Home", href: "/" },
      { label: "About" }
    ]));
    const A = REPEATERMOCK_PRICING.about;
    app.appendChild(h("div", { class: "rm-series-hero" }, [
      h("h1", { style: "margin:0 0 10px;" }, "About Repeater Mock"),
      h("p", { class: "desc" }, A.intro),
      h("div", { class: "stats" }, A.stats.map(function (s) {
        return h("div", { class: "stat" }, [h("strong", {}, s.v), h("span", {}, s.l)]);
      })),
    ]));

    app.appendChild(h("div", { class: "rm-series-hero", style: "margin-top:18px;" }, [
      h("h2", { style: "margin:0 0 10px;font-size:18px;" }, "Our Mission"),
      h("p", { class: "desc" }, A.mission),
    ]));

    app.appendChild(h("div", { class: "rm-series-hero", style: "margin-top:18px;" }, [
      h("h2", { style: "margin:0 0 10px;font-size:18px;" }, "What We Offer"),
      h("ul", { style: "margin:0;padding-left:22px;font-size:14.5px;line-height:1.8;color:#475569;" }, A.offerings.map(function (o) { return h("li", {}, o); })),
    ]));

    app.appendChild(h("div", { class: "rm-series-hero", style: "margin-top:18px;" }, [
      h("h2", { style: "margin:0 0 10px;font-size:18px;" }, "Security First"),
      h("p", { class: "desc" }, "We use Google Authenticator (TOTP) instead of email verification. This means no email bills for us, no spam for you, and a genuinely more secure account."),
      h("div", { class: "rm-instructions-actions" }, [
        h("a", { class: "rm-btn", href: "https://repeatermock.com/tb/test-series", target: "_blank", rel: "noopener" }, "Start Practicing"),
        h("a", { class: "rm-btn rm-btn-secondary", href: "https://repeatermock.com/contact", target: "_blank", rel: "noopener" }, "Contact Us"),
      ])
    ]));
  }

  // ----- TEST RUNNER (with REAL questions) ---------------------------------
  async function renderRunner(testId) {
    clear(app);
    app.appendChild(h("div", { class: "rm-loading" }, "Loading test questions..."));

    // Fetch the real questions JSON — try both naming conventions
    let testData;
    try {
      let resp = await fetch("/tests/" + testId + ".json");
      let ct = resp.headers.get("content-type") || "";
      if (!resp.ok || !ct.includes("json")) {
        // Try alternate naming
        resp = await fetch("/tests/questions_" + testId + ".json");
        ct = resp.headers.get("content-type") || "";
      }
      if (!resp.ok || !ct.includes("json")) throw new Error("Not found");
      testData = await resp.json();
    } catch (e) {
      clear(app);
      app.appendChild(h("div", { class: "rm-not-found" }, [
        h("h1", {}, "Questions not available"),
        h("p", { class: "rm-muted" }, "This test's questions haven't been scraped yet. Only test ID 6a0f3ef125f9d428c136a83a (SSC CGL 2025 Shift 1) has real questions loaded."),
        h("a", { class: "rm-btn", href: "/" }, "← Back to Test Series"),
      ]));
      return;
    }

    clear(app);
    const questions = testData.questions;
    const sectionNames = {1: "General Intelligence and Reasoning", 2: "General Awareness", 3: "Quantitative Aptitude", 4: "English Comprehension"};
    const lang = "en"; // default English

    // Group questions by section
    const sections = {};
    questions.forEach(q => {
      const s = q.section || 1;
      if (!sections[s]) sections[s] = [];
      sections[s].push(q);
    });
    const sectionIds = Object.keys(sections).map(Number).sort((a,b) => a-b);

    const state = {
      current: 0,
      answers: new Array(questions.length).fill(null),
      marked: new Array(questions.length).fill(false),
      visited: new Array(questions.length).fill(false),
      timeLeft: testData.duration_minutes * 60,
      timer: null,
      submitted: false,
    };
    state.visited[0] = true;

    const titleEl = h("div", { class: "title" }, testData.test_title);
    const timerEl = h("div", { class: "timer", id: "timer" }, "00:00:00");
    const topbar = h("div", { class: "rm-runner-top" }, [titleEl, timerEl]);

    // Section bar
    const sectionBar = h("div", { class: "rm-section-bar" });
    sectionIds.forEach(sid => {
      const btn = h("button", { dataset: { sid: String(sid) } }, sectionNames[sid] || ("Section " + sid));
      btn.addEventListener("click", () => {
        const firstInSec = questions.findIndex(q => q.section === sid);
        if (firstInSec >= 0) { state.current = firstInSec; state.visited[firstInSec] = true; renderQ(); renderPalette(); updateTabs(); }
      });
      sectionBar.appendChild(btn);
    });

    function updateTabs() {
      const curSec = questions[state.current].section;
      sectionBar.querySelectorAll("button").forEach(b => {
        b.classList.toggle("active", Number(b.dataset.sid) === curSec);
      });
    }

    const qArea = h("div", { class: "rm-q-area", id: "q-area" });
    const paletteGrid = h("div", { class: "rm-palette-grid", id: "palette-grid" });
    const palette = h("div", { class: "rm-palette" }, [
      h("h4", {}, "Question Palette"),
      paletteGrid,
      h("div", { class: "rm-legend" }, [
        h("div", { class: "rm-legend-row" }, [h("span", { class: "rm-legend-sw", style: "background:#bbf7d0;" }), "Answered"]),
        h("div", { class: "rm-legend-row" }, [h("span", { class: "rm-legend-sw", style: "background:#fecaca;" }), "Not Answered"]),
        h("div", { class: "rm-legend-row" }, [h("span", { class: "rm-legend-sw", style: "background:#fed7aa;" }), "Marked for Review"]),
        h("div", { class: "rm-legend-row" }, [h("span", { class: "rm-legend-sw", style: "background:white;" }), "Not Visited"]),
      ]),
      h("div", { class: "rm-palette-actions" }, [
        (function () {
          const b = h("button", { class: "rm-btn rm-btn-ghost rm-btn-block rm-btn-sm" }, "Submit Test");
          b.addEventListener("click", submitTest);
          return b;
        })()
      ])
    ]);

    const body = h("div", { class: "rm-runner-body" }, [qArea, palette]);
    app.appendChild(breadcrumb([
      { label: "Home", href: "/" },
      { label: testData.test_title, href: "/series/rm-tb-ssc-cgl" },
      { label: "Test Runner" }
    ]));
    app.appendChild(h("div", { class: "rm-runner-shell" }, [topbar, sectionBar, body]));

    function pad2(n) { return (n < 10 ? "0" : "") + n; }
    function fmtTime(sec) {
      return pad2(Math.floor(sec / 3600)) + ":" + pad2(Math.floor((sec % 3600) / 60)) + ":" + pad2(sec % 60);
    }
    function tick() {
      if (state.submitted) return;
      state.timeLeft--;
      if (state.timeLeft <= 0) {
        timerEl.textContent = "00:00:00";
        timerEl.className = "timer crit";
        clearInterval(state.timer);
        submitTest(true);
        return;
      }
      timerEl.textContent = fmtTime(state.timeLeft);
      if (state.timeLeft < 60) timerEl.className = "timer crit";
      else if (state.timeLeft < 300) timerEl.className = "timer warn";
    }

    function renderQ() {
      clear(qArea);
      const q = questions[state.current];
      // Handle both old format (q.en) and new format (q.languages.en)
      const langData = q.languages ? (q.languages[lang] || q.languages.en || {}) : (q[lang] || q.en || {});
      const qText = langData.question || "";
      const opts = langData.options || [];

      qArea.appendChild(h("div", { class: "rm-q-meta" }, [
        h("span", {}, "Section: " + (sectionNames[q.section] || ("Section " + q.section))),
        h("span", {}, "Question " + (state.current + 1) + " of " + questions.length),
        h("span", {}, "Marks: +" + q.posMarks + " / -" + (q.negMarks || 0.5)),
      ]));
      // Render question HTML (may contain MathJax, images, HTML entities)
      const qDiv = h("div", { class: "rm-q-text" });
      qDiv.innerHTML = qText;
      qArea.appendChild(qDiv);

      const optsEl = h("div", { class: "rm-options" });
      opts.forEach(function (opt, oi) {
        const selected = state.answers[state.current] === oi;
        const o = h("div", { class: "rm-option" + (selected ? " selected" : "") });
        const letter = h("span", { class: "letter" }, String.fromCharCode(65 + oi));
        const textSpan = h("span", {});
        textSpan.innerHTML = opt.value;
        o.appendChild(letter);
        o.appendChild(textSpan);
        o.addEventListener("click", function () {
          state.answers[state.current] = oi;
          renderQ();
          renderPalette();
        });
        optsEl.appendChild(o);
      });
      qArea.appendChild(optsEl);

      // Trigger MathJax to render any LaTeX in the question + options
      if (window.MathJax && window.MathJax.typeset) {
        window.MathJax.typeset([qArea]);
      } else if (window.MathJax && window.MathJax.typesetPromise) {
        window.MathJax.typesetPromise([qArea]).catch(function(){});
      }

      const controls = h("div", { class: "rm-q-controls" });
      const prevBtn = h("button", { class: "rm-btn rm-btn-ghost rm-btn-sm" }, "← Previous");
      prevBtn.addEventListener("click", prev);
      const clearBtn = h("button", { class: "rm-btn rm-btn-ghost rm-btn-sm" }, "Clear Response");
      clearBtn.addEventListener("click", () => { state.answers[state.current] = null; renderQ(); renderPalette(); });
      const markBtn = h("button", { class: "rm-btn rm-btn-secondary rm-btn-sm" }, state.marked[state.current] ? "Unmark & Next" : "Mark for Review & Next");
      markBtn.addEventListener("click", () => { state.marked[state.current] = !state.marked[state.current]; next(); });
      const nextBtn = h("button", { class: "rm-btn rm-btn-sm" }, "Save & Next →");
      nextBtn.addEventListener("click", next);
      controls.appendChild(prevBtn);
      controls.appendChild(clearBtn);
      controls.appendChild(markBtn);
      controls.appendChild(nextBtn);
      qArea.appendChild(controls);
    }

    function renderPalette() {
      clear(paletteGrid);
      questions.forEach(function (_, i) {
        const answered = state.answers[i] !== null;
        const marked = state.marked[i];
        const visited = state.visited[i];
        let cls = "rm-pcell";
        if (marked && answered) cls += " answered-marked";
        else if (marked) cls += " marked";
        else if (answered) cls += " answered";
        else if (visited) cls += " not-answered";
        else cls += " not-visited";
        if (i === state.current) cls += " current";
        const cell = h("button", { class: cls, title: "Q" + (i + 1) }, String(i + 1));
        cell.addEventListener("click", () => { state.current = i; state.visited[i] = true; renderQ(); renderPalette(); updateTabs(); });
        paletteGrid.appendChild(cell);
      });
    }

    function next() {
      if (state.current < questions.length - 1) { state.current++; state.visited[state.current] = true; renderQ(); renderPalette(); updateTabs(); }
      else { if (confirm("You are on the last question. Submit the test now?")) submitTest(); }
    }
    function prev() {
      if (state.current > 0) { state.current--; state.visited[state.current] = true; renderQ(); renderPalette(); updateTabs(); }
    }

    function submitTest(auto) {
      if (state.submitted) return;
      if (!auto) {
        const ans = state.answers.filter(a => a !== null).length;
        if (!confirm("You have answered " + ans + " of " + questions.length + " questions. Submit the test?")) return;
      }
      state.submitted = true;
      clearInterval(state.timer);
      // Save answers to sessionStorage
      try {
        sessionStorage.setItem("rm_test_result_" + testId, JSON.stringify({
          answers: state.answers,
          timeTaken: (testData.duration_minutes * 60) - state.timeLeft,
          duration: testData.duration_minutes * 60,
        }));
      } catch (e) {}
      location.href = "/result/" + testId;
    }

    state.timer = setInterval(tick, 1000);
    timerEl.textContent = fmtTime(state.timeLeft);
    renderQ();
    renderPalette();
    updateTabs();
  }

  // ----- RESULT PAGE -------------------------------------------------------
  function renderResult(testId) {
    clear(app);
    app.appendChild(h("div", { class: "rm-loading" }, "Loading result..."));

    const sectionNames = {1: "General Intelligence and Reasoning", 2: "General Awareness", 3: "Quantitative Aptitude", 4: "English Comprehension"};

    fetch("/tests/" + testId + ".json")
      .then(r => r.json())
      .then(testData => {
        const questions = testData.questions || [];
        const answers = testData.answers || {};
        const analysis = testData.analysis || {};
        let payload = null;
        try { payload = JSON.parse(sessionStorage.getItem("rm_test_result_" + testId) || "null"); } catch (e) {}

        app.appendChild(breadcrumb([
          { label: "Home", href: "/" },
          { label: testData.title || testData.test_title || "Test", href: "/series/rm-tb-ssc-cgl" },
          { label: "Result" }
        ]));

        if (!payload) {
          // Show the answer key + analysis directly (for pre-scraped tests)
          if (testData.has_answers || Object.keys(answers).length > 0) {
            renderAnswerKey(testData, questions, answers, analysis, sectionNames);
            return;
          }
          app.appendChild(h("div", { class: "rm-instructions" }, [
            h("h1", {}, "No attempt recorded"),
            h("p", { class: "rm-muted" }, "We couldn't find an attempt for this test. Please start the test first."),
            h("div", { class: "rm-instructions-actions" }, [
              h("a", { class: "rm-btn", href: "/test/" + testId }, "Start Test"),
              h("a", { class: "rm-btn rm-btn-secondary", href: "/" }, "Back to Home"),
            ])
          ]));
          return;
        }

        // User submitted — calculate score using answer keys
        const answered = payload.answers.filter(a => a !== null).length;
        const unattempted = questions.length - answered;
        const timeMin = Math.floor(payload.timeTaken / 60);
        let correct = 0, wrong = 0, marks = 0;

        questions.forEach(function (q, i) {
          const userAns = payload.answers[i];
          if (userAns === null) return;
          const ansData = answers[q.id];
          if (!ansData) return;
          const correctOpt = parseInt(ansData.correctOption) - 1; // 1-based to 0-based
          if (userAns === correctOpt) {
            correct++;
            marks += q.posMarks || 2;
          } else {
            wrong++;
            marks -= q.negMarks || 0.5;
          }
        });

        // Score hero
        app.appendChild(h("div", { class: "rm-result-hero" }, [
          h("div", { class: "score-label" }, testData.title || testData.test_title),
          h("div", { class: "score-big" }, marks.toFixed(1) + " / " + (testData.total_marks || 200)),
          h("div", { class: "rm-muted" }, "Correct: " + correct + " · Wrong: " + wrong + " · Unattempted: " + unattempted + " · Time: " + timeMin + " min"),
          h("div", { class: "rm-result-stats" }, [
            h("div", { class: "rm-result-stat ok" }, [h("div", { class: "v" }, String(correct)), h("div", { class: "l" }, "Correct")]),
            h("div", { class: "rm-result-stat err" }, [h("div", { class: "v" }, String(wrong)), h("div", { class: "l" }, "Wrong")]),
            h("div", { class: "rm-result-stat warn" }, [h("div", { class: "v" }, String(unattempted)), h("div", { class: "l" }, "Unattempted")]),
            h("div", { class: "rm-result-stat" }, [h("div", { class: "v" }, Math.round((correct / questions.length) * 100) + "%"), h("div", { class: "l" }, "Accuracy")]),
          ]),
        ]));

        // Analysis data (rank, cutoff, etc.) — from RepeaterMock
        if (analysis.ts || analysis.analysis) {
          const ts = analysis.ts || {};
          const an = analysis.analysis || {};
          app.appendChild(h("div", { class: "rm-series-hero", style: "margin-top:18px;" }, [
            h("h2", { style: "margin:0 0 10px;font-size:17px;" }, "RepeaterMock Analysis Data"),
            h("div", { class: "rm-result-stats" }, [
              ts.rank ? h("div", { class: "rm-result-stat" }, [h("div", { class: "v" }, "#" + ts.rank), h("div", { class: "l" }, "Rank (RepeaterMock)")]) : null,
              ts.percentile != null ? h("div", { class: "rm-result-stat" }, [h("div", { class: "v" }, ts.percentile.toFixed(1) + "%"), h("div", { class: "l" }, "Percentile")]) : null,
              an.avgMarks ? h("div", { class: "rm-result-stat" }, [h("div", { class: "v" }, an.avgMarks.toFixed(1)), h("div", { class: "l" }, "Average Marks")]) : null,
              an.totalStudents ? h("div", { class: "rm-result-stat" }, [h("div", { class: "v" }, String(an.totalStudents)), h("div", { class: "l" }, "Total Students")]) : null,
            ]),
          ]));
        }

        // Detailed solutions with answer keys
        renderAnswerKey(testData, questions, answers, analysis, sectionNames, payload);
      })
      .catch(() => {
        clear(app);
        app.appendChild(h("div", { class: "rm-not-found" }, [
          h("h1", {}, "Result not available"),
          h("a", { class: "rm-btn", href: "/" }, "← Back to Test Series"),
        ]));
      });
  }

  // Helper: render answer key + solutions
  function renderAnswerKey(testData, questions, answers, analysis, sectionNames, payload) {
    const hasUserAttempt = payload && payload.answers;
    const sol = h("div", { class: "rm-solutions" }, [
      h("h2", {}, hasUserAttempt ? "Detailed Solutions & Answer Key" : "Answer Key & Solutions"),
    ]);

    questions.forEach(function (q, i) {
      const userAns = hasUserAttempt ? payload.answers[i] : null;
      const langData = q.languages ? (q.languages.en || {}) : (q.en || {});
      const qText = langData.question || "";
      const opts = langData.options || [];
      const sectionName = sectionNames[q.section] || ("Section " + q.section);
      const ansData = answers[q.id];
      const correctOpt = ansData ? (parseInt(ansData.correctOption) - 1) : null;
      const solData = ansData ? (ansData.sol || {}) : {};
      const solEn = solData.en || {};
      const solText = typeof solEn === 'object' ? (solEn.value || "") : String(solEn);

      // Status badge
      let badge;
      if (!hasUserAttempt) {
        badge = h("span", { class: "free-tag", style: "margin-left:6px;" }, "Correct: " + (correctOpt !== null ? String.fromCharCode(65 + correctOpt) : "N/A"));
      } else if (userAns === null) {
        badge = h("span", { class: "lock-tag", style: "margin-left:6px;" }, "Skipped");
      } else if (userAns === correctOpt) {
        badge = h("span", { class: "free-tag", style: "margin-left:6px;" }, "✓ Correct");
      } else {
        badge = h("span", { class: "lock-tag", style: "margin-left:6px;" }, "✗ Wrong");
      }

      const qBlock = h("div", { class: "rm-solution-item" });

      // Question heading
      const heading = h("div", { class: "q", style: "margin-bottom:8px;" });
      heading.appendChild(document.createTextNode("Q" + (i + 1) + ". [" + sectionName + "] "));
      heading.appendChild(badge);
      qBlock.appendChild(heading);

      // Question text
      const qDiv = h("div", { class: "q", style: "margin-bottom:8px;font-weight:normal;" });
      qDiv.innerHTML = qText;
      qBlock.appendChild(qDiv);

      // Options with correct/wrong highlighting
      const optsDiv = h("div", { class: "opts" });
      opts.forEach(function (opt, oi) {
        let cls = "opt";
        if (correctOpt !== null && oi === correctOpt) cls += " correct";
        if (hasUserAttempt && oi === userAns && oi !== correctOpt) cls += " wrong";
        const optDiv = h("div", { class: cls });
        optDiv.innerHTML = String.fromCharCode(65 + oi) + ". " + opt.value;
        optsDiv.appendChild(optDiv);
      });
      qBlock.appendChild(optsDiv);

      // Solution explanation — render as HTML (may contain images, MathJax, formatted text)
      if (solText && solText.length > 2 && solText !== "$" && !solText.match(/^\$\d+$/)) {
        const exDiv = h("div", { class: "ex" });
        // Create a label span + render solution HTML
        const label = document.createElement("strong");
        label.textContent = "Solution: ";
        exDiv.appendChild(label);
        const solContent = document.createElement("div");
        solContent.style.display = "inline";
        solContent.innerHTML = solText;
        exDiv.appendChild(solContent);
        qBlock.appendChild(exDiv);
      }

      sol.appendChild(qBlock);
    });
    app.appendChild(sol);

    // Clear the loading indicator if still visible
    const loading = app.querySelector(".rm-loading");
    if (loading) loading.remove();

    // Trigger MathJax
    if (window.MathJax && window.MathJax.typesetPromise) {
      window.MathJax.typesetPromise([sol]).catch(function(){});
    }
  }

  function renderNotFound() {
    clear(app);
    app.appendChild(h("div", { class: "rm-not-found" }, [
      h("h1", {}, "404"),
      h("p", {}, "The page you're looking for doesn't exist."),
      h("a", { class: "rm-btn", href: "/" }, "Go to Test Series"),
    ]));
  }

  // ----- ROUTER -------------------------------------------------------------
  function route() {
    const path = location.pathname.replace(/\/+$/, "") || "/";
    if (path === "/" || path === "/index.html") { renderHome(); return; }
    if (path === "/pricing") { renderPricing(); return; }
    if (path === "/faq") { renderFaq(); return; }
    if (path === "/about") { renderAbout(); return; }
    let m;
    if ((m = path.match(/^\/series\/([\w-]+)\/(\d+)$/))) { renderSeries(m[1], Number(m[2])); return; }
    if ((m = path.match(/^\/series\/([\w-]+)$/)))            { renderSeries(m[1], 0); return; }
    if ((m = path.match(/^\/instructions\/([\w-]+)\/(\d+)\/(\d+)$/))) { renderInstructions(m[1], m[2], m[3]); return; }
    if ((m = path.match(/^\/test\/([a-f0-9]+)$/)))            { renderRunner(m[1]); return; }
    if ((m = path.match(/^\/result\/([a-f0-9]+)$/)))          { renderResult(m[1]); return; }
    renderNotFound();
  }

  window.addEventListener("popstate", route);
  route();
})();
