# Changelog

All notable changes to YUEL are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[SemVer](https://semver.org/).

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
