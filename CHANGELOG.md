# Changelog

All notable changes to YUEL are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/) and the project uses
[SemVer](https://semver.org/).

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
