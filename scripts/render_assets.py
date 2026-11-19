#!/usr/bin/env python3
"""YUEL README asset generator (v4) — fully animated SVG card set.

Design language is modeled on modern animated GitHub README banners
(reference studied for TECHNIQUE only, re-implemented from scratch for
YUEL): deep gradient card, centered hero composition, spinning dashed
orbits, ping rings, traveling packets on marching-dashed connectors,
rising particle fields, layered waves, one quiet highlight sweep per
cycle, bars that draw in, heartbeat numbers. All CSS keyframes live in
an embedded <style> block and are guarded by ``prefers-reduced-motion``.

Palette: exactly the seven YUEL brand values —
  cream #FAECC5 · ink #080806 · deep green #085834 · forest #08442C
  crimson #BD2632 · maroon #7D2327 · vivid red #F32138
(the feTurbulence grain overlay is desaturated gray noise, i.e. texture).

Data: every number comes from the last real pipeline run
(``data/out/run-summary.json``, ``data/scored/score_report.json``,
``data/validated/validate_report.json``, ``data/out/all.json``,
``config/score.json``) and the generator asserts internal consistency.

Usage::

    python3 scripts/render_assets.py                # all cards, both themes
    python3 scripts/render_assets.py --only stats   # subset

Output: ``assets/<light|dark>/<card>.svg``. Static PNG previews (cairosvg)
show layout only — animations, grain and shadows live in the browser.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ASSETS = REPO / "assets"

# ---------------------------------------------------------------------------
# YUEL palette — the exact seven brand values
# ---------------------------------------------------------------------------

CREAM = "#FAECC5"
INK = "#080806"
GREEN_DEEP = "#085834"
GREEN_FOREST = "#08442C"
CRIMSON = "#BD2632"
MAROON = "#7D2327"
RED_VIVID = "#F32138"

DISPLAY_FONT = "Space Grotesk, Inter, system-ui, -apple-system, Segoe UI, sans-serif"
MONO_FONT = "IBM Plex Mono, ui-monospace, SFMono-Regular, Menlo, monospace"

THEMES = {
    "dark": {
        "card_base": GREEN_FOREST, "card_base2": GREEN_DEEP,
        "node_fill": GREEN_FOREST,
        "text": CREAM,
        "overline": (CREAM, 0.75),
        "muted": (CREAM, 0.55),
        "link": RED_VIVID,
        "accent": RED_VIVID,
        "accent2": CREAM,
        "accent3": CRIMSON,
        "hero_grad": (RED_VIVID, CRIMSON, CREAM),
        "word_grad": (CREAM, RED_VIVID, CRIMSON),
        "glow": RED_VIVID,
        "border_muted": (CREAM, 0.20),
        "divider": (CREAM, 0.16),
        "bg_tint": (CREAM, 0.05),
        "sweep_band": (CREAM, 0.06),
        "grid_dot": CREAM,
        "grain_fill": CREAM,
        "shadow_tint": RED_VIVID,
        "wave_a": (RED_VIVID, 0.10),
        "wave_b": (CREAM, 0.07),
        "bar_track": (CREAM, 0.14),
        "accent_line": (GREEN_DEEP, CRIMSON, RED_VIVID),
    },
    "light": {
        "card_base": CREAM, "card_base2": CREAM,
        "node_fill": CREAM,
        "text": INK,
        "overline": (GREEN_DEEP, None),
        "muted": (MAROON, 0.80),
        "link": CRIMSON,
        "accent": CRIMSON,
        "accent2": GREEN_DEEP,
        "accent3": MAROON,
        "hero_grad": (CRIMSON, MAROON, RED_VIVID),
        "word_grad": (MAROON, CRIMSON, RED_VIVID),
        "glow": RED_VIVID,
        "border_muted": (MAROON, 0.35),
        "divider": (GREEN_DEEP, 0.25),
        "bg_tint": (GREEN_FOREST, 0.05),
        "sweep_band": (RED_VIVID, 0.05),
        "grid_dot": GREEN_DEEP,
        "grain_fill": INK,
        "shadow_tint": CRIMSON,
        "wave_a": (CRIMSON, 0.09),
        "wave_b": (GREEN_DEEP, 0.07),
        "bar_track": (GREEN_DEEP, 0.13),
        "accent_line": (GREEN_DEEP, CRIMSON, RED_VIVID),
    },
}

# alternating cell/node accents (reference-style multi-accent rhythm,
# realized strictly inside the 7-color palette)
ACCENTS = {
    "dark": [RED_VIVID, CREAM, RED_VIVID, CREAM, RED_VIVID, CREAM],
    "light": [CRIMSON, GREEN_DEEP, MAROON, GREEN_DEEP, CRIMSON, GREEN_DEEP],
}

TIER_COLORS = {  # per tier, per theme
    "gold": {"light": CRIMSON, "dark": RED_VIVID},
    "silver": {"light": GREEN_DEEP, "dark": CREAM},
    "bronze": {"light": MAROON, "dark": CRIMSON},
}


def oc(th: dict, key: str) -> tuple[str, float | None]:
    hx, op = th[key]
    return hx, op


# ---------------------------------------------------------------------------
# real data — every number from the last actual run
# ---------------------------------------------------------------------------


def load_real_data() -> dict:
    summary = json.loads((REPO / "data/out/run-summary.json").read_text(encoding="utf-8"))
    score = json.loads((REPO / "data/scored/score_report.json").read_text(encoding="utf-8"))
    validate = json.loads((REPO / "data/validated/validate_report.json").read_text(encoding="utf-8"))
    cfg = json.loads((REPO / "config/score.json").read_text(encoding="utf-8"))
    all_records = json.loads((REPO / "data/out/all.json").read_text(encoding="utf-8"))

    totals = summary["totals"]
    alive = totals["validated_alive"]
    tiers = summary["by_tier"]
    assert sum(tiers.values()) == alive, f"tier counts {tiers} do not sum to alive {alive}"
    assert totals["published_records"] == alive, "published records != alive"
    assert len(all_records) == alive, "all.json rows != alive"

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
        "score_stats": score["score_stats"],
        "latency": validate["handshake_check"]["latency_ms"],
        "by_type": validate["handshake_check"]["alive_by_confirmed_type"],
        "thresholds": cfg["tiers"],
        "top_countries": countries,
    }


def fmt(n) -> str:
    return f"{n:,}"


def esc(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def est_width(text: str, size: float, spacing: float = 0.0) -> float:
    return len(text) * size * 0.62 + max(0, len(text) - 1) * spacing


# ---------------------------------------------------------------------------
# geometric line icons (24-unit grid, rounded 2px strokes)
# ---------------------------------------------------------------------------

ICON_PATHS = {
    "cluster": (  # many sources feeding one point — collect
        '<circle cx="5.5" cy="6" r="2.4"/><circle cx="5.5" cy="18" r="2.4"/>'
        '<circle cx="18.5" cy="12" r="2.4"/>'
        '<path d="M7.7 7.1 L16.3 11 M7.7 16.9 L16.3 13"/>'
    ),
    "layers": (  # dedup stacks — normalize / unique
        '<path d="M12 3 L20 7.5 L12 12 L4 7.5 Z"/>'
        '<path d="M4 12.5 L12 17 L20 12.5"/>'
        '<path d="M4 16.5 L12 21 L20 16.5"/>'
    ),
    "shield": (  # handshake-tested
        '<path d="M12 3 L19 5.8 V11 C19 15.6 16.1 18.6 12 20.2 '
        'C7.9 18.6 5 15.6 5 11 V5.8 Z"/>'
        '<path d="M9 11.6 L11.3 13.9 L15.3 9.7"/>'
    ),
    "globe": (  # countries
        '<circle cx="12" cy="12" r="8.2"/>'
        '<ellipse cx="12" cy="12" rx="3.6" ry="8.2"/>'
        '<path d="M4.4 12 H19.6"/>'
    ),
    "funnel": (  # validated alive
        '<path d="M4 5 H20 L14 12 V17.5 L10 20.5 V12 Z"/>'
        '<path d="M7.5 8.2 H16.5"/>'
    ),
    "gem": (  # gold tier
        '<path d="M8 4 H16 L20 9 L12 20 L4 9 Z"/>'
        '<path d="M4 9 H20 M8 4 L11.5 9 M16 4 L12.5 9 M12 9 L12 20" stroke-width="1.4"/>'
    ),
    "hexagon": (  # silver tier
        '<path d="M12 3.6 L19.2 7.8 V16.2 L12 20.4 L4.8 16.2 V7.8 Z"/>'
        '<circle cx="12" cy="12" r="3.2" stroke-width="1.4"/>'
    ),
    "database": (  # sources
        '<ellipse cx="12" cy="5.5" rx="7.5" ry="2.8"/>'
        '<path d="M4.5 5.5 V18.5 C4.5 20 7.9 21.3 12 21.3 C16.1 21.3 19.5 20 19.5 18.5 V5.5"/>'
        '<path d="M4.5 12 C4.5 13.5 7.9 14.8 12 14.8 C16.1 14.8 19.5 13.5 19.5 12"/>'
    ),
    "gauge": (  # score
        '<path d="M4.5 15.5 A 8 8 0 1 1 19.5 15.5"/>'
        '<path d="M12 14.5 L16.4 10.1"/>'
        '<circle cx="12" cy="15" r="1.8"/>'
    ),
    "box": (  # publish / output
        '<path d="M4 8 L12 4 L20 8 V16 L12 20 L4 16 Z"/>'
        '<path d="M4 8 L12 12 L20 8 M12 12 V20"/>'
    ),
    "target": (  # alive / hit
        '<circle cx="12" cy="12" r="7.5"/><circle cx="12" cy="12" r="3"/>'
        '<path d="M12 2.5 V5 M12 19 V21.5 M2.5 12 H5 M19 12 H21.5"/>'
    ),
    "bolt": (  # automation / CI
        '<path d="M13 3 L6 13 H11 L10 21 L18 10 H12.6 Z"/>'
    ),
}


def icon(name: str, x: float, y: float, size: float, color: str,
         opacity: float | None = None) -> str:
    sw = 2.0 * 24.0 / size
    op = f' opacity="{opacity}"' if opacity is not None else ""
    return (
        f'<g transform="translate({x:.1f},{y:.1f}) scale({size / 24:.4f})" '
        f'fill="none" stroke="{color}" stroke-width="{sw:.2f}" '
        f'stroke-linecap="round" stroke-linejoin="round"{op}>'
        f'{ICON_PATHS[name]}</g>'
    )


# ---------------------------------------------------------------------------
# svg primitives
# ---------------------------------------------------------------------------


def lin_grad(gid: str, stops, x1=0.0, y1=0.0, x2=1.0, y2=1.0,
             units="objectBoundingBox") -> str:
    s = "\n".join(
        f'      <stop offset="{pos}" stop-color="{hx}" stop-opacity="{op}"/>'
        for hx, pos, op in stops
    )
    return (f'    <linearGradient id="{gid}" gradientUnits="{units}" '
            f'x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}">\n{s}\n    </linearGradient>')


def text_el(x, y, s, size, fill, weight=400, family=DISPLAY_FONT,
            spacing=None, anchor="start", opacity=None) -> str:
    ls = f' letter-spacing="{spacing}"' if spacing else ""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    return (
        f'  <text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
        f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{ls}{op}>{esc(s)}</text>'
    )


def overline(x, y, s, th, size=11, accent=None) -> str:
    hx, op = oc(th, "overline")
    return text_el(x, y, s.upper(), size, accent or hx, weight=700,
                   spacing="2.4", opacity=op if accent is None else None)


def mono_text(x, y, s, size, fill, anchor="start", opacity=None) -> str:
    return text_el(x, y, s, size, fill, weight=500, family=MONO_FONT,
                   anchor=anchor, opacity=opacity)


def live_dot(t, cx, cy, r, color, opacity=None) -> str:
    op = f' fill-opacity="{opacity}"' if opacity is not None else ""
    return (f'  <circle class="bgl-{t}" cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" '
            f'fill="{color}"{op}/>')


def ping_rings(t, cx, cy, r, color, rings=2, static_op=0.35) -> str:
    """Expanding ping rings (transient by nature; faint static ring stays)."""
    out = [f'  <g class="pls-{t}" style="animation-delay:0s">'
           f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
           f'stroke-width="2" opacity="{static_op}"/></g>']
    for i in range(1, rings):
        out.append(
            f'  <g class="pls-{t}" style="animation-delay:-{i * 1.2:.1f}s">'
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="2" opacity="{static_op}"/></g>')
    return "\n".join(out)


def glow_stack(t, cx, cy, scale=1.0) -> str:
    """Three stacked radial ellipses: tight core / soft mid / wide ambient."""
    return (
        f'  <g class="glowG-{t}">'
        f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{200 * scale:.0f}" ry="{88 * scale:.0f}" '
        f'fill="url(#glow-{t})" opacity="0.28"/>'
        f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{130 * scale:.0f}" ry="{58 * scale:.0f}" '
        f'fill="url(#glow-{t})" opacity="0.5"/>'
        f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" rx="{76 * scale:.0f}" ry="{34 * scale:.0f}" '
        f'fill="url(#glow-{t})" opacity="0.85"/>'
        f'</g>'
    )


def chip(x, y, w, h, label, th, accent, filled=False, size=11.5) -> str:
    """Pill chip, centered label."""
    rect = (
        f'  <rect x="{x:.0f}" y="{y}" width="{w:.0f}" height="{h}" rx="{h / 2:.0f}" '
        f'fill="{accent}" fill-opacity="{0.16 if filled else 0.07}" '
        f'stroke="{accent}" stroke-opacity="{0.55 if filled else 0.30}" stroke-width="1"/>'
    )
    hx, op = oc(th, "overline")
    txt = text_el(x + w / 2, y + h / 2 + size * 0.36, label.upper(), size,
                  accent if filled else hx,
                  weight=700, spacing="1.4", anchor="middle",
                  opacity=None if filled else op)
    return rect + "\n" + txt


def wave_path(W: int, y: float, amp: float, halfwave: int = 170) -> str:
    """Wide sine-ish wave extending past both edges (for the translate loop)."""
    span = W + 640
    x = -320
    d = [f"M {x} {y:.0f}"]
    up = True
    while x < span:
        d.append(f"q {halfwave / 2} {-amp if up else amp:.0f} {halfwave} 0")
        up = not up
        x += halfwave
    return " ".join(d)


# ---------------------------------------------------------------------------
# animation vocabulary (CSS only, theme-suffixed, reduced-motion guarded)
# ---------------------------------------------------------------------------


def build_style(t: str) -> str:
    guarded = (f".pt-{t},.sweep-{t},.wv-{t},.spin-{t},.rev-{t},.beat-{t},"
               f".glowG-{t},.shn-{t},.bgl-{t},.dash-{t},.pk-{t},.pkv-{t},"
               f".pls-{t},.flt-{t},.grow-{t}")
    return f"""    <style>
      @keyframes fl-{t} {{
        0% {{ transform: translateY(0); opacity: 0; }}
        12% {{ opacity: 0.85; }}
        80% {{ opacity: 0.45; }}
        100% {{ transform: translateY(-330px); opacity: 0; }}
      }}
      .pt-{t} {{ animation: fl-{t} 9s linear infinite; }}

      @keyframes sw-{t} {{
        0%, 52% {{ transform: translateX(0) skewX(-20deg); }}
        100% {{ transform: translateX(1900px) skewX(-20deg); }}
      }}
      .sweep-{t} {{ animation: sw-{t} 7.5s ease-in-out infinite; }}

      @keyframes wvm-{t} {{ to {{ transform: translateX(-170px); }} }}
      .wv-{t} {{ animation: wvm-{t} 9s ease-in-out infinite alternate; }}
      .wv2-{t} {{ animation-duration: 14s; }}

      @keyframes sp-{t} {{ to {{ transform: rotate(360deg); }} }}
      .spin-{t} {{ transform-box: fill-box; transform-origin: center;
                  animation: sp-{t} 8s linear infinite; }}
      .rev-{t} {{ animation-direction: reverse; }}

      @keyframes bt-{t} {{ 50% {{ transform: scale(1.12); }} }}
      .beat-{t} {{ transform-box: fill-box; transform-origin: center;
                  animation: bt-{t} 2.4s ease-in-out infinite; }}

      @keyframes gw-{t} {{ 50% {{ opacity: 0.55; }} }}
      .glowG-{t} {{ animation: gw-{t} 3.2s ease-in-out infinite; }}

      @keyframes shn-{t} {{
        0%, 46% {{ transform: translateX(-540px); }}
        100% {{ transform: translateX(1620px); }}
      }}
      .shn-{t} {{ animation: shn-{t} 5.5s ease-in-out infinite; }}

      @keyframes bgl-{t} {{ 0%, 100% {{ opacity: 0.35; }} 12% {{ opacity: 1; }} }}
      .bgl-{t} {{ animation: bgl-{t} 2.2s ease-in-out infinite; }}

      @keyframes dsh-{t} {{ to {{ stroke-dashoffset: -36; }} }}
      .dash-{t} {{ stroke-dasharray: 8 10; animation: dsh-{t} 1.2s linear infinite; }}

      @keyframes pk-{t} {{
        0% {{ transform: translateX(0); opacity: 0; }}
        10% {{ opacity: 1; }}
        88% {{ opacity: 1; }}
        100% {{ transform: translateX(var(--d, 200px)); opacity: 0; }}
      }}
      .pk-{t} {{ animation: pk-{t} 2.6s linear infinite; }}

      @keyframes pkv-{t} {{
        0% {{ transform: translateY(0); opacity: 0; }}
        10% {{ opacity: 1; }}
        88% {{ opacity: 1; }}
        100% {{ transform: translateY(var(--dy, 40px)); opacity: 0; }}
      }}
      .pkv-{t} {{ animation: pkv-{t} 2.6s linear infinite; }}

      @keyframes pls-{t} {{
        0% {{ transform: scale(0.55); opacity: 0.85; }}
        100% {{ transform: scale(2.4); opacity: 0; }}
      }}
      .pls-{t} {{ transform-box: fill-box; transform-origin: center;
                 animation: pls-{t} 2.4s ease-out infinite; }}

      @keyframes flt-{t} {{ 50% {{ transform: translateY(-6px); }} }}
      .flt-{t} {{ animation: flt-{t} 6s ease-in-out infinite; }}

      @keyframes grw-{t} {{ from {{ transform: scaleX(0); }} }}
      .grow-{t} {{ transform-box: fill-box; transform-origin: left center;
                  animation: grw-{t} 1.5s 0.2s ease-out both; }}

      @media (prefers-reduced-motion: reduce) {{
        {guarded} {{ animation: none; }}
      }}
    </style>"""


# ---------------------------------------------------------------------------
# shared defs + card frame
# ---------------------------------------------------------------------------


def frame_defs(t: str, th: dict, W: int, H: int) -> str:
    border = oc(th, "border_muted")
    tint = oc(th, "bg_tint")
    div = oc(th, "divider")
    wa = oc(th, "wave_a")
    wb = oc(th, "wave_b")
    bar = th["accent_line"]
    defs = [
        lin_grad(f"bg-{t}", [(th["card_base"], 0, 1), (th["card_base2"], 1, 1)]),
        lin_grad(f"tint-{t}", [(tint[0], 0, tint[1]), (tint[0], 1, 0)], x2=0, y2=1),
        lin_grad(f"inner-{t}", [
            (CREAM, 0, 0.10 if t == "dark" else 0.55), (CREAM, 0.28, 0),
        ], x2=0, y2=1),
        lin_grad(f"topbar-{t}", [
            (bar[0], 0, 0.9), (bar[1], 0.55, 0.9), (bar[2], 1, 0.9),
        ], x1=0, y1=1.5, x2=W, y2=1.5, units="userSpaceOnUse"),
        lin_grad(f"hero-{t}", [(th["hero_grad"][0], 0, 1),
                               (th["hero_grad"][1], 0.55, 1),
                               (th["hero_grad"][2], 1, 1)], x2=0, y2=1),
        lin_grad(f"word-{t}", [(th["word_grad"][0], 0, 1),
                               (th["word_grad"][1], 0.6, 1),
                               (th["word_grad"][2], 1, 1)], x1=0, y1=0, x2=1, y2=0),
        lin_grad(f"ib-{t}", [
            (th["accent"], 0, 0.5), (th["accent"], 0.45, 0.16), (th["accent"], 1, 0.05),
        ], x2=0, y2=1),
        lin_grad(f"border-{t}", [
            (border[0], 0, border[1]), (border[0], 1, border[1] * 0.55),
        ]),
        lin_grad(f"div-{t}", [
            (div[0], 0, div[1]), (div[0], 1, div[1] * 0.35),
        ], x2=1, y2=0),
        f'    <radialGradient id="glow-{t}" cx="0.5" cy="0.5" r="0.5">'
        f'<stop offset="0" stop-color="{th["glow"]}" stop-opacity="0.55"/>'
        f'<stop offset="0.55" stop-color="{th["glow"]}" stop-opacity="0.18"/>'
        f'<stop offset="1" stop-color="{th["glow"]}" stop-opacity="0"/></radialGradient>',
        lin_grad(f"shine-{t}", [
            (oc(th, "sweep_band")[0], 0, 0),
            (oc(th, "sweep_band")[0], 0.5, oc(th, "sweep_band")[1]),
            (oc(th, "sweep_band")[0], 1, 0),
        ], x2=1, y2=0),
        lin_grad(f"wavea-{t}", [(wa[0], 0, wa[1]), (wa[0], 1, wa[1] * 0.2)], x2=0, y2=1),
        lin_grad(f"waveb-{t}", [(wb[0], 0, wb[1]), (wb[0], 1, wb[1] * 0.2)], x2=0, y2=1),
        f'    <pattern id="grid-{t}" width="24" height="24" patternUnits="userSpaceOnUse">',
        f'      <circle cx="1.6" cy="1.6" r="1.05" fill="{th["grid_dot"]}"/>',
        "    </pattern>",
        f'    <filter id="grain-{t}" x="0" y="0" width="100%" height="100%">',
        '      <feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" '
        'stitchTiles="stitch" result="n"/>',
        '      <feColorMatrix in="n" type="saturate" values="0" result="m"/>',
        '      <feComposite in="m" in2="SourceGraphic" operator="in"/>',
        "    </filter>",
        f'    <filter id="shadow-{t}" x="-15%" y="-15%" width="130%" height="140%">',
        f'      <feDropShadow dx="0" dy="10" stdDeviation="16" flood-color="{th["shadow_tint"]}" flood-opacity="0.20"/>',
        f'      <feDropShadow dx="0" dy="2" stdDeviation="5" flood-color="{th["shadow_tint"]}" flood-opacity="0.25"/>',
        "    </filter>",
        f'    <clipPath id="clip-{t}"><rect x="0" y="0" width="{W}" height="{H}" rx="26"/></clipPath>',
    ]
    return "\n".join(defs)


def particles(t: str, th: dict, W: int, H: int, n: int = 14) -> str:
    out = []
    for i in range(n):
        x = 40 + (i * 83 + (i % 3) * 27) % (W - 80)
        dur = 8 + (i % 4) * 1.7
        delay = -(i * 0.9 % dur)
        r = 2.0 + (i % 3) * 0.7
        color = th["accent"] if i % 3 == 0 else th["accent2"]
        out.append(
            f'  <circle class="pt-{t}" cx="{x}" cy="{H - 16}" r="{r}" fill="{color}" '
            f'opacity="0.55" style="animation-duration:{dur:.1f}s;animation-delay:{delay:.1f}s"/>')
    return "\n".join(out)


def card_frame(t: str, th: dict, W: int, H: int, rx: int = 26,
               particles_n: int = 14) -> str:
    """Shadow + layered bg + grain + dot grid + double border + top accent
    line + highlight sweep + waves + rising particles + bottom dot row."""
    parts = [
        f'  <g filter="url(#shadow-{t})"><rect width="{W}" height="{H}" rx="{rx}" '
        f'fill="{th["card_base"]}"/></g>',
        f'  <g clip-path="url(#clip-{t})">',
        f'    <rect width="{W}" height="{H}" fill="url(#bg-{t})"/>',
        f'    <rect width="{W}" height="{H}" fill="url(#tint-{t})"/>',
        f'    <rect width="{W}" height="{H}" fill="url(#inner-{t})"/>',
        f'    <rect width="{W}" height="{H}" fill="url(#grid-{t})" opacity="0.05"/>',
        f'    <rect width="{W}" height="{H}" fill="{th["grain_fill"]}" '
        f'filter="url(#grain-{t})" opacity="0.045"/>',
        # ambient corner glows
        f'    <ellipse cx="130" cy="60" rx="260" ry="140" fill="url(#glow-{t})" opacity="0.22"/>',
        f'    <ellipse cx="{W - 110}" cy="{H - 50}" rx="240" ry="130" fill="url(#glow-{t})" opacity="0.14"/>',
        # waves hugging the bottom
        f'    <path class="wv-{t}" d="{wave_path(W, H - 34, 11)}" fill="url(#wavea-{t})" opacity="0.8"/>',
        f'    <path class="wv-{t} wv2-{t}" d="{wave_path(W, H - 22, 9)}" fill="url(#waveb-{t})" opacity="0.9"/>',
        # top accent line
        f'    <rect width="{W}" height="3" fill="url(#topbar-{t})"/>',
        # one quiet highlight sweep
        f'    <g class="sweep-{t}"><rect x="-320" y="-60" width="230" height="{H + 120}" '
        f'fill="url(#shine-{t})" opacity="0.75"/></g>',
        particles(t, th, W, H, particles_n),
    ]
    for i in range(26):
        x = 46 + i * 43.2
        blink = i % 5 == 2
        dot = (f'  <circle class="bgl-{t}" cx="{x:.0f}" cy="{H - 7}" r="1.8" '
               f'fill="{th["accent2"]}" style="animation-delay:-{i * 0.23:.2f}s"/>'
               if blink else
               f'  <circle cx="{x:.0f}" cy="{H - 7}" r="1.8" fill="{th["accent2"]}" '
               f'opacity="0.28"/>')
        parts.append(dot)
    parts.append("  </g>")
    # double border
    parts.append(f'  <rect x="3.5" y="3.5" width="{W - 7}" height="{H - 7}" rx="{rx - 3}" '
                 f'fill="none" stroke="url(#ib-{t})" stroke-width="1.5"/>')
    parts.append(f'  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="{rx}" '
                 f'fill="none" stroke="url(#border-{t})" stroke-width="1"/>')
    return "\n".join(parts)


def svg_open(t: str, th: dict, W: int, H: int) -> str:
    return "\n".join([
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img">',
        "  <defs>",
        frame_defs(t, th, W, H),
        "  </defs>",
        build_style(t),
    ])


# ---------------------------------------------------------------------------
# card: header hero banner
# ---------------------------------------------------------------------------


def card_header(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 480
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H, particles_n=16)]
    muted_c, muted_o = oc(th, "muted")

    # emblem: ping rings + spinning dashed orbit + gradient tile + icon
    parts.append(ping_rings(t, 600, 112, 44, th["accent"], rings=2, static_op=0.3))
    parts.append(f'  <circle class="spin-{t}" cx="600" cy="112" r="42" fill="none" '
                 f'stroke="{th["accent2"]}" stroke-opacity="0.5" stroke-width="1.6" '
                 f'stroke-dasharray="6 8"/>')
    parts.append(glow_stack(t, 600, 112, 0.5))
    parts.append(f'  <rect x="568" y="80" width="64" height="64" rx="17" '
                 f'fill="url(#hero-{t})"/>')
    parts.append(f'  <rect x="568.5" y="80.5" width="63" height="63" rx="17" '
                 f'fill="none" stroke="{CREAM}" stroke-opacity="0.35" stroke-width="1"/>')
    parts.append(icon("funnel", 588, 100, 24, CREAM, 0.95))

    # badge pill
    label = "plain-proxy intelligence · refreshed hourly"
    bw = est_width(label, 11.5, 1.4) + 30
    parts.append(chip(600 - bw / 2, 172, bw, 30, label, th, th["accent2"]))

    # wordmark + glow + tagline
    parts.append(glow_stack(t, 600, 268, 1.2))
    parts.append(text_el(600, 300, "YUEL", 112, f"url(#word-{t})", weight=800,
                         spacing="6", anchor="middle"))
    sub = (f'{fmt(d["alive"])} plain proxies alive right now · {d["countries"]} countries · '
           f'{d["sources"]} public sources')
    parts.append(text_el(600, 348, sub, 17, muted_c, weight=500, anchor="middle",
                         opacity=muted_o))

    # chips row
    labels = ["SOCKS4 · SOCKS5 · HTTP", "ONE CLI", "JSON OUTPUT", "NO TUNNELS BY DESIGN"]
    widths = [est_width(s, 11.5, 1.4) + 30 for s in labels]
    total = sum(widths) + 3 * 14
    cx = 600 - total / 2
    for i, (lab, w) in enumerate(zip(labels, widths)):
        parts.append(chip(cx, 372, w, 36, lab, th,
                          th["accent"] if i == 0 else th["accent2"], filled=(i == 0)))
        cx += w + 14

    parts.append(mono_text(600, 446,
                           f"latency p50 {fmt(d['latency']['p50'])} ms — measured through real handshakes",
                           11.5, muted_c, anchor="middle", opacity=muted_o))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: stats strip
# ---------------------------------------------------------------------------


def card_stats(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 190
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H, particles_n=8)]
    muted_c, muted_o = oc(th, "muted")

    stamp = d["generated_utc"][:16].replace("T", " · ") + " UTC"
    parts.append(live_dot(t, 46, 40, 4, th["accent"]))
    parts.append(overline(58, 44, f"last run — {stamp}", th))
    parts.append(mono_text(W - 40, 44, "plain SOCKS4 / SOCKS5 / HTTP", 11.5,
                           muted_c, anchor="end", opacity=muted_o))

    cells = [
        ("funnel", "Validated alive", d["alive"]),
        ("database", "Collected", d["collected"]),
        ("layers", "Unique", d["unique"]),
        ("shield", "Handshake-tested", d["tested"]),
        ("globe", "Countries", d["countries"]),
    ]
    cw, gap = 211, 16
    for i, (ic, label, value) in enumerate(cells):
        x0 = 40 + i * (cw + gap)
        acc = ACCENTS[t][i]
        if i == 0:
            parts.append(ping_rings(t, x0 + 34, 104, 15, acc, rings=1, static_op=0.3))
        parts.append(icon(ic, x0, 66, 15, acc, 0.9))
        num_cls = f' class="beat-{t}"' if i == 0 else ""
        parts.append(f'  <text x="{x0}" y="118" font-family="{DISPLAY_FONT}" '
                     f'font-size="38" font-weight="800" fill="{acc}"{num_cls}>{fmt(value)}</text>')
        parts.append(overline(x0, 140, label, th, size=10))
        if i:
            parts.append(f'  <line x1="{x0 - gap / 2}" y1="62" x2="{x0 - gap / 2}" '
                         f'y2="138" stroke="url(#div-{t})" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: pipeline flow (node graph with traveling packets)
# ---------------------------------------------------------------------------


def card_flow(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 340
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H)]
    muted_c, muted_o = oc(th, "muted")

    parts.append(overline(600, 54, "from public sources to a curated feed", th,
                          accent=th["accent"], size=12))
    # side rules beside the title
    parts.append(f'  <line x1="330" y1="50" x2="404" y2="50" stroke="url(#div-{t})" stroke-width="1.5"/>')
    parts.append(f'  <line x1="796" y1="50" x2="870" y2="50" stroke="url(#div-{t})" stroke-width="1.5"/>')

    nodes = [
        ("database", "SOURCES", fmt(d["sources"])),
        ("layers", "NORMALIZE", fmt(d["unique"])),
        ("shield", "HANDSHAKE", fmt(d["tested"])),
        ("gauge", "SCORE", f"p50 {d['score_stats']['p50']}"),
        ("globe", "GEO", fmt(d["countries"])),
        ("box", "PUBLISH", fmt(d["alive"])),
    ]
    cy, r = 176, 44
    for i, (ic, name, value) in enumerate(nodes):
        cx = 130 + i * 188
        acc = ACCENTS[t][i]
        if i < 5:
            # marching-dashed connector + traveling packets
            parts.append(f'  <line class="dash-{t}" x1="{cx + r + 6}" y1="{cy}" '
                         f'x2="{cx + 188 - r - 6}" y2="{cy}" stroke="{th["accent2"]}" '
                         f'stroke-opacity="0.45" stroke-width="1.6"/>')
            parts.append(f'  <circle class="pk-{t}" cx="{cx + r + 6}" cy="{cy}" r="3.2" '
                         f'fill="{th["accent"]}" opacity="0" '
                         f'style="--d:{188 - 2 * r - 12}px;animation-delay:-{i * 0.7:.1f}s"/>')
        if i == 5:
            parts.append(ping_rings(t, cx, cy, r + 6, acc, rings=2, static_op=0.3))
            parts.append(glow_stack(t, cx, cy, 0.62))
        parts.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="{th["node_fill"]}" '
                     f'stroke="{acc}" stroke-opacity="{0.9 if i == 5 else 0.55}" stroke-width="2"/>')
        parts.append(icon(ic, cx - 11, cy - 26, 22, acc, 0.92))
        val_cls = f' class="beat-{t}"' if i == 5 else ""
        parts.append(f'  <text x="{cx}" y="{cy + 22}" font-family="{DISPLAY_FONT}" '
                     f'font-size="13.5" font-weight="700" fill="{th["text"]}" '
                     f'text-anchor="middle"{val_cls}>{esc(value)}</text>')
        parts.append(overline(cx, cy + 74, name, th, size=10, accent=acc))

    parts.append(mono_text(600, 300,
                           "every hop re-verified each run — dead exits never publish",
                           12, muted_c, anchor="middle", opacity=muted_o))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: quality tiers
# ---------------------------------------------------------------------------


def card_tiers(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 290
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H)]
    muted_c, muted_o = oc(th, "muted")

    parts.append(overline(40, 52, "quality tiers — scored, handshake-checked", th))
    thr = d["thresholds"]
    parts.append(mono_text(W - 40, 52,
                           f"gold ≥ {thr['gold']:g} · silver ≥ {thr['silver']:g} · bronze ≥ {thr['bronze']:g}",
                           11.5, muted_c, anchor="end", opacity=muted_o))

    icons = {"gold": "gem", "silver": "hexagon", "bronze": "shield"}
    pw, gap = 357, 24
    for i, tier in enumerate(("gold", "silver", "bronze")):
        x0 = 40 + i * (pw + gap)
        y0 = 72
        color = TIER_COLORS[tier][t]
        count = d["by_tier"][tier]
        share = count / d["alive"] * 100
        c1, c2 = color, th["card_base"]
        parts.append(f'  <defs><linearGradient id="tp-{t}-{tier}" x1="0" y1="0" x2="0" y2="1">'
                     f'<stop offset="0" stop-color="{c1}" stop-opacity="{0.20 if t == "dark" else 0.13}"/>'
                     f'<stop offset="1" stop-color="{c2}" stop-opacity="0.03"/>'
                     f'</linearGradient></defs>')
        gold = tier == "gold"
        if gold:
            parts.append(glow_stack(t, x0 + pw / 2, y0 + 70, 0.55))
        parts.append(f'  <rect x="{x0}" y="{y0}" width="{pw}" height="176" rx="20" '
                     f'fill="url(#tp-{t}-{tier})" stroke="{color}" '
                     f'stroke-opacity="{0.75 if gold else 0.4}" stroke-width="1.4"/>')
        if gold:
            tw = est_width("TOP TIER", 10, 1.2) + 20
            parts.append(f'  <rect x="{x0 + pw - tw - 14}" y="{y0 + 14}" width="{tw:.0f}" '
                         f'height="22" rx="11" fill="{color}"/>')
            parts.append(text_el(x0 + pw - tw / 2 - 14, y0 + 29, "TOP TIER", 10, CREAM,
                                 weight=700, spacing="1.2", anchor="middle"))
        parts.append(f'  <g class="flt-{t}" style="animation-delay:-{i * 1.4:.1f}s">'
                     + icon(icons[tier], x0 + 26, y0 + 22, 24, color, 0.95) + "</g>")
        parts.append(overline(x0 + 60, y0 + 40, tier, th, size=12, accent=color))
        cnt_cls = f' class="beat-{t}"' if gold else ""
        parts.append(f'  <text x="{x0 + 26}" y="{y0 + 116}" font-family="{DISPLAY_FONT}" '
                     f'font-size="56" font-weight="800" fill="{color}"{cnt_cls}>{fmt(count)}</text>')
        parts.append(mono_text(x0 + 28, y0 + 144, f"{share:.1f}% of alive", 12,
                               muted_c, opacity=muted_o))
        track_w = pw - 56
        parts.append(f'  <rect x="{x0 + 28}" y="{y0 + 156}" width="{track_w}" height="7" '
                     f'rx="3.5" fill="{oc(th, "bar_track")[0]}" '
                     f'fill-opacity="{oc(th, "bar_track")[1]}"/>')
        parts.append(f'  <rect class="grow-{t}" x="{x0 + 28}" y="{y0 + 156}" '
                     f'width="{track_w * share / 100:.0f}" height="7" rx="3.5" '
                     f'fill="{color}" style="animation-delay:{0.25 + i * 0.2:.2f}s"/>')
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: collection funnel
# ---------------------------------------------------------------------------


def card_funnel(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 330
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H)]
    muted_c, muted_o = oc(th, "muted")

    parts.append(overline(40, 52, "collection funnel — one hourly run", th))
    pass_rate = d["alive"] / d["tested"] * 100
    parts.append(mono_text(W - 40, 52,
                           f"{fmt(d['alive'])} of {fmt(d['tested'])} tested survive — {pass_rate:.1f}%",
                           11.5, muted_c, anchor="end", opacity=muted_o))

    stages = [
        ("COLLECTED", d["collected"]),
        ("UNIQUE", d["unique"]),
        ("HANDSHAKE-TESTED", d["tested"]),
        ("ALIVE", d["alive"]),
    ]
    bx, maxw, bh = 210, 520, 36
    vmax = stages[0][1]
    for i, (name, v) in enumerate(stages):
        y = 82 + i * 56
        bw = max(64, int(maxw * math.sqrt(v / vmax)))
        acc = th["accent"] if i == 3 else th["accent2"]
        if i == 3:
            parts.append(glow_stack(t, bx + bw / 2, y + bh / 2, 0.45))
        parts.append(f'  <rect class="grow-{t}" x="{bx}" y="{y}" width="{bw}" height="{bh}" '
                     f'rx="{bh / 2}" fill="{f"url(#hero-{t})" if i == 3 else acc}" '
                     f'fill-opacity="{1.0 if i == 3 else 0.15}" '
                     f'stroke="{acc}" stroke-opacity="{0.6 if i == 3 else 0.4}" '
                     f'stroke-width="1" style="animation-delay:{0.15 + i * 0.18:.2f}s"/>')
        parts.append(overline(40, y + bh / 2 + 4, name, th, size=10.5))
        parts.append(text_el(bx + bw + 14, y + bh / 2 + 2, fmt(v), 19,
                             th["text"] if i < 3 else th["accent"], weight=800))
        pct = v / vmax * 100
        parts.append(mono_text(bx + bw + 14 + est_width(fmt(v), 19) + 10,
                               y + bh / 2 + 2, f"{pct:.1f}%", 11.5, muted_c, opacity=muted_o))
        if i < 3:
            parts.append(f'  <circle class="pkv-{t}" cx="{bx + 60}" cy="{y + bh + 4}" r="2.6" '
                         f'fill="{th["accent"]}" opacity="0" style="--dy:14px;animation-delay:-{i * 0.8:.1f}s"/>')

    # survivors panel
    px, py = 880, 82
    parts.append(f'  <rect x="{px}" y="{py}" width="280" height="212" rx="18" '
                 f'fill="{th["node_fill"]}" fill-opacity="0.5" stroke="{th["accent"]}" '
                 f'stroke-opacity="0.35" stroke-width="1.2"/>')
    parts.append(icon("funnel", px + 18, py + 18, 26, th["accent"], 0.95))
    parts.append(overline(px + 18, py + 84, "the survivors", th, accent=th["accent"]))
    parts.append(f'  <text class="beat-{t}" x="{px + 16}" y="{py + 142}" '
                 f'font-family="{DISPLAY_FONT}" font-size="54" font-weight="800" '
                 f'fill="url(#hero-{t})">{fmt(d["alive"])}</text>')
    parts.append(mono_text(px + 18, py + 176,
                           f"score p50 {d['score_stats']['p50']}", 12, muted_c, opacity=muted_o))
    parts.append(mono_text(px + 18, py + 196,
                           f"latency p50 {fmt(d['latency']['p50'])} ms", 12, muted_c, opacity=muted_o))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: top countries
# ---------------------------------------------------------------------------


def card_countries(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 440
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H, particles_n=8)]
    muted_c, muted_o = oc(th, "muted")

    parts.append(overline(40, 52, "where the alive exits live", th))
    parts.append(mono_text(W - 40, 52,
                           f"{d['countries']} countries · ip→country via the iptoasn table",
                           11.5, muted_c, anchor="end", opacity=muted_o))

    top = d["top_countries"][:12]
    vmax = top[0][1]
    bx, maxw = 96, 880
    for i, (cc, v) in enumerate(top):
        y = 80 + i * 26
        bw = max(10, int(maxw * v / vmax))
        acc = th["accent"] if i < 3 else th["accent2"]
        parts.append(f'  <rect x="40" y="{y}" width="36" height="20" rx="6" '
                     f'fill="none" stroke="{acc}" stroke-opacity="0.4" stroke-width="1"/>')
        parts.append(text_el(58, y + 14.5, cc, 10.5, acc, weight=700,
                             family=MONO_FONT, anchor="middle"))
        parts.append(f'  <rect x="{bx}" y="{y + 4}" width="{maxw}" height="12" rx="6" '
                     f'fill="{oc(th, "bar_track")[0]}" fill-opacity="{oc(th, "bar_track")[1]}"/>')
        op = max(0.35, 0.95 - i * 0.05)
        parts.append(f'  <rect class="grow-{t}" x="{bx}" y="{y + 4}" width="{bw}" height="12" '
                     f'rx="6" fill="{acc}" fill-opacity="{op:.2f}" '
                     f'style="animation-delay:{0.15 + i * 0.07:.2f}s"/>')
        parts.append(text_el(bx + maxw + 16, y + 15.5, fmt(v), 13, th["text"], weight=700))

    more = len(d["top_countries"]) - 12
    parts.append(icon("globe", 40, 404, 16, th["accent"], 0.85))
    parts.append(mono_text(64, 416,
                           f"+ {more} more countries in data/out/by-country/<CC>.json",
                           12, muted_c, opacity=muted_o))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: protocol donut
# ---------------------------------------------------------------------------


def card_protocols(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 300
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H)]
    muted_c, muted_o = oc(th, "muted")

    parts.append(overline(40, 52, "protocol mix — measured by real handshake", th))
    parts.append(mono_text(W - 40, 52,
                           "claimed type never trusted — first working protocol wins",
                           11.5, muted_c, anchor="end", opacity=muted_o))

    colors = {"dark": [RED_VIVID, CREAM, CRIMSON], "light": [CRIMSON, GREEN_DEEP, MAROON]}[t]
    protos = [("http", d["by_type"]["http"]), ("socks5", d["by_type"]["socks5"]),
              ("socks4", d["by_type"]["socks4"])]
    total = sum(v for _, v in protos)
    cx, cy, r, sw = 250, 168, 76, 24
    circ = 2 * math.pi * r
    cum = 0.0
    for i, (name, v) in enumerate(protos):
        frac = v / total
        seg = max(2.0, frac * circ - 5)
        offset = -(cum * circ) + 2.5
        parts.append(f'  <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{colors[i]}" '
                     f'stroke-width="{sw}" stroke-dasharray="{seg:.1f} {circ - seg + 5:.1f}" '
                     f'stroke-dashoffset="{offset:.1f}" transform="rotate(-90 {cx} {cy})"/>')
        cum += frac
    parts.append(f'  <circle class="spin-{t}" cx="{cx}" cy="{cy}" r="108" fill="none" '
                 f'stroke="{th["accent2"]}" stroke-opacity="0.30" stroke-width="1.6" '
                 f'stroke-dasharray="3 10"/>')
    parts.append(glow_stack(t, cx, cy, 0.55))
    parts.append(f'  <text class="beat-{t}" x="{cx}" y="{cy + 2}" font-family="{DISPLAY_FONT}" '
                 f'font-size="30" font-weight="800" fill="{th["text"]}" '
                 f'text-anchor="middle">{fmt(total)}</text>')
    parts.append(overline(cx, cy + 26, "alive", th, size=9))

    icons = {"http": "layers", "socks5": "shield", "socks4": "cluster"}
    for i, (name, v) in enumerate(protos):
        y = 100 + i * 52
        parts.append(f'  <rect x="440" y="{y - 16}" width="20" height="20" rx="6" '
                     f'fill="{colors[i]}"/>')
        parts.append(icon(icons[name], 472, y - 16, 18, colors[i], 0.9))
        parts.append(text_el(500, y, name.upper(), 17, th["text"], weight=800, spacing="0.8"))
        parts.append(mono_text(500, y + 22, f"{fmt(v)} · {v / total * 100:.1f}%", 12,
                               muted_c, opacity=muted_o))

    lat = d["latency"]
    parts.append(mono_text(600, 274,
                           f"handshake latency p50 {fmt(lat['p50'])} ms · p90 {fmt(lat['p90'])} ms · "
                           f"min {fmt(lat['min'])} · max {fmt(lat['max'])}",
                           12, muted_c, anchor="middle", opacity=muted_o))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: pipeline architecture
# ---------------------------------------------------------------------------


def card_architecture(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 470
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H, particles_n=8)]
    muted_c, muted_o = oc(th, "muted")

    parts.append(overline(40, 52, "pipeline — seven stages, one entrypoint", th))
    parts.append(mono_text(W - 40, 52, "python3 -m yuel.pipeline run", 12,
                           th["link"], anchor="end", opacity=0.9))

    boxes = [
        ("database", "COLLECT", fmt(d["sources"]) + " sources",
         f"{fmt(d['collected'])} claimed entries", 64, 78, 0),
        ("layers", "NORMALIZE", fmt(d["unique"]) + " unique",
         "dedup by connection identity", 435, 78, 1),
        ("shield", "VALIDATE", fmt(d["tested"]) + " tested",
         "real SOCKS5/4 + HTTP handshakes", 806, 78, 2),
        ("gauge", "SCORE", f"p50 {d['score_stats']['p50']}",
         "latency · success · freshness", 806, 252, 3),
        ("globe", "GEO", fmt(d["countries"]) + " countries",
         "ip→country table, never guessed", 435, 252, 4),
        ("box", "PUBLISH", fmt(d["alive"]) + " alive",
         "all.json · by-country · by-tier", 64, 252, 5),
    ]
    bw, bh = 330, 118
    for ic, name, value, desc, x0, y0, i in boxes:
        acc = ACCENTS[t][i]
        parts.append(f'  <rect x="{x0}" y="{y0}" width="{bw}" height="{bh}" rx="18" '
                     f'fill="{th["node_fill"]}" fill-opacity="0.55" stroke="{acc}" '
                     f'stroke-opacity="0.45" stroke-width="1.2"/>')
        parts.append(icon(ic, x0 + 18, y0 + 16, 20, acc, 0.92))
        parts.append(overline(x0 + 48, y0 + 32, name, th, size=11, accent=acc))
        parts.append(text_el(x0 + 18, y0 + 68, value, 21, th["text"], weight=800))
        parts.append(mono_text(x0 + 18, y0 + 92, desc, 10.5, muted_c, opacity=muted_o))

    # connectors: top row L→R, drop down, bottom row R→L
    for x0 in (394, 765):
        parts.append(f'  <line class="dash-{t}" x1="{x0}" y1="137" x2="{x0 + 41}" y2="137" '
                     f'stroke="{th["accent2"]}" stroke-opacity="0.5" stroke-width="1.6"/>')
        parts.append(f'  <circle class="pk-{t}" cx="{x0}" cy="137" r="3" fill="{th["accent"]}" '
                     f'opacity="0" style="--d:41px"/>')
    parts.append(f'  <line class="dash-{t}" x1="971" y1="196" x2="971" y2="252" '
                 f'stroke="{th["accent2"]}" stroke-opacity="0.5" stroke-width="1.6"/>')
    parts.append(f'  <circle class="pkv-{t}" cx="971" cy="200" r="3" fill="{th["accent"]}" '
                 f'opacity="0" style="--dy:48px"/>')
    for x0 in (765, 394):
        parts.append(f'  <line class="dash-{t}" x1="{x0}" y1="311" x2="{x0 + 41}" y2="311" '
                     f'stroke="{th["accent2"]}" stroke-opacity="0.5" stroke-width="1.6"/>')
        parts.append(f'  <circle class="pk-{t}" cx="{x0 + 41}" cy="311" r="3" fill="{th["accent"]}" '
                     f'opacity="0" style="--d:-41px"/>')

    # output contract strip
    parts.append(glow_stack(t, 600, 402, 0.5))
    parts.append(f'  <rect x="150" y="380" width="900" height="44" rx="22" '
                 f'fill="{th["node_fill"]}" fill-opacity="0.6" stroke="{th["accent"]}" '
                 f'stroke-opacity="0.4" stroke-width="1.2"/>')
    parts.append(icon("bolt", 176, 392, 20, th["accent"], 0.95))
    parts.append(mono_text(600, 407,
                           "refreshed hourly by GitHub Actions → data/out/{all,by-country/*,by-tier/*}.json",
                           12, th["text"], anchor="middle"))
    parts.append(live_dot(t, 1020, 402, 4.5, th["accent"]))
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: divider
# ---------------------------------------------------------------------------


def card_divider(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 64
    parts = [svg_open(t, th, W, H)]
    parts.append(f'  <g filter="url(#shadow-{t})"><rect width="{W}" height="{H}" rx="16" '
                 f'fill="{th["card_base"]}"/></g>')
    parts.append(f'  <rect width="{W}" height="{H}" rx="16" fill="url(#bg-{t})"/>')
    parts.append(f'  <rect x="90" y="28" width="1020" height="8" rx="4" fill="url(#topbar-{t})" opacity="0.9"/>')
    parts.append(f'  <line class="dash-{t}" x1="90" y1="32" x2="1110" y2="32" '
                 f'stroke="{th["accent"]}" stroke-opacity="0.55" stroke-width="2"/>')
    for cx, delay in ((90, 0.0), (1110, 1.1)):
        parts.append(f'  <g class="pls-{t}" style="animation-delay:-{delay}s">'
                     f'<circle cx="{cx}" cy="32" r="6" fill="none" stroke="{th["accent"]}" '
                     f'stroke-width="2" opacity="0.35"/></g>')
        parts.append(live_dot(t, cx, 32, 4, th["accent"]))
    parts.append(f'  <rect class="beat-{t}" x="595" y="27" width="10" height="10" rx="2" '
                 f'transform="rotate(45 600 32)" fill="{th["accent2"]}"/>')
    parts.append(f'  <rect x="0.5" y="0.5" width="{W - 1}" height="{H - 1}" rx="16" '
                 f'fill="none" stroke="url(#border-{t})" stroke-width="1"/>')
    parts.append("</svg>")
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# card: footer
# ---------------------------------------------------------------------------


def card_footer(t: str, d: dict) -> str:
    th = THEMES[t]
    W, H = 1200, 96
    parts = [svg_open(t, th, W, H), card_frame(t, th, W, H, particles_n=6)]
    muted_c, muted_o = oc(th, "muted")
    stamp = d["generated_utc"][:16].replace("T", " · ") + " UTC"
    parts.append(live_dot(t, 320, 40, 4, th["accent"]))
    parts.append(mono_text(600, 44,
                           f"YUEL · last run {stamp} · regenerated by scripts/render_assets.py",
                           12.5, th["text"], anchor="middle"))
    parts.append(mono_text(600, 70,
                           "artifacts: data/out/all.json · by-country/<CC>.json · by-tier/<tier>.json · run-summary.json",
                           10.5, muted_c, anchor="middle", opacity=muted_o))
    parts.append("</svg>")
    return "\n".join(parts)


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
    wanted = set(args.only.split(",")) if args.only else set(CARDS)
    unknown = wanted - set(CARDS)
    if unknown:
        print(f"unknown cards: {sorted(unknown)}; known: {sorted(CARDS)}")
        return 2

    written = []
    for name in sorted(wanted):
        for t in ("light", "dark"):
            svg = CARDS[name](t, data)
            out = ASSETS / t / f"{name}.svg"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(svg + "\n", encoding="utf-8")
            written.append(out)
    for path in written:
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

