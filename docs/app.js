/* YUEL — signal edition.
   Data: data/out/all.json + run-summary.json. The base URL is resolved at
   runtime (Pages can serve either the repo root or /docs), then cached in
   sessionStorage. Override with ?data=<base> when previewing locally. */

"use strict";

const REPO = "Edsel-Rahimi/YUEL";
const qs = new URLSearchParams(location.search);
const FORCED_BASE = qs.get("data");
const BASES = FORCED_BASE ? [FORCED_BASE] : [
  "data/out/",                                                   // if data ships inside docs/
  "../data/out/",                                                // Pages serving the repo root
  `https://raw.githubusercontent.com/${REPO}/main/data/out/`,    // always works (CORS-enabled)
];
const PER_PAGE = 40;
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)").matches;

const regionNames = new Intl.DisplayNames(["en"], { type: "region" });
const validCC = (cc) => /^[A-Z]{2}$/.test(cc);
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
const fmt = (n) => num.format(Math.round(n));
const conn = (r) => `${r.type}://${r.ip}:${r.port}`;

const state = {
  records: [], summary: null, ready: false, base: null,
  q: "", country: "", sort: "score", maxLat: 0,
  types: new Set(["socks5", "socks4", "http"]),
  tiers: new Set(["gold", "silver", "bronze"]),
  page: 1, hits: [], picked: new Set(), showAll: false,
};

/* ----- tiny helpers -------------------------------------------------- */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];

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

function countUp(el, target, dur = 1100) {
  const from = Number(el.dataset.v || 0);
  el.dataset.v = target;
  if (REDUCED) { el.textContent = fmt(target); return; }
  const t0 = performance.now();
  const tick = (t) => {
    const p = Math.min(1, (t - t0) / dur);
    const e = 1 - Math.pow(2, -10 * p); // easeOutExpo
    el.textContent = fmt(from + (target - from) * e);
    if (p < 1) requestAnimationFrame(tick);
    else el.textContent = fmt(target);
  };
  requestAnimationFrame(tick);
}

/* ----- theme ---------------------------------------------------------- */

$("#theme-toggle").addEventListener("click", () => {
  const root = document.documentElement;
  const next = root.dataset.theme === "light" ? "dark" : "light";
  root.dataset.theme = next;
  try { localStorage.setItem("yuel-theme", next); } catch (e) {}
});

/* ----- nav shadow ----------------------------------------------------- */

const nav = $("#nav");
addEventListener("scroll", () => nav.classList.toggle("scrolled", scrollY > 8), { passive: true });

/* ----- reveal on scroll ------------------------------------------------- */

const revealObs = new IntersectionObserver((entries) => {
  for (const en of entries) {
    if (en.isIntersecting) { en.target.classList.add("in"); revealObs.unobserve(en.target); }
  }
}, { threshold: 0.15, rootMargin: "0px 0px -36px" });
$$("[data-reveal]").forEach((el) => revealObs.observe(el));

/* ----- data loading (robust) -------------------------------------------- */

async function resolveBase() {
  if (state.base) return state.base;
  try {
    const cached = sessionStorage.getItem("yuel-base");
    if (cached) { state.base = cached; return cached; }
  } catch (e) {}
  let lastErr = null;
  for (const base of BASES) {
    try {
      const r = await fetch(base + "run-summary.json", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      const j = await r.json();
      if (!j || !j.totals) throw new Error("unexpected payload");
      state.base = base;
      try { sessionStorage.setItem("yuel-base", base); } catch (e) {}
      return base;
    } catch (e) { lastErr = e; }
  }
  throw new Error(`data source unreachable (last attempt: ${lastErr ? lastErr.message : "unknown"})`);
}

async function get(name) {
  const r = await fetch(state.base + name, { cache: "no-store" });
  if (!r.ok) throw new Error(`${name}: HTTP ${r.status}`);
  return r.json();
}

function hideSkeleton() { $("#flash-skeleton").hidden = true; }

function fail(err) {
  hideSkeleton();
  $("#flash-error").hidden = false;
  $("#flash-error-msg").textContent =
    `${err.message} — the publish job may still be running. The page tried: ` +
    BASES.map((b) => b.replace("https://raw.githubusercontent.com/", "raw@")).join(", ");
}

async function boot() {
  $("#flash-error").hidden = true;
  $("#flash-skeleton").hidden = false;
  state.base = null;
  try { sessionStorage.removeItem("yuel-base"); } catch (e) {}
  try {
    const base = await resolveBase();
    const [records, summary] = await Promise.all([get("all.json"), get("run-summary.json")]);
    state.records = records;
    state.summary = summary;
    state.ready = true;
    fillSummary();
    fillCountrySelect();
    paintFlagWall();
    buildTicker();
    startFeed();
    run();
  } catch (err) { fail(err); }
}

/* ----- summary → hero / stats / beacon ----------------------------------- */

function setNumSlots(key, val) {
  $$(`[data-num="${key}"]`).forEach((el) => { el.textContent = fmt(val); });
}

function fillSummary() {
  const t = state.summary.totals;
  const tiers = state.summary.by_tier || {};
  const when = new Date(state.summary.generated_utc);
  const stamp = when.toISOString().slice(0, 16).replace("T", " ");

  setNumSlots("alive", t.validated_alive);
  setNumSlots("countries", t.countries);
  setNumSlots("candidates", t.candidates_collected);
  setNumSlots("tested", t.tested);
  setNumSlots("sources", t.sources_used);

  $("#beacon-count").textContent = fmt(t.validated_alive);
  $("#chip-gold").textContent = fmt(tiers.gold ?? 0);
  $("#chip-cc").textContent = fmt(t.countries);
  $("#meta-run").textContent = `${stamp} UTC`;
  $("#meta-ago").textContent = ago(state.summary.generated_utc);

  const stats = {
    "f-alive": t.validated_alive,
    "f-gold": tiers.gold ?? 0,
    "f-countries": t.countries,
    "f-tested": t.tested,
    "f-sources": t.sources_used,
  };
  for (const [id, v] of Object.entries(stats)) {
    const el = document.getElementById(id);
    el.dataset.count = v;
    if (el.classList.contains("in") || REDUCED) countUp(el, v);
  }
  $("#f-tested-inline").textContent = fmt(t.tested);
  $("#f-candidates-inline").textContent = fmt(t.candidates_collected);
  const goldPct = t.validated_alive ? Math.round(((tiers.gold ?? 0) / t.validated_alive) * 100) : 0;
  $("#f-goldpct").textContent = fmt(goldPct);

  clearInterval(agoTimer);
  agoTimer = setInterval(() => {
    if (state.summary) $("#meta-ago").textContent = ago(state.summary.generated_utc);
  }, 60000);
}
let agoTimer;

/* stats count-ups fire when the band scrolls into view */
const statsObs = new IntersectionObserver((entries) => {
  if (!entries.some((en) => en.isIntersecting)) return;
  statsObs.disconnect();
  for (const el of $$(".stat-num")) countUp(el, Number(el.dataset.count || 0));
}, { threshold: 0.3 });
statsObs.observe($("#stats"));

/* ----- countries ---------------------------------------------------------- */

function countsByCountry() {
  const counts = new Map();
  for (const r of state.records) counts.set(r.country, (counts.get(r.country) || 0) + 1);
  return [...counts.entries()].sort((a, b) => b[1] - a[1]);
}

function fillCountrySelect() {
  const sel = $("#country");
  sel.replaceChildren(Object.assign(document.createElement("option"), { value: "", textContent: "All" }));
  for (const [cc, n] of countsByCountry()) {
    const opt = document.createElement("option");
    opt.value = cc;
    opt.textContent = `${placeName(cc)} (${fmt(n)})`;
    sel.appendChild(opt);
  }
}

const WALL_PREVIEW = 24;

function paintFlagWall() {
  const wall = $("#flag-wall");
  wall.classList.remove("go");
  const counts = countsByCountry();
  const max = counts.length ? counts[0][1] : 1;
  const shown = state.showAll ? counts : counts.slice(0, WALL_PREVIEW);
  wall.replaceChildren();
  shown.forEach(([cc, n], i) => {
    const b = document.createElement("button");
    b.className = "flag-card" + (state.country === cc ? " is-active" : "");
    b.style.setProperty("--i", Math.min(i, 16));
    b.title = `Filter by ${placeName(cc)}`;
    b.appendChild(flagImg(cc));
    const name = document.createElement("span");
    name.className = "card-name";
    name.textContent = placeName(cc);
    const count = document.createElement("span");
    count.className = "n";
    count.textContent = fmt(n);
    const bar = document.createElement("span");
    bar.className = "bar";
    bar.style.setProperty("--w", `${Math.max(6, (n / max) * 100)}%`);
    b.append(name, count, bar);
    b.addEventListener("click", () => {
      state.country = state.country === cc ? "" : cc;
      $("#country").value = state.country;
      paintFlagWall();
      run();
      $("#list").scrollIntoView({ behavior: REDUCED ? "auto" : "smooth" });
    });
    wall.appendChild(b);
  });
  requestAnimationFrame(() => wall.classList.add("go"));
  const btn = $("#show-all");
  btn.hidden = counts.length <= WALL_PREVIEW;
  btn.textContent = state.showAll
    ? "Show top countries"
    : `Show all ${counts.length} countries`;
}

$("#show-all").addEventListener("click", () => {
  state.showAll = !state.showAll;
  paintFlagWall();
});

/* ----- ticker -------------------------------------------------------------- */

function buildTicker() {
  const track = $("#ticker-track");
  const picks = [...state.records].sort((a, b) => b.score - a.score).slice(0, 30);
  const frag = document.createDocumentFragment();
  for (const r of picks) {
    const chip = document.createElement("span");
    chip.className = "tick";
    chip.appendChild(flagImg(r.country));
    const b = document.createElement("b");
    b.textContent = conn(r);
    const dot = document.createElement("i");
    dot.className = `dot t-${r.tier}`;
    chip.append(b, dot);
    frag.appendChild(chip);
  }
  track.replaceChildren(frag);
  track.innerHTML += track.innerHTML; // seamless loop
}

/* ----- hero live feed -------------------------------------------------------- */

function startFeed() {
  const body = $("#feed-lines");
  const picks = [...state.records].sort((a, b) => b.score - a.score).slice(0, 14);
  if (!picks.length) return;
  if (REDUCED) {
    for (const r of picks.slice(0, 8)) body.insertBefore(feedLine(r), body.lastElementChild);
    return;
  }
  let i = 0;
  const push = () => {
    if (document.hidden) return;
    body.insertBefore(feedLine(picks[i % picks.length]), body.lastElementChild);
    while (body.children.length > 10) body.removeChild(body.firstChild);
    i++;
  };
  for (let k = 0; k < 7; k++) push(); // pre-fill so the terminal looks alive immediately
  setInterval(push, 2400);
}

function feedLine(r) {
  const line = document.createElement("div");
  line.className = "feed-line";
  const dot = document.createElement("i");
  dot.className = `dot t-${r.tier}`;
  const address = document.createElement("b");
  address.className = "conn";
  const meta = document.createElement("span");
  meta.className = "meta";
  meta.textContent = `${(r.country || "—").toUpperCase()} · ${fmt(r.latency ?? 0)} ms`;
  line.append(dot, address, meta);
  const full = conn(r);
  if (REDUCED) { address.textContent = full; return line; }
  let pos = 0;
  const typer = setInterval(() => {
    pos += 2;
    address.textContent = full.slice(0, pos);
    if (pos >= full.length) { address.textContent = full; clearInterval(typer); }
  }, 16);
  return line;
}

/* ----- filtering -------------------------------------------------------------- */

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

/* ----- painting ------------------------------------------------------------------ */

function paint() {
  const total = state.hits.length;
  const pages = Math.max(1, Math.ceil(total / PER_PAGE));
  state.page = Math.min(state.page, pages);
  const slice = state.hits.slice((state.page - 1) * PER_PAGE, state.page * PER_PAGE);

  hideSkeleton();
  $("#flash-empty").hidden = !(state.ready && total === 0);
  $("#count-line").textContent = state.ready
    ? `${fmt(total)} prox${total === 1 ? "y" : "ies"} match · page ${state.page}/${pages} · sorted by ${state.sort}`
    : "connecting to the latest run…";
  $("#pager").hidden = pages <= 1;
  $("#page-label").textContent = `${state.page} / ${pages}`;
  $("#prev").disabled = state.page <= 1;
  $("#next").disabled = state.page >= pages;

  const grid = $("#grid");
  grid.classList.remove("go");
  grid.hidden = $("#mode-grid").getAttribute("aria-pressed") !== "true";
  grid.replaceChildren();
  slice.forEach((r, i) => grid.appendChild(proxyRow(r, i)));
  grid.offsetWidth; // flush, so the meters animate in
  requestAnimationFrame(() => grid.classList.add("go"));

  paintText(slice);
  syncDock();
}

function proxyRow(r, i) {
  const row = document.createElement("article");
  row.className = "proxy" + (state.picked.has(conn(r)) ? " picked" : "");
  row.style.setProperty("--i", Math.min(i, 16));

  const fl = flagImg(r.country);
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
  host.title = "Copy ip:port to clipboard";
  host.innerHTML = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg><span></span>`;
  host.lastElementChild.textContent = `${r.ip}:${r.port}`;
  host.addEventListener("click", async () => { await copy(`${r.ip}:${r.port}`); snack(`copied ${r.ip}:${r.port}`); });
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
  const score = document.createElement("span");
  score.className = "score-num";
  score.textContent = `${r.score.toFixed(1)} score`;
  const meter = document.createElement("span");
  meter.className = "meter";
  const fill = document.createElement("i");
  fill.style.setProperty("--w", `${Math.max(3, Math.min(100, r.score))}%`);
  meter.appendChild(fill);
  scorecell.append(score, meter);

  const ms = document.createElement("span");
  ms.className = "ms";
  ms.textContent = r.latency == null ? "—" : `${fmt(r.latency)} ms`;

  const when = document.createElement("span");
  when.className = "when";
  when.textContent = ago(r.last_checked);
  when.title = new Date(r.last_checked).toLocaleString("en");

  const pick = document.createElement("input");
  pick.type = "checkbox";
  pick.className = "pick";
  pick.checked = state.picked.has(conn(r));
  pick.setAttribute("aria-label", `Pick ${conn(r)}`);
  pick.addEventListener("change", () => {
    pick.checked ? state.picked.add(conn(r)) : state.picked.delete(conn(r));
    row.classList.toggle("picked", pick.checked);
    syncDock();
  });

  row.append(fl, who, addr, scorecell, ms, when, pick);
  return row;
}

function paintText(rows) {
  const pre = $("#rawlist");
  pre.replaceChildren();
  for (const r of rows) {
    const line = document.createElement("div");
    const b = document.createElement("b");
    b.textContent = conn(r);
    line.append(b, document.createTextNode(`  # ${r.tier} · ${placeName(r.country)} · ${r.latency ?? "?"} ms`));
    pre.appendChild(line);
  }
}

/* ----- dock ---------------------------------------------------------------- */

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
  snack(`copied ${list.length} proxies`);
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
  snack(`downloaded ${list.length} proxies`);
});

$("#dock-clear").addEventListener("click", () => {
  state.picked.clear();
  paint();
});

/* ----- controls -------------------------------------------------------------- */

$("#q").addEventListener("input", (e) => { state.q = e.target.value; run(); });
$("#country").addEventListener("change", (e) => { state.country = e.target.value; paintFlagWall(); run(); });
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; run(); });

$("#lat").addEventListener("input", (e) => {
  state.maxLat = Number(e.target.value);
  $("#lat-out").textContent = state.maxLat === 0 ? "any" : `${fmt(state.maxLat)} ms`;
  run();
});

for (const group of $$(".chips")) {
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
  for (const b of $$(".chips .chip")) b.classList.add("is-on");
  paintFlagWall();
  run();
}

$("#reset").addEventListener("click", clearAll);
$("#reset2").addEventListener("click", clearAll);
$("#retry").addEventListener("click", boot);

$("#prev").addEventListener("click", () => { state.page--; paint(); scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" }); });
$("#next").addEventListener("click", () => { state.page++; paint(); scrollTo({ top: 0, behavior: REDUCED ? "auto" : "smooth" }); });

for (const [id, mode] of [["mode-grid", "grid"], ["mode-text", "text"]]) {
  $("#" + id).addEventListener("click", () => {
    $("#mode-grid").setAttribute("aria-pressed", String(mode === "grid"));
    $("#mode-text").setAttribute("aria-pressed", String(mode === "text"));
    $("#grid").hidden = mode !== "grid";
    $("#rawlist").hidden = mode !== "text";
    if (mode === "grid") paint();
  });
}

boot();
