// ==UserScript==
// @name         RepeaterMock Unlocker v3 — Free Account PRO Access
// @namespace    https://repeatermock.com
// @version      3.0
// @description  View questions + answers + solutions + analysis on ANY test (free or PRO) using your free account. Bypasses the "Unlock" button by calling the API directly.
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

    function dbg(msg, data) {
        if (DEBUG) {
            console.log(`%c[RM v3] ${msg}`, 'color:#38bdf8;font-weight:bold', data || '');
        }
    }

    function log(msg) {
        console.log(`%c[RM v3] ${msg}`, 'color:#4ade80;font-weight:bold');
    }

    function err(msg) {
        console.error(`%c[RM v3] ERROR: ${msg}`, 'color:#f87171;font-weight:bold');
    }

    dbg('Script loaded on:', window.location.href);
    dbg('Document readyState:', document.readyState);

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

    function extractPayloadFromHTML(html) {
        let payload = '';
        // Method 1: Parse from script tags
        const div = document.createElement('div');
        div.innerHTML = html;
        const scripts = div.querySelectorAll('script');
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
        // Method 2: Raw regex on HTML string
        if (!payload) {
            const matches = html.matchAll(/self\.__next_f\.push\(\[1,"((?:[^"\\]|\\.)*)"\]\)/g);
            for (const match of matches) {
                let chunk = match[1];
                chunk = chunk.replace(/\\n/g, '\n').replace(/\\r/g, '\r')
                             .replace(/\\"/g, '"').replace(/\\\\/g, '\\');
                payload += chunk;
            }
        }
        return payload;
    }

    function extractPayloadFromPage() {
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
                        try {
                            questions.push(JSON.parse(payload.substring(start, j + 1)));
                        } catch (e) {}
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
        const type = q.type || 'mcq';
        const marks = q.marks || 1;
        const section = q.section || '';
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
        return { id, type, marks, section, textEn, textHi, options };
    }

    async function startAttempt(testId, apiPrefix) {
        const url = `${API_BASE}${apiPrefix}/attempts/${testId}/start`;
        log(`POST ${url}`);
        try {
            const resp = await fetch(url, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: '{}',
            });
            const data = await resp.json();
            if (data.success) {
                log(`✓ Attempt started: ${data.data.attemptId}`);
                return data.data;
            }
            err(`Start failed: ${JSON.stringify(data).substring(0, 300)}`);
            return null;
        } catch (e) {
            err(`Start error: ${e.message}`);
            return null;
        }
    }

    async function submitAttempt(testId, apiPrefix) {
        const url = `${API_BASE}${apiPrefix}/attempts/${testId}/submit`;
        log(`POST ${url}`);
        const payload = { answers: [], timeTaken: 1, language: 'en', interface: 'classic' };
        try {
            const resp = await fetch(url, {
                method: 'POST', credentials: 'include',
                headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
                body: JSON.stringify(payload),
            });
            const data = await resp.json();
            if (data.success) {
                log(`✓ Submitted successfully`);
                return true;
            }
            err(`Submit failed: ${JSON.stringify(data).substring(0, 300)}`);
            return false;
        } catch (e) {
            err(`Submit error: ${e.message}`);
            return false;
        }
    }

    async function fetchPage(url) {
        try {
            const resp = await fetch(url, { credentials: 'include' });
            const html = await resp.text();
            return { status: resp.status, html };
        } catch (e) {
            err(`Fetch error: ${e.message}`);
            return { status: 0, html: '' };
        }
    }

    async function run() {
        dbg('run() called on URL:', window.location.pathname);

        // Match: /{variant}/test-series/{slug}/test/{testId}/...
        const m = window.location.pathname.match(/^\/(tb-pro|tb|gd)\/test-series\/([\w-]+)\/test\/([a-f0-9]+)/);
        if (!m) {
            dbg('Not a test page — skipping. Path:', window.location.pathname);
            return;
        }

        const variant = m[1];
        const slug = m[2];
        const testId = m[3];
        const apiPrefix = variant === 'gd' ? '/api/v2' : '/api/v1';
        const baseUrl = `https://repeatermock.com/${variant}/test-series/${slug}/test/${testId}`;

        log(`Test: ${testId} | Variant: ${variant} | Slug: ${slug}`);
        dbg('Parsed URL components:', { variant, slug, testId, apiPrefix, baseUrl });

        // Step 1: Extract questions from current page
        let payload = extractPayloadFromPage();
        dbg('Payload from current page:', `${payload.length} chars`);
        let questions = parseQuestions(payload).map(cleanQuestion);
        dbg('Questions from current page:', questions.length);

        // If no questions, fetch /attempt page
        if (questions.length === 0) {
            log('No questions on current page — fetching /attempt...');
            const { status, html } = await fetchPage(`${baseUrl}/attempt`);
            dbg('/attempt fetch:', `HTTP ${status}, ${html.length} bytes`);
            if (status === 200 && html.length > 5000) {
                payload = extractPayloadFromHTML(html);
                dbg('Payload from /attempt:', `${payload.length} chars`);
                questions = parseQuestions(payload).map(cleanQuestion);
                log(`Found ${questions.length} questions from /attempt`);
            }
        }

        if (questions.length === 0) {
            err('No questions found — this might not be a valid test page');
            showFloatingMessage('No questions found. Make sure you are on a test page and logged in.', '#f87171');
            return;
        }

        // Step 2: Check for answersData + analysisData in current page
        let answersData = extractJSONObject(payload, 'answersData');
        let analysisData = extractJSONObject(payload, 'analysisData');
        dbg('answersData from current page:', answersData ? `${Object.keys(answersData).length} keys` : 'NONE');
        dbg('analysisData from current page:', analysisData ? 'YES' : 'NONE');

        // Step 3: If no answers, auto-start + submit + fetch solution + analysis
        if (!answersData) {
            log('No answers found — auto-starting attempt (bypasses "Unlock" button)...');
            const attempt = await startAttempt(testId, apiPrefix);
            if (attempt) {
                await new Promise(r => setTimeout(r, 1000));
                const submitted = await submitAttempt(testId, apiPrefix);
                if (submitted) {
                    await new Promise(r => setTimeout(r, 2000));

                    // Fetch /solution
                    log('Fetching /solution...');
                    const solResp = await fetchPage(`${baseUrl}/solution`);
                    dbg('/solution fetch:', `HTTP ${solResp.status}, ${solResp.html.length} bytes`);
                    if (solResp.status === 200 && solResp.html.length > 5000) {
                        const solPayload = extractPayloadFromHTML(solResp.html);
                        dbg('Payload from /solution:', `${solPayload.length} chars`);
                        answersData = extractJSONObject(solPayload, 'answersData');
                        if (answersData) {
                            log(`✓ Got ${Object.keys(answersData).length} answers + solutions`);
                        } else {
                            dbg('answersData keys found in payload:', payload.includes('answersData'));
                        }
                    }

                    // Fetch /analysis
                    log('Fetching /analysis...');
                    const anaResp = await fetchPage(`${baseUrl}/analysis`);
                    dbg('/analysis fetch:', `HTTP ${anaResp.status}, ${anaResp.html.length} bytes`);
                    if (anaResp.status === 200 && anaResp.html.length > 5000) {
                        const anaPayload = extractPayloadFromHTML(anaResp.html);
                        dbg('Payload from /analysis:', `${anaPayload.length} chars`);
                        analysisData = extractJSONObject(anaPayload, 'analysisData');
                        if (analysisData) {
                            log(`✓ Got analysis data`);
                            const ts = analysisData.ts || {};
                            const analysis = analysisData.analysis || {};
                            dbg('Analysis details:', {
                                rank: ts.rank,
                                percentile: ts.percentile,
                                avgMarks: analysis.avgMarks,
                                totalStudents: analysis.totalStudents
                            });
                        }
                    }
                }
            }
        }

        // Step 4: Display results
        displayOverlay(questions, answersData, analysisData, testId, variant, slug);

        log('=== EXTRACTION COMPLETE ===');
        log(`Questions: ${questions.length}`);
        log(`Answers: ${answersData ? Object.keys(answersData).length : 0}`);
        log(`Analysis: ${analysisData ? 'YES' : 'NO'}`);

        window.__RM_DATA = { questions, answersData, analysisData, testId, variant, slug };
        log('Data saved to window.__RM_DATA — type __RM_DATA in console');
    }

    function showFloatingMessage(msg, color) {
        const div = document.createElement('div');
        div.style.cssText = `
            position:fixed; top:10px; right:10px; background:#0f172a; color:${color||'#e2e8f0'};
            border:2px solid ${color||'#38bdf8'}; border-radius:8px; padding:12px; z-index:999999;
            font-family:monospace; font-size:13px; max-width:400px;
        `;
        div.textContent = msg;
        document.body.appendChild(div);
        setTimeout(() => div.remove(), 10000);
    }

    function displayOverlay(questions, answersData, analysisData, testId, variant, slug) {
        const existing = document.getElementById('rm-unlocker-overlay');
        if (existing) existing.remove();

        const overlay = document.createElement('div');
        overlay.id = 'rm-unlocker-overlay';
        overlay.style.cssText = `
            position:fixed; top:10px; right:10px; width:520px; max-height:90vh;
            overflow-y:auto; background:#0f172a; color:#e2e8f0; border:2px solid #38bdf8;
            border-radius:10px; z-index:999999; font-family:monospace; font-size:12px;
            padding:16px; box-shadow:0 4px 20px rgba(0,0,0,0.5);
        `;

        let html = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
            <h3 style="margin:0;color:#38bdf8;">📊 RM Unlocker v3</h3>
            <button id="rm-close" style="background:#ef4444;color:white;border:0;padding:4px 8px;border-radius:4px;cursor:pointer;">✕</button>
        </div>`;

        const platformLabel = variant === 'tb-pro' ? '🔒 PRO' : (variant === 'tb' ? 'FREE' : 'GUIDELY');
        html += `<div style="margin-bottom:10px;color:#94a3b8;">Test: ${testId}<br>Variant: <b style="color:#facc15;">${platformLabel}</b> | Slug: ${slug}</div>`;

        if (analysisData) {
            const ts = analysisData.ts || {};
            const analysis = analysisData.analysis || {};
            html += `<div style="background:#1e293b;padding:10px;border-radius:6px;margin-bottom:10px;">
                <h4 style="color:#4ade80;margin:0 0 8px;">📈 Analysis</h4>
                <div>Rank: <b style="color:#facc15;">${ts.rank || 'N/A'}</b></div>
                <div>Percentile: <b style="color:#facc15;">${ts.percentile || 'N/A'}%</b></div>
                <div>Avg Marks: <b>${(analysis.avgMarks || 0).toFixed(2)}</b></div>
                <div>Total Students: <b>${analysis.totalStudents || 'N/A'}</b></div>
            </div>`;
        }

        if (questions.length > 0) {
            html += `<div style="margin-bottom:10px;">
                <h4 style="color:#4ade80;margin:0 0 8px;">📝 Questions (${questions.length})</h4>`;
            questions.forEach((q, i) => {
                const ans = answersData ? answersData[q.id] : null;
                const correctOpt = ans ? ans.correctOption : null;
                const solEn = ans?.sol?.en?.value || (typeof ans?.sol?.en === 'string' ? ans.sol.en : '') || '';
                const qText = thoroughUnescape(q.textEn);
                html += `<div style="background:#1e293b;padding:8px;border-radius:4px;margin-bottom:6px;border-left:3px solid ${correctOpt ? '#4ade80' : '#64748b'};">
                    <div style="color:#f1f5f9;font-weight:bold;">Q${i+1}. ${qText.substring(0,250)}</div>`;
                q.options.forEach((opt, oi) => {
                    const isCorrect = correctOpt === (oi + 1);
                    const optText = thoroughUnescape(opt.en);
                    html += `<div style="margin-left:16px;color:${isCorrect ? '#4ade80' : '#94a3b8'};${isCorrect ? 'font-weight:bold;' : ''}">${'ABCD'[oi]}. ${optText.substring(0,120)}${isCorrect ? ' ✓' : ''}</div>`;
                });
                if (solEn) {
                    const solText = thoroughUnescape(solEn);
                    html += `<div style="margin-top:4px;padding:4px;background:#0f172a;border-radius:3px;color:#7dd3fc;font-size:11px;">💡 ${solText.substring(0,400)}</div>`;
                }
                html += `</div>`;
            });
            html += `</div>`;
        } else {
            html += `<div style="color:#f87171;">No questions found</div>`;
        }

        html += `<button id="rm-download" style="width:100%;background:#2563eb;color:white;border:0;padding:8px;border-radius:6px;cursor:pointer;margin-top:8px;">💾 Download JSON</button>`;

        overlay.innerHTML = html;
        document.body.appendChild(overlay);

        document.getElementById('rm-close').onclick = () => overlay.remove();
        document.getElementById('rm-download').onclick = () => {
            const blob = new Blob([JSON.stringify(window.__RM_DATA, null, 2)], { type: 'application/json' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url; a.download = `${testId}.json`; a.click();
            URL.revokeObjectURL(url);
        };
    }

    // Run on page load AND on SPA navigation
    function init() {
        dbg('init() called', { readyState: document.readyState, url: window.location.href });

        // Run immediately
        run();

        // Also run on SPA navigation (RepeaterMock is a Next.js SPA)
        let lastUrl = window.location.href;
        const observer = new MutationObserver(() => {
            if (window.location.href !== lastUrl) {
                lastUrl = window.location.href;
                dbg('URL changed:', lastUrl);
                setTimeout(run, 2000); // Wait for SPA to render
            }
        });
        observer.observe(document.body, { childList: true, subtree: true });

        // Also listen for popstate
        window.addEventListener('popstate', () => {
            dbg('popstate event');
            setTimeout(run, 2000);
        });
    }

    if (document.readyState === 'complete' || document.readyState === 'interactive') {
        setTimeout(init, 1000); // Wait 1s for SPA to fully load
    } else {
        window.addEventListener('DOMContentLoaded', () => setTimeout(init, 1000));
    }

    // Make debug function available globally
    window.__RM_DEBUG = {
        run: run,
        getData: () => window.__RM_DATA,
        extractPayload: extractPayloadFromPage,
        log: dbg,
    };
    dbg('Debug functions available at window.__RM_DEBUG');
})();
