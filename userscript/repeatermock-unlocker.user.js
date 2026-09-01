// ==UserScript==
// @name         RepeaterMock PRO Unlocker — Take Any Test (Free or PRO)
// @namespace    https://repeatermock.com
// @version      5.0
// @description  Unlocks ALL tests (free + PRO) so you can take them directly on the website. Bypasses the "Unlock" button by fetching test IDs via API and creating working links. Take the test normally → get score → see solutions → see rank & analysis. Works with FREE accounts.
// @author       PWThor
// @match        *://repeatermock.com/*
// @match        *://www.repeatermock.com/*
// @grant        none
// @run-at       document-idle
// ==/UserScript==

(function() {
    'use strict';

    const API_BASE = 'https://api.repeatermock.com';
    const DEBUG = true;

    function dbg(...args) {
        if (DEBUG) console.log('%c[RM Unlock v5]', 'color:#facc15;font-weight:bold', ...args);
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 1: Fetch test IDs via API and build working links
    // ═════════════════════════════════════════════════════════════════════

    // Cache of test IDs per series (fetched from API)
    const testCache = new Map(); // seriesUrl → [{title, id, ...}]

    async function fetchTestIds(variant, slug) {
        const cacheKey = `${variant}/${slug}`;
        if (testCache.has(cacheKey)) return testCache.get(cacheKey);

        dbg(`Fetching test list for ${cacheKey}...`);
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';
        const tests = [];

        try {
            // 1. Fetch series details to get series ID + sections
            const seriesResp = await fetch(`${API_BASE}${apiPrefix}/test-series/${slug}${variant !== 'gd' ? `?variant=${variant}` : ''}`, {
                credentials: 'include',
                headers: { 'Accept': 'application/json' },
            });
            const seriesData = await seriesResp.json();
            const details = seriesData?.data?.details || seriesData?.details;
            if (!details || !details.id) {
                dbg('✗ Could not fetch series details');
                return [];
            }

            dbg(`Series: ${details.name} (${details.id})`);

            // 2. Fetch tests for each section/subsection
            for (const sec of details.sections || []) {
                const secId = sec.id;
                const subs = sec.subsections || [];

                if (subs.length === 0) {
                    // Fetch tests for this section directly
                    const url = `${API_BASE}${apiPrefix}/test-series/${details.id}/sections/${secId}/tests?limit=500&offset=0${variant !== 'gd' ? `&variant=${variant}` : ''}`;
                    const r = await fetch(url, { credentials: 'include', headers: { 'Accept': 'application/json' } });
                    if (r.ok) {
                        const d = await r.json();
                        for (const t of d.data || []) {
                            tests.push({ id: t.id, title: t.title, ...t });
                        }
                    }
                } else {
                    for (const sub of subs) {
                        const url = `${API_BASE}${apiPrefix}/test-series/${details.id}/sections/${secId}/tests?limit=500&offset=0${variant !== 'gd' ? `&variant=${variant}` : ''}&subSectionId=${sub.id}`;
                        const r = await fetch(url, { credentials: 'include', headers: { 'Accept': 'application/json' } });
                        if (r.ok) {
                            const d = await r.json();
                            for (const t of d.data || []) {
                                tests.push({ id: t.id, title: t.title, ...t });
                            }
                        }
                    }
                }
            }

            dbg(`✓ Fetched ${tests.length} tests for ${cacheKey}`);
        } catch (e) {
            dbg('Fetch error:', e.message);
        }

        testCache.set(cacheKey, tests);
        return tests;
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 2: Find "Unlock" buttons and replace them with working links
    // ═════════════════════════════════════════════════════════════════════

    async function unlockTests() {
        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)/);
        if (!m) return;

        const variant = m[1];
        const slug = m[2];

        // Fetch all test IDs for this series
        const tests = await fetchTestIds(variant, slug);
        if (tests.length === 0) {
            dbg('No tests found via API — cannot unlock');
            return;
        }

        // Build a map: test title (lowercase) → test ID
        const titleToId = new Map();
        const partialTitleToId = new Map();
        for (const t of tests) {
            titleToId.set(t.title.toLowerCase().trim(), t.id);
            // Also map first 20 chars of title for fuzzy matching
            partialTitleToId.set(t.title.toLowerCase().trim().substring(0, 20), t.id);
        }
        dbg(`Test cache: ${titleToId.size} tests`);

        // Find all "Unlock" buttons on the page
        const unlockBtns = document.querySelectorAll('button, a, [role="button"], span, div');
        let unlocked = 0;

        for (const btn of unlockBtns) {
            const text = (btn.textContent || '').trim();
            if (text !== 'Unlock' && !text.match(/^Unlock$/)) continue;

            // Walk up to find the test card container
            let card = btn.parentElement;
            for (let i = 0; i < 8 && card; i++) {
                const cardText = (card.textContent || '').toLowerCase();
                // Try to match card text to a test title
                let matchedId = null;
                let matchedTitle = null;

                for (const [title, id] of titleToId) {
                    // Check if the card contains the test title (or a meaningful part)
                    if (cardText.includes(title.substring(0, Math.min(title.length, 30)))) {
                        matchedId = id;
                        matchedTitle = title;
                        break;
                    }
                }

                if (matchedId) {
                    const testUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${matchedId}/attempt`;

                    // Replace the Unlock button with a Start Test link
                    const newLink = document.createElement('a');
                    newLink.href = testUrl;
                    newLink.innerHTML = '▶ Start Test';
                    newLink.style.cssText = `
                        display:inline-block; background:#16a34a; color:white !important;
                        padding:8px 16px; border-radius:8px; font-weight:bold;
                        text-decoration:none; cursor:pointer; font-size:14px;
                        border:0; font-family:inherit;
                    `;
                    newLink.onclick = async (e) => {
                        e.preventDefault();
                        dbg(`Starting test: ${matchedTitle} (${matchedId})`);

                        // Pre-start the attempt via API (bypasses payment check)
                        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';
                        try {
                            dbg(`POST ${API_BASE}${apiPrefix}/attempts/${matchedId}/start`);
                            const resp = await fetch(`${API_BASE}${apiPrefix}/attempts/${matchedId}/start`, {
                                method: 'POST',
                                credentials: 'include',
                                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                                body: '{}',
                            });
                            const data = await resp.json();
                            dbg('Start response:', data);

                            if (data.success || data.code === 'already_in_progress') {
                                dbg('✓ Attempt started — navigating to test page...');
                                window.location.href = testUrl;
                            } else if (data.code === 'payment_required') {
                                dbg('⚠ Payment required — trying v1 endpoint...');
                                const resp2 = await fetch(`${API_BASE}/api/v1/attempts/${matchedId}/start`, {
                                    method: 'POST', credentials: 'include',
                                    headers: { 'Content-Type': 'application/json' }, body: '{}',
                                });
                                const data2 = await resp2.json();
                                dbg('Retry:', data2);
                                if (data2.success) {
                                    window.location.href = testUrl;
                                } else {
                                    dbg('✗ Still blocked — navigating anyway to try');
                                    window.location.href = testUrl;
                                }
                            } else {
                                dbg('Unexpected response — navigating anyway');
                                window.location.href = testUrl;
                            }
                        } catch (e) {
                            dbg('Start error:', e.message);
                            window.location.href = testUrl;
                        }
                    };

                    // Replace the button
                    btn.parentNode.replaceChild(newLink, btn);
                    unlocked++;
                    dbg(`✓ Unlocked: ${matchedTitle.substring(0, 40)} → ${matchedId}`);
                    break;
                }
                card = card.parentElement;
            }
        }

        dbg(`Unlocked ${unlocked} test buttons`);
        return unlocked;
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 3: On test pages — bypass paywall if detected
    // ═════════════════════════════════════════════════════════════════════

    async function bypassPaywall() {
        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)\/test\/([a-f0-9]+)/);
        if (!m) return;

        const variant = m[1];
        const slug = m[2];
        const testId = m[3];
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';

        // Wait for page to load
        await new Promise(r => setTimeout(r, 3000));

        // Check if we're on a pricing/redirect page or if test isn't visible
        const bodyText = (document.body?.innerText || '').toLowerCase();
        const isPaywall = bodyText.includes('unlock') || bodyText.includes('subscribe') ||
                         bodyText.includes('upgrade') || bodyText.includes('pricing') ||
                         window.location.pathname.includes('/pricing');

        // Check if test questions are visible
        const hasQuestions = document.querySelector('[class*="question"], [class*="Question"], [class*="option"], [class*="Option"]');

        if (isPaywall || !hasQuestions) {
            dbg('⚠ Paywall or blank test page detected — auto-starting attempt...');

            try {
                const resp = await fetch(`${API_BASE}${apiPrefix}/attempts/${testId}/start`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: '{}',
                });
                const data = await resp.json();
                dbg('Start response:', data);

                if (data.success) {
                    dbg('✓ Attempt started — reloading page...');
                    // Navigate to /attempt page (not /pricing)
                    const attemptUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}/attempt`;
                    if (window.location.pathname !== `${variant}/test-series/${slug}/test/${testId}/attempt`) {
                        window.location.href = attemptUrl;
                    } else {
                        window.location.reload();
                    }
                    return;
                } else if (data.code === 'payment_required') {
                    dbg('⚠ Payment required — trying v1 fallback...');
                    const resp2 = await fetch(`${API_BASE}/api/v1/attempts/${testId}/start`, {
                        method: 'POST', credentials: 'include',
                        headers: { 'Content-Type': 'application/json' }, body: '{}',
                    });
                    const data2 = await resp2.json();
                    dbg('v1 retry:', data2);
                    if (data2.success) {
                        window.location.href = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}/attempt`;
                        return;
                    }
                    // Last resort: show a message
                    showPaywallBypass(testId, variant, slug, apiPrefix);
                }
            } catch (e) {
                dbg('Start error:', e.message);
                showPaywallBypass(testId, variant, slug, apiPrefix);
            }
        } else {
            dbg('✓ Test page looks normal — no bypass needed');
        }
    }

    function showPaywallBypass(testId, variant, slug, apiPrefix) {
        const existing = document.getElementById('rm-bypass-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'rm-bypass-overlay';
        overlay.style.cssText = `
            position:fixed; top:0; left:0; width:100%; height:100%;
            background:#0f172a; color:#e2e8f0; z-index:999999;
            display:flex; align-items:center; justify-content:center;
            font-family:system-ui;
        `;
        overlay.innerHTML = `
            <div style="text-align:center; max-width:500px; padding:40px;">
                <h2 style="color:#38bdf8;">🔓 Bypassing Paywall...</h2>
                <p style="color:#94a3b8;">Starting attempt via API for test ${testId}</p>
                <div style="margin:20px; padding:20px; background:#1e293b; border-radius:8px;">
                    <p id="rm-bypass-status">Calling /start API...</p>
                </div>
                <a href="https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}/attempt"
                   style="display:inline-block; background:#16a34a; color:white;
                   padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:bold;">
                   ▶ Go to Test Page
                </a>
            </div>
        `;
        document.body.innerHTML = '';
        document.body.appendChild(overlay);

        // Try starting
        fetch(`${API_BASE}${apiPrefix}/attempts/${testId}/start`, {
            method: 'POST', credentials: 'include',
            headers: { 'Content-Type': 'application/json' }, body: '{}',
        })
        .then(r => r.json())
        .then(data => {
            document.getElementById('rm-bypass-status').textContent = JSON.stringify(data);
            if (data.success) {
                setTimeout(() => {
                    window.location.href = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}/attempt`;
                }, 1500);
            }
        })
        .catch(e => {
            document.getElementById('rm-bypass-status').textContent = `Error: ${e.message}`;
        });
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 4: Floating "Unlock All" button
    // ═════════════════════════════════════════════════════════════════════

    function addUnlockAllButton() {
        if (document.getElementById('rm-unlock-all-btn')) return;
        if (!window.location.pathname.includes('/test-series/')) return;

        const btn = document.createElement('button');
        btn.id = 'rm-unlock-all-btn';
        btn.textContent = '🔓 Unlock All Tests';
        btn.style.cssText = `
            position:fixed; bottom:20px; right:20px; z-index:999999;
            background:#16a34a; color:white; border:0; padding:12px 24px;
            border-radius:12px; font-size:16px; font-weight:bold; cursor:pointer;
            box-shadow:0 4px 12px rgba(0,0,0,0.3);
        `;
        btn.onclick = async () => {
            btn.textContent = '⏳ Unlocking...';
            dbg('Unlocking all tests...');
            await unlockTests();
            setTimeout(unlockTests, 2000);
            setTimeout(unlockTests, 5000);
            btn.textContent = '✓ Unlocked!';
            setTimeout(() => { btn.textContent = '🔓 Unlock All Tests'; }, 3000);
        };
        document.body.appendChild(btn);
        dbg('Unlock All button added');
    }

    // ═════════════════════════════════════════════════════════════════════
    // INIT
    // ═════════════════════════════════════════════════════════════════════

    async function init() {
        dbg('v5 initialized on:', window.location.pathname);
        addUnlockAllButton();

        if (window.location.pathname.includes('/test-series/')) {
            await unlockTests();
        }

        if (window.location.pathname.includes('/test/')) {
            await bypassPaywall();
        }
    }

    let lastUrl = window.location.href;
    const observer = new MutationObserver(() => {
        if (window.location.href !== lastUrl) {
            lastUrl = window.location.href;
            dbg('URL changed:', lastUrl);
            setTimeout(init, 2000);
        }
    });

    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }

    setTimeout(init, 2000);
    setTimeout(init, 5000);
    setTimeout(init, 10000);

    window.addEventListener('popstate', () => setTimeout(init, 2000));

    dbg('v5 loaded — waiting for page...');
})();
