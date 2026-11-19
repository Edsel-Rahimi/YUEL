# Changelog

All notable changes to YUEL are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[SemVer](https://semver.org/).

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
