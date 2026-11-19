# Changelog

All notable changes to YUEL are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[SemVer](https://semver.org/).

## [Unreleased]

### Added

- **README: fully animated SVG card set.** Ten cards (header, stats strip,
  flow graph, quality tiers, collection funnel, top countries, protocol
  donut, pipeline architecture, divider, footer), each in a light and a
  dark variant, generated from the real run output by
  `scripts/render_assets.py` — CSS-keyframe animations (traveling packets,
  marching dashes, ping rings, rising particles, waves, highlight sweep,
  draw-in bars, heartbeat numbers) all guarded by `prefers-reduced-motion`.
- **publish: per-tier output files.** The publish stage now writes
  `data/out/by-tier/{gold,silver,bronze}.json` (stable contract: all three
  files always exist) alongside `all.json` and the per-country lists;
  the README tier/funnel cards link to them.

## [0.7.1] - 2026-11-19

### Fixed

- **geo: parse the real `ip2asn-v4.tsv` format.** The first full end-to-end
  run degraded gracefully (all 841 alive proxies `unclassified`, warning
  surfaced, pipeline exit 0 — degradation worked as designed) because the
  table's bounds are **dotted quads** (`1.0.0.0\t1.0.0.255\t13335\tUS\t…`),
  not integers, so the integer-only parser rejected every row and produced
  an empty table. `GeoTable.from_tsv` now accepts both dotted-quad and
  integer bounds and skips iptoasn's `None`-country "Not routed" rows.
  Fixture updated to the real format; suite: **165 tests**.

## [0.7.0] - 2026-11-19

### Added

- Stage 7 — **automate** (`.github/workflows/pipeline.yml`):
  - Scheduled GitHub Actions workflow running the full chain
    (collect → normalize → validate → score → geo → publish) every 30
    minutes (`*/30 * * * *`, matching the consumer cadence) plus
    `workflow_dispatch` for manual triggers.
  - **Fail-loud**: the pipeline exits non-zero on the first failing stage
    and a sanity step re-verifies `run-summary.json` (published > 0) — any
    failure is a red run in the Actions tab, never silently-stale data.
  - Publishes by committing `data/out/` to `main` (`[skip ci]`, one commit
    per run) so consumers read stable raw.githubusercontent URLs;
    `permissions: contents: write`, `concurrency` group serializes runs
    (never a killed mid-publish run), `timeout-minutes: 90`.
  - README documents manual runs (`python3 -m yuel.pipeline run`,
    `gh workflow run pipeline`) and an honest free-tier assessment: public
    repo = free standard runners with no minutes cap; full-run runtime
    (~30–45 min) exceeds the 30-minute cron, so the concurrency group makes
    the effective cadence back-to-back; scheduled workflows auto-pause
    after 60 days without repo activity.
- All seven stages are now implemented; the pipeline is end-to-end.

## [0.6.0] - 2026-11-19

### Added

- Stage 6 — **publish** (`yuel/publish.py`, `config/publish.json`):
  - The stable output contract now exists: `data/out/all.json` (every alive
    proxy, all tiers — documented interpretation of "all tiers"),
    `data/out/by-country/<ISO2>.json` (tier != `excluded` only),
    `data/out/by-country/unclassified.json` (always present, may be empty),
    `data/out/run-summary.json` (counts per country/tier + chain totals
    pulled from the earlier stages' reports). Records are plain-proxy
    shaped — `{ip, port, type: socks5|socks4|http, user?, pass?, country,
    score, tier, last_checked, consecutive_successes,
    consecutive_failures}` — with `user`/`pass` present only when the
    proxy has credentials. Must never be confused with a tunnel-config feed.
  - **Atomic publish**: everything is built in `data/.out_staging/`,
    validated (every file parses, `all.json` non-empty, country files
    non-empty — `unclassified.json` exempt), then swapped into
    `data/out/` with rollback; a validation failure or I/O error aborts and
    **previously-good output stays intact**. A run with zero alive proxies
    refuses to publish entirely (an empty fleet is a health problem, not
    fresh data).
  - `data/out/` is committed by the automation (stage 7) so consumers get
    stable raw.githubusercontent URLs; `.gitignore` restructured
    (`data/*` + `!data/out/`, staging/prev/cache/history still ignored).
- CLI: `python -m yuel.pipeline publish [--publish-config PATH]`; `run`
  chain is now collect → normalize → validate → score → geo → publish.
- Tests: 13 new — exact contract shape (with/without credentials),
  per-country grouping + score-desc ordering, unclassified exemptions,
  run-summary totals, empty-run refusal, simulated validation failure with
  old-output intact, replacement between runs. Suite total: **164 tests**.

## [0.5.0] - 2026-11-19

### Added

- Stage 5 — **geo** (`yuel/geo.py`, `config/geo.json`):
  - Data source: **iptoasn.com `ip2asn-v4.tsv.gz`** — free, public-domain,
    refreshed daily, single gzip TSV, no registration (choice documented in
    the module docstring). The lookup core is `GeoTable` (parsed from TSV
    text, sorted ranges + bisect) so the source is swappable by changing
    only the fetch/parse glue; `table_url` and `refresh_hours` live in
    `config/geo.json`.
  - Downloaded **once per refresh window** (default 72 h), cached at
    `data/cache/geo/ip2asn-v4.tsv.gz` with an atomic cache write.
  - Graceful degradation, never crashes the pipeline: refresh failure →
    stale cache still used with a warning surfaced in the stage detail and
    report; no cache at all → every proxy `unclassified`, stage still OK.
  - Only literal IPv4 hosts are classified; domain-hosted proxies and IPv6
    hosts are explicitly `unclassified` — never guessed. IPs outside every
    range are also `unclassified`. The report separates the reasons
    (domain_or_ipv6_host / not_in_table / table_unavailable).
  - Stage output: `data/geo/proxies_geo.json` (scored entries + `country`)
    and `data/geo/geo_report.json` (table info, per-country counts,
    unclassified reasons).
- CLI: `python -m yuel.pipeline geo [--geo-config PATH]`; `run` chain is now
  collect → normalize → validate → score → geo.
- Tests: 20 new — fixture-table lookup (inside ranges, inclusive boundaries,
  gaps, single-IP ranges, invalid rows, unsorted input), cache freshness /
  stale-reuse / corrupt-refetch / no-cache degradation (fetch seam, no
  network), config validation, and stage flows. Suite total: **151 tests**.

## [0.4.0] - 2026-11-19

### Added

- Stage 4 — **score** (`yuel/score.py`, `yuel/history.py`,
  `config/score.json`):
  - Four components, each normalized 0–100 with **weight re-normalization
    over the components actually available** per proxy: relative latency
    (percentile rank within the current run's alive distribution — fastest
    ≈ 100, slowest ≈ 0, ties share a rank; never a fixed arbitrary scale),
    success rate from rolling history (only meaningful from
    `min_events_for_success` events — checked-once-alive proxies are not
    "reliable" yet, so the weight is redistributed), linear freshness decay
    (`freshness_window_hours`, default 24), and anonymity level
    (elite 100 / anonymous 70 / transparent 30; unknown → unavailable).
    Anonymity replaces the tunnel-era "protocol strength" component.
  - Tier thresholds are **config**, not magic numbers: gold ≥ 80, silver ≥ 50,
    bronze ≥ 20, below → `excluded` (defaults in `config/score.json`,
    validated: gold > silver > bronze > 0).
  - Rolling per-identity history (`yuel/history.py`, file
    `data/history/check_history.json`): every tested proxy (alive or dead)
    appends `{utc, ok, latency_ms}` per run; per-identity events capped at
    `max_entries_per_identity` (10); identities silent beyond
    `inactivity_days` (7) are pruned; corrupt file degrades to fresh;
    save is atomic (temp + `os.replace`). Derived facts: success_rate,
    total_events, consecutive_successes, consecutive_failures.
  - Stage output: `data/scored/proxies_scored.json` (alive only, sorted by
    score, each entry carries `score` {total, tier, components,
    weights_effective} + `history` facts) and `data/scored/score_report.json`
    (tier distribution, score percentiles, history stats).
- CLI: `python -m yuel.pipeline score [--score-config PATH]`; `run` chain is
  now collect → normalize → validate → score.
- Tests: 38 new — hand-picked formula cases with expected values computed in
  the assertions (component math, exact renormalization, tier boundaries,
  custom thresholds), history append/cap/prune/streaks, atomic save, corrupt
  handling, and stage flows with pre-seeded history. Suite total: **131 tests**.

## [0.3.0] - 2026-11-19

### Changed — SCOPE CORRECTION (breaking)

The project goal was mis-specified before this release. YUEL collects **plain
SOCKS4/SOCKS5/HTTP proxy servers** — bare `ip:port` / `ip:port:user:pass`
entries meant to be chained as an outbound hop (egress-IP/country swap) —
**not** standalone tunnel endpoints (`vmess://`, `vless://`, `trojan://`,
`ss://`, `hysteria2://`, `tuic://`), which are complete VPN servers of a
different product. Everything below re-aligns the pipeline with the
corrected goal; v0.1.0/v0.2.0 shipped tunnel-scope stages 1–2, and an
unreleased tunnel-scope stage 3 (xray/sing-box engine machinery) existed in
the working tree and was replaced.

- **Kept and adapted** (the genuinely reusable pieces):
  - Repo scaffolding: layout, MIT, `.gitignore`, defensive per-source error
    capture, never-raises parsing discipline, stage reports with samples,
    `StageResult` + orchestrator + CLI pattern (`yuel/stage.py`,
    `yuel/pipeline.py`), default-path helpers and strict config validation.
  - `socks5.py` — the stdlib SOCKS5 no-auth CONNECT client and tunneled-HTTP
    probe survive as the core of the new `yuel/proxy_client.py`, extended
    with SOCKS5 username/password auth (RFC 1929), a SOCKS4 client, and
    HTTP-proxy GET (absolute-URI) / CONNECT clients.
  - Stage 3's TCP prefilter, bounded worker pool, latency percentiles, and
    report structure carried over from the engine-based draft.
- **Rewritten**:
  - `config/sources.json` (schema v2): 24 verified plain-proxy sources
    (GitHub raw lists + public aggregator APIs). Every seed source from the
    corrected brief is included after a live check (clarketm is reachable
    but stale since 2023 — kept `enabled: false` with a note). Independently
    discovered and verified: monosans (×3 files), zloi-user/hideip.me (×3),
    mmpx12 (×2), iplocate, geonode JSON API, ProxyScrape free API (×2).
    Evaluated and skipped: ShmoTick (dead 404), roosterkid (near-dead),
    TheSpeedX/PROXY-List (exact duplicate of SOCKS-List). Each source
    records url, format, claimed type/country/anonymity, and
    added/verified notes.
  - `yuel/config.py` — schema v2 with `format` (six formats: `ip:port`,
    `ip:port:user:pass`, `ip:port:country`, `user:pass@ip:port`,
    `proto-prefixed`, `json-structured`) and claim fields.
  - `yuel/collect.py` — fetch layer kept; all URI/tunnel parsing replaced by
    plain-proxy line parsers for the six formats, junk-tolerant, claims
    attached per entry; `identity` = `host|port|user|pass`.
  - `yuel/normalize.py` — dedupe by the new identity (credentials are part
    of it), deterministic claim merging (agreement → value, disagreement →
    null + `claim_conflicts` flag), `sources` merge preserved.
  - `yuel/validate.py` — the key difference: **no engine binaries at all**.
    Prefilter (TCP connect per unique host:port, 128 workers) then direct
    handshakes in claim-implied order (unknown → SOCKS5 → HTTP GET → HTTP
    CONNECT); first real HTTP < 400 through the proxy wins and is recorded
    as `type_confirmed` + `method_used`; claim-vs-measured calibration
    (agree/disagree/unknown) in the report.
- **Removed**: `yuel/engine_config.py`, `yuel/engines.py`, `yuel/socks5.py`
  (superseded by `yuel/proxy_client.py`), `scripts/pin_engines.py`, the
  engines block of `config/validate.json`, and their tests — plain-proxy
  validation needs no external binaries, downloads, or process cleanup.
- Tests: rewritten for the new scope — format parsers, claim merging, and
  real handshake flows against in-process fake SOCKS5 (incl. RFC 1929 auth),
  SOCKS4, and HTTP-proxy servers (plain GET / CONNECT / 407 / 405 paths).
  Suite total: **93 tests**.
- Docs: README rewritten for the corrected scope (chaining use case, source
  formats, validation approach, plain-proxy output contract with an explicit
  never-confuse-with-tunnel-configs note).

## [0.2.0] - 2026-11-19

### Added

- Stage 2 — **normalize** (`yuel/normalize.py`):
  - Dedupe by *effective connection identity* (`scheme|host|port|secret`,
    host lowercased) — the same node with reordered query params, different
    display tags, or published by several sources collapses to one entry.
  - Deterministic representative selection per target: richest metadata
    wins (most params → most extras → longest name → canonical JSON dump
    tie-break), so output is reproducible byte-for-byte.
  - Merged `sources` list (sorted, unique) on every entry — preserves how
    many independent lists carried the node, for later freshness scoring.
  - Defensive re-validation of stage-1 rows: invalid entries are dropped,
    counted, and sampled (up to 5) in `normalize_report.json`; the stage
    never raises on malformed rows.
  - Per-target output sorted by `identity`; per-scheme counts in the report.
- CLI: `python -m yuel.pipeline normalize` (stage 2 only) and a real
  `run` chain (collect → normalize), stopping at the first failing stage.
  `normalize` fails gracefully when stage-1 output is missing/corrupt.
- `validate_endpoint` is now a public API of `yuel.collect`, reused by
  normalize (was private `_validate_endpoint`).
- Tests: 17 new pure-logic tests (dedupe identity, merge determinism,
  invalid-row handling, sources merging, by-scheme counts, stage-2 file
  handling with corrupt/missing input). Suite total: **65 tests**.

## [0.1.0] - 2026-11-19

### Added

- Project scaffold: package layout (`yuel/`), orchestrator CLI
  (`python -m yuel.pipeline collect|run`), MIT license, `.gitignore`.
- Stage 1 — **collect**:
  - Source list externalized to `config/sources.json` (data, not code),
    with strict schema validation in `yuel/config.py` (unique ids, known
    types, http(s) URLs, positive defaults).
  - Fetchers for `raw_http` sources and public Telegram channel web
    previews (`https://t.me/s/<channel>`), with per-source timeout, size
    cap, UA header, and concurrency-limited parallel fetching.
  - Per-source error capture: one dead source never fails the stage —
    HTTP errors, DNS/URL errors, timeouts, oversized bodies, and even
    worker crashes are recorded in the run report and the run continues.
  - Regex extraction for vmess/vless/trojan/ss/hysteria2 (`hy2`)/tuic,
    tolerant of HTML-escaped text, comma-separated lists, trailing
    punctuation, and wrong base64 padding/urlsafe alphabets; `ssr://` and
    plain `http(s)://` deliberately ignored.
  - Whole-body base64 subscription fallback (mode recorded per source).
  - Per-scheme parsing into a canonical endpoint dict, including SIP002 +
    legacy ss forms, plain 2022-cipher userinfos, bracketed IPv6, trailing
    dot FQDNs, userinfo containing `@`, hysteria2 `?auth=` fallback, and
    tuic `uuid:password` splitting.
  - `identity` key on every endpoint (`scheme|host|port|secret`, host
    lowercased) — the future dedupe key for stage 2 (normalize).
  - Endpoint validation: host shape, port range, uuid shape, ss cipher
    method, hysteria2 auth presence.
- Tests: 48 pure-logic unit tests (extraction, per-scheme parsing,
  identity stability, parse-never-raises corpus, run_collect error
  handling with fake fetchers, sources-file schema validation). No
  network or engines required.
- Source intake verified live on 2026-11-19: 5 working sources
  (2 large GitHub aggregators, 2 base64 subscription files, 1 Telegram
  channel preview). Pruned with evidence: `Epodonios/v2ray-configs`
  (repo gone → 404), `barry-far/V2ray-Configs` (renamed — correct path is
  `V2ray-Config`), `t.me/s/freev2ray` and `t.me/s/vless_config_vpn`
  (placeholder pages, 0 endpoints).

### Notes

- Stages 2–7 (normalize, validate, score, geo, publish, automation) are
  scaffolded in the architecture and will be implemented one stage at a
  time; stage 1 pauses here for review of the source list and extraction
  approach.
