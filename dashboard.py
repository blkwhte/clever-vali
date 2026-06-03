import json
import threading
from datetime import datetime, timezone
from flask import Flask, jsonify, render_template_string, request
from airtable_client import get_all_partners, get_partner_by_id, write_vali_results, get_mapped_fields

# Import the existing Vali test logic from your current vali.py.
# We're reusing the OAuth tests and data ingestion logic directly —
# no need to rewrite them.
from vali_core import test_oauth_security, evaluate_integration, load_diagnostic_data

app = Flask(__name__)

# In-memory store for test runs that are currently in progress.
# Key: Airtable record ID, Value: status dict
_running_tests = {}


# ---------------------------------------------------------------------------
# HTML TEMPLATE
# The entire dashboard UI lives here as a single-file template.
# ---------------------------------------------------------------------------
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
      <button class="btn" id="sync-btn" onclick="syncAirtable()" title="Re-sync Airtable" style="padding:5px 8px;font-size:12px;">⟳</button>
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
  const oauthResults = results.filter(r => r.requirement && r.requirement.startsWith('OAuth'));
  const dataResults  = results.filter(r => r.requirement && !r.requirement.startsWith('OAuth'));
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
        ${status === 'NOT RUN'
          ? `<div class="empty"><div class="empty-title">No tests run yet</div>Click "Run tests" to validate this partner's integration.</div>`
          : `
          <div class="metrics">
            <div class="metric"><div class="metric-label">Tests run</div><div class="metric-val">${results.length}</div></div>
            <div class="metric"><div class="metric-label">Passed</div><div class="metric-val green">${pass}</div></div>
            <div class="metric"><div class="metric-label">Failed</div><div class="metric-val red">${fail}</div></div>
            <div class="metric"><div class="metric-label">Skipped</div><div class="metric-val">${skip}</div></div>
          </div>
          <div class="section-label">OAuth security</div>
          ${oauthResults.map(r => resultCard(r)).join('') || '<div style="font-size:13px;color:var(--text3)">No OAuth results.</div>'}
          <div class="section-label">Data ingestion</div>
          ${dataResults.map(r => resultCard(r)).join('') || '<div style="font-size:13px;color:var(--text3)">No data ingestion results.</div>'}
          `
        }
      </div>

      <div class="tab-panel" id="tab-airtable">
        ${renderAirtableFields(partner.fields)}
      </div>
    </div>
  `;
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
            config = {
                "use_state": True,
                "callback_url": partner.get("callback_url") or "http://localhost:8080/auth/clever/callback",
                "data_file": "diagnostic.json",
            }

            # Run OAuth tests
            oauth_results = test_oauth_security(config)

            # Run data ingestion tests if a diagnostic file exists.
            # If it doesn't exist, skip gracefully — OAuth results still
            # get written back to Airtable so the run isn't lost entirely.
            data_results = []
            data_passed = True
            import os as _os
            if _os.path.exists(config["data_file"]):
                data = load_diagnostic_data(config["data_file"])
                if data:
                    data_results, data_passed = evaluate_integration(data)
            else:
                data_results.append({
                    "requirement": "Data ingestion tests",
                    "status": "SKIPPED",
                    "details": "No diagnostic.json file found — data ingestion tests were not run."
                })

            # Calculate overall pass/fail across whichever tests did run.
            failing = {"FAIL", "NEEDS_WORK"}
            oauth_passed = not any(r["status"] in failing for r in oauth_results)
            overall_pass = data_passed and oauth_passed
            overall_status = "PASS" if overall_pass else "NEEDS_WORK"

            all_results = oauth_results + data_results
            write_vali_results(record_id, overall_status, all_results)
            _running_tests[record_id] = {"status": "done", "overall": overall_status}

        except Exception as e:
            _running_tests[record_id] = {"status": "error", "message": str(e)}
            write_vali_results(record_id, "FAIL", [{"requirement": "Test runner error", "status": "FAIL", "details": str(e)}])

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
# STARTUP
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("="*50)
    print("⚡ Vali Internal Dashboard")
    print("="*50)
    print("Opening at http://localhost:5000")
    print("Press Ctrl+C to stop.")
    print()
    app.run(debug=True, port=5000)