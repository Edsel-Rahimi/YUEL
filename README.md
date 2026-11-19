# YUEL

Automated pipeline that collects publicly published **plain SOCKS4/SOCKS5/HTTP
proxy servers** — bare `ip:port` / `ip:port:user:pass` entries — really tests
which ones are alive (and which protocol each one actually speaks), scores and
tiers them by quality, classifies them by country, and publishes
machine-readable files that a proxy-chaining consumer can use directly to
swap its egress hop (e.g. "give me an Italian exit").

**These are NOT tunnel configs.** YUEL deliberately does not handle
`vmess://` / `vless://` / `trojan://` / `ss://` / `hysteria2://` / `tuic://`
URIs — those are standalone VPN endpoints with their own tunnel encryption,
a different product (that was the pre-0.3.0 scope; it has been removed).
Plain proxies chain in FRONT of or BEHIND another connection as an outbound
hop; their output contract below is different by design and must never be
confused with a tunnel-config feed downstream.

**Status: stages 1–3 (collect, normalize, validate) implemented against the
corrected scope. Later stages are built one at a time — see the table.**

This repository is a fresh, independently written codebase. It shares no
code, config, or history with any other project.

---

## Architecture

```
 config/sources.json
 (plain-proxy list sources)
        │
        ▼
 ┌─────────────┐    ┌─────────────┐    ┌──────────────┐    ┌─────────┐
 │ 1. collect  │───▶│ 2. normalize│───▶│ 3. validate  │───▶│ 4. score│
 │ fetch lists │    │ dedupe by   │    │ TCP prefilter│    │ latency,│
 │ parse ip:port│   │ connection  │    │ + real SOCKS5│    │ success,│
 │ (+creds)    │    │ identity    │    │ /SOCKS4/HTTP │    │ freshness│
 │             │    │             │    │ handshakes   │    │ anonymity│
 └─────────────┘    └─────────────┘    └──────────────┘    └─────────┘
                                                                │
 ┌─────────────┐    ┌─────────────┐    ┌──────────────────────────▼──┐
 │ 7. automate │◀───│ 6. publish  │◀───│ 5. geo                        │
 │ scheduled   │    │ {ip,port,   │    │ IP→country via a free public  │
 │ CI runs     │    │ type,user?, │    │ IP-to-country table           │
 │             │    │ pass?,countr│    │                               │
 │             │    │ ,score,tier}│    │                               │
 └─────────────┘    └─────────────┘    └───────────────────────────────┘
```

| Stage | What it does | Status |
| --- | --- | --- |
| 1. collect | Fetch list sources (raw `ip:port` text files, proto-prefixed csv, JSON APIs) from GitHub repos and public aggregator APIs, parse every entry into a canonical dict with the source's *claims* (type / country / anonymity) attached. One dead source never crashes the run — errors are recorded per source; malformed lines are counted and sampled. | **implemented** (v0.3.0) |
| 2. normalize | Dedupe by *effective connection identity* (`host\|port\|user\|pass`, host lowercased — same server with different credentials stays separate), merge claims deterministically (agreement → value; disagreement → null + flagged as a data-quality signal), merge sorted `sources` lists, drop invalid rows. Byte-for-byte reproducible. | **implemented** (v0.3.0) |
| 3. validate | Two passes, **no engine binaries**. Prefilter: plain TCP connect per unique `host:port` (128 workers). Handshake pass: real SOCKS5 greeting (+ RFC 1929 auth when creds exist) → CONNECT, real SOCKS4 CONNECT, real HTTP proxy GET (absolute-URI) / CONNECT — tried in claim-implied order (unknown → SOCKS5 first, then HTTP GET, then HTTP CONNECT). The first protocol that returns a real HTTP status < 400 through the proxy wins and is recorded as `type_confirmed`. Bounded worker pool, latency percentiles, claim-vs-measured calibration in the report. | **implemented** (v0.3.0) |
| 4. score | Weighted formula over latency, success rate, freshness — plus *anonymity level* (transparent / anonymous / elite) where the source or the proxy's behavior reveals it, replacing the old "protocol strength" component (plain proxies are undifferentiated; there is no reality/hysteria2 tier to rank). Mapped to configurable tiers (gold/silver/bronze). | planned |
| 5. geo | Country of literal-IP hosts via a free public IP-to-country table (iptoasn.com `ip2asn-v4.tsv`), refreshed regularly; table download failure degrades to "unclassified" instead of crashing. Domain-hosted endpoints are explicitly `unclassified`, never guessed. This is what lets a member pick "Italy" and get an Italian-exit proxy. | planned |
| 6. publish | Writes the chaining-consumer contract (see below): per-tier lists, **per-country lists**, audit history, run summary. Explicitly a plain-proxy format — never a vmess/vless/... feed. | planned |
| 7. automate | One entrypoint runs all stages in order with graceful partial-failure handling; GitHub Actions runs it on a schedule and commits the output. | planned |

## Repository layout

```
YUEL/
├── README.md                  ← you are here
├── CHANGELOG.md               ← running changelog, updated every stage
├── LICENSE                    ← MIT
├── config/
│   ├── sources.json           ← the plain-proxy source list (data, not code)
│   └── validate.json          ← validate stage: probe URL + timeouts + workers
├── yuel/
│   ├── __init__.py
│   ├── config.py              ← sources-file loading + strict schema validation
│   ├── collect.py             ← stage 1: fetchers + plain-proxy line parsers
│   ├── normalize.py           ← stage 2: identity dedupe + claim merge
│   ├── proxy_client.py        ← stage 3: SOCKS5(+auth)/SOCKS4/HTTP proxy clients
│   ├── validate.py            ← stage 3: TCP prefilter + handshake checks
│   ├── stage.py               ← shared StageResult dataclass
│   └── pipeline.py            ← orchestrator + CLI entrypoint
├── tests/
│   ├── test_collect.py        ← format parsers, identity, run error-handling
│   ├── test_config.py         ← sources-file schema validation
│   ├── test_normalize.py      ← dedupe, claim merging, determinism
│   ├── test_pipeline.py       ← stage chaining + graceful failure (file-based)
│   ├── test_proxy_client.py   ← handshakes against fake SOCKS5/SOCKS4/HTTP servers
│   └── test_validate.py       ← prefilter + checks + stage flows (fake proxies)
└── data/                      ← stage output (gitignored; the publish stage
                                  will define what gets committed)
```

## Quickstart

Python 3.10+ — **no third-party dependencies** (stdlib only), and validation
spawns **no binaries**: everything is raw sockets.

```bash
# run the test suite (pure logic + fake proxy servers, no network)
python3 -m unittest discover -s tests -t .

# run all implemented stages in order (collect → … → publish)
python3 -m yuel.pipeline run

# or a single stage
python3 -m yuel.pipeline collect     # stage 1: fetch sources, parse entries
python3 -m yuel.pipeline normalize   # stage 2: dedupe stage-1 output
python3 -m yuel.pipeline validate    # stage 3: prefilter + handshake checks
python3 -m yuel.pipeline validate --prefilter-only   # pass 1 only
python3 -m yuel.pipeline validate --limit 100        # demo: first 100 survivors

# stage output lands in:
#   data/collected/
#     proxies_raw.json         canonical proxy dicts, one per parsed line
#     collect_report.json      per-source status, totals, failure samples
#   data/normalized/
#     proxies_normalized.json  ONE entry per effective connection target
#     normalize_report.json    dedupe totals, claim counts, audit samples
#   data/validated/
#     proxies_validated.json   tested targets with check verdict + latency
#     validate_report.json     prefilter/check totals, percentiles, calibration
```

Every command accepts `--sources PATH` and `--data-dir PATH`; the same can be
set through the `YUEL_SOURCES` and `YUEL_DATA_DIR` environment variables
(`YUEL_VALIDATE_CONFIG` overrides the validate config path).

Exit code is 0 when every stage succeeded, 1 when a stage failed (the run
stops at the first failing stage; earlier stages' output stays intact).

## Source config format

Sources live in `config/sources.json` — never hardcoded — so the list can
grow without touching the collector. Every source was verified live
(HTTP 200 + plausible content) before being added; the verification date is
recorded in its `notes`:

```json
{
  "schema_version": 2,
  "defaults": {"timeout_seconds": 20, "max_bytes": 20000000,
               "fetch_concurrency": 6, "user_agent": "YUEL-collector/0.3"},
  "sources": [
    {
      "id": "my-source",            // lowercase a-z, digits, '-', '_'; unique
      "url": "https://...",         // http(s) only
      "format": "ip:port",          // see the six formats below
      "claimed_type": "socks5",     // source-level claim: socks4/socks5/http/https/null
      "claimed_country": false,     // does the source assert a country?
      "claimed_anonymity": null,    // "transparent"/"anonymous"/"elite"/null
      "enabled": true,              // optional, default true
      "notes": "added 2026-11-19; verified live 2026-11-19 (2797 lines)"
    }
  ]
}
```

The six supported `format` values:

| format | line shape | example |
| --- | --- | --- |
| `ip:port` | bare entries, `#` comments skipped | `1.2.3.4:8080` |
| `ip:port:user:pass` | credentials (password may contain `:`) | `1.2.3.4:8080:alice:s3cret` |
| `ip:port:country` | trailing country-name claim | `1.2.3.4:8080:United States` |
| `user:pass@ip:port` | credentials before the host | `alice:s3cret@1.2.3.4:8080` |
| `proto-prefixed` | `proto://[user:pass@]ip:port[,COUNTRY,CITY]` | `socks5://1.2.3.4:1080,US,Alexandria` |
| `json-structured` | JSON rows with ip/port/protocols/country/anonymity | geonode API |

Rules:

- Claims are **not trusted** — they are recorded so stage 3 can calibrate
  them against its own live measurements; a source whose claims frequently
  disagree is a future data-quality flag.
- A dead source never fails the stage: its error is recorded in
  `collect_report.json` under that source's entry and the run continues.
- Malformed lines inside a source (junk, error pages, bad ports) are counted,
  with up to 5 samples kept in `failure_samples` for debugging.
- Only openly published sources are added (raw GitHub files, public APIs
  built for this exact purpose). No payment, no registration, no scraping
  against robots/ToS. Stale repos are kept `enabled: false` with a note
  rather than deleted, so the history stays auditable.

## Stage 1: parsing approach

1. **Format-driven parsing.** Each source declares its line format; one
   small parser per format handles host/port extraction (bracketed IPv6
   literals supported, trailing-dot FQDNs tolerated), credential splitting
   (split at the last `@`; password keeps embedded colons), and claim
   extraction (protocol prefix, country column, anonymity level).
2. **Junk tolerance.** Comment/blank lines are skipped silently; anything
   unparseable (Cloudflare error pages that leak into some lists, bad ports,
   whitespace inside credentials) becomes a counted failure with samples.
3. **JSON APIs.** Geonode-style documents (`{"data": [...]}`) yield one
   candidate per record; a record with exactly one claimed protocol gets it,
   a multi-protocol record stays `claimed_type: null` for validation to
   decide; `anonymityLevel` is kept when it is one of the known levels.
4. **Canonical form.** Every parsed entry passes a sanity check (host shape,
   port range, credential charset) and becomes:

```json
{
  "host": "1.2.3.4",
  "port": 8080,
  "username": "",
  "password": "",
  "claimed_type": "socks5",
  "claimed_country": "US",
  "claimed_anonymity": null,
  "identity": "1.2.3.4|8080||",
  "source": "thespeedx-socks5"
}
```

`identity` is the dedupe key stage 2 uses: `host|port|username|password`
with the host lowercased. Stage 1 does **not** dedupe; that is normalize's
job.

### Normalized proxy schema (v0.1 draft)

`data/normalized/proxies_normalized.json` is a JSON array with **one entry
per effective connection target**, sorted by `identity`:

```json
{
  "host": "1.2.3.4",
  "port": 8080,
  "username": "",
  "password": "",
  "claimed_type": "socks5",
  "claimed_country": "US",
  "claimed_anonymity": null,
  "identity": "1.2.3.4|8080||",
  "sources": ["thespeedx-socks5", "monosans-socks5"],
  "claim_conflicts": []
}
```

Merge rules (documented so downstream consumers can rely on them):

- Credentials are part of the identity: the same server with different
  credentials is a different entry (different access path).
- Claims are merged across duplicates: when all sources agree, the value is
  kept; when they disagree, the claim is set to `null` and the conflict is
  listed in `claim_conflicts` (`"type"`, `"country"`, `"anonymity"`).
- `sources` accumulates every source id that published this target — how
  many independent lists carried the server is preserved for later scoring.
- Rows failing validation (defensive re-check of stage-1 output) are dropped
  and counted in `normalize_report.json` with up to 5 samples.

## Stage 3: validation approach

**Pass 1 — TCP prefilter.** One plain `socket.create_connection` per
*unique* `host:port` pair (128 workers). Unreachable targets never reach
the handshake pass — the prefilter keeps the expensive pass small. Their
verdict lives in `validate_report.json`, not in the validated list.

**Pass 2 — real protocol handshakes (no engines, no subprocesses).** Each
survivor is tried with the strategies its claim implies:

| claimed type | strategies tried, in order |
| --- | --- |
| `socks5` | SOCKS5 greeting (+ RFC 1929 username/password when creds exist) → CONNECT → GET |
| `socks4` | SOCKS4 CONNECT (target resolved to IPv4 locally) → GET |
| `http`   | plain proxied GET (absolute-URI), then CONNECT tunnel |
| `https`  | CONNECT tunnel, then plain proxied GET |
| unknown  | SOCKS5 → HTTP GET → HTTP CONNECT |

The first strategy that returns a real HTTP status < 400 through the proxy
wins. The measured protocol is recorded as `type_confirmed`
(`socks5`/`socks4`/`http`; CONNECT success also counts as `http` with
`method_used: "http_connect"` — tunneling capability is a separate fact the
score stage can use). Latency covers connect → handshake → CONNECT → GET →
status line. HTTP statuses ≥ 400 (e.g. a 407 auth demand or a 405) count as
a *failed* attempt, not a success.

**Claim calibration.** For every alive proxy the report compares the
claimed type with the measured one (`agree` / `disagree` / `claim-unknown`).
Over many runs this exposes sources whose assertions are unreliable — the
data-quality signal the claims were recorded for.

**Bounded concurrency.** `workers` (default 100) handshake checks run in
parallel as plain socket clients; the prefilter uses its own larger pool
(128). Progress prints every 200 checks.

### Validated proxy schema (v0.1 draft)

`data/validated/proxies_validated.json` contains every *tested* proxy (the
normalized dict plus the check verdict; the score stage filters on
`check.ok`):

```json
{
  "...": "normalized proxy fields",
  "check": {
    "ok": true,
    "type_confirmed": "socks5",
    "method_used": "socks5",
    "latency_ms": 412.7,
    "http_status": 204,
    "checked_utc": "2026-11-19T10:00:00+00:00",
    "error": null
  }
}
```

## Output file contract (v0.1 draft — finalized at stage 6)

The publish stage will make the following the stable contract. The record
shape is for **plain proxies only** and must never be confused downstream
with a vmess/vless/... tunnel-config feed:

```json
{
  "ip": "1.2.3.4",
  "port": 8080,
  "type": "socks5",
  "user": null,
  "pass": null,
  "country": "IT",
  "score": 87.2,
  "tier": "gold",
  "last_checked": "2026-11-19T10:00:00+00:00"
}
```

Planned layout:

```
data/
├── collected/                 # stage 1 output (produced)
│   ├── proxies_raw.json       # array of canonical proxy dicts (pre-dedupe)
│   └── collect_report.json    # per-source status + totals (audit trail)
├── normalized/                # stage 2 output (produced)
│   ├── proxies_normalized.json  # one entry per connection target
│   └── normalize_report.json    # dedupe totals + claim merges + samples
├── validated/                 # stage 3 output (produced)
│   ├── proxies_validated.json   # tested targets + check verdict/latency
│   └── validate_report.json     # prefilter/check totals, calibration
└── out/                       # stage 6 output (published, committed)
    ├── all.json               # every alive proxy, scored + tiered
    ├── by-tier/gold.json | silver.json | bronze.json
    ├── by-country/<ISO2>.json # alive, scored proxies per country
    ├── unclassified.json      # proxies without a trustworthy country
    ├── history/results.json   # per-proxy test history (auditable)
    └── run-summary.json       # counts, durations, stage statuses
```

Field names, tiers, and the history schema will be frozen and fully
documented here when stage 6 lands.

## Automation (stage 7)

`.github/workflows/pipeline.yml` runs the full pipeline on a schedule and
commits the published contract to `main`, so consumers read stable URLs like:

```
https://raw.githubusercontent.com/Edsel-Rahimi/YUEL/main/data/out/all.json
https://raw.githubusercontent.com/Edsel-Rahimi/YUEL/main/data/out/by-country/IT.json
https://raw.githubusercontent.com/Edsel-Rahimi/YUEL/main/data/out/run-summary.json
```

Why `main` + `data/out/` (and not a separate branch): raw file URLs stay
predictable, consumers diff outputs with plain git tooling, and one commit
per run (`[skip ci]`, so it never loops) is the simplest auditable history.
The commit is produced only by the workflow; local runs write `data/out/`
too but leave committing to git.

**Fail-loud, never stale:** the workflow runs `python3 -m yuel.pipeline run`,
which exits non-zero on the *first* failing stage; a sanity step then
re-verifies `data/out/run-summary.json` (published > 0). Any failure is a red
run in the Actions tab — a publish is atomic (stage 6), so a broken run can
never replace good output with empty data.

**Running it manually** (identical to the scheduled path):

```bash
# local, no GitHub needed
python3 -m yuel.pipeline run

# or trigger the GitHub workflow on demand
gh workflow run pipeline
```

**Honest free-tier / cadence assessment (checked 2026-11-19):**

- Public repository → GitHub-hosted `ubuntu-latest` runners are **free with
  no minutes cap**; the 30-minute cron itself is fine on the free tier.
- A full run takes **~30–45 minutes** (the handshake pass over ~40k
  reachable targets dominates). The workflow therefore serializes via a
  `concurrency` group: with a 30-minute cron the *effective* cadence is
  "one full run at a time, back-to-back" (~40–45 min), and overlapping
  scheduled invocations queue rather than pile up. If you want true
  30-minute freshness, either raise `workers` in `config/validate.json`
  (network-bound, ~150–200 is safe) or shorten the handshake pass — not by
  lowering timeouts, which would misclassify slow-but-alive proxies.
- GitHub pauses scheduled workflows on repos with **no activity for 60
  days** (any push counts; our own output commits keep it alive, but after
  a long pause re-enable the workflow from the Actions tab once).
- Very heavily scheduled workflows can be delayed during peak load — the
  cron is best-effort timing, not a guarantee.

## Security

- No secrets in code: nothing sensitive is hardcoded; CI credentials flow
  only through environment variables / GitHub Actions secrets.
- The GitHub token used to create/push this repo is never printed, logged,
  committed, or stored in the repo or in git remote URLs.
- Validation connects only to the configured probe URL *through* the
  candidate proxies; candidates are untrusted network peers, so every
  reply is length-capped and parsed defensively (never `eval`/`exec`, never
  shell-outs — there are no subprocesses at all).
- Only openly published list sources are fetched (raw GitHub files, public
  APIs meant for this); no paid, registration-walled, or
  robots/ToS-forbidden pages.
