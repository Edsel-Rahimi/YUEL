# YUEL

Automated pipeline that collects publicly available proxy/VPN endpoint
configs (vmess / vless / trojan / ss / hysteria2 / tuic), really tests which
ones are alive, scores and tiers them by quality, classifies them by country,
and publishes machine-readable files that another system can consume.

**Status: stage 1 (collect) implemented and shipped. Later stages are being
built one at a time — see the stage table below.**

This repository is a fresh, independently written codebase. It shares no
code, config, or history with any other project.

---

## Architecture

```
 config/sources.json
        │
        ▼
 ┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌─────────┐
 │ 1. collect  │───▶│ 2. normalize│───▶│ 3. validate  │───▶│ 4. score│
 │ fetch +     │    │ dedupe by   │    │ TCP prefilter│    │ weighted│
 │ extract URIs│    │ connection  │    │ + xray-core /│    │ formula │
 │             │    │ identity    │    │ sing-box live│    │ + tiers │
 └─────────────┘    └─────────────┘    └──────────────┘    └─────────┘
                                                                │
 ┌─────────────┐    ┌─────────────┐    ┌──────────────────────────▼──┐
 │ 7. automate │◀───│ 6. publish  │◀───│ 5. geo                        │
 │ scheduled   │    │ documented  │    │ IP→country via public         │
 │ CI runs     │    │ output files│    │ IP-to-ASN table               │
 └─────────────┘    └─────────────┘    └───────────────────────────────┘
```

| Stage | What it does | Status |
| --- | --- | --- |
| 1. collect | Fetch raw text from configured public sources (plain HTTP files and `https://t.me/s/<channel>` Telegram web previews), extract endpoint URIs per scheme, parse each into a canonical dict. One dead source never crashes the run — errors are recorded per source. | **implemented** (v0.1.0) |
| 2. normalize | Dedupe by *effective connection identity* (host + port + secret, not literal string — query-param order and display tags are ignored), strip invalid entries, emit one canonical list. | planned |
| 3. validate | Cheap TCP-connect prefilter; survivors get a real one-shot xray-core (vmess/vless/trojan/ss) or sing-box (hysteria2/tuic) process with a local SOCKS5 inbound routed to that outbound; a real fetch through the port measures latency and success. Engine binaries are pinned to exact versions and cached. Concurrency-limited worker pool; process cleanup on timeout. | planned |
| 4. score | Weighted formula over latency, success rate, freshness, and protocol strength (reality/hysteria2 > plain vless > ss > ssr); each component 0–100, weights re-normalized when a component is unavailable; final score mapped to configurable tiers (gold/silver/bronze). | planned |
| 5. geo | Country of literal-IP hosts via a free public IP-to-ASN/country table (iptoasn.com `ip2asn-v4.tsv`), refreshed regularly; table download failure degrades to "unclassified" instead of crashing. Domain-hosted endpoints are explicitly `unclassified`, never guessed. | planned |
| 6. publish | Writes per-tier lists, per-country lists, an auditable results/history JSON, and a run summary to a documented directory layout (contract below). | planned |
| 7. automate | One entrypoint runs all stages in order with graceful partial-failure handling; GitHub Actions runs it on a schedule and commits the output. | planned |

## Repository layout

```
YUEL/
├── README.md                  ← you are here
├── CHANGELOG.md               ← running changelog, updated every stage
├── LICENSE                    ← MIT
├── config/
│   └── sources.json           ← the source list (data, not code)
├── yuel/
│   ├── __init__.py
│   ├── config.py              ← sources-file loading + strict schema validation
│   ├── collect.py             ← stage 1: fetchers + URI extraction/parsing
│   └── pipeline.py            ← orchestrator + CLI entrypoint
├── tests/
│   ├── test_collect.py        ← extraction, parsing, identity, run error-handling
│   └── test_config.py         ← sources-file schema validation
└── data/                      ← stage output (gitignored; publish stage will
                                  define what gets committed)
```

## Quickstart

Python 3.10+ — **no third-party dependencies** (stdlib only).

```bash
# run the test suite (pure logic, no network)
python3 -m unittest discover -s tests -t .

# run stage 1 (collect) against config/sources.json
python3 -m yuel.pipeline collect

# output lands in data/collected/
#   endpoints_raw.json    canonical endpoint dicts (one JSON list)
#   collect_report.json   per-source status, totals, failure samples
```

Both commands accept `--sources PATH` and `--data-dir PATH`; the same can be
set through the `YUEL_SOURCES` and `YUEL_DATA_DIR` environment variables.

Exit code is 0 when every stage succeeded, 1 when a stage failed (the run
stops at the first failing stage; earlier stages' output stays intact).

## Source config format

Sources live in `config/sources.json` — never hardcoded — so the list can
grow without touching the collector:

```json
{
  "schema_version": 1,
  "defaults": {"timeout_seconds": 20, "max_bytes": 8000000, "fetch_concurrency": 6},
  "sources": [
    {
      "id": "my-source",            // lowercase a-z, digits, '-', '_'; unique
      "type": "raw_http",           // "raw_http" or "telegram_preview"
      "url": "https://...",         // http(s) only
      "enabled": true,              // optional, default true
      "tags": ["github"],           // optional
      "note": "why this source exists"  // optional
    }
  ]
}
```

Rules:

- `type: "raw_http"` — plain file (URI list or whole-body base64 subscription).
- `type: "telegram_preview"` — public channel web preview at `https://t.me/s/<channel>`.
- A dead source never fails the stage: its error is recorded in
  `collect_report.json` under that source's entry and the run continues.
- Malformed entries inside a source are counted, with up to 5 samples kept in
  `failure_samples` for debugging.

## Stage 1: extraction approach

1. **Regex per scheme.** One token regex matches all supported schemes
   (`vmess|vless|trojan|ss|hysteria2|hy2|tuic`) with a charset that excludes
   whitespace and the characters that wrap URIs in HTML/Markdown (quotes,
   angle brackets, backticks, parentheses, braces, pipes, asterisks,
   commas). This splits comma-separated lists and ignores `ssr://` and
   plain `http(s)://` URLs.
2. **HTML tolerance.** Telegram preview pages are fetched, `<script>` /
   `<style>` blocks are stripped, and `&amp;`-style entities are unescaped
   before/while parsing, so URIs embedded in message HTML parse correctly.
3. **Whole-body base64 fallback.** If a document yields no URIs directly and
   looks like one big base64 blob (subscription style), it is decoded and
   re-scanned; the report records `mode: "base64"` per source.
4. **Per-scheme parsing.**
   - `vmess://` — base64(JSON) payload (v2fly format); requires `add`,
     `port`, `id`; transport/TLS keys map into `params`; extra JSON keys are
     preserved under `extra.fields`.
   - `ss://` — both SIP002 (`ss://b64(method:pass)@host:port`) and the
     legacy whole-base64 form, plus plain 2022-cipher userinfos; `plugin`
     query preserved.
   - `vless://`, `trojan://` — `secret@host:port?params#tag`.
   - `hysteria2://` (alias `hy2://`) — auth from userinfo or `?auth=`.
   - `tuic://` — `uuid:password@host:port`.
   - Bracketed IPv6 literals, trailing-dot FQDNs, userinfo containing `@`
     (split at the last `@`), wrong base64 padding, urlsafe alphabets, and
     trailing punctuation glued to tokens are all handled.
5. **Validation and canonical form.** Every parsed entry is checked (host
   shape, port range, uuid shape where applicable, cipher method present for
   ss, auth present for hysteria2) and turned into a canonical dict.

### Canonical endpoint schema (v0.1 draft)

`data/collected/endpoints_raw.json` is a JSON array of these objects:

```json
{
  "scheme": "vless",
  "host": "v1.example.com",
  "port": 443,
  "secret": "<uuid or password>",
  "params": {"security": "reality", "sni": "www.example.com", "pbk": "..."},
  "name": "display tag / ps field",
  "extra": {"method": "aes-256-gcm"},     // scheme-specific extras
  "identity": "vless|v1.example.com|443|<secret>",
  "source": "solispirit-all"
}
```

- `identity` is the dedupe key stage 2 will use: same host + port + secret
  is the same target even when query-param order or the display tag differs.
  Host is lowercased (trailing root dot stripped); scheme is part of the key
  because one host:port can speak two protocols.
- Stage 1 does **not** dedupe across sources; that is normalize's job.

## Output file contract (v0.1 draft — finalized at stage 6)

The publish stage (stage 6) will make the following the stable contract;
until then treat everything under `data/` as moving. Planned layout:

```
data/
├── collected/                 # stage 1 output (already produced)
│   ├── endpoints_raw.json     # array of canonical endpoint dicts
│   └── collect_report.json    # per-source status + totals (audit trail)
└── out/                       # stage 6 output (published, committed)
    ├── all.json               # every alive endpoint, scored + tiered
    ├── by-tier/gold.json | silver.json | bronze.json
    ├── by-country/<ISO2>.json # alive, scored endpoints per country
    ├── unclassified.json      # endpoints without a trustworthy country
    ├── history/results.json   # per-endpoint test history (auditable)
    └── run-summary.json       # counts, durations, stage statuses
```

Field names, tiers, and the history schema will be frozen and fully
documented here when stage 6 lands.

## Security

- No secrets in code: nothing sensitive is hardcoded; CI credentials flow
  only through environment variables / GitHub Actions secrets.
- The GitHub token used to create/push this repo is never printed, logged,
  committed, or stored in the repo or in git remote URLs.
- Later stages pin exact xray-core / sing-box release versions (downloaded
  once per run, cached) — never floating "latest".
