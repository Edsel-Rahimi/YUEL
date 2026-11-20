/* YUEL proxy finder — app shell (step 1: static preview).
   Theme toggle + sample-row rendering + demo interactions only.
   Live data fetching, real filtering/sorting and selection persistence
   arrive in step 2; the DOM hooks below are the contract for that wiring. */

"use strict";

/* ------------------------------------------------------------------ */
/* theme (prefers-color-scheme default + manual override persisted)    */
/* ------------------------------------------------------------------ */

(function initThemeToggle() {
  const root = document.documentElement;
  const btn = document.getElementById("theme-toggle");
  const moon = '<svg class="ico-moon" viewBox="0 0 16 16" fill="currentColor" aria-hidden="true"><path d="M5.5 1.44a.5.5 0 0 1 .5.5 5.06 5.06 0 0 0 5.06 5.06.5.5 0 0 1 .5.5A6.06 6.06 0 1 1 5.5 1.44Z"/></svg>';
  const sun = '<svg class="ico-sun" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><circle cx="8" cy="8" r="3.2"/><path d="M8 1v2m0 10v2M1 8h2m10 0h2M2.9 2.9l1.4 1.4m7.4 7.4 1.4 1.4M13.1 2.9l-1.4 1.4M4.3 11.7l-1.4 1.4"/></svg>';

  const iconFor = (theme) => theme === "dark" ? sun : moon;

  const current = () => {
    if (root.dataset.theme) return root.dataset.theme;
    return window.matchMedia("(prefers-color-scheme: dark)").matches
      ? "dark" : "light";
  };

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
/* sample data (real records from the latest run; latency illustrative */
/* — all.json does not publish latency yet, that lands in step 2)      */
/* ------------------------------------------------------------------ */

const COUNTRY_NAMES = {
  CN: "China", US: "United States", ID: "Indonesia", RU: "Russia",
  DE: "Germany", CH: "Switzerland", FR: "France", GB: "United Kingdom",
  SG: "Singapore", IN: "India",
};

const SAMPLES = [
  { ip: "142.93.245.61", port: 80, type: "http", country: "US", score: 99.79, tier: "gold", ago: "14m", latency: 96 },
  { ip: "47.251.166.203", port: 1080, type: "socks5", country: "CN", score: 98.92, tier: "gold", ago: "12m", latency: 184 },
  { ip: "78.129.141.197", port: 1080, type: "socks5", country: "GB", score: 97.77, tier: "gold", ago: "9m", latency: 121 },
  { ip: "5.75.133.113", port: 10802, type: "socks5", country: "DE", score: 79.95, tier: "silver", ago: "17m", latency: 143 },
  { ip: "157.66.16.48", port: 8181, type: "http", country: "ID", score: 79.95, tier: "silver", ago: "11m", latency: 402 },
  { ip: "163.172.167.48", port: 80, type: "http", country: "FR", score: 48.73, tier: "bronze", ago: "21m", latency: 167 },
];

const SAMPLE_COUNTRIES = [
  { cc: "CN", count: 896 }, { cc: "US", count: 287 }, { cc: "ID", count: 130 },
  { cc: "RU", count: 54 }, { cc: "DE", count: 52 }, { cc: "CH", count: 34 },
];

/* ------------------------------------------------------------------ */
/* sample table render                                                 */
/* ------------------------------------------------------------------ */

const flagUrl = (cc) => `https://flagcdn.com/24x18/${cc.toLowerCase()}.png`;

function renderSampleRows() {
  const tbody = document.getElementById("results-body");
  tbody.innerHTML = SAMPLES.map((r) => `
    <tr data-conn="${r.type}://${r.ip}:${r.port}">
      <td class="col-check"><input type="checkbox" class="row-check" aria-label="Select ${r.ip}"></td>
      <td class="ip-cell">${r.ip}<span class="port">:${r.port}</span></td>
      <td><span class="type-badge"><span class="tdot ${r.type}"></span>${r.type}</span></td>
      <td><span class="country-cell"><img src="${flagUrl(r.country)}" alt="" loading="lazy">${COUNTRY_NAMES[r.country] || r.country} <span class="code">${r.country}</span></span></td>
      <td><span class="tier-badge ${r.tier}">${r.tier}</span></td>
      <td class="score-cell">${r.score.toFixed(2)}</td>
      <td class="latency-cell">${r.latency} ms</td>
      <td class="checked-cell">${r.ago} ago</td>
      <td><button class="row-copy" aria-label="Copy ${r.type}://${r.ip}:${r.port}" title="Copy connection string">
        <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5v-2A1.5 1.5 0 0 0 9 2H3.5A1.5 1.5 0 0 0 2 3.5V9a1.5 1.5 0 0 0 1.5 1.5h2"/></svg>
      </button></td>
    </tr>`).join("");
}

renderSampleRows();

/* ------------------------------------------------------------------ */
/* demo interactions (replaced by real state in step 2)                */
/* ------------------------------------------------------------------ */

// searchable country combobox (demo list, narrows as you type)
const combo = document.getElementById("country-combo");
const comboInput = document.getElementById("country-input");
const comboList = document.getElementById("country-list");

function renderComboList(filter = "") {
  const q = filter.trim().toLowerCase();
  const hits = SAMPLE_COUNTRIES.filter((c) =>
    c.cc.toLowerCase().includes(q) ||
    (COUNTRY_NAMES[c.cc] || c.cc).toLowerCase().includes(q));
  comboList.innerHTML = hits.length
    ? hits.map((c) => `
      <button type="button" class="combo-item" data-cc="${c.cc}">
        <img src="${flagUrl(c.cc)}" alt=""> <span class="n">${COUNTRY_NAMES[c.cc] || c.cc}</span>
        <span class="c">${c.count}</span>
      </button>`).join("")
    : '<div class="combo-empty">No country matches.</div>';
}
renderComboList();

comboInput.addEventListener("focus", () => {
  combo.classList.add("open");
  comboInput.setAttribute("aria-expanded", "true");
});
comboInput.addEventListener("input", () => renderComboList(comboInput.value));
comboInput.addEventListener("blur", () => setTimeout(() => {
  combo.classList.remove("open");
  comboInput.setAttribute("aria-expanded", "false");
}, 150));
comboList.addEventListener("mousedown", (e) => {
  const item = e.target.closest(".combo-item");
  if (!item) return;
  e.preventDefault();
  comboInput.value = COUNTRY_NAMES[item.dataset.cc] || item.dataset.cc;
  combo.classList.remove("open");
});

// selection bar demo
const selBar = document.getElementById("selection-bar");
const selCount = document.getElementById("sel-count");

function refreshSelDemo() {
  const n = document.querySelectorAll(".row-check:checked").length;
  selCount.textContent = n;
  document.getElementById("copy-n").textContent = n;
  document.getElementById("dl-n").textContent = n;
  selBar.classList.toggle("hidden", n === 0);
  document.querySelectorAll("#results-body tr").forEach((tr) => {
    tr.classList.toggle("selected", tr.querySelector(".row-check").checked);
  });
}

document.getElementById("results-body").addEventListener("change", (e) => {
  if (e.target.classList.contains("row-check")) refreshSelDemo();
});
document.getElementById("check-all").addEventListener("change", (e) => {
  document.querySelectorAll(".row-check").forEach((cb) => { cb.checked = e.target.checked; });
  refreshSelDemo();
});
document.getElementById("clear-sel").addEventListener("click", () => {
  document.querySelectorAll(".row-check").forEach((cb) => { cb.checked = false; });
  document.getElementById("check-all").checked = false;
  refreshSelDemo();
});

// single-row copy demo (real clipboard; visual swap, no alert())
const copyIco = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="5.5" y="5.5" width="8" height="8" rx="1.5"/><path d="M10.5 5.5v-2A1.5 1.5 0 0 0 9 2H3.5A1.5 1.5 0 0 0 2 3.5V9a1.5 1.5 0 0 0 1.5 1.5h2"/></svg>';
const checkIco = '<svg viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="m3 8.5 3.5 3.5L13 5"/></svg>';

function copyText(text) {
  if (navigator.clipboard && window.isSecureContext) {
    return navigator.clipboard.writeText(text);
  }
  return new Promise((resolve) => {  // file:// fallback
    const ta = document.createElement("textarea");
    ta.value = text;
    ta.style.position = "fixed";
    ta.style.opacity = "0";
    document.body.appendChild(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
    resolve();
  });
}

document.getElementById("results-body").addEventListener("click", (e) => {
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
