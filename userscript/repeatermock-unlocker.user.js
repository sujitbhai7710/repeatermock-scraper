// ==UserScript==
// @name         RepeaterMock PRO Unlocker — Take Any Test (Free or PRO)
// @namespace    https://repeatermock.com
// @version      6.0
// @description  Intercepts the 402 Payment Required response and prevents redirect to /pricing. Renders test UI from RSC payload. Take the test normally → submit → see results + solutions + rank.
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
        if (DEBUG) console.log('%c[RM v6]', 'color:#facc15;font-weight:bold', ...args);
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 1: Intercept fetch — block 402 redirect to /pricing
    // ═════════════════════════════════════════════════════════════════════

    const originalFetch = window.fetch;
    let blockedRedirect = false;
    let lastTestId = null;
    let lastVariant = null;
    let lastSlug = null;

    window.fetch = async function(...args) {
        const url = typeof args[0] === 'string' ? args[0] : (args[0]?.url || '');
        const options = args[1] || {};

        const resp = await originalFetch.apply(this, args);

        // Intercept /start attempts that return 402
        if (url.includes('/attempts/') && url.includes('/start') && resp.status === 402) {
            dbg('⚠ Intercepted 402 Payment Required from /start:', url);

            const match = url.match(/\/attempts\/([a-f0-9]+)\/start/);
            if (match) {
                lastTestId = match[1];
                dbg('Test ID:', lastTestId);
            }

            const fakeResponse = {
                success: true,
                data: {
                    attemptId: 'rm_unlocked_' + Date.now(),
                    timeLeft: 3600,
                    status: 'in_progress',
                    resuming: false
                }
            };

            dbg('✓ Returning fake success response to prevent /pricing redirect');
            return new Response(JSON.stringify(fakeResponse), {
                status: 200,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        // Intercept /responses — the SPA tries to POST answer saves here, gets 404
        // Return fake success to stop the error spam
        if (url.includes('/attempts/') && url.includes('/responses')) {
            dbg('⚠ Intercepted /responses call (fake success to prevent 404 spam)');
            return new Response(JSON.stringify({ success: true, data: {} }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        // Intercept /submit — return fake success
        if (url.includes('/attempts/') && url.includes('/submit')) {
            if (resp.status === 404 || resp.status === 402) {
                dbg('⚠ Intercepted /submit error — returning fake success');
                return new Response(JSON.stringify({
                    success: true,
                    data: { attemptId: 'rm_unlocked_' + Date.now() }
                }), {
                    status: 200,
                    headers: { 'Content-Type': 'application/json' }
                });
            }
        }

        // Intercept /save-question — return fake success
        if (url.includes('/save-question')) {
            return new Response(JSON.stringify({ success: true }), {
                status: 200,
                headers: { 'Content-Type': 'application/json' }
            });
        }

        return resp;
    };

    // Also intercept XMLHttpRequest (some RepeaterMock calls use XHR)
    const originalXHROpen = XMLHttpRequest.prototype.open;
    const originalXHRSend = XMLHttpRequest.prototype.send;
    XMLHttpRequest.prototype.open = function(method, url, ...rest) {
        this._rmUrl = url;
        this._rmMethod = method;
        return originalXHROpen.apply(this, [method, url, ...rest]);
    };
    XMLHttpRequest.prototype.send = function(body) {
        this.addEventListener('load', function() {
            if (this._rmUrl && this._rmUrl.includes('/responses')) {
                dbg('⚠ XHR /responses intercepted');
            }
        });
        // If this is a /responses or /save-question call, fake the response
        if (this._rmUrl && (this._rmUrl.includes('/responses') || this._rmUrl.includes('/save-question'))) {
            Object.defineProperty(this, 'status', { value: 200, writable: false });
            Object.defineProperty(this, 'responseText', { value: '{"success":true,"data":{}}', writable: false });
            Object.defineProperty(this, 'readyState', { value: 4, writable: false });
            setTimeout(() => {
                if (this.onreadystatechange) this.onreadystatechange();
                if (this.onload) this.onload();
            }, 10);
            return;
        }
        return originalXHRSend.apply(this, [body]);
    };

    // Also intercept history.pushState + replaceState to block /pricing navigation
    const originalPushState = history.pushState;
    history.pushState = function(state, title, url) {
        if (url && typeof url === 'string' && url.includes('/pricing')) {
            dbg('🚫 Blocked pushState to /pricing:', url);
            blockedRedirect = true;
            setTimeout(() => {
                dbg('Triggering test UI injection after blocked redirect...');
                injectTestUI();
            }, 500);
            return;
        }
        return originalPushState.apply(this, arguments);
    };

    const originalReplaceState = history.replaceState;
    history.replaceState = function(state, title, url) {
        if (url && typeof url === 'string' && url.includes('/pricing')) {
            dbg('🚫 Blocked replaceState to /pricing');
            return;
        }
        return originalReplaceState.apply(this, arguments);
    };

    dbg('Fetch + pushState + replaceState interceptors installed');

    // Inject CSS to hide RepeaterMock's payment modals + popups
    const style = document.createElement('style');
    style.textContent = `
        /* Hide pricing/payment modals */
        [class*="modal"][class*="payment"],
        [class*="modal"][class*="pricing"],
        [class*="Modal"][class*="Payment"],
        [class*="Modal"][class*="Pricing"],
        [class*="paywall"],
        [class*="Paywall"],
        [class*="upgrade"],
        [class*="Upgrade"],
        [class*="unlock-modal"],
        [class*="UnlockModal"],
        div[class*="overlay"][class*="payment"],
        div[role="dialog"][class*="payment"],
        div[role="dialog"][class*="pricing"],
        div[role="dialog"][class*="upgrade"],
        [class*="toast"][class*="error"],
        [class*="Toast"][class*="Error"],
        [class*="snackbar"][class*="error"],
        [class*="Snackbar"][class*="Error"],
        [class*="alert"][class*="error"],
        [class*="Alert"][class*="Error"] {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            pointer-events: none !important;
        }
        /* Keep our injected UI visible */
        #rm-test-container,
        #rm-test-container * {
            display: revert !important;
            visibility: visible !important;
            opacity: 1 !important;
            pointer-events: auto !important;
        }
    `;
    (document.head || document.documentElement).appendChild(style);
    dbg('Modal-hiding CSS injected');

    // ═════════════════════════════════════════════════════════════════════
    // PART 2: Extract questions from RSC payload
    // ═════════════════════════════════════════════════════════════════════

    function thoroughUnescape(text) {
        if (!text) return '';
        let result = text;
        for (let i = 0; i < 3; i++) {
            const tmp = document.createElement('div');
            tmp.innerHTML = result;
            const unescaped = tmp.textContent || tmp.innerText;
            if (unescaped === result) break;
            result = unescaped;
        }
        return result;
    }

    function extractPayload() {
        let payload = '';
        const scripts = document.querySelectorAll('script');
        for (const script of scripts) {
            const text = script.textContent || '';
            const matches = text.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
            for (const match of matches) {
                let chunk = match[1];
                chunk = chunk.replace(/\\n/g, '\n').replace(/\\r/g, '\r')
                             .replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                payload += chunk;
            }
        }
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
            else if (c === '}') {
                depth--;
                if (depth === 0) {
                    try { return JSON.parse(payload.substring(start, j + 1)); }
                    catch (e) { return null; }
                }
            }
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
            let depth = 0, inStr = false, esc = false;
            let start = idx;
            for (let j = idx; j < payload.length; j++) {
                const c = payload[j];
                if (esc) { esc = false; continue; }
                if (c === '\\') { esc = true; continue; }
                if (c === '"') { inStr = !inStr; continue; }
                if (inStr) continue;
                if (c === '{') depth++;
                else if (c === '}') {
                    depth--;
                    if (depth === 0) {
                        try { questions.push(JSON.parse(payload.substring(start, j + 1))); }
                        catch (e) {}
                        break;
                    }
                }
            }
            idx += 1;
        }
        return questions;
    }

    function cleanQuestion(q) {
        const id = q._id || q.id || '';
        let textEn = '', textHi = '';
        if (q.text) {
            if (typeof q.text.en === 'string') textEn = q.text.en;
            else if (q.text.en && q.text.en.value) textEn = q.text.en.value;
            if (typeof q.text.hi === 'string') textHi = q.text.hi;
            else if (q.text.hi && q.text.hi.value) textHi = q.text.hi.value;
        }
        const options = (q.options || []).map(o => {
            let en = '', hi = '';
            if (typeof o.en === 'string') en = o.en;
            else if (o.en && o.en.value) en = o.en.value;
            if (typeof o.hi === 'string') hi = o.hi;
            else if (o.hi && o.hi.value) hi = o.hi.value;
            return { en, hi };
        });
        return { id, type: q.type || 'mcq', marks: q.marks || 1, textEn, textHi, options };
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 3: Inject full test UI
    // ═════════════════════════════════════════════════════════════════════

    async function injectTestUI() {
        // Don't inject twice
        if (document.getElementById('rm-test-container')) return;

        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)\/test\/([a-f0-9]+)/);
        if (!m) return;

        const variant = m[1];
        const slug = m[2];
        const testId = m[3];
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';
        const baseUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}`;

        dbg('Injecting test UI for:', { variant, slug, testId });

        // Try to extract questions from current page first
        let payload = extractPayload();
        let questions = parseQuestions(payload).map(cleanQuestion);

        // If no questions, fetch /attempt page
        if (questions.length === 0) {
            dbg('No questions on current page — fetching /attempt...');
            try {
                const resp = await originalFetch(`${baseUrl}/attempt`, { credentials: 'include' });
                const html = await resp.text();
                // Extract payload from fetched HTML
                const matches = html.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
                for (const match of matches) {
                    let chunk = match[1];
                    chunk = chunk.replace(/\\n/g, '\n').replace(/\\r/g, '\r')
                                 .replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                    payload += chunk;
                }
                questions = parseQuestions(payload).map(cleanQuestion);
            } catch (e) {
                dbg('Fetch /attempt error:', e.message);
            }
        }

        dbg(`Found ${questions.length} questions`);
        if (questions.length === 0) {
            dbg('No questions found — cannot inject test UI');
            return;
        }

        // Build test UI
        const container = document.createElement('div');
        container.id = 'rm-test-container';
        container.style.cssText = `
            position:fixed; top:0; left:0; width:100%; min-height:100vh;
            background:#0f172a; color:#e2e8f0; z-index:999999;
            overflow-y:auto; padding:20px; font-family:system-ui, -apple-system, sans-serif;
        `;

        let html = `
            <div style="max-width:900px; margin:0 auto;">
                <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:20px;">
                    <h2 style="color:#38bdf8; margin:0;">📝 Test (Unlocked)</h2>
                    <div>
                        <span id="rm-timer" style="color:#facc15; font-size:18px; font-weight:bold;">⏱ 60:00</span>
                        <button id="rm-close" style="background:#ef4444; color:white; border:0; padding:6px 12px; border-radius:6px; cursor:pointer; margin-left:10px;">✕</button>
                    </div>
                </div>
                <p style="color:#94a3b8;">${questions.length} questions | ${variant.toUpperCase()} | ${slug}</p>
                <div id="rm-questions">
        `;

        const userAnswers = {};

        questions.forEach((q, i) => {
            const qText = thoroughUnescape(q.textEn);
            html += `
                <div class="rm-question" style="background:#1e293b; padding:16px; border-radius:8px; margin-bottom:12px;" data-qid="${q.id}" data-idx="${i}">
                    <div style="font-size:15px; font-weight:600; margin-bottom:10px; line-height:1.6;">
                        <span style="color:#38bdf8;">Q${i+1}.</span> ${qText}
                    </div>
                    <div class="rm-options">
            `;
            q.options.forEach((opt, oi) => {
                const optText = thoroughUnescape(opt.en);
                html += `
                    <label style="display:flex; align-items:flex-start; padding:10px; margin:4px 0; border-radius:6px; cursor:pointer; transition:background 0.2s;"
                           onmouseover="this.style.background='#334155'"
                           onmouseout="if(!this.dataset.selected)this.style.background='transparent'">
                        <input type="radio" name="q${i}" value="${oi+1}" style="margin-right:10px; margin-top:3px; transform:scale(1.3);"
                               onchange="document.querySelectorAll('label[for=\\'q${i}\\']').forEach(l=>{l.dataset.selected='';l.style.background='transparent';l.style.border='0';});this.parentElement.dataset.selected='1';this.parentElement.style.background='#1e40af';this.parentElement.style.borderLeft='3px solid #3b82f6';">
                        <span style="font-size:14px;"><b>${'ABCD'[oi]}.</b> ${optText}</span>
                    </label>
                `;
            });
            html += `
                    </div>
                </div>
            `;
        });

        html += `
                </div>
                <div style="position:sticky; bottom:0; background:#0f172a; padding:16px 0; border-top:1px solid #334155;">
                    <button id="rm-submit" style="width:100%; background:#16a34a; color:white; border:0; padding:14px; border-radius:8px; font-size:18px; font-weight:bold; cursor:pointer;">
                        ✓ Submit Test
                    </button>
                </div>
                <div id="rm-results" style="margin-top:20px;"></div>
            </div>
        `;

        container.innerHTML = html;

        // Clear existing page content and inject our UI
        document.body.innerHTML = '';
        document.body.appendChild(container);

        // Timer
        let timeLeft = 3600;
        const timerEl = document.getElementById('rm-timer');
        const timerInterval = setInterval(() => {
            timeLeft--;
            const mins = Math.floor(timeLeft / 60);
            const secs = timeLeft % 60;
            timerEl.textContent = `⏱ ${mins}:${secs.toString().padStart(2,'0')}`;
            if (timeLeft <= 0) {
                clearInterval(timerInterval);
                document.getElementById('rm-submit').click();
            }
        }, 1000);

        // Close button
        document.getElementById('rm-close').onclick = () => {
            if (confirm('Leave test? Your answers will be lost.')) {
                window.location.href = `https://repeatermock.com/${variant}/test-series/${slug}`;
            }
        };

        // Submit button
        document.getElementById('rm-submit').onclick = async () => {
            clearInterval(timerInterval);
            const submitBtn = document.getElementById('rm-submit');
            submitBtn.textContent = '⏳ Submitting...';
            submitBtn.disabled = true;

            // Collect answers
            const answers = [];
            questions.forEach((q, i) => {
                const selected = document.querySelector(`input[name="q${i}"]:checked`);
                answers.push({
                    questionId: q.id,
                    selectedOption: selected ? parseInt(selected.value) : null,
                    markedForReview: false,
                    timeSpent: 0,
                });
            });

            const answered = answers.filter(a => a.selectedOption !== null).length;
            dbg(`Submitting: ${answered}/${questions.length} answered`);

            // Try to start + submit via API
            let submitted = false;
            try {
                // Start attempt (our interceptor will catch 402 and fake success)
                dbg('Starting attempt...');
                const startResp = await originalFetch(`${API_BASE}${apiPrefix}/attempts/${testId}/start`, {
                    method: 'POST', credentials: 'include',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: '{}',
                });
                const startData = await startResp.json();
                dbg('Start:', startData);

                // Submit
                dbg('Submitting answers...');
                const submitResp = await originalFetch(`${API_BASE}${apiPrefix}/attempts/${testId}/submit`, {
                    method: 'POST', credentials: 'include',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: JSON.stringify({ answers, timeTaken: 3600 - timeLeft, language: 'en', interface: 'classic' }),
                });
                const submitData = await submitResp.json();
                dbg('Submit:', submitData);
                submitted = submitData.success;
            } catch (e) {
                dbg('Submit error:', e.message);
            }

            // Fetch solutions (works even if submit failed — for previously attempted tests)
            dbg('Fetching /solution...');
            let answersData = null;
            try {
                const solResp = await originalFetch(`${baseUrl}/solution`, { credentials: 'include' });
                const solHtml = await solResp.text();
                let solPayload = '';
                const matches = solHtml.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
                for (const match of matches) {
                    let chunk = match[1];
                    chunk = chunk.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                    solPayload += chunk;
                }
                answersData = extractJSONObject(solPayload, 'answersData');
                dbg('Answers:', answersData ? `${Object.keys(answersData).length} keys` : 'NONE');
            } catch (e) {
                dbg('Solution fetch error:', e.message);
            }

            // Fetch analysis
            dbg('Fetching /analysis...');
            let analysisData = null;
            try {
                const anaResp = await originalFetch(`${baseUrl}/analysis`, { credentials: 'include' });
                const anaHtml = await anaResp.text();
                let anaPayload = '';
                const matches = anaHtml.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
                for (const match of matches) {
                    let chunk = match[1];
                    chunk = chunk.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                    anaPayload += chunk;
                }
                analysisData = extractJSONObject(anaPayload, 'analysisData');
                dbg('Analysis:', analysisData ? 'YES' : 'NO');
            } catch (e) {
                dbg('Analysis fetch error:', e.message);
            }

            // Display results
            displayResults(questions, answers, answersData, analysisData, baseUrl);
        };

        dbg('✓ Test UI injected');
    }

    function displayResults(questions, userAnswers, answersData, analysisData, baseUrl) {
        const resultsDiv = document.getElementById('rm-results');
        let score = 0;
        let correctCount = 0;
        let attempted = 0;

        let html = '<h3 style="color:#4ade80; margin-top:20px;">📊 Results & Solutions</h3>';

        if (analysisData) {
            const ts = analysisData.ts || {};
            const an = analysisData.analysis || {};
            html += `
                <div style="background:#1e293b; padding:16px; border-radius:8px; margin-bottom:16px;">
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:12px;">
                        <div><span style="color:#94a3b8;">Rank:</span> <b style="color:#facc15; font-size:20px;">${ts.rank || 'N/A'}</b></div>
                        <div><span style="color:#94a3b8;">Percentile:</span> <b style="color:#facc15; font-size:20px;">${ts.percentile || 'N/A'}%</b></div>
                        <div><span style="color:#94a3b8;">Avg Marks:</span> <b>${(an.avgMarks || 0).toFixed(2)}</b></div>
                        <div><span style="color:#94a3b8;">Total Students:</span> <b>${an.totalStudents || 'N/A'}</b></div>
                    </div>
                </div>
            `;
        }

        questions.forEach((q, i) => {
            const ans = answersData ? answersData[q.id] : null;
            const correct = ans ? ans.correctOption : null;
            const userAns = userAnswers[i] ? userAnswers[i].selectedOption : null;
            const isCorrect = correct && userAns && correct === userAns;
            const isAttempted = userAns !== null;

            if (isCorrect) { score++; correctCount++; }
            if (isAttempted) attempted++;

            const qText = thoroughUnescape(q.textEn);
            const solEn = ans?.sol?.en?.value || (typeof ans?.sol?.en === 'string' ? ans.sol.en : '') || '';

            let status = '⬜ Not Attempted';
            let bgColor = '#1e293b';
            if (isCorrect) { status = '✅ Correct'; bgColor = '#166534'; }
            else if (isAttempted) { status = '❌ Wrong'; bgColor = '#7f1d1d'; }

            html += `
                <div style="background:${bgColor}; padding:12px; border-radius:6px; margin-bottom:8px;">
                    <div style="font-weight:bold; margin-bottom:6px;">Q${i+1}. ${qText.substring(0,300)}</div>
                    <div style="margin-bottom:4px;">${status}</div>
            `;
            q.options.forEach((opt, oi) => {
                const optText = thoroughUnescape(opt.en);
                const isCorrectOpt = correct === (oi + 1);
                const isUserOpt = userAns === (oi + 1);
                let prefix = '   ';
                let color = '#94a3b8';
                if (isCorrectOpt) { prefix = '✓ '; color = '#4ade80'; }
                if (isUserOpt && !isCorrectOpt) { prefix = '✗ '; color = '#f87171'; }
                if (isUserOpt && isCorrectOpt) { prefix = '✓ '; color = '#4ade80'; }
                html += `<div style="color:${color}; margin-left:16px;">${prefix}${'ABCD'[oi]}. ${optText.substring(0,150)}</div>`;
            });
            if (solEn) {
                const solText = thoroughUnescape(solEn);
                html += `<div style="margin-top:8px; padding:8px; background:#0f172a; border-radius:4px; color:#7dd3fc; font-size:13px;">💡 <b>Solution:</b> ${solText.substring(0,500)}</div>`;
            }
            html += `</div>`;
        });

        html += `
            <div style="text-align:center; margin:24px 0;">
                <div style="font-size:32px; color:#facc15; font-weight:bold;">Score: ${correctCount}/${questions.length}</div>
                <div style="color:#94a3b8; margin-top:8px;">Attempted: ${attempted} | Correct: ${correctCount} | Wrong: ${attempted - correctCount}</div>
            </div>
            <div style="display:flex; gap:12px; justify-content:center;">
                <a href="${baseUrl}/analysis" style="background:#2563eb; color:white; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:bold;">📈 View Full Analysis</a>
                <a href="${baseUrl}/solution" style="background:#7c3aed; color:white; padding:12px 24px; border-radius:8px; text-decoration:none; font-weight:bold;">📖 View Solutions</a>
            </div>
        `;

        resultsDiv.innerHTML = html;
        resultsDiv.scrollIntoView({ behavior: 'smooth' });

        dbg(`Results displayed: ${correctCount}/${questions.length} correct`);
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 4: On series pages — unlock buttons
    // ═════════════════════════════════════════════════════════════════════

    const testCache = new Map();

    async function fetchTestIds(variant, slug) {
        const cacheKey = `${variant}/${slug}`;
        if (testCache.has(cacheKey)) return testCache.get(cacheKey);

        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';
        const tests = [];

        try {
            const seriesResp = await originalFetch(`${API_BASE}${apiPrefix}/test-series/${slug}${variant !== 'gd' ? `?variant=${variant}` : ''}`, {
                credentials: 'include', headers: { 'Accept': 'application/json' },
            });
            const seriesData = await seriesResp.json();
            const details = seriesData?.data?.details || seriesData?.details;
            if (!details || !details.id) return [];

            dbg(`Fetching tests for: ${details.name}`);

            for (const sec of details.sections || []) {
                const subs = sec.subsections || [];
                if (subs.length === 0) {
                    const url = `${API_BASE}${apiPrefix}/test-series/${details.id}/sections/${sec.id}/tests?limit=500&offset=0${variant !== 'gd' ? `&variant=${variant}` : ''}`;
                    const r = await originalFetch(url, { credentials: 'include', headers: { 'Accept': 'application/json' } });
                    if (r.ok) {
                        const d = await r.json();
                        for (const t of d.data || []) tests.push({ id: t.id, title: t.title });
                    }
                } else {
                    for (const sub of subs) {
                        const url = `${API_BASE}${apiPrefix}/test-series/${details.id}/sections/${sec.id}/tests?limit=500&offset=0${variant !== 'gd' ? `&variant=${variant}` : ''}&subSectionId=${sub.id}`;
                        const r = await originalFetch(url, { credentials: 'include', headers: { 'Accept': 'application/json' } });
                        if (r.ok) {
                            const d = await r.json();
                            for (const t of d.data || []) tests.push({ id: t.id, title: t.title });
                        }
                    }
                }
            }
            dbg(`✓ Fetched ${tests.length} tests`);
        } catch (e) {
            dbg('Fetch tests error:', e.message);
        }

        testCache.set(cacheKey, tests);
        return tests;
    }

    async function unlockTests() {
        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)/);
        if (!m) return;

        const variant = m[1];
        const slug = m[2];
        const tests = await fetchTestIds(variant, slug);
        if (tests.length === 0) return;

        const titleToId = new Map();
        for (const t of tests) {
            titleToId.set(t.title.toLowerCase().trim(), t.id);
        }

        let unlocked = 0;
        const allBtns = document.querySelectorAll('button, a, span, div');

        for (const btn of allBtns) {
            const text = (btn.textContent || '').trim();
            if (text !== 'Unlock') continue;

            let card = btn.parentElement;
            for (let i = 0; i < 8 && card; i++) {
                const cardText = (card.textContent || '').toLowerCase();
                for (const [title, id] of titleToId) {
                    if (cardText.includes(title.substring(0, Math.min(title.length, 25)))) {
                        const testUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${id}/attempt`;
                        const newLink = document.createElement('a');
                        newLink.href = testUrl;
                        newLink.innerHTML = '▶ Start Test';
                        newLink.style.cssText = 'display:inline-block; background:#16a34a; color:white !important; padding:8px 16px; border-radius:8px; font-weight:bold; text-decoration:none; cursor:pointer; font-size:14px; border:0;';
                        btn.parentNode.replaceChild(newLink, btn);
                        unlocked++;
                        dbg(`✓ Unlocked: ${title.substring(0, 30)}`);
                        break;
                    }
                }
                card = card.parentElement;
            }
        }
        dbg(`Unlocked ${unlocked} buttons`);
    }

    function addUnlockAllButton() {
        if (document.getElementById('rm-unlock-all-btn')) return;
        if (!window.location.pathname.includes('/test-series/')) return;
        if (window.location.pathname.includes('/test/')) return;

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

        // On test pages — inject UI (our fetch interceptor blocks the /pricing redirect)
        if (window.location.pathname.includes('/test/')) {
            // Wait for page to render, then inject
            setTimeout(injectTestUI, 3000);
            setTimeout(injectTestUI, 5000);
        }

        // On series pages — unlock buttons
        if (window.location.pathname.includes('/test-series/') && !window.location.pathname.includes('/test/')) {
            addUnlockAllButton();
            await unlockTests();
        }

        // If we got redirected to /pricing, go back to the test page
        if (window.location.pathname.includes('/pricing') && lastTestId) {
            dbg('On /pricing — redirecting back to test...');
            const m = window.location.pathname;
            // Can't know variant/slug from /pricing — use history back
            history.back();
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

    window.addEventListener('popstate', () => setTimeout(init, 2000));

    dbg('v6 loaded — interceptors active');
})();
