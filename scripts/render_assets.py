#!/usr/bin/env python3
"""YUEL README asset generator (v5) — editorial-minimal brand card set.

A complete visual redesign. The v4 style (busy gradient dashboard: film
grain, particle fields, layered waves, orbit rings, glow stacks, chips
everywhere) is gone. The new system is quiet and typographic:

- flat brand surfaces (cream canvas / white panels in light, aubergine /
  plum surfaces in dark) inside hairline borders and 26px radii
- pure typography: uppercase IBM Plex Mono micro-labels with wide
  letter-spacing, huge Space Grotesk numerals — no icon set, no
  decorative machinery
- one brand gradient (ember → coral → magenta → violet, straight from
  the logo) used sparingly: hero numerals, one rule per card, the final
  pipeline node, the top country bar
- restrained motion: staggered fade-in rows, draw-in bars, a slow dash
  march on the flow connectors, one heartbeat numeral — all guarded by
  ``prefers-reduced-motion``

The logo lockup (``assets/brand/yuel-logo-*.png``, color variant on
light / white variant on dark) is the hero of the header card and marks
the footer.

Data: every number comes from the last real pipeline run
(``data/out/run-summary.json`` + ``data/out/all.json`` — the CI-published
output — and ``config/score.json``). Protocol mix and score percentiles
are derived from ``all.json`` itself so every card describes the same
run, and the generator asserts internal consistency.

Usage::

    python3 scripts/render_assets.py              # all cards, both themes
    python3 scripts/render_assets.py --only stats # subset

Output: ``assets/<light|dark>/<card>.svg``. Static PNG previews (cairosvg)
show layout only — animations live in the browser.
"""

from __future__ import annotations

import argparse
import base64
import collections
import json
import math
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets"

# ---------------------------------------------------------------------------
# YUEL brand kit — exact values from assets/tokens.json v1.0.0
# ---------------------------------------------------------------------------

AUBERGINE = "#1E0D2F"  # color.origin.aubergine — logo mark, dark bg-canvas
EMBER = "#FC671F"      # color.origin.ember    — brand gradient start
CORAL = "#ED4A3B"      # color.origin.coral    — brand gradient 38%
MAGENTA = "#CC3C77"    # color.origin.magenta  — brand gradient 66%
VIOLET = "#6574C9"     # color.origin.violet   — brand gradient end
CREAM = "#FAECC5"      # color.origin.cream    — official palette
INK = "#080806"        # color.origin.ink      — official palette
CRIMSON = "#BD2632"    # color.origin.crimson  — semantic light link
MAROON = "#7D2327"     # color.origin.maroon   — semantic light link-hover
RED_VIVID = "#F32138"  # color.origin.red_vivid — primary.500

DISPLAY_FONT = "Space Grotesk, Inter, system-ui, -apple-system, Segoe UI, sans-serif"
MONO_FONT = "IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace"

TIER_COLORS = {  # per tier, per theme — ember / violet / coral = brand ramp
    "gold": {"light": "#D03D00", "dark": EMBER},
    "silver": {"light": "#4854A6", "dark": VIOLET},
    "bronze": {"light": MAGENTA, "dark": CORAL},
}

PROTO_COLORS = {  # http / socks5 / socks4, per theme
    "dark": [EMBER, VIOLET, CORAL],
    "light": ["#D03D00", "#4854A6", MAGENTA],
}

# editorial v5 design tokens, derived from the kit's semantic layer
SURFACE = {"light": "#FCF7E8", "dark": AUBERGINE}   # card fill (bg-canvas)
PANEL = {"light": "#FFFFFF", "dark": "#4F3F62"}     # inner panel (bg-surface)
PANEL_O = {"light": 0.55, "dark": 0.30}
BORDER = {"light": "#E8E0C5", "dark": "#645676"}    # outer card stroke
HAIR = {"light": "#D1C9AC", "dark": "#645676"}      # hairlines / tracks
HAIR_O = {"light": 0.9, "dark": 0.65}
TEXT = {"light": INK, "dark": "#F7F6F9"}
MUTED = {"light": "#545242", "dark": "#CCC5D5"}
MUTED_O = {"light": 0.85, "dark": 0.62}
ACC = {"light": "#D03D00", "dark": EMBER}           # accent.600 on cream
ACC2 = {"light": "#4854A6", "dark": VIOLET}         # secondary.700/600

LOGO_W, LOGO_H = 201, 298  # native px of assets/brand/yuel-logo-*.png


# ---------------------------------------------------------------------------
# real data — every number from the last actual run
# ---------------------------------------------------------------------------


def load_real_data() -> dict:
    summary = json.loads((REPO / "data/out/run-summary.json").read_text(encoding="utf-8"))
    cfg = json.loads((REPO / "config/score.json").read_text(encoding="utf-8"))
    all_records = json.loads((REPO / "data/out/all.json").read_text(encoding="utf-8"))

    totals = summary["totals"]
    alive = totals["validated_alive"]
    tiers = summary["by_tier"]
    assert sum(tiers.values()) == alive, f"tier counts {tiers} do not sum to alive {alive}"
    assert totals["published_records"] == alive, "published records != alive"
    assert len(all_records) == alive, "all.json rows != alive"

    # protocol mix and score stats are derived from the published all.json so
    # they always describe the SAME run as the headline numbers (the local
    # validate/score reports can lag behind the CI-published output)
    by_type = collections.Counter(record["type"] for record in all_records)
    assert sum(by_type.values()) == alive, "protocol counts do not sum to alive"
    scores = sorted(record["score"] for record in all_records)
    n = len(scores)
    p50 = scores[n // 2] if n % 2 else (scores[n // 2 - 1] + scores[n // 2]) / 2

    countries = sorted(summary["by_country"].items(), key=lambda kv: (-kv[1], kv[0]))

    return {
        "generated_utc": summary["generated_utc"],
        "sources": totals["sources_used"],
        "collected": totals["candidates_collected"],
        "unique": totals["unique_normalized"],
        "tested": totals["tested"],
        "alive": alive,
        "countries": totals["countries"],
        "by_tier": tiers,
        "score_stats": {"p50": p50, "mean": sum(scores) / n},
        "by_type": dict(by_type),
        "thresholds": cfg["tiers"],
        "top_countries": countries,
    }


def fmt(n) -> str:
    return f"{n:,}"


def stamp(d: dict) -> str:
    return d["generated_utc"][:16].replace("T", " · ") + " UTC"


# ---------------------------------------------------------------------------
# drawing primitives — deliberately few
# ---------------------------------------------------------------------------


def logo_image(t: str, x: float, y: float, w: float) -> str:
    """Embed the brand logo lockup as a data URI.

    Color variant on light surfaces, white variant on dark (the kit's
    bg-inverse pairing) so the mark always reads clearly."""
    variant = "color" if t == "light" else "white"
    png = (ASSETS / "brand" / f"yuel-logo-{variant}.png").read_bytes()
    b64 = base64.b64encode(png).decode("ascii")
    h = w * LOGO_H / LOGO_W
    return (f'  <image x="{x}" y="{y}" width="{w}" height="{h:.1f}" '
            f'href="data:image/png;base64,{b64}"/>')


def card_css() -> str:
    """Shared motion vocabulary. Small on purpose.

    Hidden states live ONLY inside the keyframes with fill-mode ``both``:
    renderers without CSS animation support (static image pipelines, some
    feed readers) then show everything at natural visibility instead of
    blank cards."""
    return (
        ".m-fade{animation:vf .7s ease-out both}"
        ".m-grow{transform-box:fill-box;transform-origin:left center;"
        "animation:vg .9s cubic-bezier(.2,.7,.2,1) both}"
        ".m-dash{animation:vm 26s linear infinite}"
        ".m-beat{animation:vb 2.6s ease-in-out infinite;transform-box:fill-box;"
        "transform-origin:center}"
        "@keyframes vf{from{opacity:0}to{opacity:1}}"
        "@keyframes vg{from{transform:scaleX(0)}to{transform:scaleX(1)}}"
        "@keyframes vm{to{stroke-dashoffset:-320}}"
        "@keyframes vb{0%,86%,100%{transform:scale(1)}90%{transform:scale(1.05)}"
        "95%{transform:scale(1.01)}}"
        "@media (prefers-reduced-motion:reduce){.m-fade,.m-grow,.m-dash,.m-beat"
        "{animation:none}}"
    )


def card_open(t: str, W: int, H: int, defs: str = "", rx: int = 26) -> str:
    """Card canvas: flat brand surface, hairline border, rounded corners."""
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" font-family="{DISPLAY_FONT}">\n'
        f"  <style>{card_css()}</style>\n"
        f"{defs}"
        f'  <rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="{rx}" '
        f'fill="{SURFACE[t]}" stroke="{BORDER[t]}" stroke-width="1.5"/>\n'
    )


def brand_grad(t: str, gid: str, x2: int = 1, y2: int = 0) -> str:
    """The logo gradient: ember → coral → magenta → violet."""
    stops = [(EMBER, 0), (CORAL, 0.38), (MAGENTA, 0.66), (VIOLET, 1)]
    s = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for c, o in stops)
    return (f'  <linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f"{s}</linearGradient>\n")


def text_el(x, y, s, size, fill, weight=400, family=DISPLAY_FONT, spacing=None,
            anchor=None, opacity=None, cls=None) -> str:
    a = f' text-anchor="{anchor}"' if anchor else ""
    sp = f' letter-spacing="{spacing}"' if spacing else ""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    cl = f' class="{cls}"' if cls else ""
    fam = f' font-family="{family}"'
    esc = s.replace("&", "&amp;").replace("<", "&lt;")
    return (f'  <text{cl} x="{x}" y="{y}" font-size="{size}" font-weight="{weight}"'
            f"{fam}{sp}{a} fill=\"{fill}\"{op}>{esc}</text>")


def micro(x, y, s, t: str, anchor=None, color=None, opacity=None) -> str:
    """Uppercase mono micro-label with wide tracking — the system's voice."""
    c = color or MUTED[t]
    return text_el(x, y, s.upper(), 10.5, c, weight=500, family=MONO_FONT,
                   spacing=2.4, anchor=anchor, opacity=opacity)


def mono(x, y, s, t: str, size=11.5, anchor=None, color=None, opacity=None,
         spacing=None) -> str:
    c = color or MUTED[t]
    return text_el(x, y, s, size, c, weight=500, family=MONO_FONT,
                   anchor=anchor, opacity=opacity, spacing=spacing)


def hairline(x1, y1, x2, y2, t: str, width=1.2, opacity=None, dashed=False,
             animate=False) -> str:
    op = opacity if opacity is not None else HAIR_O[t]
    dash = ' stroke-dasharray="2 8"' if dashed else ""
    cls = ' class="m-dash"' if animate else ""
    return (f'  <line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{HAIR[t]}" '
            f'stroke-opacity="{op}" stroke-width="{width}"'
            f' stroke-linecap="round"{dash}{cls}/>')


def panel(x, y, w, h, t: str, rx=18) -> str:
    return (f'  <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{PANEL[t]}" fill-opacity="{PANEL_O[t]}" stroke="{HAIR[t]}" '
            f'stroke-opacity="{HAIR_O[t]}" stroke-width="1.2"/>')


def delay(i: float) -> str:
    return f' style="animation-delay:{i:.2f}s"'


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------


def card_header(t: str, d: dict) -> str:
    W, H = 1200, 480
    wash_c = VIOLET if t == "dark" else EMBER
    wash_o = 0.14 if t == "dark" else 0.06
    defs = (
        brand_grad(t, f"brand-{t}")
        + f'  <radialGradient id="wash-{t}" gradientUnits="userSpaceOnUse" '
        f'cx="600" cy="150" r="430">'
        f'<stop offset="0" stop-color="{wash_c}" stop-opacity="{wash_o}"/>'
        f'<stop offset="1" stop-color="{wash_c}" stop-opacity="0"/>'
        f'</radialGradient>\n'
        f'  <circle cx="600" cy="150" r="430" fill="url(#wash-{t})"/>\n'
    )
    p = [card_open(t, W, H, defs)]

    # the logo IS the hero — lockup centered, generous air around it
    lw = 118
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(logo_image(t, 600 - lw / 2, 40, lw))
    p.append("  </g>")

    p.append(f'  <g class="m-fade"{delay(0.15)}>')
    p.append(micro(600, 264, "plain-proxy intelligence · refreshed hourly", t,
                   anchor="middle", color=ACC[t]))
    p.append("  </g>")

    # one honest stat line, hero numeral in the logo gradient
    # (tspan gaps use explicit dx — XML whitespace collapsing would eat them)
    p.append(f'  <g class="m-fade"{delay(0.3)}>')
    p.append(
        f'  <text x="600" y="326" text-anchor="middle" font-family="{DISPLAY_FONT}">'
        f'<tspan font-size="42" font-weight="800" fill="url(#brand-{t})">'
        f'{fmt(d["alive"])}</tspan>'
        f'<tspan dx="10" font-size="28" font-weight="700" fill="{TEXT[t]}">'
        f'alive</tspan>'
        f'<tspan dx="18" font-size="19" font-weight="500" fill="{MUTED[t]}" '
        f'opacity="{MUTED_O[t]}">· {d["countries"]} countries · '
        f'{d["sources"]} sources</tspan></text>'
    )
    p.append("  </g>")

    p.append(f'  <g class="m-fade"{delay(0.45)}>')
    p.append(f'  <rect x="480" y="354" width="240" height="3" rx="1.5" '
             f'fill="url(#brand-{t})"/>')
    p.append(micro(600, 396, "socks4 · socks5 · http — one cli · json output · "
                             "no tunnels by design", t, anchor="middle"))
    p.append(mono(600, 446, f"score p50 {d['score_stats']['p50']} — every hop "
                            f"handshake-verified each run", t, anchor="middle"))
    p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_stats(t: str, d: dict) -> str:
    W, H = 1200, 190
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"))]
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(micro(48, 46, f"last run — {stamp(d)}", t))
    p.append(micro(1152, 46, "plain socks4 / socks5 / http", t, anchor="end",
                   color=ACC[t]))
    p.append("  </g>")

    cols = [
        ("validated alive", fmt(d["alive"]), True),
        ("collected", fmt(d["collected"]), False),
        ("unique", fmt(d["unique"]), False),
        ("handshake-tested", fmt(d["tested"]), False),
        ("countries", str(d["countries"]), False),
    ]
    x0, cw = 48, 1104 / 5
    for i, (label, value, hero) in enumerate(cols):
        cx = x0 + (i + 0.5) * cw
        p.append(f'  <g class="m-fade"{delay(0.1 + i * 0.12)}>')
        fill = f"url(#brand-{t})" if hero else TEXT[t]
        p.append(micro(cx, 94, label, t, anchor="middle"))
        p.append(text_el(cx, 144, value, 40, fill, weight=800, anchor="middle",
                         cls="m-beat" if hero else None))
        uw = 30 if hero else 20
        uf = f"url(#brand-{t})" if hero else HAIR[t]
        uo = 1.0 if hero else HAIR_O[t]
        p.append(f'  <rect x="{cx - uw / 2}" y="158" width="{uw}" height="3" '
                 f'rx="1.5" fill="{uf}" opacity="{uo}"/>')
        p.append("  </g>")
        if i:
            p.append(hairline(x0 + i * cw, 72, x0 + i * cw, 158, t))
    p.append("</svg>")
    return "\n".join(p)


def card_flow(t: str, d: dict) -> str:
    W, H = 1200, 280
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"))]
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(micro(48, 50, "from public sources to a curated feed", t))
    p.append(micro(1152, 50, "every hop verified each run — dead lists never "
                             "publish", t, anchor="end"))
    p.append("  </g>")

    nodes = [
        (str(d["sources"]), "sources"),
        (fmt(d["unique"]), "unique"),
        (fmt(d["tested"]), "handshake-tested"),
        (f"p50 {d['score_stats']['p50']}", "score"),
        (str(d["countries"]), "geo"),
        (fmt(d["alive"]), "published"),
    ]
    x0, cw, cy = 48, 1104 / 6, 150
    centers = [x0 + (i + 0.5) * cw for i in range(6)]
    for i, ((value, label), cx) in enumerate(zip(nodes, centers)):
        last = i == len(nodes) - 1
        if i:
            p.append(hairline(centers[i - 1] + 56, cy, cx - 56, cy, t,
                              width=1.6, dashed=True, animate=True))
        p.append(f'  <g class="m-fade"{delay(0.1 + i * 0.12)}>')
        ring = ACC2[t] if i and not last else ACC[t]
        ring_op = 0.9 if (i == 0 or last) else 0.45
        stroke_w = 2 if last else 1.4
        ring_fill = f"url(#brand-{t})" if last else ring
        p.append(f'  <circle cx="{cx}" cy="{cy}" r="46" fill="{PANEL[t]}" '
                 f'fill-opacity="{PANEL_O[t] + (0.15 if last else 0)}" '
                 f'stroke="{ring_fill}" stroke-opacity="{ring_op}" '
                 f'stroke-width="{stroke_w}"/>')
        vsize = 15 if len(value) > 5 else 17
        vfill = f"url(#brand-{t})" if last else TEXT[t]
        p.append(text_el(cx, cy + 6, value, vsize, vfill, weight=700,
                         anchor="middle"))
        p.append(micro(cx, cy + 76, label, t, anchor="middle"))
        p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_tiers(t: str, d: dict) -> str:
    W, H = 1200, 300
    p = [card_open(t, W, H)]
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(micro(48, 50, "quality tiers — scored, handshake-checked", t))
    p.append(micro(1152, 50, "gold ≥ 80 · silver ≥ 50 · bronze ≥ 20", t,
                   anchor="end"))
    p.append("  </g>")

    pw, gap, py, ph = 344, 36, 76, 188
    ordered = [("gold", d["by_tier"]["gold"], 80),
               ("silver", d["by_tier"]["silver"], 50),
               ("bronze", d["by_tier"]["bronze"], 20)]
    for i, (tier, count, thr) in enumerate(ordered):
        x = 48 + i * (pw + gap)
        color = TIER_COLORS[tier][t]
        pct = count / d["alive"] * 100
        p.append(f'  <g class="m-fade"{delay(0.1 + i * 0.14)}>')
        p.append(panel(x, py, pw, ph, t))
        p.append(f'  <circle cx="{x + 28}" cy="{py + 34}" r="5" fill="{color}"/>')
        p.append(micro(x + 44, py + 38, tier, t, color=TEXT[t]))
        p.append(text_el(x + 28, py + 102, fmt(count), 56, color, weight=800))
        p.append(micro(x + 28, py + 134, f"score ≥ {thr} · {pct:.1f}% of alive",
                       t))
        bw = pw - 56
        p.append(f'  <rect x="{x + 28}" y="{py + 152}" width="{bw}" height="6" '
                 f'rx="3" fill="{HAIR[t]}" fill-opacity="{HAIR_O[t]}"/>')
        p.append(f'  <rect class="m-grow"{delay(0.3 + i * 0.14)} x="{x + 28}" '
                 f'y="{py + 152}" width="{bw * pct / 100:.1f}" height="6" '
                 f'rx="3" fill="{color}"/>')
        p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_funnel(t: str, d: dict) -> str:
    W, H = 1200, 330
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"))]
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(micro(48, 50, "collection funnel — one hourly run", t))
    p.append(micro(1152, 50, "what survives is what gets published", t,
                   anchor="end"))
    p.append("  </g>")

    rows = [
        ("collected", d["collected"]),
        ("unique", d["unique"]),
        ("handshake-tested", d["tested"]),
        ("alive", d["alive"]),
    ]
    lx, tx, tw = 48, 250, 700
    for i, (label, value) in enumerate(rows):
        y = 86 + i * 56
        last = i == len(rows) - 1
        frac = value / d["collected"]
        cls_attr = f'class="m-grow"{delay(0.3 + i * 0.14)}' if last else ""
        p.append(f'  <g class="m-fade"{delay(0.08 + i * 0.14)}>')
        p.append(micro(lx, y + 15, label, t))
        p.append(f'  <rect x="{tx}" y="{y}" width="{tw}" height="22" rx="11" '
                 f'fill="{HAIR[t]}" fill-opacity="{HAIR_O[t] * 0.45}"/>')
        fill = f"url(#brand-{t})" if last else ACC2[t]
        fop = 1.0 if last else 0.85 - i * 0.08
        p.append(f'  <rect {cls_attr} x="{tx}" y="{y}" '
                 f'width="{tw * frac:.1f}" height="22" rx="11" '
                 f'fill="{fill}" fill-opacity="{fop:.2f}"/>')
        vfill = f"url(#brand-{t})" if last else TEXT[t]
        p.append(text_el(tx + tw + 28, y + 17, fmt(value), 20, vfill,
                         weight=800, cls="m-beat" if last else None))
        p.append(micro(tx + tw + 28, y + 36, f"{frac * 100:.1f}% of collected",
                       t))
        p.append("  </g>")
    p.append(f'  <g class="m-fade"{delay(0.7)}>')
    p.append(micro(48, 314, f"{fmt(d['alive'])} of {fmt(d['tested'])} tested "
                            f"survive — {d['alive'] / d['tested'] * 100:.1f}% "
                            f"end-to-end", t, color=ACC[t]))
    p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_countries(t: str, d: dict) -> str:
    W, H = 1200, 460
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"))]
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(micro(48, 50, "where the alive exits live", t))
    p.append(micro(1152, 50, f"{d['countries']} countries · ip-geolocation via "
                             f"the ipapi table", t, anchor="end"))
    p.append("  </g>")

    top = d["top_countries"][:12]
    vmax = top[0][1]
    bx, bw = 130, 890
    for i, (cc, n) in enumerate(top):
        y = 84 + i * 28
        cls_attr = f'class="m-grow"{delay(0.15 + i * 0.05)}'
        p.append(f'  <g class="m-fade"{delay(0.05 + i * 0.05)}>')
        p.append(mono(48, y + 10, cc, t, size=11.5, color=TEXT[t], spacing=1.5))
        fill = f"url(#brand-{t})" if i == 0 else ACC2[t]
        op = 1.0 if i == 0 else max(0.85 - i * 0.055, 0.3)
        p.append(f'  <rect {cls_attr} x="{bx}" y="{y}" '
                 f'width="{bw * n / vmax:.1f}" height="10" rx="5" '
                 f'fill="{fill}" fill-opacity="{op:.2f}"/>')
        p.append(mono(1152, y + 10, str(n), t, size=11.5, anchor="end",
                      color=TEXT[t]))
        p.append("  </g>")
    p.append(f'  <g class="m-fade"{delay(0.75)}>')
    p.append(micro(48, 444, f"+ {d['countries'] - len(top)} more countries in "
                            f"data/out/by-country/<cc>.json", t))
    p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_protocols(t: str, d: dict) -> str:
    W, H = 1200, 330
    cx, cy, r = 330, 188, 95
    circ = 2 * math.pi * r
    protos = [("http", d["by_type"]["http"]),
              ("socks5", d["by_type"]["socks5"]),
              ("socks4", d["by_type"]["socks4"])]
    total = sum(v for _, v in protos)
    colors = PROTO_COLORS[t]
    p = [card_open(t, W, H)]

    # donut: three butt-joined arc strokes on one circle, 4px gaps
    cum = 0.0
    arcs = []
    for i, (name, v) in enumerate(protos):
        frac = v / total
        seg = max(frac * circ - 4, 1)
        arcs.append(
            f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
            f'stroke="{colors[i]}" stroke-width="26" '
            f'stroke-dasharray="{seg:.1f} {circ - seg:.1f}" '
            f'stroke-dashoffset="{-cum * circ:.1f}" '
            f'transform="rotate(-90 {cx} {cy})"/>'
        )
        cum += frac
    p.append(f'  <g class="m-fade"{delay(0.1)}>')
    p.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
             f'stroke="{HAIR[t]}" stroke-opacity="{HAIR_O[t] * 0.4}" '
             f'stroke-width="26"/>')
    p.extend(arcs)
    p.append(text_el(cx, cy - 2, fmt(total), 44, TEXT[t], weight=800,
                     anchor="middle"))
    p.append(micro(cx, cy + 26, "alive", t, anchor="middle"))
    p.append("  </g>")

    p.append(micro(560, 96, "protocol mix — measured by real handshake", t))
    p.append(micro(1152, 96, "confirmed type never guessed — first working "
                             "protocol wins", t, anchor="end"))
    for i, (name, v) in enumerate(protos):
        y = 148 + i * 56
        p.append(f'  <g class="m-fade"{delay(0.25 + i * 0.14)}>')
        p.append(f'  <rect x="560" y="{y - 14}" width="12" height="12" rx="4" '
                 f'fill="{colors[i]}"/>')
        p.append(text_el(588, y, name.upper(), 19, TEXT[t], weight=700,
                         spacing=1.2))
        p.append(mono(588, y + 24, f"{fmt(v)} · {v / total * 100:.1f}%", t,
                      size=11.5))
        p.append(hairline(560, y + 40, 1152, y + 40, t, opacity=HAIR_O[t] * 0.5))
        p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_architecture(t: str, d: dict) -> str:
    W, H = 1200, 400
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"))]
    p.append(f'  <g class="m-fade"{delay(0.0)}>')
    p.append(micro(48, 50, "pipeline — seven stages, one entrypoint", t))
    p.append(mono(1152, 50, "python3 -m yuel.pipeline run", t, size=11.5,
                  anchor="end", color=ACC[t], spacing=1.2))
    p.append("  </g>")

    stages = [
        ("collect", f'{d["sources"]} sources', "public lists, refreshed hourly"),
        ("normalize", f'{fmt(d["unique"])} unique', "exact + fuzzy dedup"),
        ("validate", f'{fmt(d["tested"])} tested', "real socks/http handshakes"),
        ("score", f'p50 {d["score_stats"]["p50"]}',
         "latency · success · freshness"),
        ("geo", f'{d["countries"]} countries', "ip-api country lookup"),
        ("publish", f'{fmt(d["alive"])} alive', "data/out/*.json contract"),
    ]
    pw, ph, gapx, gapy = 344, 140, 36, 20
    for i, (stage, value, desc) in enumerate(stages):
        col, row = i % 3, i // 3
        x = 48 + col * (pw + gapx)
        y = 76 + row * (ph + gapy)
        last = i == len(stages) - 1
        p.append(f'  <g class="m-fade"{delay(0.1 + i * 0.1)}>')
        p.append(panel(x, y, pw, ph, t))
        dot = f"url(#brand-{t})" if last else ACC2[t]
        dop = 1.0 if last else 0.8
        p.append(f'  <rect x="{x + 26}" y="{y + 24}" width="10" height="10" '
                 f'rx="3" fill="{dot}" fill-opacity="{dop}"/>')
        p.append(micro(x + 48, y + 34, stage, t))
        vfill = f"url(#brand-{t})" if last else TEXT[t]
        p.append(text_el(x + 26, y + 84, value, 24, vfill, weight=800))
        p.append(mono(x + 26, y + 114, desc, t, size=10.5))
        p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


def card_divider(t: str, d: dict) -> str:
    W, H = 1200, 56
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"))]
    p.append(f'  <rect x="440" y="26.5" width="320" height="3" rx="1.5" '
             f'fill="url(#brand-{t})"/>')
    p.append(f'  <rect x="596" y="22.5" width="11" height="11" rx="2" '
             f'fill="url(#brand-{t})" transform="rotate(45 601.5 28)"/>')
    p.append("</svg>")
    return "\n".join(p)


def card_footer(t: str, d: dict) -> str:
    W, H = 1200, 84
    p = [card_open(t, W, H)]
    lw = 30
    p.append(logo_image(t, 48, (H - lw * LOGO_H / LOGO_W) / 2, lw))
    p.append(f'  <g class="m-fade"{delay(0.1)}>')
    p.append(mono(600, 40, f"YUEL · last run {stamp(d)} · regenerated by "
                           f"scripts/render_assets.py", t, size=11.5,
                  anchor="middle", color=TEXT[t]))
    p.append(micro(600, 64, "artifacts: data/out/all.json · by-country/<cc>"
                            ".json · by-tier/<tier>.json · run-summary.json",
                   t, anchor="middle"))
    p.append("  </g>")
    p.append("</svg>")
    return "\n".join(p)


# ---------------------------------------------------------------------------
# top-20 country cards (README fast-path grid) — data from the last run
# ---------------------------------------------------------------------------

RAW_BASE = "https://raw.githubusercontent.com/Edsel-Rahimi/YUEL/main/data/out"
GRID_START = "<!-- country-grid:start -->"
GRID_END = "<!-- country-grid:end -->"
README_PATH = REPO / "README.md"

# ISO 3166-1 alpha-2 → short display name (static reference data; codes that
# appear in the data but not here fall back to the code itself)
ISO_NAMES = {
    "AD": "Andorra", "AE": "United Arab Emirates", "AF": "Afghanistan",
    "AG": "Antigua and Barbuda", "AI": "Anguilla", "AL": "Albania",
    "AM": "Armenia", "AO": "Angola", "AQ": "Antarctica", "AR": "Argentina",
    "AS": "American Samoa", "AT": "Austria", "AU": "Australia",
    "AW": "Aruba", "AX": "Åland Islands", "AZ": "Azerbaijan",
    "BA": "Bosnia and Herzegovina", "BB": "Barbados", "BD": "Bangladesh",
    "BE": "Belgium", "BF": "Burkina Faso", "BG": "Bulgaria", "BH": "Bahrain",
    "BI": "Burundi", "BJ": "Benin", "BL": "Saint Barthélemy",
    "BM": "Bermuda", "BN": "Brunei", "BO": "Bolivia",
    "BQ": "Caribbean Netherlands", "BR": "Brazil", "BS": "Bahamas",
    "BT": "Bhutan", "BW": "Botswana", "BY": "Belarus", "BZ": "Belize",
    "CA": "Canada", "CD": "DR Congo", "CF": "Central African Republic",
    "CG": "Congo", "CH": "Switzerland", "CI": "Côte d'Ivoire",
    "CK": "Cook Islands", "CL": "Chile", "CM": "Cameroon", "CN": "China",
    "CO": "Colombia", "CR": "Costa Rica", "CU": "Cuba", "CV": "Cape Verde",
    "CW": "Curaçao", "CX": "Christmas Island", "CY": "Cyprus",
    "CZ": "Czechia", "DE": "Germany", "DJ": "Djibouti", "DK": "Denmark",
    "DM": "Dominica", "DO": "Dominican Republic", "DZ": "Algeria",
    "EC": "Ecuador", "EE": "Estonia", "EG": "Egypt",
    "EH": "Western Sahara", "ER": "Eritrea", "ES": "Spain",
    "ET": "Ethiopia", "FI": "Finland", "FJ": "Fiji",
    "FK": "Falkland Islands", "FM": "Micronesia", "FO": "Faroe Islands",
    "FR": "France", "GA": "Gabon", "GB": "United Kingdom", "GD": "Grenada",
    "GE": "Georgia", "GF": "French Guiana", "GG": "Guernsey", "GH": "Ghana",
    "GI": "Gibraltar", "GL": "Greenland", "GM": "Gambia", "GN": "Guinea",
    "GP": "Guadeloupe", "GQ": "Equatorial Guinea", "GR": "Greece",
    "GT": "Guatemala", "GU": "Guam", "GW": "Guinea-Bissau", "GY": "Guyana",
    "HK": "Hong Kong", "HN": "Honduras", "HR": "Croatia", "HT": "Haiti",
    "HU": "Hungary", "ID": "Indonesia", "IE": "Ireland", "IL": "Israel",
    "IM": "Isle of Man", "IN": "India", "IO": "British Indian Ocean "
                                              "Territory",
    "IQ": "Iraq", "IR": "Iran", "IS": "Iceland", "IT": "Italy",
    "JE": "Jersey", "JM": "Jamaica", "JO": "Jordan", "JP": "Japan",
    "KE": "Kenya", "KG": "Kyrgyzstan", "KH": "Cambodia", "KI": "Kiribati",
    "KM": "Comoros", "KN": "Saint Kitts and Nevis", "KP": "North Korea",
    "KR": "South Korea", "KW": "Kuwait", "KY": "Cayman Islands",
    "KZ": "Kazakhstan", "LA": "Laos", "LB": "Lebanon", "LC": "Saint Lucia",
    "LI": "Liechtenstein", "LK": "Sri Lanka", "LR": "Liberia",
    "LS": "Lesotho", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
    "LY": "Libya", "MA": "Morocco", "MC": "Monaco", "MD": "Moldova",
    "ME": "Montenegro", "MF": "Saint Martin", "MG": "Madagascar",
    "MH": "Marshall Islands", "MK": "North Macedonia", "ML": "Mali",
    "MM": "Myanmar", "MN": "Mongolia", "MO": "Macao",
    "MP": "Northern Mariana Islands", "MQ": "Martinique",
    "MR": "Mauritania", "MS": "Montserrat", "MT": "Malta",
    "MU": "Mauritius", "MV": "Maldives", "MW": "Malawi", "MX": "Mexico",
    "MY": "Malaysia", "MZ": "Mozambique", "NA": "Namibia",
    "NC": "New Caledonia", "NE": "Niger", "NF": "Norfolk Island",
    "NG": "Nigeria", "NI": "Nicaragua", "NL": "Netherlands", "NO": "Norway",
    "NP": "Nepal", "NR": "Nauru", "NU": "Niue", "NZ": "New Zealand",
    "OM": "Oman", "PA": "Panama", "PE": "Peru",
    "PF": "French Polynesia", "PG": "Papua New Guinea", "PH": "Philippines",
    "PK": "Pakistan", "PL": "Poland", "PM": "Saint Pierre and Miquelon",
    "PR": "Puerto Rico", "PS": "Palestine", "PT": "Portugal", "PW": "Palau",
    "PY": "Paraguay", "QA": "Qatar", "RE": "Réunion", "RO": "Romania",
    "RS": "Serbia", "RU": "Russia", "RW": "Rwanda", "SA": "Saudi Arabia",
    "SB": "Solomon Islands", "SC": "Seychelles", "SD": "Sudan",
    "SE": "Sweden", "SG": "Singapore", "SI": "Slovenia", "SK": "Slovakia",
    "SL": "Sierra Leone", "SM": "San Marino", "SN": "Senegal",
    "SO": "Somalia", "SR": "Suriname", "SS": "South Sudan",
    "ST": "São Tomé and Príncipe", "SV": "El Salvador",
    "SX": "Sint Maarten", "SY": "Syria", "SZ": "Eswatini",
    "TC": "Turks and Caicos Islands", "TD": "Chad", "TG": "Togo",
    "TH": "Thailand", "TJ": "Tajikistan", "TK": "Tokelau",
    "TL": "Timor-Leste", "TM": "Turkmenistan", "TN": "Tunisia",
    "TO": "Tonga", "TR": "Turkey", "TT": "Trinidad and Tobago",
    "TV": "Tuvalu", "TW": "Taiwan", "TZ": "Tanzania", "UA": "Ukraine",
    "UG": "Uganda", "US": "United States", "UY": "Uruguay",
    "UZ": "Uzbekistan", "VA": "Vatican City",
    "VC": "Saint Vincent and the Grenadines", "VE": "Venezuela",
    "VG": "British Virgin Islands", "VI": "U.S. Virgin Islands",
    "VN": "Vietnam", "VU": "Vanuatu", "WF": "Wallis and Futuna",
    "WS": "Samoa", "XK": "Kosovo", "YE": "Yemen", "YT": "Mayotte",
    "ZA": "South Africa", "ZM": "Zambia", "ZW": "Zimbabwe",
}


def load_country_entries() -> list[dict]:
    """Top 20 countries by alive count from run-summary.json, with per-type
    counts taken from each country's published JSON (never hardcoded)."""
    summary = json.loads(
        (REPO / "data/out/run-summary.json").read_text(encoding="utf-8"))
    top = sorted(((c, n) for c, n in summary["by_country"].items()
                  if c != "unclassified"),
                 key=lambda kv: (-kv[1], kv[0]))[:20]
    entries = []
    for cc, count in top:
        records = json.loads(
            (REPO / f"data/out/by-country/{cc}.json").read_text(encoding="utf-8"))
        entries.append({
            "cc": cc,
            "name": ISO_NAMES.get(cc, cc),
            "count": count,
            "types": dict(collections.Counter(r["type"] for r in records)),
        })
    return entries


def fetch_flag(cc: str) -> str | None:
    """flagcdn.com static flag as a data URI (external refs are blocked in
    SVGs rendered via <img>, so the verified PNG gets embedded)."""
    url = f"https://flagcdn.com/24x18/{cc.lower()}.png"
    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            data = resp.read()
        return base64.b64encode(data).decode("ascii") if data else None
    except OSError:
        return None  # card still renders, minus the flag


def card_country(t: str, cc: str, name: str, count: int, flag_b64: str | None,
                 rank: int) -> str:
    """One grid card in the v5 system: flag, name, alive count."""
    W, H = 320, 140
    p = [card_open(t, W, H, brand_grad(t, f"brand-{t}"), rx=20)]
    hero = rank == 0
    if flag_b64:
        p.append(f'  <image x="24" y="24" width="48" height="36" '
                 f'href="data:image/png;base64,{flag_b64}"/>')
    else:
        p.append(f'  <rect x="24" y="24" width="48" height="36" rx="4" '
                 f'fill="{HAIR[t]}" fill-opacity="{HAIR_O[t]}"/>')
    display = name if len(name) <= 16 else name[:15] + "…"
    p.append(text_el(86, 46, display, 17, TEXT[t], weight=700))
    p.append(micro(86, 66, cc, t))
    fill = f"url(#brand-{t})" if hero else TEXT[t]
    p.append(text_el(24, 112, fmt(count), 40, fill, weight=800))
    count_w = len(fmt(count)) * 40 * 0.62
    p.append(micro(24 + count_w + 14, 112, "alive", t))
    p.append(f'  <rect x="24" y="122" width="28" height="3" rx="1.5" '
             f'fill="url(#brand-{t})" opacity="{1.0 if hero else 0.35}"/>')
    p.append("</svg>")
    return "\n".join(p)


def write_country_cards(entries: list[dict]) -> None:
    """Write country-<CC>.svg for both themes; remove stale country cards
    from countries that dropped out of the top 20."""
    flags = {e["cc"]: fetch_flag(e["cc"]) for e in entries}
    missing = [cc for cc, f in flags.items() if f is None]
    if missing:
        print(f"flagcdn fetch failed for {missing} — cards render without flag")
    for theme in ("light", "dark"):
        for i, e in enumerate(entries):
            out = ASSETS / theme / f"country-{e['cc']}.svg"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(
                card_country(theme, e["cc"], e["name"], e["count"],
                             flags[e["cc"]], i),
                encoding="utf-8")
        keep = {f"country-{e['cc']}.svg" for e in entries}
        for stale in ASSETS.glob(f"{theme}/country-*.svg"):
            if stale.name not in keep:
                stale.unlink()


def build_grid_block(entries: list[dict]) -> str:
    """HTML table (raw markup — no GitHub-interactive tricks): card image
    links to the combined per-country .txt; a closed <details> holds three
    per-type chips, zero-count types rendered as plain unlinked <code>."""
    def cell(e: dict) -> str:
        chips = []
        for ptype in ("socks5", "socks4", "http"):
            n = e["types"].get(ptype, 0)
            if n:
                chips.append(f'<a href="{RAW_BASE}/by-country/{e["cc"]}/'
                             f'{ptype}.txt"><code>{ptype} · {n}</code></a>')
            else:
                chips.append(f'<code>{ptype} · 0</code>')
        alt = f"{e['name']} — {e['count']} alive proxies, plain-text list"
        return (
            f'<a href="{RAW_BASE}/by-country/{e["cc"]}.txt">'
            f'<picture><source media="(prefers-color-scheme: dark)" '
            f'srcset="assets/dark/country-{e["cc"]}.svg">'
            f'<img src="assets/light/country-{e["cc"]}.svg" alt="{alt}">'
            f'</picture></a>'
            f'<br><details><summary>socks5 · socks4 · http</summary>'
            f'{" · ".join(chips)}</details>'
        )

    rows = [entries[i:i + 4] for i in range(0, len(entries), 4)]
    body = "".join(
        "<tr>" + "".join(f"<td>{cell(e)}</td>" for e in row) + "</tr>\n"
        for row in rows)
    return f'<table>\n{body}</table>'


def update_readme_grid(entries: list[dict]) -> None:
    readme = README_PATH.read_text(encoding="utf-8")
    if GRID_START not in readme or GRID_END not in readme:
        print("country-grid markers missing from README — grid not updated")
        return
    start = readme.index(GRID_START) + len(GRID_START)
    end = readme.index(GRID_END)
    updated = (readme[:start] + "\n\n" + build_grid_block(entries) + "\n\n"
               + readme[end:])
    README_PATH.write_text(updated, encoding="utf-8")
    print(f"updated README country grid ({len(entries)} countries)")


# ---------------------------------------------------------------------------
# registry + main
# ---------------------------------------------------------------------------

CARDS = {
    "header": card_header,
    "stats": card_stats,
    "flow": card_flow,
    "tiers": card_tiers,
    "funnel": card_funnel,
    "countries": card_countries,
    "protocols": card_protocols,
    "architecture": card_architecture,
    "divider": card_divider,
    "footer": card_footer,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", default=None,
                        help="comma-separated card names (default: all)")
    args = parser.parse_args()
    data = load_real_data()
    names = [n.strip() for n in args.only.split(",")] if args.only else list(CARDS)
    unknown = [n for n in names if n not in CARDS]
    if unknown:
        parser.error(f"unknown card(s): {', '.join(unknown)}")
    for theme in ("light", "dark"):
        for name in names:
            out = ASSETS / theme / f"{name}.svg"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(CARDS[name](theme, data), encoding="utf-8")
            print(f"wrote {out}")
    # top-20 country fast-path cards + README grid (always derived from the
    # just-published run output; skipped with --only unless "countries" ran)
    if args.only is None or "countries" in names:
        entries = load_country_entries()
        write_country_cards(entries)
        update_readme_grid(entries)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
