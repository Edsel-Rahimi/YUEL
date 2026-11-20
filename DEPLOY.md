# Deploying the YUEL site (GitHub Pages)

The site is a **static single-page app** that lives in [`docs/`](.) — plain
HTML + CSS + vanilla JS, no framework, no build step. GitHub Pages serves it
directly from `main /docs`.

**Live URL: https://edsel-rahimi.github.io/YUEL/**

## What is where

| Path | Role |
| --- | --- |
| `docs/index.html` | the single page (header, filter bar, results table, selection bar) |
| `docs/style.css` | all styling |
| `docs/app.js` | data fetch, filters, sort, pagination, selection, copy/download |
| `docs/tokens.css` | **generated** from `assets/tokens.json` — do not hand-edit |
| `docs/fonts.css` + `docs/fonts/*.woff2` | self-hosted Space Grotesk / Inter / IBM Plex Mono (latin subsets) |
| `assets/tokens.json` | the brand kit — single source of truth for every color/spacing/type value |

Regenerate the token stylesheet after editing the brand kit:

```bash
python3 scripts/gen_site_tokens.py   # writes docs/tokens.css
```

## One-time Pages setup (already done)

Pages was enabled through the API — equivalent to clicking:
**Settings → Pages → Build and deployment → Source: “Deploy from a branch” →
Branch: `main`, Folder: `/docs` → Save**. Reproduce it manually if ever needed:

```bash
curl -X POST \
  -H "Authorization: Bearer <a token with pages:write>" \
  -H "Accept: application/vnd.github+json" \
  https://api.github.com/repos/Edsel-Rahimi/YUEL/pages \
  -d '{"source":{"branch":"main","path":"/docs"}}'
```

## How the site gets fresh data (no manual redeploy ever needed)

The site fetches two files client-side at page load:

- `data/out/all.json` — every alive proxy (ip, port, type, country, tier,
  score, latency, last_checked, consecutive counters)
- `data/out/run-summary.json` — totals + `generated_utc` for the header

It reads them from `raw.githubusercontent.com`, which serves
`access-control-allow-origin: *` (verified), so cross-origin client-side
fetches work without any proxy or build. When the site is served from
`main /docs` on github.io, the files are also same-origin-adjacent to the
repo itself; the raw URLs are used so the page keeps working from any
mirror/preview host too.

Freshness comes from the existing pipeline automation — **no extra deploy
step exists or is needed**:

1. `.github/workflows/pipeline.yml` runs collect → normalize → validate →
   score → geo → publish every 30 minutes and atomically replaces
   `data/out/` (staging directory + swap; a failed run never overwrites
   good output).
2. The workflow commits `data/out/` back to `main` — that commit IS the
   redeploy: the site fetches the raw URLs on every visit, so the next
   visitor gets the new run's data (raw content is served with a short
   CDN cache, ~5 min).

Because the site has no build stage, nothing else has to be rebuilt when
the data changes. Theme, filters and selection state live entirely in the
browser (localStorage + page state).

## Local development

Any static server from the repo root, then point the page at the local
data with the `?data=` override:

```bash
python3 -m http.server 8787 --directory .
# open http://localhost:8787/docs/index.html?data=../data/out/
```

Without a local run's data, run `python3 -m yuel.pipeline publish` first
(or omit `?data=` to fetch the published raw URLs like production does).
