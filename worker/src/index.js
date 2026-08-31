/**
 * RepeaterMock Scraper — Cloudflare Worker (optimized)
 *
 * OPTIMIZATION: Single combined /api/dashboard endpoint returns ALL data in ONE
 * request (overview + series + runs + failures). Dashboard refreshes every 5
 * minutes (not 60s) to minimize D1 read requests.
 *
 * Routes:
 *   GET  /                       Public dashboard (HTML)
 *   GET  /api/dashboard          All data in one response (overview + series + runs + failures)
 *   GET  /api/overview           Overall stats
 *   GET  /api/series             All series with progress
 *   GET  /api/series/:platform/:slug  Single series detail + tests
 *   GET  /api/tests?status=...   Tests filtered by status
 *   GET  /api/runs               Run history
 *   POST /api/trigger            Trigger GitHub Actions scrape (admin-only)
 *   GET  /admin                  Admin login page
 *   POST  /admin                 Verify password, set cookie
 *
 * Cron: every hour at :05 — triggers GitHub Actions workflow_dispatch
 */

const HTML_DASHBOARD = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Scraper Dashboard — RepeaterMock Mirror</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; line-height: 1.5; }
  .container { max-width: 1280px; margin: 0 auto; padding: 24px; }
  header { background: #1e293b; border-bottom: 1px solid #334155; padding: 16px 24px;
           display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 18px; color: #38bdf8; }
  header a { color: #94a3b8; text-decoration: none; font-size: 14px; }
  header a:hover { color: #38bdf8; }
  .hero { background: linear-gradient(135deg, #1e293b, #0f172a); padding: 32px;
          border-radius: 12px; margin-bottom: 24px; border: 1px solid #334155; }
  .hero h2 { font-size: 28px; margin-bottom: 8px; color: #f1f5f9; }
  .hero p { color: #94a3b8; font-size: 14px; }
  .stats-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
                gap: 16px; margin-bottom: 24px; }
  .stat-card { background: #1e293b; padding: 20px; border-radius: 10px;
               border: 1px solid #334155; }
  .stat-card .label { font-size: 12px; color: #94a3b8; text-transform: uppercase;
                      letter-spacing: 0.5px; margin-bottom: 6px; }
  .stat-card .value { font-size: 32px; font-weight: 700; color: #f1f5f9; }
  .stat-card.green .value { color: #4ade80; }
  .stat-card.yellow .value { color: #facc15; }
  .stat-card.red .value { color: #f87171; }
  .stat-card.blue .value { color: #38bdf8; }
  .stat-card.gray .value { color: #94a3b8; }
  .section { background: #1e293b; padding: 20px; border-radius: 10px;
             border: 1px solid #334155; margin-bottom: 24px; }
  .section h3 { font-size: 16px; margin-bottom: 12px; color: #f1f5f9; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; padding: 8px 12px; color: #94a3b8; font-weight: 600;
       border-bottom: 1px solid #334155; text-transform: uppercase; font-size: 11px;
       letter-spacing: 0.5px; }
  td { padding: 10px 12px; border-bottom: 1px solid #1e293b; vertical-align: middle; }
  tr:hover td { background: #1e293b80; }
  .badge { display: inline-block; padding: 2px 8px; border-radius: 12px;
           font-size: 11px; font-weight: 600; }
  .badge.green { background: #166534; color: #4ade80; }
  .badge.yellow { background: #713f12; color: #facc15; }
  .badge.red { background: #7f1d1d; color: #f87171; }
  .badge.gray { background: #374151; color: #94a3b8; }
  .progress-bar { background: #334155; border-radius: 6px; height: 8px;
                  overflow: hidden; min-width: 80px; }
  .progress-bar > div { height: 100%; background: linear-gradient(90deg, #4ade80, #22c55e); }
  .filter-bar { display: flex; gap: 12px; margin-bottom: 16px; flex-wrap: wrap; }
  .filter-bar select, .filter-bar input { background: #0f172a; color: #e2e8f0;
                                          border: 1px solid #334155; padding: 6px 10px;
                                          border-radius: 6px; font-size: 13px; }
  .empty { color: #64748b; text-align: center; padding: 40px; font-style: italic; }
  .timestamp { color: #64748b; font-size: 11px; }
  .platform-pill { display: inline-block; padding: 1px 6px; border-radius: 4px;
                   font-size: 10px; font-weight: 700; text-transform: uppercase; }
  .platform-pill.tb { background: #1e40af; color: #93c5fd; }
  .platform-pill.tb-pro { background: #581c87; color: #d8b4fe; }
  .platform-pill.gd { background: #14532d; color: #86efac; }
  footer { text-align: center; color: #64748b; font-size: 12px; padding: 20px; }
  .live-dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%;
              background: #4ade80; margin-right: 6px; animation: pulse 2s infinite; }
  @keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.4} }
</style>
</head>
<body>
<header>
  <h1>📊 RepeaterMock Scraper Dashboard</h1>
  <div>
    <a href="/" style="margin-right: 16px;">Overview</a>
    <a href="/admin">Admin</a>
  </div>
</header>
<div class="container">
  <div class="hero">
    <h2><span class="live-dot"></span>Mock Test Mirror — Scrape Progress</h2>
    <p>Real-time tracking of SSC, Railways, and Banking mock test scraping across 53 target series. Auto-refresh every 5 min.</p>
  </div>

  <div class="stats-grid" id="overview"></div>

  <div class="section">
    <h3>📋 Series Progress (<span id="series-count">0</span>)</h3>
    <div class="filter-bar">
      <select id="filter-status">
        <option value="">All statuses</option>
        <option value="complete">Complete</option>
        <option value="in-progress">In progress</option>
        <option value="pending">Pending</option>
      </select>
      <input type="text" id="filter-search" placeholder="Search series name...">
    </div>
    <div style="overflow-x: auto;">
      <table>
        <thead>
          <tr>
            <th>Platform</th>
            <th>Series Name</th>
            <th>Total</th>
            <th>Scraped</th>
            <th>Partial</th>
            <th>Failed</th>
            <th>Pending</th>
            <th>Progress</th>
            <th>Last Updated</th>
          </tr>
        </thead>
        <tbody id="series-tbody">
          <tr><td colspan="9" class="empty">Loading series data...</td></tr>
        </tbody>
      </table>
    </div>
  </div>

  <div class="section">
    <h3>⏱️ Recent Runs</h3>
    <table>
      <thead>
        <tr>
          <th>Started</th>
          <th>Ended</th>
          <th>Duration</th>
          <th>Account</th>
          <th>Scraped</th>
          <th>Partial</th>
          <th>Failed</th>
          <th>Questions</th>
        </tr>
      </thead>
      <tbody id="runs-tbody">
        <tr><td colspan="8" class="empty">Loading runs...</td></tr>
      </tbody>
    </table>
  </div>

  <div class="section">
    <h3>⚠️ Recent Failures (last 50 partial/failed tests)</h3>
    <div style="overflow-x: auto; max-height: 400px; overflow-y: auto;">
      <table>
        <thead>
          <tr>
            <th>Test</th>
            <th>Series</th>
            <th>Status</th>
            <th>Missing</th>
            <th>Error</th>
            <th>Last Attempt</th>
          </tr>
        </thead>
        <tbody id="failures-tbody">
          <tr><td colspan="6" class="empty">Loading failures...</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</div>

<footer>RepeaterMock Mirror • Auto-refresh every 5 min • <a href="/api/dashboard" style="color:#64748b">API</a></footer>

<script>
let allSeries = [], allRuns = [], allFailures = [], overview = {};

function fmtTime(ts) {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleString('en-US', { month:'short', day:'numeric', hour:'2-digit', minute:'2-digit' });
}
function fmtDur(min) {
  if (!min) return '—';
  if (min < 60) return min.toFixed(1) + 'm';
  return (min/60).toFixed(1) + 'h';
}
function pct(s) { return s.total ? Math.round(s.scraped / s.total * 100) : 0; }
function statCard(label, value, color) {
  return '<div class="stat-card ' + color + '"><div class="label">' + label + '</div><div class="value">' + value + '</div></div>';
}

// SINGLE API CALL — fetches everything in one request (optimization)
async function loadDashboard() {
  try {
    const r = await fetch('/api/dashboard');
    const d = await r.json();
    overview = d.overview || {};
    allSeries = d.series || [];
    allRuns = d.runs || [];
    allFailures = d.failures || [];
    renderAll();
  } catch (e) {
    console.error('Load failed:', e);
  }
}

function renderAll() {
  // Stats
  document.getElementById('overview').innerHTML = [
    statCard('Total Series', overview.total_series || 0, 'blue'),
    statCard('Total Tests', overview.total_tests || 0, 'blue'),
    statCard('Fully Scraped', overview.scraped || 0, 'green'),
    statCard('Partial', overview.partial || 0, 'yellow'),
    statCard('Failed', overview.failed || 0, 'red'),
    statCard('Pending', overview.pending || 0, 'gray'),
    statCard('Questions', (overview.questions||0).toLocaleString(), 'green'),
    statCard('Progress', (overview.progress_pct||0) + '%', 'green'),
  ].join('');

  renderSeries();
  renderRuns();
  renderFailures();
}

function renderSeries() {
  const statusFilter = document.getElementById('filter-status').value;
  const search = document.getElementById('filter-search').value.toLowerCase();
  const filtered = allSeries.filter(s => {
    const p = pct(s);
    if (statusFilter === 'complete' && p < 100) return false;
    if (statusFilter === 'in-progress' && (p === 0 || p === 100)) return false;
    if (statusFilter === 'pending' && p > 0) return false;
    if (search && !s.name.toLowerCase().includes(search)) return false;
    return true;
  });
  document.getElementById('series-count').textContent = allSeries.length;
  document.getElementById('series-tbody').innerHTML = filtered.map(s => {
    const p = pct(s);
    return '<tr>' +
      '<td><span class="platform-pill ' + s.platform + '">' + s.platform + '</span></td>' +
      '<td>' + s.name + '</td>' +
      '<td>' + s.total + '</td>' +
      '<td style="color:#4ade80;font-weight:600">' + s.scraped + '</td>' +
      '<td style="color:#facc15">' + s.partial + '</td>' +
      '<td style="color:#f87171">' + s.failed + '</td>' +
      '<td style="color:#94a3b8">' + s.pending + '</td>' +
      '<td><div class="progress-bar"><div style="width:' + p + '%"></div></div></td>' +
      '<td class="timestamp">' + fmtTime(s.last_scraped_at) + '</td>' +
      '</tr>';
  }).join('') || '<tr><td colspan="9" class="empty">No matching series</td></tr>';
}

function renderRuns() {
  document.getElementById('runs-tbody').innerHTML = allRuns.slice(0, 10).map(r => {
    return '<tr>' +
      '<td class="timestamp">' + fmtTime(r.started_at) + '</td>' +
      '<td class="timestamp">' + fmtTime(r.ended_at) + '</td>' +
      '<td>' + fmtDur(r.time_minutes) + '</td>' +
      '<td>Account ' + (r.account_used || '?') + '</td>' +
      '<td style="color:#4ade80">' + r.tests_scraped + '</td>' +
      '<td style="color:#facc15">' + r.tests_partial + '</td>' +
      '<td style="color:#f87171">' + r.tests_failed + '</td>' +
      '<td>' + (r.questions_scraped || 0).toLocaleString() + '</td>' +
      '</tr>';
  }).join('') || '<tr><td colspan="8" class="empty">No runs yet</td></tr>';
}

function renderFailures() {
  document.getElementById('failures-tbody').innerHTML = allFailures.map(t => {
    const missing = [];
    if (!t.has_questions) missing.push('Q');
    if (!t.has_answers) missing.push('A');
    if (!t.has_solutions) missing.push('Sol');
    if (!t.has_analysis) missing.push('Ana');
    if (!t.has_images) missing.push('Img');
    const badge = t.status === 'partial' ? 'yellow' : 'red';
    return '<tr>' +
      '<td title="' + (t.test_id || '') + '">' + (t.title || t.test_id).slice(0, 60) + '</td>' +
      '<td>' + (t.series_name || '').slice(0, 40) + '</td>' +
      '<td><span class="badge ' + badge + '">' + t.status + '</span></td>' +
      '<td>' + missing.join(', ') + '</td>' +
      '<td style="color:#94a3b8;font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis">' + (t.error_message || '—') + '</td>' +
      '<td class="timestamp">' + fmtTime(t.last_attempted_at) + '</td>' +
      '</tr>';
  }).join('') || '<tr><td colspan="6" class="empty">No failures 🎉</td></tr>';
}

loadDashboard();
// Refresh every 5 min instead of 60s — saves D1 reads
setInterval(loadDashboard, 300000);

document.getElementById('filter-status').addEventListener('change', renderSeries);
document.getElementById('filter-search').addEventListener('input', renderSeries);
</script>
</body>
</html>`;

const HTML_ADMIN = `<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Admin — RepeaterMock Scraper</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
         background: #0f172a; color: #e2e8f0; min-height: 100vh; display: flex;
         align-items: center; justify-content: center; }
  .card { background: #1e293b; padding: 32px; border-radius: 12px;
          border: 1px solid #334155; max-width: 480px; width: 100%; }
  h1 { font-size: 22px; margin-bottom: 8px; color: #38bdf8; }
  p { color: #94a3b8; margin-bottom: 20px; font-size: 14px; }
  label { display: block; margin-bottom: 6px; font-size: 13px; color: #cbd5e1; }
  input { width: 100%; background: #0f172a; color: #e2e8f0; border: 1px solid #334155;
          padding: 10px 14px; border-radius: 8px; font-size: 14px; margin-bottom: 16px; }
  button { background: #2563eb; color: white; border: 0; padding: 12px 24px;
           border-radius: 8px; cursor: pointer; font-size: 14px; width: 100%; }
  button:hover { background: #1d4ed8; }
  .err { color: #f87171; font-size: 13px; margin-top: 12px; }
  .ok { color: #4ade80; font-size: 13px; margin-top: 12px; }
  a { color: #38bdf8; text-decoration: none; }
</style>
</head>
<body>
<div class="card">
  <h1>🔐 Admin Access</h1>
  <p>Enter password to access admin actions (trigger scrape, view logs, etc.)</p>
  <form id="login-form">
    <label for="pw">Password</label>
    <input type="password" id="pw" required autofocus>
    <button type="submit">Login</button>
    <div id="msg"></div>
  </form>
  <div id="admin-actions" style="display:none;margin-top:24px">
    <h2 style="font-size:16px;margin-bottom:12px;color:#f1f5f9">Admin Actions</h2>
    <button onclick="triggerScrape()" style="margin-bottom:8px">▶ Trigger Scrape Now</button>
    <a href="/" style="display:block;margin-top:16px;text-align:center">← Back to Dashboard</a>
  </div>
</div>
<script>
async function checkAuth() {
  const r = await fetch('/api/admin/check');
  const d = await r.json();
  if (d.authed) {
    document.getElementById('login-form').style.display = 'none';
    document.getElementById('admin-actions').style.display = 'block';
  }
}
checkAuth();

document.getElementById('login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const pw = document.getElementById('pw').value;
  const r = await fetch('/admin', { method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({ password: pw }) });
  const d = await r.json();
  if (d.success) {
    document.getElementById('msg').className = 'ok';
    document.getElementById('msg').textContent = '✓ Authenticated';
    setTimeout(() => location.reload(), 500);
  } else {
    document.getElementById('msg').className = 'err';
    document.getElementById('msg').textContent = '✗ ' + (d.error || 'Wrong password');
  }
});

async function triggerScrape() {
  if (!confirm('Trigger a scrape run now?')) return;
  const r = await fetch('/api/trigger', { method: 'POST' });
  const d = await r.json();
  if (d.success) {
    alert('✓ Scrape triggered! Check GitHub Actions.');
  } else {
    alert('✗ Failed: ' + (d.error || 'unknown'));
  }
}
</script>
</body>
</html>`;

// ─── Cookie helpers ─────────────────────────────────────────────────────────

function parseCookies(cookieHeader) {
  const cookies = {};
  if (!cookieHeader) return cookies;
  for (const pair of cookieHeader.split(';')) {
    const [k, ...v] = pair.trim().split('=');
    if (k) {
      try {
        cookies[k] = decodeURIComponent(v.join('='));
      } catch (e) {
        cookies[k] = v.join('=');
      }
    }
  }
  return cookies;
}

function makeResponse(body, status = 200, headers = {}) {
  const isHtml = typeof body === 'string' && body.startsWith('<!DOCTYPE');
  return new Response(body, {
    status,
    headers: {
      'Content-Type': isHtml ? 'text/html;charset=utf-8' : 'application/json',
      'Cache-Control': isHtml ? 'no-cache' : 'public, max-age=60',
      'Access-Control-Allow-Origin': '*',
      ...headers,
    },
  });
}

// ─── Combined dashboard endpoint (1 request instead of 4) ──────────────────

async function handleDashboard(DB) {
  // Run 5 queries in a single batch call to minimize round trips
  const results = await DB.batch([
    DB.prepare(`
      SELECT
        COUNT(*) as total_series,
        COALESCE(SUM(total_tests), 0) as total_tests,
        COALESCE(SUM(scraped_count), 0) as scraped,
        COALESCE(SUM(partial_count), 0) as partial,
        COALESCE(SUM(failed_count), 0) as failed,
        COALESCE(SUM(pending_count), 0) as pending
      FROM series
    `),
    DB.prepare(`
      SELECT COALESCE(SUM(actual_questions), 0) as q
      FROM tests WHERE status = 'scraped'
    `),
    DB.prepare(`
      SELECT platform, slug, name, series_url, total_tests as total, scraped_count as scraped,
             partial_count as partial, failed_count as failed, pending_count as pending,
             last_fetched_at, last_scraped_at, updated_at
      FROM series ORDER BY pending_count DESC, name
    `),
    DB.prepare(`
      SELECT * FROM runs ORDER BY started_at DESC LIMIT 20
    `),
    DB.prepare(`
      SELECT * FROM tests WHERE status IN ('partial', 'failed')
      ORDER BY last_attempted_at DESC LIMIT 50
    `),
  ]);

  const overviewRes = results[0];
  const qCountRes = results[1];
  const seriesRes = results[2];
  const runsRes = results[3];
  const failuresRes = results[4];

  const o1 = overviewRes.results[0] || {};
  const o2 = qCountRes.results[0] || {};
  const total = o1.total_tests || 0;
  const scraped = o1.scraped || 0;

  return {
    overview: {
      total_series: o1.total_series,
      total_tests: total,
      scraped,
      partial: o1.partial,
      failed: o1.failed,
      pending: o1.pending,
      questions: o2.q || 0,
      progress_pct: total ? Math.round(scraped / total * 100) : 0,
    },
    series: seriesRes.results || [],
    runs: runsRes.results || [],
    failures: failuresRes.results || [],
  };
}


// ─── Individual API handlers (kept for compatibility) ──────────────────────

async function handleOverview(DB) {
  const r = await handleDashboard(DB);
  return r.overview;
}

async function handleSeriesList(DB) {
  const r = await DB.prepare(`
    SELECT platform, slug, name, series_url, total_tests as total, scraped_count as scraped,
           partial_count as partial, failed_count as failed, pending_count as pending,
           last_fetched_at, last_scraped_at, updated_at
    FROM series ORDER BY pending_count DESC, name
  `).all();
  return r.results || [];
}

async function handleSeriesDetail(DB, platform, slug) {
  const seriesUrl = `https://repeatermock.com/${platform}/test-series/${slug}`;
  const series = await DB.prepare(`SELECT * FROM series WHERE series_url = ?`)
    .bind(seriesUrl).first();
  if (!series) return { error: 'Series not found' };
  const tests = await DB.prepare(`
    SELECT * FROM tests WHERE series_url = ? ORDER BY status, last_attempted_at DESC
  `).bind(seriesUrl).all();
  return { series, tests: tests.results || [] };
}

async function handleTestsList(DB, url) {
  const params = new URL(url).searchParams;
  const status = params.get('status') || '';
  const limit = parseInt(params.get('limit') || '100');

  let sql = `SELECT * FROM tests`;
  const binds = [];
  const where = [];

  if (status) {
    const statuses = status.split(',').filter(Boolean);
    if (statuses.length === 1) {
      where.push('status = ?');
      binds.push(statuses[0]);
    } else if (statuses.length > 1) {
      where.push(`status IN (${statuses.map(() => '?').join(',')})`);
      binds.push(...statuses);
    }
  }

  if (where.length) sql += ' WHERE ' + where.join(' AND ');
  sql += ` ORDER BY last_attempted_at DESC LIMIT ?`;
  binds.push(limit);

  const r = await DB.prepare(sql).bind(...binds).all();
  return r.results || [];
}

async function handleRunsList(DB) {
  const r = await DB.prepare(`
    SELECT * FROM runs ORDER BY started_at DESC LIMIT 50
  `).all();
  return r.results || [];
}

async function handleAdminCheck(request, env) {
  const cookies = parseCookies(request.headers.get('Cookie'));
  const authed = cookies.admin_token === env.ADMIN_PASSWORD;
  return { authed };
}

async function handleAdminLogin(request, env) {
  const body = await request.json();
  if (body.password !== env.ADMIN_PASSWORD) {
    return makeResponse(JSON.stringify({ success: false, error: 'Wrong password' }));
  }
  return new Response(JSON.stringify({ success: true }), {
    status: 200,
    headers: {
      'Content-Type': 'application/json',
      'Set-Cookie': `admin_token=${encodeURIComponent(env.ADMIN_PASSWORD)}; HttpOnly; Path=/; Max-Age=86400; SameSite=Strict`,
    },
  });
}

async function handleTrigger(request, env) {
  const cookies = parseCookies(request.headers.get('Cookie'));
  if (cookies.admin_token !== env.ADMIN_PASSWORD) {
    return makeResponse(JSON.stringify({ success: false, error: 'Unauthorized' }), 401);
  }
  if (!env.GH_TOKEN || !env.GH_REPO) {
    return makeResponse(JSON.stringify({
      success: false,
      error: 'GH_TOKEN or GH_REPO not set',
      has_gh_token: !!env.GH_TOKEN,
      has_gh_repo: !!env.GH_REPO,
      gh_token_len: env.GH_TOKEN ? env.GH_TOKEN.length : 0,
    }), 500);
  }
  try {
    const r = await fetch(
      `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/scrape.yml/dispatches`,
      {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GH_TOKEN}`,
          'Accept': 'application/vnd.github+json',
          'Content-Type': 'application/json',
          'User-Agent': 'repeatermock-dashboard-worker',
        },
        body: JSON.stringify({ ref: 'main' }),
      }
    );
    if (r.status === 204) {
      return makeResponse(JSON.stringify({ success: true, message: 'Triggered' }));
    }
    const errBody = await r.text().catch(() => '');
    return makeResponse(JSON.stringify({
      success: false,
      error: `GitHub API ${r.status}`,
      details: errBody.slice(0, 300),
      gh_token_len: env.GH_TOKEN.length,
      gh_repo: env.GH_REPO,
    }), 500);
  } catch (e) {
    return makeResponse(JSON.stringify({ success: false, error: 'Fetch error: ' + e.message }), 500);
  }
}

// ─── Cron handler (every hour at :05) ───────────────────────────────────────

async function handleCron(env) {
  if (env.GH_TOKEN && env.GH_REPO) {
    try {
      await fetch(
        `https://api.github.com/repos/${env.GH_REPO}/actions/workflows/scrape.yml/dispatches`,
        {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${env.GH_TOKEN}`,
            'Accept': 'application/vnd.github+json',
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ ref: 'main' }),
        }
      );
      console.log('Cron: triggered GitHub Actions scrape');
    } catch (e) {
      console.error('Cron: failed to trigger', e);
    }
  }
}

// ─── Main entry ─────────────────────────────────────────────────────────────

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const path = url.pathname;
    const DB = env.DB;

    try {
      if (path === '/' || path === '/index.html') {
        return makeResponse(HTML_DASHBOARD);
      }
      if (path === '/admin' && request.method === 'GET') {
        return makeResponse(HTML_ADMIN);
      }
      if (path === '/admin' && request.method === 'POST') {
        return handleAdminLogin(request, env);
      }

      // SINGLE COMBINED ENDPOINT (optimized — main one used by dashboard)
      if (path === '/api/dashboard') {
        return makeResponse(JSON.stringify(await handleDashboard(DB)));
      }

      // Individual endpoints (kept for compatibility, but dashboard uses /api/dashboard)
      if (path === '/api/overview') {
        return makeResponse(JSON.stringify(await handleOverview(DB)));
      }
      if (path === '/api/series' || path === '/api/series/') {
        return makeResponse(JSON.stringify(await handleSeriesList(DB)));
      }
      const m = path.match(/^\/api\/series\/([^/]+)\/([^/]+)$/);
      if (m) {
        return makeResponse(JSON.stringify(await handleSeriesDetail(DB, m[1], m[2])));
      }
      if (path === '/api/tests' || path.startsWith('/api/tests?')) {
        const tests = await handleTestsList(DB, url);
        return makeResponse(JSON.stringify({ tests }));
      }
      if (path === '/api/runs') {
        return makeResponse(JSON.stringify(await handleRunsList(DB)));
      }
      if (path === '/api/admin/check') {
        return makeResponse(JSON.stringify(await handleAdminCheck(request, env)));
      }
      if (path === '/api/trigger' && request.method === 'POST') {
        return handleTrigger(request, env);
      }

      return makeResponse(JSON.stringify({ error: 'Not found', path }), 404);
    } catch (e) {
      console.error('Handler error:', e);
      return makeResponse(JSON.stringify({ error: e.message, stack: e.stack }), 500);
    }
  },

  async scheduled(event, env, ctx) {
    ctx.waitUntil(handleCron(env));
  },
};
