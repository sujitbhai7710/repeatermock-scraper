// ==UserScript==
// @name         RepeaterMock Test Unlocker — Take FREE Tests + View PRO Questions
// @namespace    https://repeatermock.com
// @version      8.0
// @description  Unlock FREE tests (tb platform) — take them normally with timer, submit, score, solutions, rank. For PRO tests (tb-pro), view all questions. No popups, no pricing redirects.
// @author       PWThor
// @match        *://repeatermock.com/*
// @match        *://www.repeatermock.com/*
// @grant        none
// @run-at       document-start
// ==/UserScript==

(function() {
    'use strict';

    const API_BASE = 'https://api.repeatermock.com';
    const DEBUG = true;

    function dbg(...args) {
        if (DEBUG) console.log('%c[RM v8]', 'color:#facc15;font-weight:bold', ...args);
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 1: Intercept fetch — handle 402 and 404 gracefully
    // ═════════════════════════════════════════════════════════════════════

    const originalFetch = window.fetch;
    window.fetch = async function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
        const resp = await originalFetch.apply(this, args);

        // Intercept /start that returns 402 — inject our UI instead of redirecting
        if (url.includes('/attempts/') && url.includes('/start') && resp.status === 402) {
            dbg('⚠ 402 Payment Required — this is a PRO test, injecting question viewer...');
            const match = url.match(/\/attempts\/([a-f0-9]+)/);
            if (match) {
                const testId = match[1];
                // Return fake success so SPA doesn't redirect to /pricing
                const fake = { success: true, data: { attemptId: 'rm_' + Date.now(), timeLeft: 3600, status: 'in_progress', resuming: false } };
                // Trigger our UI injection
                setTimeout(() => injectQuestionViewer(testId), 500);
                return new Response(JSON.stringify(fake), { status: 200, headers: { 'Content-Type': 'application/json' } });
            }
        }

        // Intercept /responses, /save-question, /submit errors — return fake success
        if (url.includes('/responses') || url.includes('/save-question')) {
            return new Response(JSON.stringify({ success: true, data: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }
        if (url.includes('/submit') && (resp.status === 404 || resp.status === 402)) {
            return new Response(JSON.stringify({ success: true, data: { attemptId: 'rm_' + Date.now() } }), { status: 200, headers: { 'Content-Type': 'application/json' } });
        }

        return resp;
    };

    // Intercept pushState + replaceState — block /pricing
    const originalPushState = history.pushState;
    history.pushState = function(state, title, url) {
        if (url && typeof url === 'string' && url.includes('/pricing')) {
            dbg('🚫 Blocked /pricing redirect');
            return;
        }
        return originalPushState.apply(this, arguments);
    };
    const originalReplaceState = history.replaceState;
    history.replaceState = function(state, title, url) {
        if (url && typeof url === 'string' && url.includes('/pricing')) {
            dbg('🚫 Blocked /pricing replaceState');
            return;
        }
        return originalReplaceState.apply(this, arguments);
    };

    // Hide error toasts/modals
    const style = document.createElement('style');
    style.textContent = `
        [class*="toast"], [class*="Toast"], [class*="snackbar"], [class*="Snackbar"],
        [class*="alert"], [class*="Alert"], [class*="modal"][class*="error"],
        [class*="Modal"][class*="Error"], [class*="paywall"], [class*="Paywall"],
        [class*="modal"][class*="payment"], [class*="Modal"][class*="Payment"],
        [class*="modal"][class*="pricing"], [class*="Modal"][class*="Pricing"] {
            display: none !important; visibility: hidden !important;
            opacity: 0 !important; pointer-events: none !important;
        }
        #rm-viewer, #rm-viewer * { display: revert !important; visibility: visible !important; opacity: 1 !important; }
    `;
    (document.head || document.documentElement).appendChild(style);

    dbg('Interceptors + CSS installed');

    // ═════════════════════════════════════════════════════════════════════
    // PART 2: Helpers
    // ═════════════════════════════════════════════════════════════════════

    function thoroughUnescape(text) {
        if (!text) return '';
        let r = text;
        for (let i = 0; i < 3; i++) {
            const t = document.createElement('div'); t.innerHTML = r;
            const u = t.textContent || t.innerText;
            if (u === r) break; r = u;
        }
        return r;
    }

    function extractPayload() {
        let payload = '';
        document.querySelectorAll('script').forEach(s => {
            const text = s.textContent || '';
            const matches = text.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
            for (const m of matches) {
                let c = m[1].replace(/\\n/g,'\n').replace(/\\r/g,'\r').replace(/\\"/g,'"').replace(/\\\\/g,'\\');
                payload += c;
            }
        });
        return payload;
    }

    function extractJSONObject(payload, key) {
        const search = `"${key}":{`;
        const idx = payload.indexOf(search);
        if (idx < 0) return null;
        let start = payload.indexOf('{', idx + key.length + 2);
        let depth = 0, inStr = false, esc = false;
        for (let j = start; j < payload.length; j++) {
            const c = payload[j];
            if (esc) { esc = false; continue; }
            if (c === '\\') { esc = true; continue; }
            if (c === '"') { inStr = !inStr; continue; }
            if (inStr) continue;
            if (c === '{') depth++;
            else if (c === '}') { depth--; if (depth === 0) { try { return JSON.parse(payload.substring(start, j+1)); } catch(e) { return null; } } }
        }
        return null;
    }

    function parseQuestions(payload) {
        const questions = [];
        const searchStr = '{"isNum":';
        let idx = 0;
        while (true) {
            idx = payload.indexOf(searchStr, idx);
            if (idx < 0) break;
            let depth = 0, inStr = false, esc = false, start = idx;
            for (let j = idx; j < payload.length; j++) {
                const c = payload[j];
                if (esc) { esc = false; continue; }
                if (c === '\\') { esc = true; continue; }
                if (c === '"') { inStr = !inStr; continue; }
                if (inStr) continue;
                if (c === '{') depth++;
                else if (c === '}') { depth--; if (depth === 0) { try { questions.push(JSON.parse(payload.substring(start, j+1))); } catch(e) {} break; } }
            }
            idx += 1;
        }
        return questions;
    }

    function cleanQuestion(q) {
        const id = q._id || q.id || '';
        let textEn = '';
        if (q.text) {
            if (typeof q.text.en === 'string') textEn = q.text.en;
            else if (q.text.en && q.text.en.value) textEn = q.text.en.value;
        }
        const options = (q.options || []).map(o => {
            if (typeof o.en === 'string') return o.en;
            if (o.en && o.en.value) return o.en.value;
            return '';
        });
        return { id, textEn, options };
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 3: Inject question viewer (for PRO tests — questions only)
    // ═════════════════════════════════════════════════════════════════════

    async function injectQuestionViewer(testId) {
        if (document.getElementById('rm-viewer')) return;

        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)\/test\/([a-f0-9]+)/);
        if (!m) return;
        const variant = m[1], slug = m[2];
        const baseUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}`;
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';

        dbg('Injecting question viewer for PRO test:', testId);

        // Extract questions from current page
        let payload = extractPayload();
        let questions = parseQuestions(payload).map(cleanQuestion);

        // If no questions, fetch /attempt
        if (questions.length === 0) {
            dbg('Fetching /attempt for questions...');
            const resp = await originalFetch(`${baseUrl}/attempt`, { credentials: 'include' });
            const html = await resp.text();
            const matches = html.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
            for (const m of matches) {
                let c = m[1].replace(/\\n/g,'\n').replace(/\\r/g,'\r').replace(/\\"/g,'"').replace(/\\\\/g,'\\');
                payload += c;
            }
            questions = parseQuestions(payload).map(cleanQuestion);
        }

        dbg(`Found ${questions.length} questions`);
        if (questions.length === 0) return;

        // Try to submit (works for FREE tests, fails for PRO — but we try anyway)
        let submitted = false;
        try {
            const startResp = await originalFetch(`${API_BASE}${apiPrefix}/attempts/${testId}/start`, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json' }, body: '{}'
            });
            const startData = await startResp.json();
            if (startData.success) {
                dbg('Attempt started — submitting empty answers...');
                const submitResp = await originalFetch(`${API_BASE}${apiPrefix}/attempts/${testId}/submit`, {
                    method: 'POST', credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ answers: [], timeTaken: 1, language: 'en', interface: 'classic' })
                });
                const submitData = await submitResp.json();
                submitted = submitData.success;
                if (submitted) dbg('✓ Submitted — fetching solutions...');
            }
        } catch(e) { dbg('Submit error:', e.message); }

        // Fetch solution if submitted
        let answersData = null;
        if (submitted) {
            await new Promise(r => setTimeout(r, 2000));
            try {
                const solResp = await originalFetch(`${baseUrl}/solution`, { credentials: 'include' });
                const solHtml = await solResp.text();
                let solPayload = '';
                const matches = solHtml.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
                for (const m of matches) {
                    let c = m[1].replace(/\\n/g,'\n').replace(/\\r/g,'\r').replace(/\\"/g,'"').replace(/\\\\/g,'\\');
                    solPayload += c;
                }
                answersData = extractJSONObject(solPayload, 'answersData');
                dbg('Answers:', answersData ? `${Object.keys(answersData).length} keys` : 'NONE');
            } catch(e) { dbg('Solution fetch error:', e.message); }
        }

        // Fetch analysis if submitted
        let analysisData = null;
        if (submitted) {
            try {
                const anaResp = await originalFetch(`${baseUrl}/analysis`, { credentials: 'include' });
                const anaHtml = await anaResp.text();
                let anaPayload = '';
                const matches = anaHtml.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
                for (const m of matches) {
                    let c = m[1].replace(/\\n/g,'\n').replace(/\\r/g,'\r').replace(/\\"/g,'"').replace(/\\\\/g,'\\');
                    anaPayload += c;
                }
                analysisData = extractJSONObject(anaPayload, 'analysisData');
            } catch(e) {}
        }

        displayUI(questions, answersData, analysisData, testId, variant, slug, submitted);
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 4: Display UI
    // ═════════════════════════════════════════════════════════════════════

    function displayUI(questions, answersData, analysisData, testId, variant, slug, submitted) {
        const existing = document.getElementById('rm-viewer');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'rm-viewer';
        overlay.style.cssText = `position:fixed;top:0;left:0;width:100%;min-height:100vh;background:#0f172a;color:#e2e8f0;z-index:999999;overflow-y:auto;padding:20px;font-family:system-ui;`;

        const isPRO = variant === 'tb-pro';
        let html = `<div style="max-width:900px;margin:0 auto;">
            <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
                <h2 style="color:${isPRO ? '#facc15' : '#38bdf8'};margin:0;">${isPRO ? '🔒 PRO Test — Questions Only' : '📝 Test — Full Access'}</h2>
                <button id="rm-close" style="background:#ef4444;color:white;border:0;padding:6px 12px;border-radius:6px;cursor:pointer;">✕</button>
            </div>`;

        if (isPRO && !submitted) {
            html += `<div style="background:#7f1d1d;padding:12px;border-radius:8px;margin-bottom:16px;color:#fca5a5;">
                ⚠ This is a PRO test. Your account doesn't have PRO access. Showing questions only — answers/solutions/rank require a paid plan.
            </div>`;
        }

        if (analysisData) {
            const ts = analysisData.ts || {};
            const an = analysisData.analysis || {};
            html += `<div style="background:#1e293b;padding:12px;border-radius:8px;margin-bottom:16px;">
                <h4 style="color:#4ade80;margin:0 0 8px;">📈 Analysis</h4>
                <div>Rank: <b style="color:#facc15;">${ts.rank||'N/A'}</b> | Percentile: <b style="color:#facc15;">${ts.percentile||'N/A'}%</b></div>
                <div>Avg: <b>${(an.avgMarks||0).toFixed(2)}</b> | Students: <b>${an.totalStudents||'N/A'}</b></div>
            </div>`;
        }

        html += `<div id="rm-questions">`;
        questions.forEach((q, i) => {
            const ans = answersData ? answersData[q.id] : null;
            const correct = ans ? ans.correctOption : null;
            const solEn = ans?.sol?.en?.value || (typeof ans?.sol?.en === 'string' ? ans.sol.en : '') || '';
            const qText = thoroughUnescape(q.textEn);

            html += `<div style="background:#1e293b;padding:12px;border-radius:6px;margin-bottom:8px;border-left:3px solid ${correct ? '#4ade80' : '#64748b'};">
                <div style="font-weight:bold;margin-bottom:6px;">Q${i+1}. ${qText.substring(0,300)}</div>`;
            q.options.forEach((opt, oi) => {
                const isCorrect = correct === (oi + 1);
                html += `<div style="margin-left:16px;color:${isCorrect ? '#4ade80' : '#94a3b8'};${isCorrect ? 'font-weight:bold;' : ''}">${'ABCD'[oi]}. ${thoroughUnescape(opt).substring(0,150)}${isCorrect ? ' ✓' : ''}</div>`;
            });
            if (solEn) {
                html += `<div style="margin-top:4px;padding:4px;background:#0f172a;border-radius:3px;color:#7dd3fc;font-size:11px;">💡 ${thoroughUnescape(solEn).substring(0,400)}</div>`;
            }
            html += `</div>`;
        });
        html += `</div>`;

        if (submitted) {
            html += `<div style="margin-top:16px;display:flex;gap:12px;justify-content:center;">
                <a href="https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}/analysis" style="background:#2563eb;color:white;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">📈 View Full Analysis</a>
            </div>`;
        }

        html += `<button id="rm-download" style="width:100%;background:#2563eb;color:white;border:0;padding:10px;border-radius:6px;cursor:pointer;margin-top:12px;">💾 Download JSON</button>`;
        html += `</div>`;

        overlay.innerHTML = html;

        // Clear page and inject
        document.body.innerHTML = '';
        document.body.appendChild(overlay);

        document.getElementById('rm-close').onclick = () => {
            window.location.href = `https://repeatermock.com/${variant}/test-series/${slug}`;
        };
        document.getElementById('rm-download').onclick = () => {
            const data = { questions, answersData, analysisData, testId, variant, slug };
            const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${testId}.json`; a.click();
            URL.revokeObjectURL(url);
        };

        dbg('✓ UI injected');
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 5: Unlock buttons on series pages (with null checks)
    // ═════════════════════════════════════════════════════════════════════

    const testCache = new Map();

    async function fetchTestIds(variant, slug) {
        const cacheKey = `${variant}/${slug}`;
        if (testCache.has(cacheKey)) return testCache.get(cacheKey);
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';
        const tests = [];
        try {
            const r = await originalFetch(`${API_BASE}${apiPrefix}/test-series/${slug}${variant !== 'gd' ? `?variant=${variant}` : ''}`, { credentials: 'include', headers: { Accept: 'application/json' } });
            const d = await r.json();
            const details = d?.data?.details || d?.details;
            if (!details?.id) return [];
            for (const sec of details.sections || []) {
                const subs = sec.subsections || [];
                const fetchList = subs.length ? subs.map(s => ({ subId: s.id })) : [{ subId: null }];
                for (const { subId } of fetchList) {
                    let url = `${API_BASE}${apiPrefix}/test-series/${details.id}/sections/${sec.id}/tests?limit=500&offset=0${variant !== 'gd' ? `&variant=${variant}` : ''}`;
                    if (subId) url += `&subSectionId=${subId}`;
                    const tr = await originalFetch(url, { credentials: 'include', headers: { Accept: 'application/json' } });
                    if (tr.ok) {
                        const td = await tr.json();
                        for (const t of td.data || []) tests.push({ id: t.id, title: t.title });
                    }
                }
            }
            dbg(`Fetched ${tests.length} tests for ${cacheKey}`);
        } catch(e) { dbg('Fetch tests error:', e.message); }
        testCache.set(cacheKey, tests);
        return tests;
    }

    async function unlockTests() {
        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)/);
        if (!m) return;
        const variant = m[1], slug = m[2];
        const tests = await fetchTestIds(variant, slug);
        if (!tests.length) return;

        const titleToId = new Map();
        for (const t of tests) titleToId.set(t.title.toLowerCase().trim(), t.id);

        let unlocked = 0;
        const btns = document.querySelectorAll('button, a, span, div');
        for (const btn of btns) {
            if (!btn || !btn.parentNode) continue;  // NULL CHECK — fixes the crash
            const text = (btn.textContent || '').trim();
            if (text !== 'Unlock') continue;

            let card = btn.parentElement;
            let found = false;
            for (let i = 0; i < 8 && card && !found; i++) {
                const cardText = (card.textContent || '').toLowerCase();
                for (const [title, id] of titleToId) {
                    if (cardText.includes(title.substring(0, Math.min(title.length, 25)))) {
                        const testUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${id}/attempt`;
                        const newLink = document.createElement('a');
                        newLink.href = testUrl;
                        newLink.innerHTML = '▶ Start Test';
                        newLink.style.cssText = 'display:inline-block;background:#16a34a;color:white !important;padding:8px 16px;border-radius:8px;font-weight:bold;text-decoration:none;cursor:pointer;font-size:14px;border:0;';
                        try {
                            btn.parentNode.replaceChild(newLink, btn);
                            unlocked++;
                        } catch(e) { dbg('Replace error:', e.message); }
                        found = true;
                        break;
                    }
                }
                card = card?.parentElement;
            }
        }
        dbg(`Unlocked ${unlocked} buttons`);
    }

    function addUnlockAllButton() {
        if (document.getElementById('rm-unlock-all-btn')) return;
        if (!window.location.pathname.includes('/test-series/') || window.location.pathname.includes('/test/')) return;
        const btn = document.createElement('button');
        btn.id = 'rm-unlock-all-btn';
        btn.textContent = '🔓 Unlock All Tests';
        btn.style.cssText = 'position:fixed;bottom:20px;right:20px;z-index:999999;background:#16a34a;color:white;border:0;padding:12px 24px;border-radius:12px;font-size:16px;font-weight:bold;cursor:pointer;box-shadow:0 4px 12px rgba(0,0,0,0.3);';
        btn.onclick = async () => {
            btn.textContent = '⏳ Unlocking...';
            await unlockTests();
            setTimeout(unlockTests, 2000);
            btn.textContent = '✓ Unlocked!';
            setTimeout(() => { btn.textContent = '🔓 Unlock All Tests'; }, 3000);
        };
        document.body.appendChild(btn);
    }

    // ═════════════════════════════════════════════════════════════════════
    // INIT
    // ═════════════════════════════════════════════════════════════════════

    async function init() {
        dbg('init on:', window.location.pathname);
        if (window.location.pathname.includes('/test/')) {
            // Test page — let the SPA try, our interceptor handles 402
            const m = window.location.pathname.match(/\/test\/([a-f0-9]+)/);
            if (m) {
                // Wait for SPA to attempt /start (which will trigger our interceptor)
                setTimeout(() => {
                    if (!document.getElementById('rm-viewer')) {
                        injectQuestionViewer(m[1]);
                    }
                }, 4000);
            }
        }
        if (window.location.pathname.includes('/test-series/') && !window.location.pathname.includes('/test/')) {
            addUnlockAllButton();
            await unlockTests();
        }
    }

    let lastUrl = window.location.href;
    const observer = new MutationObserver(() => {
        if (window.location.href !== lastUrl) {
            lastUrl = window.location.href;
            setTimeout(init, 2000);
        }
    });
    if (document.body) observer.observe(document.body, { childList: true, subtree: true });
    setTimeout(init, 2000);
    setTimeout(init, 5000);
    window.addEventListener('popstate', () => setTimeout(init, 2000));
    dbg('v8 loaded');
})();
