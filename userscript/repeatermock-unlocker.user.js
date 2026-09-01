// ==UserScript==
// @name         RepeaterMock PRO Unlocker — Take Any Test (Free or PRO)
// @namespace    https://repeatermock.com
// @version      4.0
// @description  Unlocks ALL tests (free + PRO) so you can take them directly on the website. Bypasses the "Unlock" button. Take the test normally → get score → see solutions → see rank & analysis. Works with FREE accounts.
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
        if (DEBUG) console.log('%c[RM Unlock]', 'color:#facc15;font-weight:bold', ...args);
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 1: On series pages — make locked tests clickable
    // ═════════════════════════════════════════════════════════════════════

    function unlockTestButtons() {
        // Find all test items that have "Unlock" or "PRO" badges
        // RepeaterMock renders test cards with buttons/links
        const allElements = document.querySelectorAll('a, button, [role="button"], [class*="test"], [class*="card"]');

        allElements.forEach(el => {
            const text = (el.textContent || '').toLowerCase().trim();
            const href = el.getAttribute('href') || '';

            // If this element contains "unlock" text
            if (text === 'unlock' || text.includes('unlock') || text.includes('🔒')) {
                // Find the parent test card
                let card = el.closest('[class*="card"]') || el.closest('[class*="test"]') || el.parentElement;
                if (card && !card.dataset.rmUnlocked) {
                    card.dataset.rmUnlocked = '1';
                    dbg('Found locked test card:', card.textContent.substring(0, 80));

                    // Find the test ID from any link in the card
                    const testLink = card.querySelector('a[href*="/test/"]');
                    if (testLink) {
                        const testHref = testLink.getAttribute('href');
                        dbg('Test URL found:', testHref);

                        // Replace the "Unlock" button with a "Start Test" link
                        el.outerHTML = `<a href="${testHref}" class="rm-unlock-btn" style="
                            display:inline-block; background:#16a34a; color:white;
                            padding:8px 16px; border-radius:8px; font-weight:bold;
                            text-decoration:none; cursor:pointer; font-size:14px;
                        ">▶ Start Test</a>`;
                        dbg('✓ Replaced Unlock button with Start Test link');
                    }
                }
            }
        });

        // Also: find any test links that are disabled/grayed out
        document.querySelectorAll('a[href*="/test/"]').forEach(link => {
            if (link.style.pointerEvents === 'none' || link.style.opacity === '0.5' || link.hasAttribute('disabled')) {
                link.style.pointerEvents = 'auto';
                link.style.opacity = '1';
                link.removeAttribute('disabled');
                dbg('✓ Re-enabled disabled test link:', link.href);
            }
        });
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 2: On test pages — ensure the test UI renders (bypass paywall)
    // ═════════════════════════════════════════════════════════════════════

    async function ensureTestRenders() {
        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)\/test\/([a-f0-9]+)/);
        if (!m) return;

        const variant = m[1];
        const slug = m[2];
        const testId = m[3];
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';

        dbg('On test page:', { variant, slug, testId });

        // Check if page shows "Unlock" or payment prompt
        const bodyText = document.body ? document.body.innerText : '';
        if (bodyText.includes('Unlock') || bodyText.includes('Subscribe') || bodyText.includes('Upgrade')) {
            dbg('⚠ Paywall detected — auto-starting attempt to bypass...');

            // Call /start API directly (free accounts CAN start PRO tests)
            try {
                const resp = await fetch(`${API_BASE}${apiPrefix}/attempts/${testId}/start`, {
                    method: 'POST',
                    credentials: 'include',
                    headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                    body: '{}',
                });
                const data = await resp.json();
                dbg('Start attempt response:', data);

                if (data.success) {
                    dbg('✓ Attempt started — reloading page to show test UI...');
                    // Reload the page — now the server knows we have an active attempt
                    window.location.reload();
                    return;
                } else if (data.code === 'payment_required') {
                    dbg('✗ Payment required — trying alternative...');
                    // Try starting without variant param
                    const resp2 = await fetch(`${API_BASE}/api/v1/attempts/${testId}/start`, {
                        method: 'POST', credentials: 'include',
                        headers: { 'Content-Type': 'application/json' }, body: '{}',
                    });
                    const data2 = await resp2.json();
                    dbg('Retry response:', data2);
                    if (data2.success) {
                        window.location.reload();
                        return;
                    }
                }
            } catch (e) {
                dbg('Start error:', e.message);
            }
        }

        // If we're on /attempt page and questions aren't visible, inject them
        if (window.location.pathname.includes('/attempt')) {
            await injectTestUI(testId, variant, slug, apiPrefix);
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 3: Inject test UI if the page is blank/paywalled
    // ═════════════════════════════════════════════════════════════════════

    async function injectTestUI(testId, variant, slug, apiPrefix) {
        // Wait for page to load
        await new Promise(r => setTimeout(r, 3000));

        // Check if test questions are already visible
        const existingQuestions = document.querySelectorAll('[class*="question"], [class*="Question"]');
        if (existingQuestions.length > 0) {
            dbg('Test UI already rendered — no injection needed');
            return;
        }

        dbg('Test UI not visible — fetching questions and injecting...');

        // Fetch the /attempt page HTML
        const baseUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}`;
        try {
            const resp = await fetch(`${baseUrl}/attempt`, { credentials: 'include' });
            const html = await resp.text();

            // Extract RSC payload
            let payload = '';
            const matches = html.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
            for (const match of matches) {
                let chunk = match[1];
                chunk = chunk.replace(/\\n/g, '\n').replace(/\\r/g, '\r')
                             .replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                payload += chunk;
            }

            // Parse questions
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

            dbg(`Found ${questions.length} questions in RSC payload`);

            if (questions.length === 0) {
                dbg('No questions found — page may require login');
                return;
            }

            // Build a simple test UI
            const testUI = document.createElement('div');
            testUI.id = 'rm-injected-test';
            testUI.style.cssText = `
                position:fixed; top:0; left:0; width:100%; height:100vh;
                background:#0f172a; color:#e2e8f0; z-index:99999;
                overflow-y:auto; padding:20px; font-family:system-ui;
            `;

            let html2 = `<div style="max-width:800px;margin:0 auto;">
                <h2 style="color:#38bdf8;">📝 Test (Injected by RM Unlocker)</h2>
                <p style="color:#94a3b8;">${questions.length} questions</p>`;

            questions.forEach((q, i) => {
                let textEn = '';
                if (q.text) {
                    if (typeof q.text.en === 'string') textEn = q.text.en;
                    else if (q.text.en && q.text.en.value) textEn = q.text.en.value;
                }
                const options = q.options || [];
                html2 += `<div style="background:#1e293b;padding:16px;border-radius:8px;margin-bottom:12px;">
                    <div style="font-weight:bold;margin-bottom:8px;">Q${i+1}. ${textEn}</div>`;
                options.forEach((opt, oi) => {
                    let optEn = '';
                    if (typeof opt.en === 'string') optEn = opt.en;
                    else if (opt.en && opt.en.value) optEn = opt.en.value;
                    html2 += `<label style="display:block;padding:8px;cursor:pointer;border-radius:4px;" onmouseover="this.style.background='#334155'" onmouseout="this.style.background='transparent'">
                        <input type="radio" name="q${i}" value="${oi+1}" style="margin-right:8px;">
                        ${'ABCD'[oi]}. ${optEn}
                    </label>`;
                });
                html2 += `</div>`;
            });

            html2 += `<button id="rm-submit-test" style="background:#16a34a;color:white;border:0;padding:12px 24px;border-radius:8px;font-size:16px;cursor:pointer;width:100%;">Submit Test</button>
            <div id="rm-results"></div>
            </div>`;

            testUI.innerHTML = html2;
            document.body.innerHTML = '';
            document.body.appendChild(testUI);

            // Handle submit
            document.getElementById('rm-submit-test').onclick = async () => {
                const answers = [];
                questions.forEach((q, i) => {
                    const selected = document.querySelector(`input[name="q${i}"]:checked`);
                    answers.push({
                        questionId: q._id || q.id,
                        selectedOption: selected ? parseInt(selected.value) : null,
                        markedForReview: false,
                        timeSpent: 0,
                    });
                });

                dbg('Submitting answers:', answers);

                // Start attempt first
                const startResp = await fetch(`${API_BASE}${apiPrefix}/attempts/${testId}/start`, {
                    method: 'POST', credentials: 'include',
                    headers: { 'Content-Type': 'application/json' }, body: '{}',
                });
                const startData = await startResp.json();
                dbg('Start:', startData);

                // Submit
                const submitResp = await fetch(`${API_BASE}${apiPrefix}/attempts/${testId}/submit`, {
                    method: 'POST', credentials: 'include',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ answers, timeTaken: 600, language: 'en', interface: 'classic' }),
                });
                const submitData = await submitResp.json();
                dbg('Submit:', submitData);

                if (submitData.success) {
                    // Fetch solutions
                    const solResp = await fetch(`${baseUrl}/solution`, { credentials: 'include' });
                    const solHtml = await solResp.text();
                    let solPayload = '';
                    const solMatches = solHtml.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
                    for (const match of solMatches) {
                        let chunk = match[1];
                        chunk = chunk.replace(/\\n/g, '\n').replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                        solPayload += chunk;
                    }

                    // Extract answersData
                    const ansIdx = solPayload.indexOf('"answersData":{');
                    let answersData = null;
                    if (ansIdx >= 0) {
                        let startIdx = solPayload.indexOf('{', ansIdx + 14);
                        let depth = 0, inStr = false, esc = false;
                        for (let j = startIdx; j < solPayload.length; j++) {
                            const c = solPayload[j];
                            if (esc) { esc = false; continue; }
                            if (c === '\\') { esc = true; continue; }
                            if (c === '"') { inStr = !inStr; continue; }
                            if (inStr) continue;
                            if (c === '{') depth++;
                            else if (c === '}') {
                                depth--;
                                if (depth === 0) {
                                    try { answersData = JSON.parse(solPayload.substring(startIdx, j + 1)); }
                                    catch (e) {}
                                    break;
                                }
                            }
                        }
                    }

                    // Show results
                    const resultsDiv = document.getElementById('rm-results');
                    if (answersData) {
                        let score = 0;
                        let resultHtml = '<h3 style="color:#4ade80;margin-top:20px;">📊 Results & Solutions</h3>';
                        questions.forEach((q, i) => {
                            const ans = answersData[q._id || q.id];
                            const correct = ans ? ans.correctOption : null;
                            const userAns = answers[i] ? answers[i].selectedOption : null;
                            const isCorrect = correct === userAns;
                            if (isCorrect) score++;

                            let textEn = '';
                            if (q.text) {
                                if (typeof q.text.en === 'string') textEn = q.text.en;
                                else if (q.text.en && q.text.en.value) textEn = q.text.en.value;
                            }
                            const solEn = ans?.sol?.en?.value || (typeof ans?.sol?.en === 'string' ? ans.sol.en : '') || '';

                            resultHtml += `<div style="background:${isCorrect ? '#166534' : '#7f1d1d'};padding:12px;border-radius:6px;margin-bottom:8px;">
                                <div style="font-weight:bold;">Q${i+1}. ${textEn.substring(0,200)} ${isCorrect ? '✅' : '❌'}</div>
                                <div style="margin-top:4px;">Your answer: ${userAns ? 'ABCD'[userAns-1] : 'Not answered'}</div>
                                <div style="color:#4ade80;">Correct answer: ${correct ? 'ABCD'[correct-1] : 'N/A'}</div>
                                ${solEn ? `<div style="margin-top:4px;padding:8px;background:#0f172a;border-radius:4px;color:#7dd3fc;">💡 ${solEn.substring(0,400)}</div>` : ''}
                            </div>`;
                        });
                        resultHtml += `<div style="text-align:center;font-size:24px;color:#facc15;margin:20px;">Score: ${score}/${questions.length}</div>`;
                        resultHtml += `<a href="${baseUrl}/analysis" style="display:block;text-align:center;background:#2563eb;color:white;padding:12px;border-radius:8px;text-decoration:none;">View Full Analysis →</a>`;
                        resultsDiv.innerHTML = resultHtml;
                        resultsDiv.scrollIntoView();
                    }
                }
            };

            dbg('✓ Test UI injected');
        } catch (e) {
            dbg('Injection error:', e.message);
        }
    }

    // ═════════════════════════════════════════════════════════════════════
    // PART 4: Add a floating "Unlock All" button on series pages
    // ═════════════════════════════════════════════════════════════════════

    function addUnlockAllButton() {
        if (document.getElementById('rm-unlock-all-btn')) return;

        // Only on series pages
        if (!window.location.pathname.includes('/test-series/')) return;

        const btn = document.createElement('button');
        btn.id = 'rm-unlock-all-btn';
        btn.textContent = '🔓 Unlock All Tests';
        btn.style.cssText = `
            position:fixed; bottom:20px; right:20px; z-index:99999;
            background:#16a34a; color:white; border:0; padding:12px 24px;
            border-radius:12px; font-size:16px; font-weight:bold; cursor:pointer;
            box-shadow:0 4px 12px rgba(0,0,0,0.3);
        `;
        btn.onclick = () => {
            dbg('Unlocking all tests...');
            unlockTestButtons();
            // Re-run after 2s (SPA might re-render)
            setTimeout(unlockTestButtons, 2000);
            setTimeout(unlockTestButtons, 5000);
            btn.textContent = '✓ Tests Unlocked!';
            setTimeout(() => { btn.textContent = '🔓 Unlock All Tests'; }, 3000);
        };
        document.body.appendChild(btn);
        dbg('Unlock All button added');
    }

    // ═════════════════════════════════════════════════════════════════════
    // INIT
    // ═════════════════════════════════════════════════════════════════════

    function init() {
        dbg('v4 initialized on:', window.location.pathname);
        unlockTestButtons();
        addUnlockAllButton();
        ensureTestRenders();
    }

    // Run on load + on SPA navigation
    let lastUrl = window.location.href;
    const observer = new MutationObserver(() => {
        if (window.location.href !== lastUrl) {
            lastUrl = window.location.href;
            dbg('URL changed:', lastUrl);
            setTimeout(init, 1500);
        }
    });

    if (document.body) {
        observer.observe(document.body, { childList: true, subtree: true });
    }

    // Initial run
    setTimeout(init, 2000);
    setTimeout(init, 5000);

    window.addEventListener('popstate', () => setTimeout(init, 1500));

    dbg('Script loaded — waiting for page...');
})();
