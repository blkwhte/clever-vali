import json
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, request
from airtable_client import get_all_partners, get_partner_by_id, write_vali_results, get_mapped_fields

# Import the existing Vali test logic from your current vali.py.
# We're reusing the OAuth tests and data ingestion logic directly —
# no need to rewrite them.
from vali_core import run_all_tests

app = Flask(__name__)

# In-memory store for test runs that are currently in progress.
# Key: Airtable record ID, Value: status dict
_running_tests = {}


# ---------------------------------------------------------------------------
# HTML TEMPLATE
# The entire dashboard UI lives here as a single-file template.
# ---------------------------------------------------------------------------

PARTNER_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vali — Partner Certification</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #ffffff; --bg2: #f5f5f3; --bg3: #ebebea;
    --text: #1a1a18; --text2: #5f5e5a; --text3: #888780;
    --border: rgba(0,0,0,0.12); --border2: rgba(0,0,0,0.08);
    --blue: #185FA5; --blue-bg: #e6f1fb;
    --green: #1D9E75; --green-bg: #eaf3de; --green-text: #27500A;
    --red: #E24B4A; --red-bg: #fcebeb; --red-text: #791F1F;
    --amber: #EF9F27; --amber-bg: #faeeda; --amber-text: #633806;
    --gray-bg: #f1efe8; --gray-text: #5f5e5a;
    --radius: 8px; --radius-lg: 12px;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1c1c1a; --bg2: #252523; --bg3: #2e2e2c;
      --text: #e8e8e4; --text2: #a8a8a0; --text3: #6e6e68;
      --border: rgba(255,255,255,0.12); --border2: rgba(255,255,255,0.07);
      --blue-bg: #0c2d4a;
      --green-bg: #173404; --green-text: #c0dd97;
      --red-bg: #2d1010; --red-text: #f09595;
      --amber-bg: #2a1a04; --amber-text: #fac775;
      --gray-bg: #2c2c2a; --gray-text: #b4b2a9;
    }
  }
  body { font-family: var(--font); background: var(--bg2); color: var(--text); font-size: 14px; min-height: 100vh; }

  /* Header */
  .header { background: var(--bg); border-bottom: 0.5px solid var(--border); padding: 16px 32px; display: flex; align-items: center; gap: 12px; }
  .logo { font-size: 18px; font-weight: 500; }
  .logo-sub { font-size: 13px; color: var(--text3); margin-top: 2px; }

  /* Layout */
  .page { max-width: 680px; margin: 48px auto; padding: 0 24px 80px; }

  /* Steps */
  .step-indicator { display: flex; align-items: center; gap: 0; margin-bottom: 40px; }
  .step { display: flex; align-items: center; gap: 8px; }
  .step-num { width: 24px; height: 24px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 500; flex-shrink: 0; }
  .step-num.active { background: var(--blue); color: #fff; }
  .step-num.done { background: var(--green); color: #fff; }
  .step-num.pending { background: var(--border); color: var(--text3); }
  .step-label { font-size: 13px; color: var(--text2); }
  .step-label.active { color: var(--text); font-weight: 500; }
  .step-divider { flex: 1; height: 1px; background: var(--border); margin: 0 12px; max-width: 48px; }

  /* Cards */
  .card { background: var(--bg); border: 0.5px solid var(--border); border-radius: var(--radius-lg); padding: 28px; margin-bottom: 20px; }
  .card-title { font-size: 16px; font-weight: 500; margin-bottom: 6px; }
  .card-sub { font-size: 13px; color: var(--text2); margin-bottom: 24px; line-height: 1.55; }

  /* Form */
  .field { margin-bottom: 18px; }
  .field label { display: block; font-size: 13px; font-weight: 500; margin-bottom: 6px; }
  .field .hint { font-size: 12px; color: var(--text3); margin-bottom: 8px; line-height: 1.5; }
  .field input { width: 100%; padding: 9px 12px; border: 0.5px solid var(--border); border-radius: var(--radius); background: var(--bg2); color: var(--text); font-size: 13px; outline: none; transition: border-color 0.15s; }
  .field input:focus { border-color: var(--blue); }
  .field input.optional { opacity: 0.8; }
  .optional-tag { font-size: 11px; color: var(--text3); font-weight: 400; margin-left: 6px; }

  /* Buttons */
  .btn-primary { width: 100%; padding: 10px; border-radius: var(--radius); border: none; background: var(--blue); color: #fff; font-size: 14px; font-weight: 500; cursor: pointer; margin-top: 8px; transition: opacity 0.15s; }
  .btn-primary:hover { opacity: 0.9; }
  .btn-primary:disabled { opacity: 0.45; cursor: not-allowed; }

  /* Progress */
  .progress-wrap { margin-bottom: 24px; }
  .progress-label { font-size: 12px; color: var(--text2); margin-bottom: 6px; display: flex; justify-content: space-between; }
  .progress-track { height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
  .progress-fill { height: 100%; background: var(--blue); border-radius: 2px; transition: width 0.4s; }

  /* Results */
  .result-section { margin-bottom: 16px; }
  .section-label { font-size: 11px; font-weight: 500; letter-spacing: 0.07em; color: var(--text3); text-transform: uppercase; margin-bottom: 8px; }
  .result-item { border: 0.5px solid var(--border); border-radius: var(--radius); padding: 12px 14px; margin-bottom: 8px; display: flex; align-items: flex-start; gap: 10px; cursor: pointer; background: var(--bg); }
  .result-item:hover { background: var(--bg2); }
  .badge { font-size: 11px; font-weight: 500; padding: 3px 9px; border-radius: var(--radius); white-space: nowrap; flex-shrink: 0; margin-top: 1px; }
  .badge-PASS { background: var(--green-bg); color: var(--green-text); }
  .badge-FAIL, .badge-NEEDS_WORK { background: var(--red-bg); color: var(--red-text); }
  .badge-SKIPPED { background: var(--gray-bg); color: var(--gray-text); }
  .result-body { flex: 1; min-width: 0; }
  .result-name { font-size: 13px; font-weight: 500; }
  .result-detail { font-size: 12px; color: var(--text2); margin-top: 6px; line-height: 1.6; white-space: pre-wrap; display: none; font-family: monospace; }
  .chevron { font-size: 12px; color: var(--text3); flex-shrink: 0; margin-top: 2px; transition: transform 0.15s; }

  /* Summary */
  .summary { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 24px; }
  .summary-item { background: var(--bg2); border-radius: var(--radius); padding: 12px; text-align: center; }
  .summary-val { font-size: 22px; font-weight: 500; }
  .summary-label { font-size: 11px; color: var(--text2); margin-top: 3px; }
  .green { color: var(--green); }
  .red { color: var(--red); }

  /* Overall badge */
  .overall { display: flex; align-items: center; gap: 12px; padding: 14px 16px; border-radius: var(--radius); margin-bottom: 24px; }
  .overall.pass { background: var(--green-bg); }
  .overall.fail { background: var(--red-bg); }
  .overall-icon { font-size: 20px; }
  .overall-text { font-size: 14px; font-weight: 500; }
  .overall-sub { font-size: 12px; opacity: 0.8; margin-top: 2px; }

  /* Running */
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { width: 14px; height: 14px; border: 2px solid var(--blue); border-top-color: transparent; border-radius: 50%; animation: spin 0.7s linear infinite; display: inline-block; }
  .running-msg { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--text2); padding: 12px 0; }

  /* Notice */
  .notice { background: var(--blue-bg); border-radius: var(--radius); padding: 12px 14px; font-size: 12px; color: var(--text2); line-height: 1.6; margin-bottom: 20px; }
  .notice strong { color: var(--text); }

  /* Error */
  .error-msg { background: var(--red-bg); color: var(--red-text); border-radius: var(--radius); padding: 12px 14px; font-size: 13px; margin-bottom: 16px; }

  /* Restart */
  .btn-ghost { width: 100%; padding: 9px; border-radius: var(--radius); border: 0.5px solid var(--border); background: transparent; color: var(--text2); font-size: 13px; cursor: pointer; margin-top: 16px; }
  .btn-ghost:hover { background: var(--bg2); }
</style>
</head>
<body>

<div class="header">
  <div>
    <div class="logo">⚡ Vali</div>
    <div class="logo-sub">Clever Secure Sync Certification</div>
  </div>
</div>

<div class="page">

  <!-- Step indicator -->
  <div class="step-indicator" id="steps">
    <div class="step">
      <div class="step-num active" id="s1">1</div>
      <div class="step-label active" id="sl1">Your details</div>
    </div>
    <div class="step-divider"></div>
    <div class="step">
      <div class="step-num pending" id="s2">2</div>
      <div class="step-label" id="sl2">Running tests</div>
    </div>
    <div class="step-divider"></div>
    <div class="step">
      <div class="step-num pending" id="s3">3</div>
      <div class="step-label" id="sl3">Results</div>
    </div>
  </div>

  <!-- Step 1: Form -->
  <div id="view-form">
    <div class="card">
      <div class="card-title">Before you begin</div>
      <div class="card-sub">
        Vali will run a series of automated tests against your integration to verify it meets
        Clever's certification requirements. Make sure your application is running locally
        before starting.
      </div>
      <div class="notice">
        <strong>Required before running:</strong> The <strong>#DEMO Certification ISD - Events</strong>
        sandbox district must be connected to your Clever application. Contact
        <a href="mailto:integrations@clever.com">integrations@clever.com</a> if you haven't completed this step.
      </div>

      <div class="field">
        <label for="client-id">Dev Account Client ID <span style="color:var(--red)">*</span></label>
        <div class="hint">Found in your Clever developer dashboard under Settings. Used to look up your certification record.</div>
        <input type="text" id="client-id" placeholder="e.g. 4c63c1cf623dce82caac" />
      </div>

      <div class="field">
        <label for="redirect-uri">Redirect URI <span style="color:var(--red)">*</span></label>
        <div class="hint">The OAuth callback URL your app receives Clever auth codes on. e.g. <code>http://localhost:8080/auth/clever/callback</code></div>
        <input type="text" id="redirect-uri" placeholder="http://localhost:8080/auth/clever/callback" />
      </div>

      <div class="field">
        <label for="login-url">Login Page URL <span class="optional-tag">optional</span></label>
        <div class="hint">The page where users see your "Log in with Clever" button. Required for SSO browser tests — leave blank to run OAuth tests only.</div>
        <input type="text" id="login-url" class="optional" placeholder="http://localhost:8080/login" />
      </div>

      <div id="form-error" class="error-msg" style="display:none"></div>
      <button class="btn-primary" id="start-btn" onclick="startTests()">Run certification tests</button>
    </div>
  </div>

  <!-- Step 2: Running -->
  <div id="view-running" style="display:none">
    <div class="card">
      <div class="card-title">Running tests</div>
      <div class="card-sub">This usually takes 1–3 minutes. Keep this window open.</div>
      <div class="progress-wrap">
        <div class="progress-label"><span id="progress-msg">Starting...</span><span id="progress-pct">0%</span></div>
        <div class="progress-track"><div class="progress-fill" id="progress-fill" style="width:0%"></div></div>
      </div>
      <div id="live-log"></div>
    </div>
  </div>

  <!-- Step 3: Results -->
  <div id="view-results" style="display:none">
    <div id="overall-banner" class="overall"></div>
    <div class="summary">
      <div class="summary-item"><div class="summary-val" id="r-total">0</div><div class="summary-label">Tests run</div></div>
      <div class="summary-item"><div class="summary-val green" id="r-pass">0</div><div class="summary-label">Passed</div></div>
      <div class="summary-item"><div class="summary-val red" id="r-fail">0</div><div class="summary-label">Failed</div></div>
      <div class="summary-item"><div class="summary-val" id="r-skip">0</div><div class="summary-label">Skipped</div></div>
    </div>
    <div id="results-list"></div>
    <button class="btn-ghost" onclick="restart()">← Run tests again</button>
  </div>

</div>

<script>
let runId = null;
let pollInterval = null;

// ---------------------------------------------------------------------------
// Step 1: Submit form and start tests
// ---------------------------------------------------------------------------
async function startTests() {
  const clientId   = document.getElementById('client-id').value.trim();
  const redirectUri = document.getElementById('redirect-uri').value.trim();
  const loginUrl   = document.getElementById('login-url').value.trim();
  const errEl      = document.getElementById('form-error');

  errEl.style.display = 'none';

  if (!clientId) {
    errEl.textContent = 'Please enter your Dev Account Client ID.';
    errEl.style.display = 'block';
    return;
  }
  if (!redirectUri) {
    errEl.textContent = 'Please enter your Redirect URI.';
    errEl.style.display = 'block';
    return;
  }

  document.getElementById('start-btn').disabled = true;
  showStep(2);

  try {
    const res = await fetch('/partner/api/run', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ client_id: clientId, redirect_uri: redirectUri, login_url: loginUrl })
    });
    const data = await res.json();

    if (!res.ok || data.error) {
      showError(data.error || 'Failed to start tests. Please try again.');
      showStep(1);
      document.getElementById('start-btn').disabled = false;
      return;
    }

    runId = data.run_id;
    pollResults();

  } catch(e) {
    showError('Could not connect to Vali. Make sure the server is running.');
    showStep(1);
    document.getElementById('start-btn').disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Polling
// ---------------------------------------------------------------------------
function pollResults() {
  let attempts = 0;
  const msgs = [
    'Checking OAuth security...',
    'Testing state parameter handling...',
    'Verifying graceful error handling...',
    'Starting SSO browser tests...',
    'Logging in with sandbox users...',
    'Checking role coverage...',
    'Testing session invalidation...',
    'Finishing up...',
  ];

  pollInterval = setInterval(async () => {
    attempts++;
    const pct = Math.min(90, attempts * 6);
    document.getElementById('progress-fill').style.width = pct + '%';
    document.getElementById('progress-pct').textContent = pct + '%';
    document.getElementById('progress-msg').textContent = msgs[Math.min(attempts - 1, msgs.length - 1)];

    // Show a live log entry every few ticks
    if (attempts % 2 === 0) {
      addLogEntry(msgs[Math.min(Math.floor(attempts / 2), msgs.length - 1)]);
    }

    try {
      const res = await fetch(`/partner/api/status/${runId}`);
      const data = await res.json();

      if (data.status === 'done' || data.status === 'error') {
        clearInterval(pollInterval);
        document.getElementById('progress-fill').style.width = '100%';
        document.getElementById('progress-pct').textContent = '100%';
        showResults(data.results, data.overall);
      }
    } catch(_) {}
  }, 2500);
}

function addLogEntry(msg) {
  const log = document.getElementById('live-log');
  const el = document.createElement('div');
  el.className = 'running-msg';
  el.innerHTML = `<div class="spinner"></div><span>${msg}</span>`;
  // Keep only last 3 entries
  if (log.children.length >= 3) log.removeChild(log.firstChild);
  log.appendChild(el);
}

// ---------------------------------------------------------------------------
// Results
// ---------------------------------------------------------------------------
function showResults(results, overall) {
  showStep(3);

  const pass  = results.filter(r => r.status === 'PASS').length;
  const fail  = results.filter(r => ['FAIL','NEEDS_WORK'].includes(r.status)).length;
  const skip  = results.filter(r => r.status === 'SKIPPED').length;

  document.getElementById('r-total').textContent = results.length;
  document.getElementById('r-pass').textContent  = pass;
  document.getElementById('r-fail').textContent  = fail;
  document.getElementById('r-skip').textContent  = skip;

  const banner = document.getElementById('overall-banner');
  if (overall === 'PASS') {
    banner.className = 'overall pass';
    banner.innerHTML = '<div class="overall-icon">✓</div><div><div class="overall-text">All tests passed</div><div class="overall-sub">Your integration meets Clever&#39;s automated certification requirements.</div></div>';
  } else {
    banner.className = 'overall fail';
    banner.innerHTML = '<div class="overall-icon">✗</div><div><div class="overall-text">Some tests need attention</div><div class="overall-sub">Review the failures below, fix the issues, and run again.</div></div>';
  }

  // Group by category
  const categories = {};
  results.forEach(r => {
    const cat = r.category || 'General';
    if (!categories[cat]) categories[cat] = [];
    categories[cat].push(r);
  });

  const list = document.getElementById('results-list');
  list.innerHTML = '';
  Object.entries(categories).forEach(([cat, items]) => {
    const sec = document.createElement('div');
    sec.className = 'result-section';
    sec.innerHTML = `<div class="section-label">${cat}</div>`;
    items.forEach(r => {
      const el = document.createElement('div');
      el.className = 'result-item';
      el.innerHTML = `
        <span class="badge badge-${r.status}">${r.status}</span>
        <div class="result-body">
          <div class="result-name">${r.requirement}</div>
          <div class="result-detail" id="detail-${Math.random().toString(36).slice(2)}">${r.details || ''}</div>
        </div>
        <span class="chevron">▾</span>`;
      el.addEventListener('click', () => {
        const detail = el.querySelector('.result-detail');
        const chev   = el.querySelector('.chevron');
        const open   = detail.style.display === 'block';
        detail.style.display = open ? 'none' : 'block';
        chev.style.transform  = open ? '' : 'rotate(180deg)';
      });
      sec.appendChild(el);
    });
    list.appendChild(sec);
  });
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function showStep(n) {
  document.getElementById('view-form').style.display    = n === 1 ? 'block' : 'none';
  document.getElementById('view-running').style.display = n === 2 ? 'block' : 'none';
  document.getElementById('view-results').style.display = n === 3 ? 'block' : 'none';

  [1,2,3].forEach(i => {
    const num = document.getElementById('s' + i);
    const lbl = document.getElementById('sl' + i);
    if (i < n) {
      num.className = 'step-num done'; num.textContent = '✓';
      lbl.className = 'step-label';
    } else if (i === n) {
      num.className = 'step-num active'; num.textContent = i;
      lbl.className = 'step-label active';
    } else {
      num.className = 'step-num pending'; num.textContent = i;
      lbl.className = 'step-label';
    }
  });
}

function showError(msg) {
  const el = document.getElementById('form-error');
  el.textContent = msg;
  el.style.display = 'block';
}

function restart() {
  if (pollInterval) clearInterval(pollInterval);
  runId = null;
  document.getElementById('start-btn').disabled = false;
  document.getElementById('form-error').style.display = 'none';
  document.getElementById('live-log').innerHTML = '';
  showStep(1);
}
</script>
</body>
</html>
"""

DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Vali — Clever Certification Dashboard</title>
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
  :root {
    --bg: #ffffff; --bg2: #f5f5f3; --bg3: #ebebea;
    --text: #1a1a18; --text2: #5f5e5a; --text3: #888780;
    --border: rgba(0,0,0,0.12); --border2: rgba(0,0,0,0.08);
    --blue: #185FA5; --blue-bg: #e6f1fb; --blue-text: #0c447c;
    --green: #1D9E75; --green-bg: #eaf3de; --green-text: #27500A;
    --red: #E24B4A; --red-bg: #fcebeb; --red-text: #791F1F;
    --amber: #EF9F27; --amber-bg: #faeeda; --amber-text: #633806;
    --gray-bg: #f1efe8; --gray-text: #5f5e5a;
    --radius: 8px; --radius-lg: 12px;
    --font: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    --mono: 'SF Mono', 'Fira Code', monospace;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      --bg: #1c1c1a; --bg2: #252523; --bg3: #2e2e2c;
      --text: #e8e8e4; --text2: #a8a8a0; --text3: #6e6e68;
      --border: rgba(255,255,255,0.12); --border2: rgba(255,255,255,0.07);
      --blue-bg: #0c2d4a; --blue-text: #85b7eb;
      --green-bg: #173404; --green-text: #c0dd97;
      --red-bg: #2d1010; --red-text: #f09595;
      --amber-bg: #2a1a04; --amber-text: #fac775;
      --gray-bg: #2c2c2a; --gray-text: #b4b2a9;
    }
  }
  body { font-family: var(--font); background: var(--bg2); color: var(--text); font-size: 14px; }
  a { color: var(--blue); text-decoration: none; }

  /* Layout */
  .shell { display: flex; height: 100vh; overflow: hidden; }
  .sidebar { width: 240px; background: var(--bg); border-right: 0.5px solid var(--border); display: flex; flex-direction: column; flex-shrink: 0; }
  .main { flex: 1; display: flex; flex-direction: column; overflow: hidden; }

  /* Sidebar */
  .sb-head { padding: 16px; border-bottom: 0.5px solid var(--border); }
  .sb-logo { font-size: 16px; font-weight: 500; color: var(--text); display: flex; align-items: center; gap: 8px; }
  .sb-sub { font-size: 11px; color: var(--text3); margin-top: 3px; }
  .sb-search { padding: 10px 12px; border-bottom: 0.5px solid var(--border); }
  .sb-search input { width: 100%; padding: 6px 10px; border-radius: var(--radius); border: 0.5px solid var(--border); background: var(--bg2); color: var(--text); font-size: 12px; outline: none; }
  .sb-search input:focus { border-color: var(--blue); }
  .partner-list { flex: 1; overflow-y: auto; }
  .partner-item { padding: 10px 14px; cursor: pointer; border-bottom: 0.5px solid var(--border2); display: flex; align-items: center; gap: 10px; transition: background 0.1s; }
  .partner-item:hover { background: var(--bg2); }
  .partner-item.active { background: var(--bg2); border-left: 2px solid var(--blue); }
  .p-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .dot-PASS { background: var(--green); }
  .dot-NEEDS_WORK, .dot-FAIL { background: var(--red); }
  .dot-NOT\\ RUN, .dot-PENDING { background: var(--amber); }
  .p-info { min-width: 0; }
  .p-name { font-size: 13px; font-weight: 500; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .p-date { font-size: 11px; color: var(--text3); margin-top: 1px; }

  /* Topbar */
  .topbar { padding: 14px 20px; border-bottom: 0.5px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: var(--bg); }
  .partner-title { font-size: 16px; font-weight: 500; }
  .partner-meta { font-size: 12px; color: var(--text3); margin-top: 2px; }
  .topbar-actions { display: flex; gap: 8px; align-items: center; }
  .btn { font-size: 12px; padding: 6px 14px; border-radius: var(--radius); border: 0.5px solid var(--border); background: transparent; color: var(--text); cursor: pointer; display: flex; align-items: center; gap: 6px; transition: background 0.1s; }
  .btn:hover { background: var(--bg2); }
  .btn-primary { background: var(--blue); color: #fff; border-color: var(--blue); }
  .btn-primary:hover { opacity: 0.9; }
  .btn:disabled { opacity: 0.45; cursor: not-allowed; }

  /* Badges */
  .badge { font-size: 11px; font-weight: 500; padding: 3px 10px; border-radius: var(--radius); white-space: nowrap; }
  .badge-PASS { background: var(--green-bg); color: var(--green-text); }
  .badge-NEEDS_WORK, .badge-FAIL { background: var(--red-bg); color: var(--red-text); }
  .badge-NOT\\ RUN, .badge-PENDING { background: var(--amber-bg); color: var(--amber-text); }
  .badge-SKIPPED { background: var(--gray-bg); color: var(--gray-text); }

  /* Tabs */
  .tabs { display: flex; border-bottom: 0.5px solid var(--border); background: var(--bg); padding: 0 20px; }
  .tab { font-size: 13px; padding: 10px 14px; cursor: pointer; color: var(--text2); border-bottom: 2px solid transparent; margin-bottom: -0.5px; transition: color 0.1s; }
  .tab:hover { color: var(--text); }
  .tab.active { color: var(--blue); border-bottom-color: var(--blue); font-weight: 500; }

  /* Content */
  .content { flex: 1; overflow-y: auto; padding: 20px; }
  .tab-panel { display: none; }
  .tab-panel.active { display: block; }

  /* Metrics */
  .metrics { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px; }
  .metric { background: var(--bg2); border-radius: var(--radius); padding: 12px 14px; }
  .metric-label { font-size: 12px; color: var(--text2); margin-bottom: 6px; }
  .metric-val { font-size: 22px; font-weight: 500; }
  .metric-val.green { color: var(--green); }
  .metric-val.red { color: var(--red); }

  /* Section label */
  .section-label { font-size: 11px; font-weight: 500; letter-spacing: 0.07em; color: var(--text3); text-transform: uppercase; margin: 16px 0 8px; }

  /* Result cards */
  .result-card { border: 0.5px solid var(--border); border-radius: var(--radius-lg); margin-bottom: 8px; overflow: hidden; background: var(--bg); }
  .result-row { padding: 12px 14px; display: flex; align-items: center; gap: 12px; cursor: pointer; transition: background 0.1s; }
  .result-row:hover { background: var(--bg2); }
  .result-name { font-size: 13px; font-weight: 500; flex: 1; }
  .result-detail { font-size: 12px; color: var(--text2); padding: 0 14px 12px; line-height: 1.6; white-space: pre-wrap; font-family: var(--mono); display: none; border-top: 0.5px solid var(--border2); padding-top: 10px; margin-top: 0; }
  .chevron { font-size: 12px; color: var(--text3); transition: transform 0.15s; display: inline-block; }
  .chevron.open { transform: rotate(180deg); }

  /* Airtable fields */
  .at-card { border: 0.5px solid var(--border); border-radius: var(--radius-lg); padding: 14px 16px; margin-bottom: 10px; background: var(--bg); }
  .at-card-title { font-size: 13px; font-weight: 500; margin-bottom: 10px; }
  .at-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; }
  .at-field { font-size: 13px; }
  .at-label { font-size: 11px; color: var(--text3); margin-bottom: 3px; }
  .at-val { color: var(--text); font-weight: 500; }
  .at-val.long { font-weight: 400; line-height: 1.55; color: var(--text2); }
  .tag { font-size: 11px; padding: 2px 8px; border-radius: var(--radius); background: var(--bg2); border: 0.5px solid var(--border); color: var(--text2); display: inline-block; margin: 2px 2px 0 0; }

  /* Empty state */
  .empty { text-align: center; padding: 48px 20px; color: var(--text3); }
  .empty-title { font-size: 15px; font-weight: 500; margin-bottom: 6px; color: var(--text2); }

  /* Running indicator */
  .running-badge { font-size: 11px; padding: 3px 10px; border-radius: var(--radius); background: var(--blue-bg); color: var(--blue-text); display: flex; align-items: center; gap: 6px; }
  @keyframes spin { to { transform: rotate(360deg); } }
  .spinner { width: 10px; height: 10px; border: 1.5px solid var(--blue-text); border-top-color: transparent; border-radius: 50%; animation: spin 0.7s linear infinite; }

  /* No partner selected */
  .no-selection { flex: 1; display: flex; align-items: center; justify-content: center; color: var(--text3); font-size: 14px; }
</style>
</head>
<body>
<div class="shell">

  <!-- SIDEBAR -->
  <div class="sidebar">
    <div class="sb-head" style="display:flex;align-items:center;justify-content:space-between;">
      <div>
        <div class="sb-logo">⚡ Vali</div>
        <div class="sb-sub">Clever certification dashboard</div>
      </div>
      <button class="btn" id="sync-btn" onclick="syncAirtable()" title="Re-sync Airtable data" style="padding:5px 10px;font-size:18px;line-height:1;border-radius:6px;">⟳</button>
    </div>
    <div class="sb-search">
      <input type="text" id="search" placeholder="Search partners..." oninput="filterPartners()" />
    </div>
    <div class="partner-list" id="partner-list">
      <div class="empty" style="padding: 24px 16px; font-size: 13px;">Loading partners...</div>
    </div>
  </div>

  <!-- MAIN -->
  <div class="main" id="main-area">
    <div class="no-selection">Select a partner to view their certification status</div>
  </div>

</div>

<script>
let allPartners = [];
let currentId = null;

// ---------------------------------------------------------------------------
// Boot — load all partners from Airtable on page load
// ---------------------------------------------------------------------------
async function boot() {
  try {
    const res = await fetch('/api/partners');
    allPartners = await res.json();
    renderSidebar(allPartners);
  } catch(e) {
    document.getElementById('partner-list').innerHTML =
      '<div class="empty" style="padding:24px 16px;font-size:13px;color:#E24B4A">Failed to load partners. Check your .env and try again.</div>';
  }
}

// ---------------------------------------------------------------------------
// Sidebar
// ---------------------------------------------------------------------------
function renderSidebar(partners) {
  const el = document.getElementById('partner-list');
  if (!partners.length) {
    el.innerHTML = '<div class="empty" style="padding:24px 16px;font-size:13px;">No partners found.</div>';
    return;
  }
  el.innerHTML = partners.map(p => `
    <div class="partner-item ${p.id === currentId ? 'active' : ''}" onclick="selectPartner('${p.id}')" id="si-${p.id}">
      <div class="p-dot dot-${(p.vali_status||'NOT RUN').replace(' ','_')}"></div>
      <div class="p-info">
        <div class="p-name">${p.app_name || p.name}</div>
        <div class="p-date" style="margin-top: 2px;">${p.name}</div>
        <div class="p-date">${formatDate(p.submitted_at)}</div>
      </div>
    </div>
  `).join('');
}

function filterPartners() {
  const q = document.getElementById('search').value.toLowerCase();
  renderSidebar(allPartners.filter(p => p.name.toLowerCase().includes(q) || (p.app_name||'').toLowerCase().includes(q)));
}

// ---------------------------------------------------------------------------
// Partner detail view
// ---------------------------------------------------------------------------
async function selectPartner(id) {
  currentId = id;
  document.querySelectorAll('.partner-item').forEach(el => {
    el.classList.toggle('active', el.id === `si-${id}`);
  });

  const partner = allPartners.find(p => p.id === id);
  if (!partner) return;
  renderMain(partner);
}

function renderMain(partner) {
  const report = partner.vali_report || {};
  const results = report.results || [];
  // Group results by category for rendering
  const pass  = results.filter(r => r.status === 'PASS').length;
  const fail  = results.filter(r => r.status === 'FAIL' || r.status === 'NEEDS_WORK').length;
  const skip  = results.filter(r => r.status === 'SKIPPED').length;
  const status = partner.vali_status || 'NOT RUN';

  document.getElementById('main-area').innerHTML = `
    <div class="topbar">
      <div>
        <div class="partner-title">${partner.name}</div>
        <div class="partner-meta">${partner.app_name ? partner.app_name + ' · ' : ''}Client ID: ${partner.client_id || '—'} · Submitted ${formatDate(partner.submitted_at)}</div>
      </div>
      <div class="topbar-actions">
        <span class="badge badge-${status.replace(' ','_')}" id="overall-badge">${status.replace('_',' ')}</span>
        ${status !== 'NOT RUN' ? `<button class="btn" onclick="exportReport('${partner.id}')">↓ Export report</button>` : ''}
        <button class="btn btn-primary" id="run-btn" onclick="runTests('${partner.id}')">▶ Run tests</button>
      </div>
    </div>

    <div class="tabs">
      <div class="tab active" onclick="switchTab('results', this)">Test results</div>
      <div class="tab" onclick="switchTab('airtable', this)">Airtable responses</div>
    </div>

    <div class="content">
      <div class="tab-panel active" id="tab-results">
        ${(status === 'NOT RUN' || !results.length)
          ? `<div class="empty"><div class="empty-title">No tests run yet</div>Click "Run tests" to validate this partner's integration.</div>`
          : `
          <div class="metrics">
            <div class="metric"><div class="metric-label">Tests run</div><div class="metric-val">${results.length}</div></div>
            <div class="metric"><div class="metric-label">Passed</div><div class="metric-val green">${pass}</div></div>
            <div class="metric"><div class="metric-label">Failed</div><div class="metric-val red">${fail}</div></div>
            <div class="metric"><div class="metric-label">Skipped</div><div class="metric-val">${skip}</div></div>
          </div>
          ${renderResultsByCategory(results)}
          `
        }
      </div>

      <div class="tab-panel" id="tab-airtable">
        ${renderAirtableFields(partner.fields)}
      </div>
    </div>
  `;
}

function renderResultsByCategory(results) {
  if (!results.length) return '<div style="font-size:13px;color:var(--color-text-tertiary,#888)">No results yet.</div>';
  // Group by category, preserving order of first appearance
  const categories = [];
  const byCategory = {};
  results.forEach(r => {
    const cat = r.category || 'General';
    if (!byCategory[cat]) { byCategory[cat] = []; categories.push(cat); }
    byCategory[cat].push(r);
  });
  return categories.map(cat =>
    `<div class="section-label">${cat}</div>` +
    byCategory[cat].map(r => resultCard(r)).join('')
  ).join('');
}

function resultCard(r) {
  const badgeClass = r.status === 'PASS' ? 'badge-PASS'
    : r.status === 'SKIPPED' ? 'badge-SKIPPED'
    : 'badge-FAIL';
  return `
    <div class="result-card">
      <div class="result-row" onclick="toggleDetail(this)">
        <span class="badge ${badgeClass}">${r.status}</span>
        <span class="result-name">${r.requirement}</span>
        <span class="chevron">▾</span>
      </div>
      <div class="result-detail">${r.details || '—'}</div>
    </div>`;
}

function renderAirtableFields(fields) {
  if (!fields || !Object.keys(fields).length) return '<div class="empty"><div class="empty-title">No Airtable data available</div></div>';

  const skip = new Set(['Vali Status','Vali Last Run','Vali Report']);
  const entries = Object.entries(fields).filter(([k]) => !skip.has(k));

  // Split into short fields (grid) and long fields (full width)
  const short = entries.filter(([,v]) => typeof v !== 'string' || v.length < 120);
  const long  = entries.filter(([,v]) => typeof v === 'string' && v.length >= 120);

  const renderVal = (v) => {
    if (Array.isArray(v)) return v.map(i => `<span class="tag">${i}</span>`).join('');
    if (typeof v === 'boolean') return v ? 'Yes' : 'No';
    return String(v);
  };

  return `
    <div class="at-card">
      <div class="at-card-title">Certification form responses</div>
      <div class="at-grid">
        ${short.map(([k,v]) => `
          <div class="at-field">
            <div class="at-label">${k}</div>
            <div class="at-val">${renderVal(v)}</div>
          </div>`).join('')}
      </div>
      ${long.map(([k,v]) => `
        <div class="at-field" style="margin-top:12px">
          <div class="at-label">${k}</div>
          <div class="at-val long">${v}</div>
        </div>`).join('')}
    </div>`;
}

// ---------------------------------------------------------------------------
// Run tests — polls until the background thread finishes, then refreshes
// ---------------------------------------------------------------------------
async function runTests(id) {
  const btn = document.getElementById('run-btn');
  const badge = document.getElementById('overall-badge');
  btn.disabled = true;
  btn.textContent = 'Running…';
  if (badge) { badge.className = 'running-badge'; badge.innerHTML = '<div class="spinner"></div> Running'; }

  try {
    await fetch(`/api/run/${id}`, { method: 'POST' });

    // Poll /api/status/:id every 2 seconds until the test thread is done.
    // The background thread in dashboard.py updates _running_tests when
    // it finishes, which this endpoint reflects.
    await pollUntilDone(id);

    // Now that the thread is done, fetch the freshly written Airtable data.
    await refreshPartner(id);
  } catch(e) {
    btn.disabled = false;
    btn.textContent = '▶ Run tests';
    alert('Test run failed. Check the terminal for details.');
  }
}

async function pollUntilDone(id, intervalMs=2000, maxAttempts=60) {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise(r => setTimeout(r, intervalMs));
    try {
      const res = await fetch(`/api/status/${id}`);
      const data = await res.json();
      if (data.status === 'done' || data.status === 'error') return;
    } catch(_) {}
  }
}

async function refreshPartner(id) {
  const refreshed = await fetch(`/api/partners/${id}`);
  const partner = await refreshed.json();
  const idx = allPartners.findIndex(p => p.id === id);
  if (idx !== -1) allPartners[idx] = partner;
  renderSidebar(allPartners.filter(p => {
    const q = document.getElementById('search').value.toLowerCase();
    return !q || p.name.toLowerCase().includes(q) || (p.app_name||'').toLowerCase().includes(q);
  }));
  renderMain(partner);
}

// ---------------------------------------------------------------------------
// Sync all partners from Airtable without losing current selection
// ---------------------------------------------------------------------------
async function syncAirtable() {
  const btn = document.getElementById('sync-btn');
  btn.textContent = '…';
  btn.disabled = true;
  try {
    const res = await fetch('/api/partners');
    allPartners = await res.json();
    const q = document.getElementById('search').value.toLowerCase();
    renderSidebar(allPartners.filter(p =>
      !q || p.name.toLowerCase().includes(q) || (p.app_name||'').toLowerCase().includes(q)
    ));
    // Re-render the current partner if one is selected
    if (currentId) {
      const current = allPartners.find(p => p.id === currentId);
      if (current) renderMain(current);
    }
  } catch(e) {
    alert('Sync failed. Check your connection and try again.');
  } finally {
    btn.textContent = '⟳';
    btn.disabled = false;
  }
}

// ---------------------------------------------------------------------------
// Export report
// ---------------------------------------------------------------------------
function exportReport(id) {
  window.open(`/api/report/${id}`, '_blank');
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------
function switchTab(name, el) {
  document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  document.getElementById(`tab-${name}`).classList.add('active');
}

function toggleDetail(row) {
  const detail = row.nextElementSibling;
  const chev = row.querySelector('.chevron');
  const open = detail.style.display === 'block';
  detail.style.display = open ? 'none' : 'block';
  chev.classList.toggle('open', !open);
}

function formatDate(iso) {
  if (!iso) return '—';
  try {
    return new Date(iso).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return iso; }
}

boot();
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# ROUTES
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template_string(DASHBOARD_HTML)


@app.route("/api/partners")
def api_partners():
    """Returns all partners from Airtable."""
    try:
        partners = get_all_partners()
        return jsonify(partners)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/partners/<record_id>")
def api_partner(record_id):
    """Returns a single partner by Airtable record ID."""
    try:
        partner = get_partner_by_id(record_id)
        return jsonify(partner)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/run/<record_id>", methods=["POST"])
def api_run_tests(record_id):
    """
    Runs Vali tests for a partner and writes results back to Airtable.
    Runs in a background thread so the dashboard stays responsive.
    """
    if record_id in _running_tests:
        return jsonify({"status": "already_running"}), 409

    try:
        partner = get_partner_by_id(record_id)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    _running_tests[record_id] = {"status": "running", "started": datetime.now(timezone.utc).isoformat()}

    def run():
        try:
            # Build config from partner's Airtable profile.
            # login_url comes from the partner's Airtable record (their app's login page).
            # callback_url is used for the raw OAuth probe tests.
            config = {
                "use_state":    True,
                "callback_url": partner.get("callback_url") or "",
                "login_url":    partner.get("login_url") or "",
                "data_file":    "diagnostic.json",
            }

            # Run all tests via the registry — one call handles everything.
            all_results, overall_pass = run_all_tests(config)
            overall_status = "PASS" if overall_pass else "NEEDS_WORK"
            write_vali_results(record_id, overall_status, all_results)
            _running_tests[record_id] = {"status": "done", "overall": overall_status}
            # Clear after a short delay so re-runs aren't blocked by the 409 guard
            import time as _time; _time.sleep(2); _running_tests.pop(record_id, None)

        except Exception as e:
            _running_tests[record_id] = {"status": "error", "message": str(e)}
            write_vali_results(record_id, "FAIL", [{"requirement": "Test runner error", "status": "FAIL", "details": str(e)}])
            import time as _time; _time.sleep(2); _running_tests.pop(record_id, None)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()

    return jsonify({"status": "started"})


@app.route("/api/status/<record_id>")
def api_status(record_id):
    """Returns the current status of a running test thread."""
    status = _running_tests.get(record_id, {"status": "not_started"})
    return jsonify(status)


@app.route("/api/report/<record_id>")
def api_report(record_id):
    """Downloads the full Vali report for a partner as a JSON file."""
    try:
        partner = get_partner_by_id(record_id)
        report = partner.get("vali_report", {})
        filename = f"vali_report_{partner['name'].replace(' ', '_')}_{datetime.now().strftime('%Y%m%d')}.json"
        return app.response_class(
            response=json.dumps(report, indent=2),
            status=200,
            mimetype="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500



# ---------------------------------------------------------------------------
# PARTNER MODE ROUTES
# A simplified self-service interface partners use to run tests themselves.
# No Airtable sidebar, no internal data — just the form and results.
# ---------------------------------------------------------------------------

# In-memory store for partner test runs (keyed by a random run ID)
_partner_runs = {}


@app.route("/partner")
def partner_index():
    return render_template_string(PARTNER_HTML)


@app.route("/partner/api/run", methods=["POST"])
def partner_run():
    """
    Starts a test run from the partner form.
    Accepts: { client_id, redirect_uri, login_url }
    Returns: { run_id } which the client polls for status.
    """
    import uuid
    data = request.get_json(silent=True) or {}

    client_id    = (data.get("client_id") or "").strip()
    redirect_uri = (data.get("redirect_uri") or "").strip()
    login_url    = (data.get("login_url") or "").strip()

    if not client_id or not redirect_uri:
        return jsonify({"error": "client_id and redirect_uri are required."}), 400

    run_id = str(uuid.uuid4())
    _partner_runs[run_id] = {"status": "running", "results": [], "overall": "NEEDS_WORK"}

    config = {
        "use_state":    True,
        "callback_url": redirect_uri,
        "login_url":    login_url,
        "data_file":    "diagnostic.json",
    }

    def run():
        try:
            results, overall_pass = run_all_tests(config)
            _partner_runs[run_id] = {
                "status":  "done",
                "results": results,
                "overall": "PASS" if overall_pass else "NEEDS_WORK",
            }
        except Exception as e:
            _partner_runs[run_id] = {
                "status":  "error",
                "results": [{"requirement": "Test runner error", "status": "FAIL",
                             "details": str(e), "category": "General"}],
                "overall": "NEEDS_WORK",
            }

    threading.Thread(target=run, daemon=True).start()
    return jsonify({"run_id": run_id})


@app.route("/partner/api/status/<run_id>")
def partner_status(run_id):
    """Returns the current status and results of a partner test run."""
    run = _partner_runs.get(run_id, {"status": "not_found"})
    return jsonify(run)


# ---------------------------------------------------------------------------
# STARTUP
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("="*50)
    print("⚡ Vali Internal Dashboard")
    print("="*50)
    print("Opening at http://localhost:5000")
    print("Press Ctrl+C to stop.")
    print()
    # host="0.0.0.0" binds to all network interfaces, which is required
    # for Docker port mapping to reach Flask from outside the container.
    # Defaults to 127.0.0.1 for local dev so behaviour is unchanged there.
    import os
    host = os.getenv("FLASK_RUN_HOST", "127.0.0.1")
    app.run(debug=True, host=host, port=5000)