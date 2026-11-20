/* YUEL proxy finder — live app.
   Data: data/out/all.json + run-summary.json, fetched client-side from
   raw.githubusercontent.com (serves access-control-allow-origin: * —
   verified; GitHub Pages /docs same-origin also satisfies CORS when the
   site is served from the repo itself). No backend, no build step.
   Local development: append ?data=<relative-base> to the URL, e.g.
   /docs/index.html?data=../data/out/ to read the repo's working copy. */

"use strict";

/* ------------------------------------------------------------------ */
/* constants + state                                                   */
/* ------------------------------------------------------------------ */

const REPO_URL = "https://github.com/Edsel-Rahimi/YUEL";
const PROD_DATA_BASE = "https://raw.githubusercontent.com/Edsel-Rahimi/YUEL/main/data/out/";
const PER_PAGE = 50;

const params = new URLSearchParams(location.search);
const DATA_BASE = params.get("data") || PROD_DATA_BASE;

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
const countryName = (cc) => {
  try { return regionNames.of(cc) || cc; } catch (e) { return cc; }
};

const state = {
  records: [],
  summary: null,
  loaded: false,
  country: null,                          // ISO2 or null (all)
  types: new Set(["socks5", "socks4", "http"]),
  tiers: new Set(["gold", "silver", "bronze"]),
  ipQuery: "",
  sort: "score",
  page: 1,
  filtered: [],
  selected: new Set(),                    // conn strings, persists across pages/filters
};

const $ = (id) => document.getElementById(id);

/* ------------------------------------------------------------------ */
/* theme (prefers-color-scheme default + manual override persisted)    */
/* ------------------------------------------------------------------ */

(function initThemeToggle() {
  const root = document.documentElement;
  const btn = $("theme-toggle");
  const moon = '<svg class="ico-moon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5.5 1.44a.5.5 0 0 1 .5.5 5.06 5.06 0 0 0 5.06 5.06.5.5 0 0 1 .5.5A6.06 6.06 0 1 1 5.5 1.44Z"/></svg>';
  const sun = '<svg class="ico-sun" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="8" cy="8" r="3.2"/><path d="M8 1v2m0 10v2M1 8h2m10 0h2M2.9 2.9l1.4 1.4m7.4 7.4 1.4 1.4M13.1 2.9l-1.4 1.4M4.3 11.7l-1.4 1.4"/></svg>';
  const iconFor = (t) => t === "dark" ? sun : moon;
  const current = () => root.dataset.theme ||
    (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  const paint = () => { btn.innerHTML = iconFor(current()); };
  paint();
  btn.addEventListener("click", () => {
    const next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("yuel-theme", next); } catch (e) { /* ok */ }
    paint();
  });
})();

/* ------------------------------------------------------------------ */
/* helpers                                                             */
/* ------------------------------------------------------------------ */

const ISO2_RE = /^[A-Z]{2}$/;
const flagUrl = (cc) => `https://flagcdn.com/24x18/${cc.toLowerCase()}.png`;
// real ISO-2 codes render a flag; anything else (e.g. "unclassified")
// gets a neutral placeholder so rows never show a broken image
function flagImg(cc, cls = "") {
  return ISO2_RE.test(cc)
    ? `<img src="${flagUrl(cc)}" alt="" loading="lazy"${cls ? ` class="${cls}"` : ""}>`
    : `<span class="flag-ph" aria-hidden="true"></span>`;
}

function connOf(r) {  // same convention as the published txt siblings
  const creds = r.user && r.pass ? `${r.user}:${r.pass}@` : "";
  return `${r.type || "unknown"}://${creds}${r.ip}:${r.port}`;
}

function relTime(iso) {
  if (!iso) return "—";
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return "just now";
  const m = Math.floor(diff / 60000);
  if (m < 1) return "just now";
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function fmt(n) { return Number(n).toLocaleString("en-US"); }

function legacyCopy(text) {
  return new Promise((resolve) => {  // works everywhere, incl. file://
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand("copy"); } catch (e) { /* best effort */ }
    ta.remove();
    resolve();
  });
}

function copyText(text) {
  // clipboard API first; fall back if it's unavailable or permission-denied
  // so the visual confirmation always fires
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text).catch(() => legacyCopy(text));
  }
  return legacyCopy(text);
}

const copyIco = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5v-2A1.5 1.5 0 0 0 9 2H3.5A1.5 1.5 0 0 0 2 3.5V9a1.5 1.5 0 0 0 1.5 1.5h2"/></svg>';
const checkIco = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m3 8.5 3.5 3.5L13 5"/></svg>';

/* ------------------------------------------------------------------ */
/* data loading + page states                                          */
/* ------------------------------------------------------------------ */

async function loadJson(name) {
  const res = await fetch(DATA_BASE + name, { cache: "no-store" });
  if (!res.ok) throw new Error(`${name}: HTTP ${res.status}`);
  return res.json();
}

function showOnly(state_) {  // 'loading' | 'error' | 'empty' | 'results'
  $("state-loading").hidden = state_ !== "loading";
  $("state-error").hidden = state_ !== "error";
  $("state-empty").hidden = state_ !== "empty";
  const showResults = state_ === "results" || state_ === "empty";
  $("results-table").style.display = showResults ? "" : "none";
  $("results-head").style.display = showResults ? "" : "none";
  $("table-foot").hidden = true;
}

function showError(message) {
  $("error-detail").textContent = message;
  showOnly("error");
}

async function load() {
  showOnly("loading");
  try {
    const [records, summary] = await Promise.all([
      loadJson("all.json"),
      loadJson("run-summary.json").catch(() => null),  // table survives without it
    ]);
    if (!Array.isArray(records)) throw new Error("all.json is not a JSON array");
    state.records = records;
    state.summary = summary;
    state.loaded = true;
    buildCountryIndex();
    paintHeader();
    applyFilters();  // renders results (or the empty state)
    if (state.filtered.length) showOnly("results");
  } catch (err) {
    console.error("YUEL data load failed:", err);
    showError(
      `Couldn't load the proxy list (${err.message}). Check your connection ` +
      "and retry — the published dataset lives in the YUEL repository and " +
      "is refreshed automatically every 30 minutes.");
  }
}

function paintHeader() {
  $("alive-count").textContent = fmt(state.records.length);
  $("of-total").textContent = `of ${fmt(state.records.length)} alive proxies`;
  const gen = state.summary && state.summary.generated_utc;
  $("updated-time").textContent = relTime(gen);
}

// header relative time recalculates live without a reload
setInterval(() => {
  if (state.summary) $("updated-time").textContent = relTime(state.summary.generated_utc);
}, 30000);

/* ------------------------------------------------------------------ */
/* country index (real list + live counts from the dataset)            */
/* ------------------------------------------------------------------ */

let countryIndex = [];  // [{cc, count}] sorted by count desc

function buildCountryIndex() {
  const counts = new Map();
  for (const r of state.records) {
    counts.set(r.country, (counts.get(r.country) || 0) + 1);
  }
  countryIndex = [...counts.entries()]
    .map(([cc, count]) => ({ cc, count }))
    .sort((a, b) => b.count - a.count || a.cc.localeCompare(b.cc));
}

const combo = $("country-combo");
const comboInput = $("country-input");
const comboList = $("country-list");

function renderComboList() {
  const q = comboInput.value.trim().toLowerCase();
  const qcc = q.length === 2 ? q.toUpperCase() : null;
  const hits = countryIndex.filter((c) => {
    if (!q) return true;
    return countryName(c.cc).toLowerCase().includes(q) ||
      c.cc.toLowerCase().includes(q) || c.cc === qcc;
  }).slice(0, 200);

  const allBtn = `<button type="button" class="combo-item" data-cc="">
    <span class="n" style="font-weight:600">All countries</span>
    <span class="c">${fmt(state.records.length)}</span></button>`;
  comboList.innerHTML = allBtn + (hits.length ? hits.map((c) => `
    <button type="button" class="combo-item" data-cc="${c.cc}">
      ${flagImg(c.cc)} <span class="n">${countryName(c.cc)}</span>
      <span class="c">${fmt(c.count)}</span>
    </button>`).join("") : '<div class="combo-empty">No country matches.</div>');
}

function closeCombo() {
  combo.classList.remove("open");
  comboInput.setAttribute("aria-expanded", "false");
}

comboInput.addEventListener("focus", () => {
  comboInput.value = "";
  renderComboList();
  combo.classList.add("open");
  comboInput.setAttribute("aria-expanded", "true");
});
comboInput.addEventListener("input", renderComboList);
comboInput.addEventListener("blur", () => setTimeout(closeCombo, 150));
comboList.addEventListener("mousedown", (e) => {
  const item = e.target.closest(".combo-item");
  if (!item) return;
  e.preventDefault();
  const cc = item.dataset.cc || null;
  state.country = cc;
  comboInput.value = cc ? countryName(cc) : "";
  closeCombo();
  state.page = 1;
  applyFilters();
});

/* ------------------------------------------------------------------ */
/* filter + sort pipeline                                              */
/* ------------------------------------------------------------------ */

const SORTS = {
  score: (a, b) => (b.score ?? -1) - (a.score ?? -1) ||
    a.ip.localeCompare(b.ip) || a.port - b.port,
  latency: (a, b) => (a.latency ?? Infinity) - (b.latency ?? Infinity) ||
    (b.score ?? -1) - (a.score ?? -1),
  country: (a, b) =>
    countryName(a.country).localeCompare(countryName(b.country)) ||
    (b.score ?? -1) - (a.score ?? -1),
};

function applyFilters() {
  const q = state.ipQuery.trim().toLowerCase();
  let rows = state.records.filter((r) =>
    (!state.country || r.country === state.country) &&
    state.types.has(r.type) &&
    state.tiers.has(r.tier) &&
    (!q || r.ip.toLowerCase().includes(q) || String(r.port).includes(q)));
  rows.sort(SORTS[state.sort]);
  state.filtered = rows;

  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  if (state.page > pages) state.page = pages;

  if (!state.filtered.length) {
    showOnly("empty");
  } else {
    $("table-foot").hidden = pages <= 1;
    renderResults();
  }
}

/* ------------------------------------------------------------------ */
/* results render (paginated)                                          */
/* ------------------------------------------------------------------ */

function renderResults() {
  const rows = state.filtered;
  const pages = Math.max(1, Math.ceil(rows.length / PER_PAGE));
  const start = (state.page - 1) * PER_PAGE;
  const slice = rows.slice(start, start + PER_PAGE);

  $("shown-range").textContent = `${fmt(start + 1)}–${fmt(start + slice.length)}`;
  $("page-info").textContent = `Page ${state.page} of ${fmt(pages)}`;
  $("page-prev").disabled = state.page <= 1;
  $("page-next").disabled = state.page >= pages;

  $("results-body").innerHTML = slice.map((r) => {
    const conn = connOf(r);
    const sel = state.selected.has(conn);
    const cc = r.country || "unclassified";
    return `
    <tr data-conn="${conn}"${sel ? ' class="selected"' : ""}>
      <td class="col-check"><input type="checkbox" class="row-check"${sel ? " checked" : ""} aria-label="Select ${r.ip}"></td>
      <td class="ip-cell">${r.ip}<span class="port">:${r.port}</span></td>
      <td><span class="type-badge"><span class="tdot ${r.type || "unknown"}"></span>${r.type || "unknown"}</span></td>
      <td><span class="country-cell">${flagImg(cc)}${countryName(cc)} <span class="code">${cc}</span></span></td>
      <td><span class="tier-badge ${r.tier}">${r.tier}</span></td>
      <td class="score-cell">${r.score != null ? Number(r.score).toFixed(2) : "—"}</td>
      <td class="latency-cell">${r.latency != null ? fmt(r.latency) + " ms" : "—"}</td>
      <td class="checked-cell">${relTime(r.last_checked)}</td>
      <td><button class="row-copy" aria-label="Copy ${conn}" title="Copy connection string">${copyIco}</button></td>
    </tr>`;
  }).join("");

  syncSelectAll();
}

function syncSelectAll() {
  const boxes = [...document.querySelectorAll(".row-check")];
  const all = $("check-all");
  const selCount = boxes.filter((b) => b.checked).length;
  all.checked = boxes.length > 0 && selCount === boxes.length;
  all.indeterminate = selCount > 0 && selCount < boxes.length;
}

/* ------------------------------------------------------------------ */
/* selection + sticky bar                                              */
/* ------------------------------------------------------------------ */

function refreshSelectionUI() {
  const n = state.selected.size;
  $("sel-count").textContent = fmt(n);
  $("copy-n").textContent = fmt(n);
  $("dl-n").textContent = fmt(n);
  $("selection-bar").classList.toggle("hidden", n === 0);
}

$("results-body").addEventListener("change", (e) => {
  const cb = e.target.closest(".row-check");
  if (!cb) return;
  const conn = cb.closest("tr").dataset.conn;
  if (cb.checked) state.selected.add(conn);
  else state.selected.delete(conn);
  cb.closest("tr").classList.toggle("selected", cb.checked);
  syncSelectAll();
  refreshSelectionUI();
});

$("check-all").addEventListener("change", (e) => {
  const checked = e.target.checked;
  document.querySelectorAll("#results-body tr").forEach((tr) => {
    const cb = tr.querySelector(".row-check");
    cb.checked = checked;
    tr.classList.toggle("selected", checked);
    if (checked) state.selected.add(tr.dataset.conn);
    else state.selected.delete(tr.dataset.conn);
  });
  syncSelectAll();
  refreshSelectionUI();
});

$("clear-sel").addEventListener("click", () => {
  state.selected.clear();
  document.querySelectorAll(".row-check").forEach((cb) => { cb.checked = false; });
  document.querySelectorAll("#results-body tr.selected").forEach((tr) => tr.classList.remove("selected"));
  syncSelectAll();
  refreshSelectionUI();
});

/* per-row copy */
$("results-body").addEventListener("click", (e) => {
  const btn = e.target.closest(".row-copy");
  if (!btn) return;
  const conn = btn.closest("tr").dataset.conn;
  copyText(conn).then(() => {
    btn.classList.add("copied");
    btn.innerHTML = checkIco;
    setTimeout(() => {
      btn.classList.remove("copied");
      btn.innerHTML = copyIco;
    }, 1100);
  });
});

/* copy N as list */
$("copy-list").addEventListener("click", () => {
  if (!state.selected.size) return;
  const text = [...state.selected].join("\n");
  copyText(text).then(() => {
    const btn = $("copy-list");
    const nSpan = $("copy-n");
    const old = nSpan.textContent;
    nSpan.textContent = `${old} ✓`;
    btn.classList.add("copied-ok");
    setTimeout(() => { nSpan.textContent = old; btn.classList.remove("copied-ok"); }, 1200);
  });
});

/* download N as .txt — same header convention as the published siblings */
$("download-txt").addEventListener("click", () => {
  if (!state.selected.size) return;
  const lines = [...state.selected];
  const ts = new Date().toISOString().replace(/\.\d+Z$/, " UTC");
  const body = `# YUEL · selected · ${lines.length} proxies · generated ${ts}\n` +
    lines.join("\n") + "\n";
  const blob = new Blob([body], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `yuel-selected-${lines.length}.txt`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
});

/* ------------------------------------------------------------------ */
/* filter bar wiring (chips, ip search, sort, pagination)              */
/* ------------------------------------------------------------------ */

function wireToggles(groupId, set, attr) {
  $(groupId).addEventListener("click", (e) => {
    const chip = e.target.closest(".toggle");
    if (!chip) return;
    const key = chip.dataset[attr];
    const on = !set.has(key);
    if (on) set.add(key); else set.delete(key);
    chip.setAttribute("aria-pressed", String(on));
    state.page = 1;
    applyFilters();
  });
}
wireToggles("type-toggles", state.types, "type");
wireToggles("tier-toggles", state.tiers, "tier");

$("ip-search").addEventListener("input", (e) => {
  state.ipQuery = e.target.value;
  state.page = 1;
  applyFilters();
});

$("sort-select").addEventListener("change", (e) => {
  state.sort = e.target.value;
  state.page = 1;
  applyFilters();
});

$("page-prev").addEventListener("click", () => {
  if (state.page > 1) { state.page -= 1; renderResults(); }
});
$("page-next").addEventListener("click", () => {
  const pages = Math.max(1, Math.ceil(state.filtered.length / PER_PAGE));
  if (state.page < pages) { state.page += 1; renderResults(); }
});

$("reset-filters").addEventListener("click", () => {
  state.country = null;
  comboInput.value = "";
  state.types = new Set(["socks5", "socks4", "http"]);
  state.tiers = new Set(["gold", "silver", "bronze"]);
  state.ipQuery = "";
  $("ip-search").value = "";
  $("sort-select").value = "score";
  state.sort = "score";
  document.querySelectorAll("#type-toggles .toggle").forEach((t) => {
    t.setAttribute("aria-pressed", String(state.types.has(t.dataset.type)));
  });
  document.querySelectorAll("#tier-toggles .toggle").forEach((t) => {
    t.setAttribute("aria-pressed", String(state.tiers.has(t.dataset.tier)));
  });
  state.page = 1;
  applyFilters();
});

$("retry-load").addEventListener("click", load);

/* ------------------------------------------------------------------ */
/* boot                                                                */
/* ------------------------------------------------------------------ */

load();
