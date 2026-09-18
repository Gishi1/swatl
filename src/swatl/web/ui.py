"""Web GUI module: redesigned multi-panel layout with tab navigation."""

from __future__ import annotations

html_page = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>swatl — Translation Studio</title>
<style>
:root {
  --bg: #0f1117; --fg: #e4e4e7; --muted: #71717a; --accent: #3b82f6;
  --green: #22c55e; --yellow: #eab308; --red: #ef4444; --border: #27272a;
  --card: #18181b; --hover: #1e1e24; --surface: #222228;
  --radius: 6px; --radius-lg: 8px; --radius-xl: 12px;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  background: var(--bg); color: var(--fg); line-height: 1.5; }

/* ── Top Bar ────────────────────────────────────────────────────── */
.topbar { display: flex; align-items: center; justify-content: space-between;
  padding: 10px 20px; border-bottom: 1px solid var(--border); background: var(--card); }
.topbar h1 { font-size: 16px; font-weight: 600; }
.topbar h1 span { color: var(--accent); }
.topbar .state-input { display: flex; gap: 8px; align-items: center; }
.topbar .state-input input {
  background: var(--bg); border: 1px solid var(--border); color: var(--fg);
  padding: 6px 12px; border-radius: var(--radius); font-size: 13px; width: 220px;
}
.topbar .state-input input:focus { outline: none; border-color: var(--accent); }

/* ── Tabs ───────────────────────────────────────────────────────── */
.tabs { display: flex; border-bottom: 1px solid var(--border); background: var(--card); }
.tab-btn {
  background: none; border: none; color: var(--muted); padding: 10px 20px;
  font-size: 13px; font-weight: 500; cursor: pointer; border-bottom: 2px solid transparent;
  transition: color 0.2s, border-color 0.2s;
}
.tab-btn:hover { color: var(--fg); }
.tab-btn.active { color: var(--accent); border-bottom-color: var(--accent); }

/* ── Main Layout ────────────────────────────────────────────────── */
.main { display: flex; height: calc(100vh - 96px); }
.sidebar { width: 220px; border-right: 1px solid var(--border); overflow-y: auto;
  background: var(--card); padding: 12px; flex-shrink: 0; }
.content { flex: 1; overflow-y: auto; padding: 20px; }

/* ── Sidebar ────────────────────────────────────────────────────── */
.sidebar h3 { font-size: 11px; text-transform: uppercase; color: var(--muted);
  margin: 16px 0 8px; letter-spacing: 0.05em; }
.sidebar h3:first-child { margin-top: 0; }
.nav-item { padding: 6px 10px; border-radius: var(--radius); font-size: 13px;
  cursor: pointer; color: var(--fg); display: flex; align-items: center; gap: 8px; }
.nav-item:hover { background: var(--hover); }
.nav-item.active { background: var(--accent); color: #fff; }
.sidebar .stats-mini { font-size: 12px; color: var(--muted); margin-top: 4px; }
.sidebar .stat-row { display: flex; justify-content: space-between; padding: 3px 0; }

/* ── Buttons ────────────────────────────────────────────────────── */
.btn { background: var(--accent); color: #fff; border: none; padding: 7px 14px;
  border-radius: var(--radius); cursor: pointer; font-size: 13px; font-weight: 500; }
.btn:hover { opacity: 0.85; }
.btn-sm { padding: 4px 10px; font-size: 12px; }
.btn-green { background: var(--green); }
.btn-yellow { background: var(--yellow); color: #000; }
.btn-red { background: var(--red); }
.btn-outline { background: transparent; border: 1px solid var(--border); color: var(--fg); }
.btn-outline:hover { border-color: var(--accent); }
.btn:disabled { opacity: 0.4; cursor: default; }

/* ── Segment List ───────────────────────────────────────────────── */
.toolbar { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
.toolbar input, .toolbar select {
  background: var(--bg); border: 1px solid var(--border); color: var(--fg);
  padding: 7px 12px; border-radius: var(--radius); font-size: 13px;
}
.toolbar input:focus, .toolbar select:focus { outline: none; border-color: var(--accent); }
.segment-list { display: flex; flex-direction: column; gap: 6px; }
.segment-card {
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg);
  padding: 14px; cursor: pointer; transition: border-color 0.2s;
}
.segment-card:hover { border-color: var(--accent); }
.segment-card.active { border-color: var(--accent); box-shadow: 0 0 0 1px var(--accent); }
.segment-card .top { display: flex; justify-content: space-between; align-items: center; }
.segment-card .id { font-size: 11px; color: var(--muted); font-family: monospace; }
.segment-card .badge { font-size: 10px; padding: 2px 8px; border-radius: 4px;
  font-weight: 600; text-transform: uppercase; }
.badge-pending { background: var(--border); color: var(--muted); }
.badge-translating { background: #1e3a5f; color: #60a5fa; }
.badge-translated { background: #1a3d2a; color: var(--green); }
.badge-proofread { background: #1a3d2a; color: var(--green); }
.badge-edited { background: #3d3a1a; color: var(--yellow); }
.badge-skipped { background: #3d3a1a; color: var(--yellow); }
.badge-failed { background: #3d1a1a; color: var(--red); }
.segment-card .source { font-size: 14px; margin-top: 8px; }
.segment-card .translation { font-size: 13px; color: var(--muted); margin-top: 4px; font-style: italic; }

/* ── Detail Panel (slide-in) ────────────────────────────────────── */
.detail-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.5); z-index: 99;
  display: none; }
.detail-overlay.open { display: block; }
.detail-panel { position: fixed; right: 0; top: 0; bottom: 0; width: 500px;
  background: var(--card); border-left: 1px solid var(--border); padding: 24px;
  overflow-y: auto; transform: translateX(100%); transition: transform 0.3s; z-index: 100; }
.detail-panel.open { transform: translateX(0); }
.detail-panel .close { position: absolute; top: 16px; right: 16px; background: none;
  border: none; color: var(--muted); font-size: 20px; cursor: pointer; }
.detail-panel h2 { font-size: 15px; margin-bottom: 16px; display: flex; align-items: center; gap: 10px; }
.detail-panel .field { margin-bottom: 14px; }
.detail-panel .field label { font-size: 11px; color: var(--muted); text-transform: uppercase;
  display: block; margin-bottom: 4px; }
.detail-panel .field .value { font-size: 14px; white-space: pre-wrap; word-break: break-word; }
.detail-panel textarea { width: 100%; min-height: 100px; background: var(--bg);
  border: 1px solid var(--border); color: var(--fg); padding: 10px; border-radius: var(--radius);
  font-size: 14px; font-family: inherit; resize: vertical; }
.detail-panel textarea:focus { outline: none; border-color: var(--accent); }
.detail-panel .actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; }

/* ── Context DB Tab ─────────────────────────────────────────────── */
.context-search { display: flex; gap: 10px; margin-bottom: 16px; }
.context-search input { flex: 1; }
.context-filters { display: flex; gap: 8px; margin-bottom: 12px; flex-wrap: wrap; }
.context-card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg);
  padding: 14px; margin-bottom: 8px; }
.context-card .meta { font-size: 11px; color: var(--muted); margin-bottom: 6px;
  display: flex; justify-content: space-between; align-items: center; }
.context-card .source-text { font-size: 14px; margin-bottom: 4px; }
.context-card .target-text { font-size: 13px; color: var(--muted); font-style: italic; }
.context-card .tags { display: flex; gap: 4px; margin-top: 8px; flex-wrap: wrap; }
.tag { font-size: 10px; padding: 2px 6px; border-radius: 3px; background: var(--border); color: var(--muted); }
.context-card .actions { display: flex; gap: 6px; margin-top: 8px; }
.context-card .actions button { font-size: 11px; padding: 3px 8px; }

/* ── Glossary Tab ───────────────────────────────────────────────── */
.glossary-entry { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg);
  padding: 12px 14px; margin-bottom: 8px; display: flex; justify-content: space-between; align-items: center; }
.glossary-entry .terms { display: flex; flex-direction: column; gap: 2px; }
.glossary-entry .source { font-weight: 600; }
.glossary-entry .target { color: var(--accent); }

/* ── Settings Tab ───────────────────────────────────────────────── */
.settings-card { background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-lg);
  padding: 20px; margin-bottom: 16px; }
.settings-card h3 { font-size: 14px; margin-bottom: 12px; }
.form-group { margin-bottom: 12px; }
.form-group label { font-size: 12px; color: var(--muted); display: block; margin-bottom: 4px; }
.form-group input, .form-group select {
  width: 100%; background: var(--bg); border: 1px solid var(--border); color: var(--fg);
  padding: 8px 12px; border-radius: var(--radius); font-size: 13px;
}
.form-group input:focus, .form-group select:focus { outline: none; border-color: var(--accent); }

/* ── Modal ──────────────────────────────────────────────────────── */
.modal { position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
  background: var(--card); border: 1px solid var(--border); border-radius: var(--radius-xl);
  padding: 24px; width: 420px; max-width: 90vw; z-index: 200; display: none; }
.modal.open { display: block; }
.modal h3 { margin-bottom: 16px; }
.modal .actions { display: flex; gap: 8px; justify-content: flex-end; margin-top: 16px; }

/* ── Toast ──────────────────────────────────────────────────────── */
#toast { position: fixed; bottom: 24px; left: 50%; transform: translateX(-50%);
  background: var(--green); color: #fff; padding: 8px 20px; border-radius: var(--radius);
  font-size: 13px; font-weight: 500; opacity: 0; transition: opacity 0.3s; z-index: 300; }
#toast.show { opacity: 1; }
#toast.error { background: var(--red); }

/* ── Empty State ────────────────────────────────────────────────── */
.empty-state { text-align: center; padding: 48px; color: var(--muted); }

/* ── Import Flow ────────────────────────────────────────────────── */
.import-section { margin-bottom: 16px; }
.import-section h4 { font-size: 13px; margin-bottom: 8px; color: var(--fg); }
.chunk-preview { background: var(--bg); border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px; margin-bottom: 8px; font-size: 13px; }
.chunk-preview .chunk-header { font-size: 11px; color: var(--muted); margin-bottom: 4px;
  display: flex; justify-content: space-between; }
.chunk-preview textarea { width: 100%; min-height: 60px; background: var(--card);
  border: 1px solid var(--border); color: var(--fg); padding: 8px; border-radius: var(--radius);
  font-size: 13px; margin-top: 6px; resize: vertical; }
.chunk-preview textarea:focus { outline: none; border-color: var(--accent); }

/* ── Progress ───────────────────────────────────────────────────── */
.progress-bar { width: 100%; height: 6px; background: var(--border); border-radius: 3px; margin-top: 8px; }
.progress-bar .fill { height: 100%; background: var(--accent); border-radius: 3px; transition: width 0.3s; }

/* ── Tab panels ─────────────────────────────────────────────────── */
.tab-panel { display: none; }
.tab-panel.active { display: block; }
</style>
</head>
<body>
<!-- Top Bar -->
<div class="topbar">
  <h1><span>swatl</span> — Translation Studio</h1>
  <div class="state-input">
    <input type="text" id="stateDir" placeholder="State dir" value=".swatl-state"
      oninput="syncStateDir(this.value)" onkeydown="if(event.key==='Enter'){loadState()}">
    <button class="btn" onclick="loadState()">Load</button>
  </div>
</div>

<!-- Tabs -->
<div class="tabs">
  <button class="tab-btn active" data-tab="segments" onclick="switchTab('segments')">Segments</button>
  <button class="tab-btn" data-tab="context" onclick="switchTab('context')">Context DB</button>
  <button class="tab-btn" data-tab="glossary" onclick="switchTab('glossary')">Glossary</button>
  <button class="tab-btn" data-tab="settings" onclick="switchTab('settings')">Settings</button>
</div>

<!-- Main Content -->
<div class="main">
  <!-- Sidebar -->
  <div class="sidebar">
    <h3>Navigation</h3>
    <div id="sidebarNav">
      <div class="nav-item active" data-section="all" onclick="resetFilters()">All Segments</div>
    </div>
    <h3>Progress</h3>
    <div id="sidebarStats">
      <div class="stat-row"><span>Total</span><span id="statTotal">—</span></div>
      <div class="stat-row"><span>Translated</span><span id="statTranslated" style="color:var(--green)">—</span></div>
      <div class="stat-row"><span>Proofread</span><span id="statProofread">—</span></div>
      <div class="stat-row"><span>Failed</span><span id="statFailed" style="color:var(--red)">—</span></div>
    </div>
    <h3>Context DB</h3>
    <div class="stat-row" style="cursor:pointer" onclick="switchTab('context')">
      <span>Entries</span><span id="statContext">—</span>
    </div>
    <button class="btn btn-sm btn-outline" style="width:100%;margin-top:8px" onclick="prefillContext()">
      Prefill from Segments
    </button>
  </div>

  <!-- Content Panels -->
  <div class="content">
    <!-- ═══ Segments Tab ═══ -->
    <div class="tab-panel active" id="panel-segments">
      <div class="toolbar">
        <input type="text" id="filter" placeholder="Search source or translation..." oninput="onFilterInput()">
        <select id="statusFilter" onchange="loadState()">
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="translating">Translating</option>
          <option value="translated">Translated</option>
          <option value="proofread">Proofread</option>
          <option value="edited">Edited</option>
          <option value="skipped">Skipped</option>
          <option value="failed">Failed</option>
        </select>
        <span id="segCount" style="color:var(--muted);font-size:12px;align-self:center"></span>
        <button class="btn btn-sm btn-outline" onclick="loadState()">Refresh</button>
      </div>
      <div class="segment-list" id="segmentList"></div>
    </div>

    <!-- ═══ Context DB Tab ═══ -->
    <div class="tab-panel" id="panel-context">
      <div class="context-search">
        <input type="text" id="ctxSearch" placeholder="Search context entries..." oninput="renderContextEntries()">
        <button class="btn btn-sm" onclick="showImportModal()">Import</button>
        <button class="btn btn-sm btn-outline" onclick="showAddEntryModal()">+ Add</button>
      </div>
      <div class="context-filters">
        <button class="btn btn-sm btn-outline ctx-filter active" data-type="">All</button>
        <button class="btn btn-sm btn-outline ctx-filter" data-type="segment">From Segments</button>
        <button class="btn btn-sm btn-outline ctx-filter" data-type="prefill">Prefilled</button>
        <button class="btn btn-sm btn-outline ctx-filter" data-type="manual">Manual</button>
      </div>
      <div id="contextList"></div>
    </div>

    <!-- ═══ Glossary Tab ═══ -->
    <div class="tab-panel" id="panel-glossary">
      <div class="toolbar">
        <button class="btn btn-sm" onclick="showGlossaryModal()">+ Add Term</button>
        <button class="btn btn-sm btn-outline" onclick="loadGlossary()">Refresh</button>
      </div>
      <div id="glossaryList"></div>
    </div>

    <!-- ═══ Settings Tab ═══ -->
    <div class="tab-panel" id="panel-settings">
      <div class="settings-card">
        <h3>Provider Configuration</h3>
        <div id="providerList"></div>
        <button class="btn btn-sm btn-outline" style="margin-top:12px" onclick="showConfigModal()">+ Add Provider</button>
      </div>
      <div class="settings-card">
        <h3>State Directory</h3>
        <div class="form-group">
          <label>State Dir</label>
          <input type="text" id="settingsStateDir" value=".swatl-state"
            oninput="syncStateDir(this.value)" onkeydown="if(event.key==='Enter'){loadState()}">
          <div style="margin-top:10px;display:flex;gap:8px">
            <button class="btn btn-sm" onclick="loadState()">Load segments</button>
            <button class="btn btn-sm btn-outline" onclick="loadGlossary(); loadProviders();">Reload all tabs</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</div>

<!-- Detail Panel -->
<div class="detail-overlay" id="detailOverlay" onclick="closeDetail()"></div>
<div class="detail-panel" id="detailPanel">
  <button class="close" onclick="closeDetail()">✕</button>
  <div id="detailContent"></div>
</div>

<!-- Config Modal -->
<div class="modal" id="configModal">
  <h3>Add Provider</h3>
  <div class="form-group"><label>Name</label><input id="cfgName" placeholder="myprovider"></div>
  <div class="form-group"><label>Base URL</label><input id="cfgUrl" placeholder="https://api.openai.com"></div>
  <div class="form-group"><label>Model</label><input id="cfgModel" placeholder="gpt-4o"></div>
  <div class="form-group"><label>API Key Env Var</label><input id="cfgKeyEnv" placeholder="OPENAI_API_KEY"></div>
  <div class="actions">
    <button class="btn btn-sm btn-outline" onclick="hideConfigModal()">Cancel</button>
    <button class="btn btn-sm btn-green" onclick="saveProvider()">Save</button>
  </div>
</div>

<!-- Add Context Entry Modal -->
<div class="modal" id="addContextModal">
  <h3>Add Context Entry</h3>
  <div class="form-group"><label>Source Text</label><textarea id="ctxSource" style="width:100%;min-height:60px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px;resize:vertical;font-family:inherit"></textarea></div>
  <div class="form-group"><label>Translation (optional)</label><textarea id="ctxTarget" style="width:100%;min-height:60px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px;resize:vertical;font-family:inherit"></textarea></div>
  <div class="form-group"><label>Type</label>
    <select id="ctxType" style="width:100%;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px">
      <option value="manual">Manual</option>
      <option value="prefill">Prefill</option>
      <option value="segment">From Segment</option>
      <option value="curated">Curated</option>
    </select>
  </div>
  <div class="form-group"><label>Tags (comma-separated)</label><input id="ctxTags" placeholder="sci-fi, terminology"></div>
  <div class="actions">
    <button class="btn btn-sm btn-outline" onclick="hideAddContextModal()">Cancel</button>
    <button class="btn btn-sm btn-green" onclick="saveContextEntry()">Save</button>
  </div>
</div>

<!-- Edit Context Entry Modal -->
<div class="modal" id="editContextModal">
  <h3>Edit Context Entry</h3>
  <input type="hidden" id="editCtxId">
  <div class="form-group"><label>Source Text</label><textarea id="editCtxSource" style="width:100%;min-height:60px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px;resize:vertical;font-family:inherit"></textarea></div>
  <div class="form-group"><label>Translation</label><textarea id="editCtxTarget" style="width:100%;min-height:60px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px;resize:vertical;font-family:inherit"></textarea></div>
  <div class="form-group"><label>Tags (comma-separated)</label><input id="editCtxTags" placeholder="tag1, tag2"></div>
  <div class="actions">
    <button class="btn btn-sm btn-outline" onclick="hideEditContextModal()">Cancel</button>
    <button class="btn btn-sm btn-green" onclick="updateContextEntry()">Update</button>
  </div>
</div>

<!-- Import Modal -->
<div class="modal" id="importModal" style="width:520px">
  <h3>Import Context</h3>
  <div class="import-section">
    <h4>Import from Text</h4>
    <textarea id="importText" style="width:100%;min-height:80px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px;resize:vertical;font-family:inherit" placeholder="Paste text here..."></textarea>
    <div style="display:flex;gap:8px;margin-top:8px;align-items:center">
      <input type="text" id="importSource" placeholder="Source name" value="imported_text" style="flex:1;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:6px 10px;border-radius:var(--radius);font-size:12px">
      <input type="number" id="importChunkSize" value="500" style="width:70px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:6px 10px;border-radius:var(--radius);font-size:12px" placeholder="Chunk size">
      <input type="number" id="importOverlap" value="100" style="width:70px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:6px 10px;border-radius:var(--radius);font-size:12px" placeholder="Overlap">
    </div>
    <button class="btn btn-sm btn-green" style="margin-top:8px" onclick="doImportText()">Import & Chunk</button>
  </div>
  <div class="import-section">
    <h4>Import JSON/CSV</h4>
    <textarea id="importJSON" style="width:100%;min-height:60px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:8px;border-radius:var(--radius);font-size:13px;resize:vertical;font-family:inherit" placeholder='[{"source":"...","target":"..."}]'></textarea>
    <input type="text" id="importJsonSource" placeholder="Source name" value="import.json" style="width:100%;margin-top:6px;background:var(--bg);border:1px solid var(--border);color:var(--fg);padding:6px 10px;border-radius:var(--radius);font-size:12px">
    <button class="btn btn-sm btn-green" style="margin-top:8px" onclick="doImportJSON()">Import JSON</button>
  </div>
  <div class="actions">
    <button class="btn btn-sm btn-outline" onclick="hideImportModal()">Close</button>
  </div>
</div>

<!-- Glossary Modal -->
<div class="modal" id="glossaryModal">
  <h3>Add Glossary Term</h3>
  <div class="form-group"><label>Source Term</label><input id="glossSource" placeholder="三体"></div>
  <div class="form-group"><label>Target Translation</label><input id="glossTarget" placeholder="Three-Body"></div>
  <div class="form-group"><label>Domain (optional)</label><input id="glossDomain" placeholder="sci-fi"></div>
  <div class="actions">
    <button class="btn btn-sm btn-outline" onclick="hideGlossaryModal()">Cancel</button>
    <button class="btn btn-sm btn-green" onclick="saveGlossaryEntry()">Save</button>
  </div>
</div>

<div id="toast"></div>

<script>
let segments = [];
let contextEntries = [];
let glossary = { entries: [] };
let activeSeg = null;
let ctxFilterType = "";
let segPage = 1;
let segTotal = 0;
let segTotalPages = 0;
let stateDirMissing = false;
let filterTimer = null;

const API = '/api';
const SEG_PAGE_SIZE = 100;
const STATE_DIR_KEY = 'swatl.stateDir';

// ── API helpers ─────────────────────────────────────────────────
function getStateDir() {
  return (document.getElementById('stateDir').value || '.swatl-state').trim();
}

function syncStateDir(v) {
  const main = document.getElementById('stateDir');
  const settings = document.getElementById('settingsStateDir');
  if (main.value !== v) main.value = v;
  if (settings.value !== v) settings.value = v;
  try { localStorage.setItem(STATE_DIR_KEY, v); } catch(e) { /* private mode */ }
}

function restoreStateDir() {
  let saved = null;
  try { saved = localStorage.getItem(STATE_DIR_KEY); } catch(e) { /* ignore */ }
  if (saved) syncStateDir(saved);
}

function resetFilters() {
  document.getElementById('filter').value = '';
  document.getElementById('statusFilter').value = '';
  loadState();
}

async function api(method, pathOrUrl, opts) {
  let url = API + pathOrUrl;
  const fetchOpts = { method, headers: {'Content-Type':'application/json'} };
  if (opts) {
    if (opts.params) {
      const qs = new URLSearchParams(opts.params).toString();
      if (qs) url += '?' + qs;
    }
    if (opts.body) {
      if (opts.body instanceof FormData) {
        fetchOpts.body = opts.body;
        delete fetchOpts.headers['Content-Type'];
      } else {
        fetchOpts.body = JSON.stringify(opts.body);
      }
    }
  }
  const r = await fetch(url, fetchOpts);
  if (!r.ok) {
    let msg = r.statusText || ('HTTP ' + r.status);
    try { const j = await r.json(); if (j && j.detail) msg = j.detail; } catch(e) { /* not JSON */ }
    throw new Error(msg);
  }
  if (r.status === 204) return null;
  return r.json();
}

function toast(msg, isError) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = isError ? 'show error' : 'show';
  setTimeout(() => t.className = '', 2500);
}

// ── Tab switching ────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-btn').forEach(b => b.classList.toggle('active', b.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.toggle('active', p.id === 'panel-' + name));
  if (name === 'context') loadContextEntries();
  if (name === 'glossary') loadGlossary();
  if (name === 'settings') loadProviders();
}

// ── Load state ───────────────────────────────────────────────────
function onFilterInput() {
  clearTimeout(filterTimer);
  filterTimer = setTimeout(() => loadState(), 250);
}

async function loadState(opts) {
  const reset = !opts || opts.reset !== false;
  const sd = getStateDir();
  if (reset) segPage = 1;
  try {
    const params = { state_dir: sd, page: segPage, page_size: SEG_PAGE_SIZE };
    const status = document.getElementById('statusFilter').value;
    const q = document.getElementById('filter').value.trim();
    if (status) params.status = status;
    if (q) params.q = q;

    const data = await api('GET', '/segments', { params });
    segments = reset ? data.segments : segments.concat(data.segments);
    segTotal = data.total;
    segTotalPages = data.total_pages;
    stateDirMissing = data.state_dir_exists === false;
    const label = document.getElementById('segCount');
    if (label) label.textContent = `${segments.length} of ${segTotal} segment${segTotal === 1 ? '' : 's'}`;
    renderSegments();
    await refreshStats();
  } catch(e) {
    toast('Failed to load state: ' + e.message, true);
    document.getElementById('segmentList').innerHTML =
      '<div class="empty-state">Could not load state directory.</div>';
  }
}

async function refresh() { await loadState(); }

async function refreshStats() {
  try {
    const stats = await api('GET', '/stats', { params: { state_dir: getStateDir() } });
    const counts = stats.by_status || {};
    document.getElementById('statTotal').textContent = stats.total;
    document.getElementById('statTranslated').textContent =
      (counts['translated']||0) + (counts['proofread']||0) + (counts['edited']||0);
    document.getElementById('statProofread').textContent = counts['proofread']||0;
    document.getElementById('statFailed').textContent = counts['failed']||0;
  } catch(e) { /* stats are advisory */ }
  try {
    const ctx = await api('GET', '/context/stats', { params: { state_dir: getStateDir() } });
    document.getElementById('statContext').textContent = ctx.total;
  } catch(e) { /* stats are advisory */ }
}

function loadMore() {
  if (segPage >= segTotalPages) return;
  segPage += 1;
  loadState({ reset: false });
}

// ── Segment rendering ────────────────────────────────────────────
function badgeClass(status) { return 'badge-' + (status||'pending'); }

function renderSegments() {
  const list = document.getElementById('segmentList');
  if (!segments.length) {
    list.innerHTML = stateDirMissing
      ? `<div class="empty-state">State directory not found:<br><code>${escHtml(getStateDir())}</code><br><br>Run <code>swatl translate &lt;book.epub&gt; --state ${escHtml(getStateDir())}</code> first, or pick another directory above.</div>`
      : '<div class="empty-state">No segments match this filter.</div>';
    return;
  }
  list.innerHTML = segments.map(s => `
    <div class="segment-card ${activeSeg && activeSeg.id===s.id?'active':''}" onclick="showDetail('${s.id}')">
      <div class="top">
        <span class="id">${escHtml(s.id)} · ${escHtml(s.doc)}</span>
        <span class="badge ${badgeClass(s.status)}">${escHtml(s.status)}</span>
      </div>
      <div class="source">${escHtml(s.source_text||'')}</div>
      ${s.translated ? '<div class="translation">' + escHtml(s.translated.substring(0,150)) + (s.translated.length>150?'...':'') + '</div>' : ''}
    </div>`).join('') + (segPage < segTotalPages
      ? `<div style="text-align:center;margin-top:14px">
           <button class="btn btn-sm btn-outline" onclick="loadMore()">Load more (${segments.length} / ${segTotal})</button>
         </div>`
      : '');
}

function escHtml(t) {
  return String(t)
    .replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;')
    .replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

// ── Detail panel ─────────────────────────────────────────────────
async function showDetail(id) {
  let seg = segments.find(s => s.id === id);
  if (!seg) {
    try {
      seg = await api('GET', `/segment/${encodeURIComponent(id)}`, { params: { state_dir: getStateDir() } });
    } catch(e) { toast('Could not load segment: ' + e.message, true); return; }
  }
  if (!seg) return;
  activeSeg = seg;
  document.getElementById('detailOverlay').className = 'detail-overlay open';
  document.getElementById('detailPanel').className = 'detail-panel open';
  const canEdit = ['translated','proofread','edited'].includes(seg.status);
  document.getElementById('detailContent').innerHTML = `
    <h2>${escHtml(seg.id)} <span class="badge ${badgeClass(seg.status)}">${escHtml(seg.status)}</span></h2>
    <div class="field"><label>Document</label><div class="value">${escHtml(seg.doc)} (${escHtml(seg.anchor)})</div></div>
    <div class="field"><label>Source</label><div class="value">${escHtml(seg.source_text)}</div></div>
    <div class="field"><label>Translation</label>
      <textarea id="editTranslation" ${canEdit?'':'disabled'}>${escHtml(seg.translated||'')}</textarea></div>
    ${seg.glossary_hits?.length ? '<div class="field"><label>Glossary hits</label><div class="value">' + escHtml(seg.glossary_hits.join(', ')) + '</div></div>' : ''}
    <div class="actions">
      ${seg.status !== 'pending' ? `<button class="btn btn-sm btn-outline" onclick="regenerate('${seg.id}')">Regenerate</button>` : ''}
      <button class="btn btn-sm btn-green" onclick="acceptSeg('${seg.id}')">Accept</button>
      <button class="btn btn-sm btn-yellow" onclick="skipSeg('${seg.id}')">Skip</button>
      ${canEdit ? `<button class="btn btn-sm btn-red" onclick="saveTranslation('${seg.id}')">Save</button>` : ''}
    </div>`;
}

function closeDetail() {
  document.getElementById('detailOverlay').className = 'detail-overlay';
  document.getElementById('detailPanel').className = 'detail-panel';
  activeSeg = null;
}

async function saveTranslation(id) {
  const text = document.getElementById('editTranslation').value;
  try {
    await api('PATCH', `/segment/${encodeURIComponent(id)}`,
      { params: { state_dir: getStateDir() }, body: { translated: text } });
    toast('Translation saved');
    await loadState();
    await showDetail(id);
  } catch(e) { toast('Save failed: ' + e.message, true); }
}

async function acceptSeg(id) {
  try {
    await api('POST', `/accept/${encodeURIComponent(id)}`, { params: { state_dir: getStateDir() } });
    toast('Segment accepted');
    await loadState();
    await showDetail(id);
  } catch(e) { toast(e.message, true); }
}

async function skipSeg(id) {
  try {
    await api('POST', `/skip/${encodeURIComponent(id)}`, { params: { state_dir: getStateDir() } });
    toast('Segment skipped');
    await loadState();
    await showDetail(id);
  } catch(e) { toast(e.message, true); }
}

async function regenerate(id) {
  if (!confirm('Reset this segment to pending so it is re-translated on the next run?')) return;
  try {
    await api('POST', `/regenerate/${encodeURIComponent(id)}`, { params: { state_dir: getStateDir() } });
    toast('Segment queued for regeneration');
    await loadState();
    await showDetail(id);
  } catch(e) { toast(e.message, true); }
}

// ── Keyboard shortcuts ──────────────────────────────────────────
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') { closeDetail(); hideConfigModal(); hideAddContextModal(); hideEditContextModal(); hideImportModal(); hideGlossaryModal(); }
  if (e.key === 'f' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); document.getElementById('filter').focus(); }
  if (e.key === '1' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); switchTab('segments'); }
  if (e.key === '2' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); switchTab('context'); }
  if (e.key === '3' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); switchTab('glossary'); }
  if (e.key === '4' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); switchTab('settings'); }
});

// ── Context DB ───────────────────────────────────────────────────
async function loadContextEntries() {
  const sd = getStateDir();
  try {
    contextEntries = await api('GET', '/context', {params: {state_dir: sd}});
    renderContextEntries();
    document.getElementById('statContext').textContent = contextEntries.length;
  } catch(e) { toast('Failed to load context: ' + e.message, true); }
}

function renderContextEntries() {
  const q = (document.getElementById('ctxSearch')?.value || '').toLowerCase();
  let entries = contextEntries;
  if (ctxFilterType) entries = entries.filter(e => e.entry_type === ctxFilterType);
  if (q) entries = entries.filter(e =>
    e.source_text.toLowerCase().includes(q) ||
    (e.translated_text||'').toLowerCase().includes(q) ||
    e.tags?.some(t => t.toLowerCase().includes(q))
  );
  const list = document.getElementById('contextList');
  if (!entries.length) { list.innerHTML = '<div class="empty-state">No context entries found.</div>'; return; }
  list.innerHTML = entries.map(e => `
    <div class="context-card">
      <div class="meta">
        <span>#${e.id} · ${e.entry_type}${e.source_file ? ' · ' + escHtml(e.source_file) : ''}</span>
        <span>${new Date(e.updated_at).toLocaleDateString()}</span>
      </div>
      <div class="source-text">${escHtml(e.source_text.substring(0, 300))}${e.source_text.length > 300 ? '...' : ''}</div>
      ${e.translated_text ? '<div class="target-text">' + escHtml(e.translated_text) + '</div>' : ''}
      ${e.tags?.length ? '<div class="tags">' + e.tags.map(t => '<span class="tag">' + escHtml(t) + '</span>').join('') + '</div>' : ''}
      <div class="actions">
        <button class="btn btn-sm btn-outline" onclick="editContextEntry('${e.id}')">✎ Edit</button>
        <button class="btn btn-sm btn-red" onclick="deleteContextEntry('${e.id}')">🗑</button>
      </div>
    </div>`).join('');
}

// Context filter buttons
document.addEventListener('click', function(e) {
  if (e.target.classList.contains('ctx-filter')) {
    document.querySelectorAll('.ctx-filter').forEach(b => b.classList.remove('active'));
    e.target.classList.add('active');
    ctxFilterType = e.target.dataset.type;
    renderContextEntries();
  }
});

async function showAddEntryModal() {
  document.getElementById('addContextModal').className = 'modal open';
}
function hideAddContextModal() {
  document.getElementById('addContextModal').className = 'modal';
}

async function saveContextEntry() {
  const entry = {
    source_text: document.getElementById('ctxSource').value,
    translated_text: document.getElementById('ctxTarget').value || null,
    entry_type: document.getElementById('ctxType').value,
    tags: document.getElementById('ctxTags').value.split(',').map(s => s.trim()).filter(Boolean),
  };
  if (!entry.source_text) { toast('Source text is required', true); return; }
  try {
    await api('POST', '/context', {params: {state_dir: getStateDir()}, body: entry});
    toast('Context entry added');
    hideAddContextModal();
    loadContextEntries();
  } catch(e) { toast(e.message, true); }
}

async function editContextEntry(id) {
  const entry = contextEntries.find(e => e.id === id);
  if (!entry) return;
  document.getElementById('editCtxId').value = id;
  document.getElementById('editCtxSource').value = entry.source_text;
  document.getElementById('editCtxTarget').value = entry.translated_text || '';
  document.getElementById('editCtxTags').value = (entry.tags || []).join(', ');
  document.getElementById('editContextModal').className = 'modal open';
}

function hideEditContextModal() {
  document.getElementById('editContextModal').className = 'modal';
}

async function updateContextEntry() {
  const id = document.getElementById('editCtxId').value;
  const body = {
    source_text: document.getElementById('editCtxSource').value,
    translated_text: document.getElementById('editCtxTarget').value || null,
    tags: document.getElementById('editCtxTags').value.split(',').map(s => s.trim()).filter(Boolean),
  };
  try {
    await api('PATCH', '/context/' + id, {params: {state_dir: getStateDir()}, body: body});
    toast('Context entry updated');
    hideEditContextModal();
    loadContextEntries();
  } catch(e) { toast(e.message, true); }
}

async function deleteContextEntry(id) {
  if (!confirm('Delete this context entry?')) return;
  try {
    await api('DELETE', '/context/' + id, {params: {state_dir: getStateDir()}});
    toast('Context entry deleted');
    loadContextEntries();
  } catch(e) { toast(e.message, true); }
}

// ── Import ────────────────────────────────────────────────────────
function showImportModal() { document.getElementById('importModal').className = 'modal open'; }
function hideImportModal() { document.getElementById('importModal').className = 'modal'; }

async function doImportText() {
  const text = document.getElementById('importText').value;
  const source = document.getElementById('importSource').value || 'text';
  const chunkSize = parseInt(document.getElementById('importChunkSize').value) || 500;
  const overlap = parseInt(document.getElementById('importOverlap').value) || 100;
  const sd = getStateDir();
  const formData = new FormData();
  formData.append('text', text);
  formData.append('source_name', source);
  formData.append('chunk_size', chunkSize);
  formData.append('overlap', overlap);
  try {
    const r = await fetch(API + '/context/import/text?state_dir=' + encodeURIComponent(sd), {
      method: 'POST', body: formData,
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    toast(`Imported ${data.entries_created} chunks`);
    hideImportModal();
    loadContextEntries();
  } catch(e) { toast('Import failed: ' + e.message, true); }
}

async function doImportJSON() {
  const content = document.getElementById('importJSON').value;
  const source = document.getElementById('importJsonSource').value || 'import.json';
  const sd = getStateDir();
  const formData = new FormData();
  formData.append('content', content);
  formData.append('source_name', source);
  try {
    const r = await fetch(API + '/context/import/json?state_dir=' + encodeURIComponent(sd), {
      method: 'POST', body: formData,
    });
    if (!r.ok) throw new Error(await r.text());
    const data = await r.json();
    toast(`Imported ${data.entries_created} entries`);
    hideImportModal();
    loadContextEntries();
  } catch(e) { toast('Import failed: ' + e.message, true); }
}

// ── Prefill ───────────────────────────────────────────────────────
async function prefillContext() {
  try {
    const data = await api('POST', '/context/prefill', {params: {state_dir: getStateDir()}});
    toast(`Prefilled ${data.entries_created} entries from segments`);
    loadContextEntries();
  } catch(e) { toast('Prefill failed: ' + e.message, true); }
}

// ── Glossary ──────────────────────────────────────────────────────
async function loadGlossary() {
  const sd = getStateDir();
  try {
    glossary = await api('GET', '/glossary', {params: {state_dir: sd}});
    renderGlossary();
  } catch(e) {
    document.getElementById('glossaryList').innerHTML =
      '<div class="empty-state">No glossary found. Use the + Add Term button.</div>';
  }
}

function renderGlossary() {
  const container = document.getElementById('glossaryList');
  if (!glossary || !glossary.entries || glossary.entries.length === 0) {
    container.innerHTML = '<div class="empty-state">No glossary terms yet. Click "+ Add Term" to add one.</div>';
    return;
  }
  container.innerHTML = glossary.entries.map((e, i) => `
    <div class="glossary-entry">
      <div class="terms">
        <span class="source">${escHtml(e.source)}</span>
        <span class="target">${escHtml(e.target)}${e.domain ? ' <span style="color:var(--muted)">(' + escHtml(e.domain) + ')</span>' : ''}</span>
      </div>
      <button class="btn btn-sm btn-red" onclick="deleteGlossaryTerm(${i})">✕</button>
    </div>`).join('');
}

function showGlossaryModal() { document.getElementById('glossaryModal').className = 'modal open'; }
function hideGlossaryModal() { document.getElementById('glossaryModal').className = 'modal'; }

async function saveGlossaryEntry() {
  const source = document.getElementById('glossSource').value.trim();
  const target = document.getElementById('glossTarget').value.trim();
  const domain = document.getElementById('glossDomain').value.trim();
  if (!source || !target) { toast('Source and Target are required', true); return; }
  try {
    await api('POST', '/glossary', {params: {state_dir: getStateDir()}, body: {source, target, domain}});
    toast('Term added');
    hideGlossaryModal();
    document.getElementById('glossSource').value = '';
    document.getElementById('glossTarget').value = '';
    document.getElementById('glossDomain').value = '';
    loadGlossary();
  } catch(e) { toast('Failed: ' + e.message, true); }
}

async function deleteGlossaryTerm(index) {
  if (!confirm('Remove this term from glossary?')) return;
  try {
    await api('DELETE', '/glossary/' + index, {params: {state_dir: getStateDir()}});
    toast('Term removed');
    loadGlossary();
  } catch(e) { toast('Failed: ' + e.message, true); }
}

// ── Settings / Providers ──────────────────────────────────────────
async function loadProviders() {
  try {
    const providers = await api('GET', '/config');
    const container = document.getElementById('providerList');
    if (!providers.length) {
      container.innerHTML = '<div class="empty-state">No providers configured.</div>';
      return;
    }
    container.innerHTML = providers.map(p => `
      <div class="glossary-entry">
        <div class="terms">
          <span class="source">${escHtml(p.name)}</span>
          <span class="target">${escHtml(p.model)} · ${escHtml(p.base_url)}</span>
        </div>
      </div>`).join('');
  } catch(e) { toast('Failed to load providers: ' + e.message, true); }
}

function showConfigModal() { document.getElementById('configModal').className = 'modal open'; }
function hideConfigModal() { document.getElementById('configModal').className = 'modal'; }

async function saveProvider() {
  const cfg = {
    name: document.getElementById('cfgName').value,
    base_url: document.getElementById('cfgUrl').value,
    model: document.getElementById('cfgModel').value,
    api_key_env: document.getElementById('cfgKeyEnv').value,
  };
  if (!cfg.name || !cfg.model) { toast('Name and Model are required', true); return; }
  try {
    await api('POST', '/config', cfg);
    toast('Provider saved');
    hideConfigModal();
    loadProviders();
  } catch(e) { toast(e.message, true); }
}

// ── Init ──────────────────────────────────────────────────────────
restoreStateDir();
loadState();
loadProviders();
</script>
</body>
</html>"""
