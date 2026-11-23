/* YUEL — editorial edition. Fresh app script.
   Data: data/out/all.json + run-summary.json (same-origin relative path works on
   GitHub Pages and local previews; override with ?data=<base>). */

"use strict";

const qs = new URLSearchParams(location.search);
const DATA_BASE = qs.get("data") || "../data/out/";
const PER_PAGE = 40;

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
const validCC = (cc) => /^[A-Z]{2}$/.test(cc);
// Emoji flags do not render on Windows, so use the bundled SVG/PNG flags in docs/flags/.
const flagOf = (cc) =>
  validCC(cc) ? String.fromCodePoint(...[...cc].map((c) => 0x1f1e6 + c.charCodeAt(0) - 65)) : "🌐";
function flagImg(cc, cls = "") {
  const img = document.createElement("img");
  img.className = `flag-img ${cls}`.trim();
  img.loading = "lazy";
  img.decoding = "async";
  img.width = 32;
  img.height = 24;
  img.src = validCC(cc)
    ? `flags/${cc.toLowerCase()}.png`
    : "data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='40' height='30'%3E%3Crect width='40' height='30' fill='%236f687f'/%3E%3C/svg%3E";
  img.alt = "";
  return img;
}
const placeName = (cc) => {
  if (!cc) return "Unclassified";
  try { return regionNames.of(cc) || cc; } catch (e) { return cc; }
};
const num = new Intl.NumberFormat("en");
const fmt = (n) => num.format(n);
const conn = (r) => `${r.type}://${r.ip}:${r.port}`;

const state = {
  records: [], summary: null, ready: false,
  q: "", country: "", sort: "score", maxLat: 0,
  types: new Set(["socks5", "socks4", "http"]),
  tiers: new Set(["gold", "silver", "bronze"]),
  page: 1, hits: [],
  picked: new Set(),
};

/* ----- helpers ------------------------------------------------------ */

const $ = (s, r = document) => r.querySelector(s);

let snackTimer;
function snack(msg) {
  const el = $("#snack");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(snackTimer);
  snackTimer = setTimeout(() => { el.hidden = true; }, 2000);
}

async function copy(text) {
  if (navigator.clipboard && window.isSecureContext) return navigator.clipboard.writeText(text);
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.cssText = "position:fixed;opacity:0";
  document.body.appendChild(ta);
  ta.select();
  try { document.execCommand("copy"); } finally { ta.remove(); }
}

function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 90) return "just now";
  if (s < 3600) return `${Math.round(s / 60)}m ago`;
  if (s < 86400) return `${Math.round(s / 3600)}h ago`;
  return `${Math.round(s / 86400)}d ago`;
}

/* ----- theme --------------------------------------------------------- */

$("#theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const next = root.dataset.theme === "light" ? "dark" : "light";
  root.dataset.theme = next;
  try { localStorage.setItem("yuel4-theme", next); } catch (e) {}
});

/* ----- data ---------------------------------------------------------- */

async function get(name) {
  const r = await fetch(DATA_BASE + name, { cache: "no-store" });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

function flash(which) {
  for (const id of ["flash-loading", "flash-error", "flash-empty"]) $("#" + id).hidden = true;
  if (which) $("#" + which).hidden = false;
}

function countsByCountry() {
  const counts = new Map();
  for (const r of state.records) counts.set(r.country, (counts.get(r.country) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

async function boot() {
  flash("flash-loading");
  $("#grid").replaceChildren();
  $("#pager").hidden = true;
  try {
    const [records, summary] = await Promise.all([get("all.json"), get("run-summary.json")]);
    state.records = records;
    state.summary = summary;
    state.ready = true;
    fillSummary();
    fillCountrySelect();
    paintFlagWall();
    run();
  } catch (err) {
    flash("flash-error");
    $("#flash-error-msg").textContent = `${err.message} — publish job may still be running, retry in a few minutes.`;
  }
}

function fillSummary() {
  const t = state.summary.totals;
  const stamp = new Date(state.summary.generated_utc).toISOString().slice(0, 16).replace("T", " ");
  $("#beacon-count").textContent = fmt(t.validated_alive);
  $("#run-stamp").textContent = `YUEL — run of ${stamp} UTC`;
  $("#meta-run").textContent = stamp;
  $("#meta-up").textContent = `${fmt(t.validated_alive)} up`;
  $("#meta-total").textContent = fmt(t.published_records);
  $("#f-alive").textContent = fmt(t.validated_alive);
  $("#f-gold").textContent = fmt((state.summary.by_tier || {}).gold ?? 0);
  $("#f-countries").textContent = fmt(t.countries);
  $("#f-tested").textContent = fmt(t.tested);
  $("#f-sources").textContent = fmt(t.sources_used);
}

function fillCountrySelect() {
  const sel = $("#country");
  for (const [cc, n] of countsByCountry()) {
    const opt = document.createElement("option");
    opt.value = cc;
    opt.textContent = `${placeName(cc)} (${fmt(n)})`;
    sel.prepend(flagImg(cc, "sel-flag"));
    sel.appendChild(opt);
  }
}

function paintFlagWall() {
  const wall = $("#flag-wall");
  wall.replaceChildren();
  for (const [cc, n] of countsByCountry()) {
    const b = document.createElement("button");
    b.className = "flag-card";
    b.title = `Filter by ${placeName(cc)}`;
    b.appendChild(flagImg(cc, "card-flag"));
    const name = document.createElement("span");
    name.className = "card-name";
    name.textContent = placeName(cc);
    const count = document.createElement("span");
    count.className = "n";
    count.textContent = fmt(n);
    b.append(name, count);
    b.addEventListener("click", () => {
      state.country = state.country === cc ? "" : cc;
      $("#country").value = state.country;
      run();
      $("#list").scrollIntoView({ behavior: "smooth" });
    });
    wall.appendChild(b);
  }
}

/* ----- filtering ------------------------------------------------------ */

function run() {
  const needle = state.q.trim();
  state.hits = state.records.filter((r) =>
    (!state.country || r.country === state.country) &&
    state.types.has(r.type) &&
    state.tiers.has(r.tier) &&
    (state.maxLat === 0 || (r.latency != null && r.latency <= state.maxLat)) &&
    (!needle || String(r.ip).startsWith(needle.replace(/\s+/g, "")))
  );
  const cmp = {
    score: (a, b) => b.score - a.score || (a.latency ?? 1e9) - (b.latency ?? 1e9),
    latency: (a, b) => (a.latency ?? 1e9) - (b.latency ?? 1e9) || b.score - a.score,
    country: (a, b) => placeName(a.country).localeCompare(placeName(b.country)) || b.score - a.score,
  }[state.sort];
  state.hits.sort(cmp);
  state.page = 1;
  paint();
}

/* ----- painting -------------------------------------------------------- */

function paint() {
  const total = state.hits.length;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  state.page = Math.min(state.page, pages);
  const slice = state.hits.slice((state.page - 1) * PER_PAGE, state.page * PER_PAGE);

  flash(state.ready && total === 0 ? "flash-empty" : null);
  $("#count-line").textContent = state.ready
    ? `${fmt(total)} prox${total === 1 ? "y" : "ies"} match · page ${state.page}/${pages}`
    : "…";
  $("#pager").hidden = pages <= 1;
  $("#page-label").textContent = `${state.page} / ${pages}`;
  $("#prev").disabled = state.page <= 1;
  $("#next").disabled = state.page >= pages;

  paintRows(slice);
  paintText(slice);
  syncDock();
}

function paintRows(rows) {
  const grid = $("#grid");
  grid.replaceChildren();
  for (const r of rows) {
    const key = conn(r);
    const row = document.createElement("article");
    row.className = "proxy" + (state.picked.has(key) ? " picked" : "");

    const fl = flagImg(r.country, "row-flag");
    fl.title = placeName(r.country);

    const who = document.createElement("div");
    who.className = "who";
    const place = document.createElement("span");
    place.className = "place";
    place.textContent = placeName(r.country);
    const cc = document.createElement("span");
    cc.className = "cc";
    cc.textContent = (r.country || "—").toUpperCase();
    who.append(place, cc);

    const addr = document.createElement("div");
    addr.className = "addr";
    const host = document.createElement("button");
    host.className = "host";
    host.title = "Copy to clipboard";
    host.textContent = `${r.ip}:${r.port}`;
    host.addEventListener("click", async () => { await copy(`${r.ip}:${r.port}`); snack("copied"); });
    const tags = document.createElement("span");
    tags.className = "tags";
    const tier = document.createElement("span");
    tier.className = `tag t-${r.tier}`;
    tier.textContent = r.tier;
    const proto = document.createElement("span");
    proto.className = "tag";
    proto.textContent = r.type;
    tags.append(tier, proto);
    addr.append(host, tags);

    const scorecell = document.createElement("div");
    scorecell.className = "scorecell";
    const meter = document.createElement("span");
    meter.className = "meter";
    const fill = document.createElement("i");
    fill.style.width = `${Math.max(3, Math.min(100, r.score))}%`;
    meter.appendChild(fill);
    const score = document.createElement("span");
    score.textContent = `${r.score.toFixed(1)} score`;
    scorecell.append(score, meter);

    const lat = document.createElement("span");
    lat.className = "lat " + (r.latency == null ? "" : r.latency < 500 ? "f" : r.latency < 1500 ? "m" : "s");
    lat.textContent = r.latency == null ? "—" : `${fmt(r.latency)} ms`;

    const when = document.createElement("span");
    when.className = "when";
    when.textContent = ago(r.last_checked);
    when.title = new Date(r.last_checked).toLocaleString("en");

    const pick = document.createElement("input");
    pick.type = "checkbox";
    pick.className = "pick";
    pick.checked = state.picked.has(key);
    pick.setAttribute("aria-label", `Pick ${key}`);
    pick.addEventListener("change", () => {
      pick.checked ? state.picked.add(key) : state.picked.delete(key);
      row.classList.toggle("picked", pick.checked);
      syncDock();
    });

    row.append(fl, who, addr, scorecell, lat, when, pick);
    grid.appendChild(row);
  }
}

function paintText(rows) {
  const pre = $("#rawlist");
  pre.replaceChildren();
  for (const r of rows) {
    const line = document.createElement("div");
    const b = document.createElement("b");
    b.textContent = `${r.ip}:${r.port}`;
    line.append(b, document.createTextNode(`  # ${r.type} · ${r.tier} · ${placeName(r.country)} · ${r.latency ?? "?"} ms`));
    pre.appendChild(line);
  }
}

/* ----- dock ------------------------------------------------------------- */

function syncDock() {
  const n = state.picked.size;
  $("#dock").hidden = n === 0;
  $("#dock-n").textContent = fmt(n);
}

function pickedConns() {
  return state.hits.filter((r) => state.picked.has(conn(r))).map(conn);
}

$("#dock-copy").addEventListener("click", async () => {
  const list = pickedConns();
  if (!list.length) return;
  await copy(list.join("\n"));
  snack(`copied ${list.length}`);
});

$("#dock-dl").addEventListener("click", () => {
  const list = pickedConns();
  if (!list.length) return;
  const url = URL.createObjectURL(new Blob([list.join("\n") + "\n"], { type: "text/plain" }));
  const a = document.createElement("a");
  a.href = url;
  a.download = "yuel-picked.txt";
  a.click();
  URL.revokeObjectURL(url);
  snack(`downloaded ${list.length}`);
});

$("#dock-clear").addEventListener("click", () => {
  state.picked.clear();
  paint();
});

/* ----- controls ----------------------------------------------------------- */

$("#q").addEventListener("input", (e) => { state.q = e.target.value; run(); });
$("#country").addEventListener("change", (e) => { state.country = e.target.value; run(); });
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; run(); });

$("#lat").addEventListener("input", (e) => {
  state.maxLat = Number(e.target.value);
  $("#lat-out").textContent = state.maxLat === 0 ? "any" : `${fmt(state.maxLat)} ms`;
  run();
});

for (const group of document.querySelectorAll(".chips")) {
  group.addEventListener("click", (e) => {
    const btn = e.target.closest(".chip");
    if (!btn) return;
    const set = group.dataset.kind === "type" ? state.types : state.tiers;
    const val = btn.dataset.v;
    if (set.has(val) && set.size === 1) return;
    set.has(val) ? set.delete(val) : set.add(val);
    btn.classList.toggle("is-on", set.has(val));
    run();
  });
}

function clearAll() {
  state.q = ""; state.country = ""; state.maxLat = 0; state.sort = "score";
  state.types = new Set(["socks5", "socks4", "http"]);
  state.tiers = new Set(["gold", "silver", "bronze"]);
  $("#q").value = ""; $("#country").value = ""; $("#sort").value = "score";
  $("#lat").value = "0";
  $("#lat-out").textContent = "any";
  for (const b of document.querySelectorAll(".chips .chip")) b.classList.add("is-on");
  run();
}

$("#reset").addEventListener("click", clearAll);
$("#reset2").addEventListener("click", clearAll);
$("#retry").addEventListener("click", boot);

$("#prev").addEventListener("click", () => { state.page--; paint(); scrollTo({ top: 0, behavior: "smooth" }); });
$("#next").addEventListener("click", () => { state.page++; paint(); scrollTo({ top: 0, behavior: "smooth" }); });

for (const [id, mode] of [["mode-grid", "grid"], ["mode-text", "text"]]) {
  $("#" + id).addEventListener("click", () => {
    $("#mode-grid").setAttribute("aria-pressed", String(mode === "grid"));
    $("#mode-text").setAttribute("aria-pressed", String(mode === "text"));
    $("#grid").hidden = mode !== "grid";
    $("#rawlist").hidden = mode !== "text";
  });
}

boot();
