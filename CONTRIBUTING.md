# Contributing to YUEL

The most useful contribution is a **new plain-proxy list source**. Sources
live in `config/sources.json` — never in code — so proposing one is a
one-object PR to that file. This guide covers exactly what such a PR needs
and what gets checked before it is merged.

## What qualifies as a source

- Publicly and openly published: raw GitHub files, public aggregator APIs
  built to be consumed. **No** payment walls, **no** registration, **no**
  fetching against robots.txt or a site's ToS.
- Contains plain proxy entries (`ip:port` / `ip:port:user:pass` shapes).
  Tunnel-config feeds (`vmess://`, `vless://`, `trojan://`, `ss://`,
  `hysteria2://`, `tuic://`) are out of scope by design and will be
  rejected — that is a different product, not a stricter filter.
- Prefer sources that update on their own schedule (repos that re-test or
  re-scrape regularly) — the pipeline runs every 30 minutes, so a list
  refreshed by its maintainers stays useful far longer.

## The PR: one object in `config/sources.json`

Add exactly one entry to the `sources` array (don't touch
`schema_version`, `description`, or `defaults`):

```json
{
  "id": "my-source",
  "url": "https://example.com/proxies.txt",
  "format": "ip:port",
  "claimed_type": "socks5",
  "claimed_country": false,
  "claimed_anonymity": null,
  "enabled": true,
  "notes": "added 2026-11-20; verified live 2026-11-20 (1,204 lines)"
}
```

Required fields:

| field | rules |
| --- | --- |
| `id` | lowercase `a-z`, digits, `-`, `_`; **unique** across the file |
| `url` | `http(s)` only |
| `format` | one of the six values below |
| `claimed_type` | what the source itself claims: `socks4` / `socks5` / `http` / `https` / `null` when it doesn't say |
| `claimed_country` | `true` only if the source actually asserts a country per entry |

Recommended: `claimed_anonymity` (`"transparent"` / `"anonymous"` /
`"elite"` / `null`), `enabled` (default `true`), and a `notes` line with
the add/verify dates and the live line count — that is the audit trail the
other sources carry.

The six supported `format` values (same table as the README, kept here so
the PR is self-contained):

| format | line shape | example |
| --- | --- | --- |
| `ip:port` | bare entries, `#` comments skipped | `1.2.3.4:8080` |
| `ip:port:user:pass` | credentials (password may contain `:`) | `1.2.3.4:8080:alice:s3cret` |
| `ip:port:country` | trailing country-name claim | `1.2.3.4:8080:United States` |
| `user:pass@ip:port` | credentials before the host | `alice:s3cret@1.2.3.4:8080` |
| `proto-prefixed` | `proto://[user:pass@]ip:port[,COUNTRY,CITY]` | `socks5://1.2.3.4:1080,US,Alexandria` |
| `json-structured` | JSON rows with ip/port/protocols/country/anonymity | geonode API |

If your source fits two formats partially, pick the one that describes the
majority of its lines; `claimed_type: null` is always more honest than a
guess — the validate stage determines the real protocol by handshake.

## What gets checked before merging

1. **Schema validation passes.** `yuel/config.py` validates the whole file
   strictly (unknown fields, bad `id`/`url`/`format`/claim values are
   rejected). Locally:

   ```bash
   python3 -m unittest tests.test_config
   ```

2. **The source is really openly published** — no payment, registration,
   or robots/ToS-forbidden fetching.
3. **The URL is verified live**: HTTP 200 and plausible proxy content, not
   an HTML error page or a login wall. The verification date goes in
   `notes`.
4. **The `format` matches reality**: sample a few lines and confirm they
   parse under the declared format.
5. **Claims describe the source, honestly.** Claims are recorded, never
   trusted — stage 3 calibrates them against its own live handshakes, and
   a source whose claims chronically disagree becomes a data-quality
   signal. Mislabeling to make a source look better defeats the point.

## Verify locally, then open the PR

```bash
# fetch + parse everything (your new source included)
python3 -m yuel.pipeline collect

# your source's entry in the audit trail:
#   data/collected/collect_report.json  → per-source status, parsed counts,
#                                         failure samples
python3 -m unittest discover -s tests -t .
```

A source that fails never breaks the run — its error is recorded under its
own entry in `collect_report.json` and the pipeline continues. In CI, the
scheduled run picks your source up automatically after merge; chronically
failing sources get `enabled: false` (kept, never deleted, so the history
stays auditable).

PR checklist:

- [ ] one new object in the `sources` array, nothing else changed
- [ ] `id` unique, `url` http(s), `format` one of the six
- [ ] `claimed_type` / `claimed_country` / `claimed_anonymity` describe the
      source truthfully
- [ ] verified live (200 + plausible content), date + line count in
      `notes`
- [ ] `python3 -m unittest discover -s tests -t .` passes locally
- [ ] `collect_report.json` shows your source parsed entries

## Other contributions

- **Parser fixes / new line shapes:** `yuel/collect.py` + a test in
  `tests/test_collect.py` (fake servers and fixture text only — tests are
  offline by design).
- **Scoring / tier tuning:** propose weight changes against real
  `data/out/` numbers in the issue, not vibes.
- **Bug reports:** include the run's `generated_utc` from
  `run-summary.json` so the failing run is identifiable.

Contributions are licensed MIT (same as the repo).
