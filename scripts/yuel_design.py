#!/usr/bin/env python3
"""YUEL "Aurora" design system (v6) — the visual language of the README set.

Every color in this module comes from assets/tokens.json v1.0.0 (the brand
kit derived from the YUEL logo): aubergine surfaces in dark, cream surfaces
in light, and ONE gradient — ember -> coral -> magenta -> violet — used the
way the logo uses it.

The motion vocabulary is deliberately rich (the v5 "editorial-minimal" set
was too quiet) but stays brand-true: drifting aurora fields, marching-dash
connectors, packets that travel the real pipeline paths (SMIL animateMotion),
ping rings, draw-in arcs and bars, shimmer sweeps, a typing terminal, and
one heartbeat on each card's hero numeral. All motion is CSS/SMIL inside the
SVG file (GitHub serves README images through <img>, which keeps both
alive), everything degrades to a complete static image, and everything
switches off under ``prefers-reduced-motion``.

Cards are pure functions ``(theme, data) -> svg-string``; render_assets.py
feeds them the last real pipeline run and writes both themes.
"""

from __future__ import annotations

import base64
import math
from pathlib import Path

# ---------------------------------------------------------------------------
# brand kit — exact values from assets/tokens.json v1.0.0
# ---------------------------------------------------------------------------

AUBERGINE = "#1E0D2F"  # color.origin.aubergine — dark bg-canvas
AUBERGINE_DEEP = "#1E112C"  # plum.950 — bg-sunken
EMBER = "#FC671F"      # color.origin.ember    — gradient start
CORAL = "#ED4A3B"      # color.origin.coral    — gradient 38%
MAGENTA = "#CC3C77"    # color.origin.magenta  — gradient 66%
VIOLET = "#6574C9"     # color.origin.violet   — gradient end
CREAM = "#FAECC5"      # color.origin.cream
INK = "#080806"        # color.origin.ink
RED_VIVID = "#F32138"  # primary.500

DISPLAY_FONT = "'Space Grotesk','Segoe UI',system-ui,-apple-system,sans-serif"
MONO_FONT = "'IBM Plex Mono',ui-monospace,'SFMono-Regular',Menlo,Consolas,monospace"

TIER_COLORS = {  # per tier, per theme — ember / violet / coral = brand ramp
    "gold": {"light": "#D03D00", "dark": EMBER},
    "silver": {"light": "#4854A6", "dark": VIOLET},
    "bronze": {"light": MAGENTA, "dark": CORAL},
}
PROTO_COLORS = {  # http / socks5 / socks4, per theme
    "dark": [VIOLET, EMBER, CORAL],
    "light": ["#4854A6", "#D03D00", MAGENTA],
}
GREEN = {"dark": "#6BC490", "light": "#20754A"}  # success.400 / .600 — "alive"

# surfaces & text (semantic layer of the kit)
SURFACE = {"light": "#FCF7E8", "dark": AUBERGINE}
PANEL = {"light": "#FFFFFF", "dark": "#4F3F62"}
PANEL_O = {"light": 0.62, "dark": 0.32}
BORDER = {"light": "#E8E0C5", "dark": "#645676"}
HAIR = {"light": "#D1C9AC", "dark": "#645676"}
HAIR_O = {"light": 0.9, "dark": 0.62}
TEXT = {"light": INK, "dark": "#F7F6F9"}
MUTED = {"light": "#545242", "dark": "#CCC5D5"}
MUTED_O = {"light": 0.9, "dark": 0.66}
ACC = {"light": "#D03D00", "dark": EMBER}      # accent text (accent.600/ember)
ACC2 = {"light": "#4854A6", "dark": VIOLET}    # secondary accents

BRAND_STOPS = ((EMBER, 0), (CORAL, 0.38), (MAGENTA, 0.66), (VIOLET, 1))

BRAND_DIR = Path(__file__).resolve().parent.parent / "assets" / "brand"
MARK_W, MARK_H = 144, 160  # yuel-mark-*.png native aspect (w/h = 0.9)

LOGO_W, LOGO_H = 201, 298  # yuel-logo-*.png native size


def fmt(n) -> str:
    return f"{n:,}"


def esc(s: str) -> str:
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


# ---------------------------------------------------------------------------
# shared motion vocabulary (one <style> per card)
# ---------------------------------------------------------------------------

STYLE = """
.r{animation:rise .8s cubic-bezier(.2,.7,.2,1) both}
.d1{animation-delay:.08s}.d2{animation-delay:.16s}.d3{animation-delay:.24s}
.d4{animation-delay:.32s}.d5{animation-delay:.4s}.d6{animation-delay:.48s}
.d7{animation-delay:.56s}.d8{animation-delay:.64s}.d9{animation-delay:.74s}
.d10{animation-delay:.9s}.d11{animation-delay:1.05s}.d12{animation-delay:1.2s}
@keyframes rise{from{opacity:0;transform:translateY(12px)}to{opacity:1;transform:none}}
.gw{transform-box:fill-box;transform-origin:left center;animation:grow 1s cubic-bezier(.2,.7,.2,1) both}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.mh{animation:march 20s linear infinite}
@keyframes march{to{stroke-dashoffset:-400}}
.bt{transform-box:fill-box;transform-origin:center;animation:beat 2.8s ease-in-out infinite}
@keyframes beat{0%,84%,100%{transform:scale(1)}88%{transform:scale(1.05)}94%{transform:scale(1.01)}}
.pz{transform-box:fill-box;transform-origin:center;animation:ping 2.6s cubic-bezier(0,0,.2,1) infinite}
@keyframes ping{0%{transform:scale(.45);opacity:.85}75%,100%{transform:scale(2.5);opacity:0}}
.sp{animation:spin 12s linear infinite}
.sr{animation-duration:20s;animation-direction:reverse}
@keyframes spin{to{transform:rotate(360deg)}}
.sw{animation:sweep 7s cubic-bezier(.45,0,.25,1) infinite}
@keyframes sweep{0%,58%{transform:translateX(-660px) skewX(-16deg)}100%{transform:translateX(1380px) skewX(-16deg)}}
.dr{animation:drift 18s ease-in-out infinite alternate}
.da{animation-duration:26s;animation-delay:-9s}
.db{animation-duration:34s;animation-delay:-17s}
@keyframes drift{to{transform:translate(44px,-28px) scale(1.09)}}
.tk{animation:tw 3.4s ease-in-out infinite}
.ta{animation-delay:-1.1s}.tb{animation-delay:-2.3s}
@keyframes tw{0%,100%{opacity:.15}50%{opacity:1}}
.eq{transform-box:fill-box;transform-origin:center bottom;animation:eq 1.5s ease-in-out infinite}
.ea{animation-delay:-.38s}.eb{animation-delay:-.76s}.ec{animation-delay:-1.14s}
@keyframes eq{0%,100%{transform:scaleY(.3)}50%{transform:scaleY(1)}}
.cr{animation:caret 1.1s steps(2,jump-none) infinite}
@keyframes caret{50%{opacity:0}}
.dd{stroke-dasharray:100 100;animation:draw 1.15s cubic-bezier(.3,.6,.3,1) both}
@keyframes draw{from{stroke-dashoffset:100}to{stroke-dashoffset:0}}
.gq{animation:glowq 3.2s ease-in-out infinite}
@keyframes glowq{0%,100%{opacity:.35}50%{opacity:1}}
.wv{animation:wv 13s linear infinite}
.wb{animation-duration:19s;animation-direction:reverse}
.wc{animation-duration:27s}
@keyframes wv{to{transform:translateX(-170px)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


# ---------------------------------------------------------------------------
# primitives
# ---------------------------------------------------------------------------

def brand_grad(t: str, gid: str, x2: int = 1, y2: int = 0) -> str:
    stops = "".join(f'<stop offset="{o}" stop-color="{c}"/>' for c, o in BRAND_STOPS)
    return (f'<linearGradient id="{gid}" x1="0" y1="0" x2="{x2}" y2="{y2}">'
            f"{stops}</linearGradient>\n")


def animated_grad(t: str, gid: str, dur: str = "9s") -> str:
    """Brand gradient whose stops slowly cycle through each other (SMIL)."""
    seq = [EMBER, CORAL, MAGENTA, VIOLET]
    out = [f'<linearGradient id="{gid}" x1="0" y1="0" x2="1" y2="0">']
    for i, (c, o) in enumerate(BRAND_STOPS):
        vals = ";".join(seq[(i + k) % 4] for k in range(5))
        out.append(f'<stop offset="{o}" stop-color="{c}">'
                   f'<animate attributeName="stop-color" values="{vals}" '
                   f'dur="{dur}" repeatCount="indefinite"/></stop>')
    out.append("</linearGradient>\n")
    return "".join(out)


def card_open(t: str, W: int, H: int, defs: str = "", rx: int = 26,
              extra_style: str = "") -> str:
    style = STYLE + extra_style
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" role="img" font-family="{DISPLAY_FONT}">\n'
        f"<style>{style}</style>\n<defs>{defs}</defs>\n"
        f'<rect x="0.75" y="0.75" width="{W - 1.5}" height="{H - 1.5}" rx="{rx}" '
        f'fill="{SURFACE[t]}" stroke="{BORDER[t]}" stroke-width="1.5"/>\n'
    )


def text_el(x, y, s, size, fill, weight=400, family=None, spacing=None,
            anchor=None, opacity=None, cls=None, style=None) -> str:
    fam = family or DISPLAY_FONT
    a = f' text-anchor="{anchor}"' if anchor else ""
    sp = f' letter-spacing="{spacing}"' if spacing else ""
    op = f' opacity="{opacity}"' if opacity is not None else ""
    cl = f' class="{cls}"' if cls else ""
    st = f' style="{style}"' if style else ""
    return (f'<text x="{x}" y="{y}" font-size="{size}" font-weight="{weight}" '
            f'font-family="{fam}"{sp}{a} fill="{fill}"{op}{cl}{st}>{esc(s)}</text>')


def micro(x, y, s, t: str, anchor=None, color=None, opacity=None, cls=None,
          size=10.5) -> str:
    c = color or MUTED[t]
    return text_el(x, y, s.upper(), size, c, weight=500, family=MONO_FONT,
                   spacing=2.4, anchor=anchor, opacity=opacity, cls=cls)


def mono(x, y, s, t: str, size=11.5, anchor=None, color=None, opacity=None,
         spacing=None, cls=None) -> str:
    c = color or MUTED[t]
    return text_el(x, y, s, size, c, weight=500, family=MONO_FONT,
                   anchor=anchor, opacity=opacity, spacing=spacing, cls=cls)


def hairline(x1, y1, x2, y2, t: str, width=1.2, opacity=None, dashed=False,
             animate=False, color=None) -> str:
    op = opacity if opacity is not None else HAIR_O[t]
    dash = ' stroke-dasharray="3 9"' if dashed else ""
    cls = ' class="mh"' if animate else ""
    c = color or HAIR[t]
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{c}" '
            f'stroke-opacity="{op}" stroke-width="{width}" '
            f'stroke-linecap="round"{dash}{cls}/>')


def panel(x, y, w, h, t: str, rx=16, opacity=None) -> str:
    op = opacity if opacity is not None else PANEL_O[t]
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="{PANEL[t]}" fill-opacity="{op}" stroke="{HAIR[t]}" '
            f'stroke-opacity="{HAIR_O[t]}" stroke-width="1.2"/>')


def grad_rect(x, y, w, h, rx, t: str, gid, opacity=1.0, cls=None) -> str:
    cl = f' class="{cls}"' if cls else ""
    return (f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
            f'fill="url(#{gid})" opacity="{opacity}"{cl}/>')


def ping(cx, cy, color, r=4, delay=None, dot=True) -> str:
    """A solid dot plus an expanding radar ring."""
    d = f' style="animation-delay:{delay}s"' if delay is not None else ""
    ring = (f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="1.6" class="pz"{d}/>')
    if not dot:
        return ring
    return ring + f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="{color}"/>'


def packet(path_d: str, color: str, dur: float, begin: float = 0.0, r=3.5,
           fade=True, glow=True) -> str:
    """A dot that travels a path forever (SMIL — runs inside <img>)."""
    gid = f"pg{id(path_d) % 9999}"
    glow_defs = ""
    dot_attr = f'fill="{color}"'
    if glow:
        glow_defs = (f'<filter id="{gid}" x="-150%" y="-150%" width="400%" '
                     f'height="400%"><feGaussianBlur stdDeviation="3.2" '
                     f'result="b"/><feMerge><feMergeNode in="b"/>'
                     f'<feMergeNode in="SourceGraphic"/></feMerge></filter>')
    fade_anim = ""
    if fade:
        fade_anim = (f'<animate attributeName="opacity" '
                     f'values="0;1;1;0" keyTimes="0;.08;.92;1" '
                     f'dur="{dur}s" begin="{begin}s" repeatCount="indefinite"/>')
    body = (f'<circle r="{r}" {dot_attr} filter="url(#{gid})">'
            f'<animateMotion dur="{dur}s" begin="{begin}s" '
            f'repeatCount="indefinite" path="{path_d}"/>{fade_anim}</circle>')
    return glow_defs, body


def spark_path(x: float, y: float, w: float, h: float, seed: int = 0) -> str:
    """Deterministic little sparkline shape (no randomness — reproducible CI)."""
    heights = (0.42, 0.6, 0.38, 0.72, 0.52, 0.82, 0.6, 0.9, 0.7, 1.0)
    n = len(heights)
    pts = []
    for i, hh in enumerate(heights):
        px = x + w * i / (n - 1)
        py = y + h - h * hh * (0.75 + 0.25 * ((seed + i) % 3) / 2)
        pts.append(f"{px:.1f},{py:.1f}")
    return "M " + " L ".join(pts)


def sparkline(x, y, w, h, t: str, color, seed=0, area_gid=None) -> str:
    d = spark_path(x, y, w, h, seed)
    drawn = (f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" '
             f'stroke-linecap="round" stroke-linejoin="round" '
             f'pathLength="100" class="dd"/>')
    if area_gid:
        area_d = d + f" L {x + w:.1f},{y + h:.1f} L {x:.1f},{y + h:.1f} Z"
        drawn += (f'<path d="{area_d}" fill="url(#{area_gid})" opacity="0.28" '
                  f'class="r d4"/>')
    return drawn


def sheen_band(t: str, y: float, h: float, clip_id: str) -> str:
    """Shimmer band that periodically sweeps across a clipped region."""
    c = "#FFFFFF" if t == "dark" else "#FFF6DC"
    op = 0.16 if t == "dark" else 0.5
    return (f'<g clip-path="url(#{clip_id})"><rect x="0" y="{y}" width="130" '
            f'height="{h}" fill="{c}" opacity="{op}" class="sw"/></g>')


def aurora(t: str, W: int, H: int, defs_id: str = "ab") -> str:
    """Three drifting brand-tinted light fields + a fine marching grid."""
    op = {"dark": (0.20, 0.16, 0.13), "light": (0.14, 0.10, 0.08)}[t]
    blobs = (
        f'<g filter="url(#{defs_id})">'
        f'<ellipse class="dr" cx="{W * 0.2:.0f}" cy="{H * 0.24:.0f}" '
        f'rx="{W * 0.26:.0f}" ry="{H * 0.36:.0f}" fill="{EMBER}" '
        f'fill-opacity="{op[0]}"/>'
        f'<ellipse class="dr da" cx="{W * 0.82:.0f}" cy="{H * 0.7:.0f}" '
        f'rx="{W * 0.3:.0f}" ry="{H * 0.4:.0f}" fill="{VIOLET}" '
        f'fill-opacity="{op[1]}"/>'
        f'<ellipse class="dr db" cx="{W * 0.55:.0f}" cy="{H * 0.08:.0f}" '
        f'rx="{W * 0.22:.0f}" ry="{H * 0.3:.0f}" fill="{MAGENTA}" '
        f'fill-opacity="{op[2]}"/></g>'
    )
    grid = (f'<g stroke="{HAIR[t]}" stroke-opacity="'
            f'{0.14 if t == "dark" else 0.3}">'
            + "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{H}" class="mh" '
                      f'stroke-dasharray="2 14" stroke-width="1"/>'
                      for x in range(60, W, 120))
            + "</g>")
    blur = (f'<filter id="{defs_id}" x="-40%" y="-40%" width="180%" '
            f'height="180%"><feGaussianBlur stdDeviation="42"/></filter>')
    return blur, blobs + grid


def mark_image(t: str, x: float, y: float, w: float) -> str:
    """Brand mark embedded as data URI (img-loaded SVGs cannot fetch files)."""
    variant = "color" if t == "light" else "white"
    png = (BRAND_DIR / f"yuel-mark-{variant}.png").read_bytes()
    b64 = base64.b64encode(png).decode("ascii")
    h = w * MARK_H / MARK_W
    return (f'<image x="{x}" y="{y}" width="{w}" height="{h:.1f}" '
            f'href="data:image/png;base64,{b64}"/>')


def logo_image(t: str, x: float, y: float, w: float) -> str:
    variant = "color" if t == "light" else "white"
    png = (BRAND_DIR / f"yuel-logo-{variant}.png").read_bytes()
    b64 = base64.b64encode(png).decode("ascii")
    h = w * LOGO_H / LOGO_W
    return (f'<image x="{x}" y="{y}" width="{w}" height="{h:.1f}" '
            f'href="data:image/png;base64,{b64}"/>')


def chip(x, y, label, t: str, accent=False, w=None, h=30, cls=None) -> str:
    """A rounded pill with a pulsing status dot and mono label."""
    lw = len(label) * 7.2 + 46
    width = w or lw
    stroke = ACC[t] if accent else HAIR[t]
    op = 0.85 if accent else HAIR_O[t]
    dot = GREEN[t]
    s = (f'<g class="r {cls or ""}">'
         f'<rect x="{x}" y="{y}" width="{width:.0f}" height="{h}" rx="{h / 2:.0f}" '
         f'fill="{PANEL[t]}" fill-opacity="{PANEL_O[t]}" stroke="{stroke}" '
         f'stroke-opacity="{op}" stroke-width="1.2"/>'
         f'<circle cx="{x + 16}" cy="{y + h / 2}" r="3.4" fill="{dot}"/>'
         + micro(x + 27, y + h / 2 + 3.6, label, t,
                 color=ACC[t] if accent else TEXT[t], size=10)
         + "</g>")
    return s


def arc_path(cx, cy, r, a0, a1) -> str:
    """Clockwise arc, 0deg = 12 o'clock (for the protocols donut)."""
    x0 = cx + r * math.sin(math.radians(a0))
    y0 = cy - r * math.cos(math.radians(a0))
    x1 = cx + r * math.sin(math.radians(a1))
    y1 = cy - r * math.cos(math.radians(a1))
    large = 1 if (a1 - a0) > 180 else 0
    return f"M {x0:.2f} {y0:.2f} A {r} {r} 0 {large} 1 {x1:.2f} {y1:.2f}"


def star4(cx, cy, r) -> str:
    """Tiny four-point sparkle."""
    k = r * 0.32
    return (f"M {cx} {cy - r} C {cx + k * 0.4} {cy - k} {cx + k} {cy - k * 0.4} "
            f"{cx + r} {cy} C {cx + k} {cy + k * 0.4} {cx + k * 0.4} {cy + k} "
            f"{cx} {cy + r} C {cx - k * 0.4} {cy + k} {cx - k} {cy + k * 0.4} "
            f"{cx - r} {cy} C {cx - k} {cy - k * 0.4} {cx - k * 0.4} {cy - k} "
            f"{cx} {cy - r} Z")


# ---------------------------------------------------------------------------
# cards — motion set (number-free, pushed once) + live set (CI-regenerated)
# ---------------------------------------------------------------------------

TERMINAL_CMD = "$ python3 -m yuel.pipeline run"
TERMINAL_SUB = ">> 7 stages · fail-loud · atomic publish"


def _terminal_panel(t: str, x: float, y: float, w: float, h: float,
                    cmd: str, sub: str) -> str:
    """Terminal window with a typing command + blinking caret (SMIL clip)."""
    cmd_w = len(cmd) * 8.3 + 6
    p = [panel(x, y, w, h, t, rx=14)]
    dots = [EMBER, VIOLET if t == "dark" else ACC2, CORAL]
    p.append("".join(f'<circle cx="{x + 24 + i * 18}" cy="{y + 22}" r="4.5" '
                     f'fill="{c}" fill-opacity=".9"/>'
                     for i, c in enumerate(dots)))
    p.append(f'<clipPath id="tclip-{int(x)}"><rect x="{x + 24}" y="{y + 34}" '
             f'width="0" height="{h - 44}"><animate attributeName="width" '
             f'values="0;{cmd_w:.0f};{cmd_w:.0f}" keyTimes="0;.42;1" '
             f'dur="6s" repeatCount="indefinite"/></rect></clipPath>')
    p.append(f'<g clip-path="url(#tclip-{int(x)})">'
             + mono(x + 24, y + 48, cmd, t, size=13, color=TEXT[t]) + "</g>")
    p.append(f'<rect x="{x + 30 + cmd_w:.0f}" y="{y + 36}" width="8" height="14" '
             f'fill="{ACC[t]}" class="cr"/>')
    p.append(mono(x + 24, y + h - 16, sub, t, size=11, cls="r d9"))
    return "".join(p)


def _constellation(t: str, cx: float, cy: float, labels) -> str:
    """Center 'alive' node, satellite nodes, marching links, travelling packets."""
    sats = [(cx - 188, cy - 120, labels[0]), (cx + 160, cy - 124, labels[1]),
            (cx + 192, cy + 70, labels[2]), (cx - 182, cy + 104, labels[3]),
            (cx + 14, cy - 156, labels[4]), (cx - 100, cy + 140, labels[5])]
    p = [f'<circle cx="{cx}" cy="{cy}" r="118" fill="none" stroke="{HAIR[t]}" '
         f'stroke-opacity=".5" stroke-width="1.2" stroke-dasharray="4 10" '
         f'class="sp" style="animation-duration:26s;'
         f'transform-origin:{cx}px {cy}px"/>']
    for sx, sy, _ in sats:
        p.append(hairline(cx, cy, sx, sy, t, width=1.3, opacity=.5,
                          dashed=True, animate=True))
    # travelling packets on three of the links
    for (sx, sy, _), color, dur, begin in zip(
            sats[:3], [EMBER, VIOLET if t == "dark" else ACC2, CORAL],
            (2.6, 3.0, 3.4), (0.0, 1.1, 2.2)):
        g, body = packet(f"M {cx} {cy} L {sx} {sy}", color, dur, begin, r=3.5)
        p.append(f"<defs>{g}</defs>{body}")
    for i, (sx, sy, lab) in enumerate(sats):
        p.append(f'<g class="r d{i + 4}">'
                 f'<circle cx="{sx}" cy="{sy}" r="9" fill="{PANEL[t]}" '
                 f'fill-opacity="{PANEL_O[t] + .2}" stroke="{ACC2[t]}" '
                 f'stroke-opacity=".8" stroke-width="1.4"/>'
                 f'<circle cx="{sx}" cy="{sy}" r="3.4" fill="{ACC2[t]}"/>'
                 + micro(sx, sy + 24, lab, t, anchor="middle", size=9.5)
                 + "</g>")
    # center node — the alive heart
    p.append(f'<circle cx="{cx}" cy="{cy}" r="28" fill="{PANEL[t]}" '
             f'fill-opacity="{PANEL_O[t] + .25}" stroke="url(#bg-{t})" '
             f'stroke-width="2"/>')
    p.append(ping(cx, cy, GREEN[t], r=5))
    p.append(micro(cx, cy - 42, "alive", t, anchor="middle", color=GREEN[t]))
    return "".join(p)


def card_hero_motion(t: str, d: dict) -> str:
    """Top banner — aurora, animated wordmark, typing terminal, live network."""
    W, H = 1200, 480
    blur, fields = aurora(t, W, H, "ab-hero")
    defs = (animated_grad(t, f"bg-{t}")
            + brand_grad(t, f"bg2-{t}") + blur)
    p = [card_open(t, W, H, defs)]
    p.append(fields)

    # left column -----------------------------------------------------------
    p.append(chip(72, 56, "pipeline live · every 30 minutes", t, accent=True,
                  cls="d1"))
    title = (f'<text x="72" y="212" font-size="96" font-weight="800" '
             f'letter-spacing="2" font-family="{DISPLAY_FONT}" '
             f'fill="url(#bg-{t})">YUEL</text>')
    p.append(f'<g class="r d2">{title}</g>')
    p.append(f'<clipPath id="ttl-{t}">{title}</clipPath>')
    p.append(sheen_band(t, 128, 92, f"ttl-{t}"))
    p.append(grad_rect(74, 228, 224, 4, 2, t, f"bg2-{t}", cls="gw d3"))
    p.append(f'<g class="r d4">'
             + text_el(72, 270, "plain socks4 / socks5 / http — collected, "
                                "handshake-verified, published", 18, TEXT[t],
                       weight=600)
             + "</g>")
    p.append(f'<g class="r d5">'
             + text_el(72, 296, "scored · tiered · geo-classified — a plain-proxy "
                                "feed, never a tunnel config", 13.5, MUTED[t],
                       opacity=MUTED_O[t])
             + "</g>")
    p.append(f'<g class="r d6">'
             + _terminal_panel(t, 72, 318, 560, 96, TERMINAL_CMD, TERMINAL_SUB)
             + "</g>")
    x = 72
    for i, lab in enumerate(("SOCKS5", "SOCKS4", "HTTP", "JSON + TXT")):
        p.append(chip(x, 438, lab, t, cls=f"d{i + 7}"))
        x += len(lab) * 7.2 + 46 + 14

    # right constellation ---------------------------------------------------
    p.append(f'<g class="r d3">'
             + _constellation(t, 930, 240, ("socks5", "http", "score", "geo",
                                            "tier", "socks4"))
             + "</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_header(t: str, d: dict) -> str:
    """Brand lockup card with the run's headline numbers."""
    W, H = 1200, 480
    blur, fields = aurora(t, W, H, "ab-hdr")
    p = [card_open(t, W, H, animated_grad(t, f"bg-{t}") + brand_grad(t, f"bg2-{t}") + blur)]
    p.append(fields)
    p.append(f'<g class="r d1">{mark_image(t, 600 - 62, 52, 124)}</g>')
    p.append(f'<g class="r d3">'
             + micro(600, 266, "plain-proxy intelligence · refreshed every 30 "
                               "minutes", t, anchor="middle", color=ACC[t])
             + "</g>")
    p.append(f'<g class="r d5">'
             f'<text x="600" y="330" text-anchor="middle" '
             f'font-family="{DISPLAY_FONT}">'
             f'<tspan font-size="46" font-weight="800" fill="url(#bg-{t})" '
             f'class="bt">{fmt(d["alive"])}</tspan>'
             f'<tspan dx="10" font-size="26" font-weight="700" '
             f'fill="{TEXT[t]}">alive</tspan>'
             f'<tspan dx="18" font-size="17" font-weight="500" '
             f'fill="{MUTED[t]}" opacity="{MUTED_O[t]}">· {d["countries"]} '
             f'countries · {d["sources"]} sources</tspan></text></g>')
    p.append(grad_rect(480, 354, 240, 3, 1.5, t, f"bg2-{t}", cls="gw d7"))
    p.append(f'<g class="r d8">'
             + micro(600, 400, "socks4 · socks5 · http — one cli · json + txt "
                               "output · no tunnels by design", t,
                     anchor="middle")
             + mono(600, 448, f"score p50 {d['score_stats']['p50']} — every hop "
                              f"handshake-verified each run", t,
                    anchor="middle")
             + "</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_stats(t: str, d: dict) -> str:
    W, H = 1200, 210
    defs = (brand_grad(t, f"bg-{t}") + brand_grad(t, f"bg2-{t}", y2=1)
            + f'<linearGradient id="sa-{t}" x1="0" y1="0" x2="0" y2="1">'
              f'<stop offset="0" stop-color="{ACC2[t]}" stop-opacity=".55"/>'
              f'<stop offset="1" stop-color="{ACC2[t]}" stop-opacity="0"/>'
              f"</linearGradient>\n")
    p = [card_open(t, W, H, defs)]
    p.append(micro(48, 26, f"last run — {d['stamp']}", t))
    p.append(micro(1152, 26, "plain socks4 / socks5 / http", t, anchor="end",
                   color=ACC[t]))
    comet = f"M 48 42 H 1152"
    g, body = packet(comet, ACC[t], 6.5, 0.0, r=2.5, glow=False)
    p.append(f"<defs>{g}</defs>{body}")
    p.append(hairline(48, 42, 1152, 42, t, opacity=.6))

    cols = [("validated alive", fmt(d["alive"]), True),
            ("collected", fmt(d["collected"]), False),
            ("unique", fmt(d["unique"]), False),
            ("handshake-tested", fmt(d["tested"]), False),
            ("countries", str(d["countries"]), False)]
    x0, cw = 48, 1104 / 5
    for i, (label, value, hero) in enumerate(cols):
        cx = x0 + (i + 0.5) * cw
        p.append(f'<g class="r d{i + 2}">'
                 + micro(cx, 94, label, t, anchor="middle")
                 + text_el(cx, 146, value, 38, f"url(#bg-{t})" if hero else TEXT[t],
                           weight=800, anchor="middle", cls="bt" if hero else None)
                 + "</g>")
        if hero:
            half = len(value) * 38 * 0.31
            p.append(ping(cx + half + 18, 132, GREEN[t], r=4))
        uw = 34 if hero else 22
        p.append(grad_rect(cx - uw / 2, 158, uw, 3, 1.5, t, f"bg-{t}",
                           opacity=1.0 if hero else .5, cls=f"gw d{i + 4}")
                 if hero else
                 f'<rect x="{cx - uw / 2}" y="158" width="{uw}" height="3" rx="1.5" '
                 f'fill="{HAIR[t]}" fill-opacity="{HAIR_O[t]}" class="gw d{i + 4}"/>')
        p.append(f'<g class="r d{i + 5}">'
                 + sparkline(cx - 62, 168, 124, 26, t,
                             f"url(#bg-{t})" if hero else ACC2[t], seed=i,
                             area_gid=f"sa-{t}" if hero else None)
                 + "</g>")
        if i:
            p.append(hairline(x0 + i * cw, 66, x0 + i * cw, 196, t,
                              opacity=HAIR_O[t] * .6))
    p.append("</svg>")
    return "\n".join(p)


def card_flow(t: str, d: dict) -> str:
    W, H = 1200, 300
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"))]
    p.append(micro(48, 48, "from public sources to a curated feed", t))
    p.append(micro(1152, 48, "every hop verified each run — dead lists never "
                             "publish", t, anchor="end"))
    nodes = [(str(d["sources"]), "sources"),
             (fmt(d["unique"]), "unique"),
             (fmt(d["tested"]), "handshake-tested"),
             (f"p50 {d['score_stats']['p50']}", "score"),
             (str(d["countries"]), "geo"),
             (fmt(d["alive"]), "published")]
    x0, cw, cy, r = 48, 1104 / 6, 164, 46
    centers = [x0 + (i + .5) * cw for i in range(6)]
    colors = [EMBER, VIOLET if t == "dark" else ACC2, CORAL]
    for i, ((value, label), cx) in enumerate(zip(nodes, centers)):
        last = i == len(nodes) - 1
        if i:
            px1, px2 = centers[i - 1] + r + 10, cx - r - 10
            p.append(hairline(px1, cy, px2, cy, t, width=1.6, dashed=True,
                              animate=True, opacity=.7))
            g, body = packet(f"M {px1} {cy} H {px2}", colors[i % 3], 1.7,
                             begin=0.3 * i, r=3)
            p.append(f"<defs>{g}</defs>{body}")
        p.append(ping(cx, cy, ACC[t] if (i == 0 or last) else ACC2[t],
                      r=r, delay=0.35 * i, dot=False))
        ring = f"url(#bg-{t})" if last else ACC2[t]
        p.append(f'<g class="r d{i + 2}">'
                 f'<circle cx="{cx}" cy="{cy}" r="{r + (4 if last else 0)}" '
                 f'fill="{PANEL[t]}" fill-opacity="{PANEL_O[t] + (.18 if last else 0)}" '
                 f'stroke="{ring}" stroke-opacity="{1 if last else .55}" '
                 f'stroke-width="{2.2 if last else 1.4}"/>'
                 + text_el(cx, cy + 6, value, 14 if len(value) > 6 else 17,
                           f"url(#bg-{t})" if last else TEXT[t], weight=700,
                           anchor="middle")
                 + micro(cx, cy + 78, label, t, anchor="middle")
                 + "</g>")
        if last:
            p.append(f'<circle cx="{cx}" cy="{cy}" r="{r + 16}" fill="none" '
                     f'stroke="url(#bg-{t})" stroke-opacity=".55" '
                     f'stroke-width="1.3" stroke-dasharray="6 10" class="sp" '
                     f'style="transform-origin:{cx}px {cy}px"/>')
            p.append(ping(cx, cy - 62, GREEN[t], r=4))
    p.append("</svg>")
    return "\n".join(p)


def card_funnel(t: str, d: dict) -> str:
    W, H = 1200, 330
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"))]
    p.append(micro(48, 48, "collection funnel — one 30-minute run", t))
    p.append(micro(1152, 48, "what survives is what gets published", t,
                   anchor="end"))
    rows = [("collected", d["collected"]), ("unique", d["unique"]),
            ("handshake-tested", d["tested"]), ("alive", d["alive"])]
    tx, tw = 250, 700
    centers = []
    for i, (label, value) in enumerate(rows):
        y = 84 + i * 54
        centers.append(y + 11)
        last = i == len(rows) - 1
        frac = value / d["collected"]
        p.append(f'<g class="r d{i + 2}">'
                 + micro(48, y + 16, label, t)
                 + f'<rect x="{tx}" y="{y}" width="{tw}" height="22" rx="11" '
                   f'fill="{HAIR[t]}" fill-opacity="{HAIR_O[t] * .45}"/>'
                 + (grad_rect(tx, y, tw * frac, 22, 11, t, f"bg-{t}",
                              cls=f"gw d{i + 5}") if last else
                    f'<rect x="{tx}" y="{y}" width="{tw * frac:.1f}" height="22" '
                    f'rx="11" fill="{ACC2[t]}" fill-opacity="{.85 - i * .08:.2f}" '
                    f'class="gw d{i + 3}"/>')
                 + text_el(tx + tw + 28, y + 17, fmt(value), 20,
                           f"url(#bg-{t})" if last else TEXT[t], weight=800,
                           cls="bt" if last else None)
                 + micro(tx + tw + 28, y + 36, f"{frac * 100:.1f}% of collected", t)
                 + "</g>")
    # packets falling through the funnel — two die on the way, two land alive
    dies = [("M 420 95 V 178", 0.0), ("M 880 149 V 208", 1.6)]
    for path_d, begin in dies:
        g, body = packet(path_d, CORAL, 4.2, begin, r=4)
        p.append(f"<defs>{g}</defs>{body}")
    for path_d, begin in [("M 560 95 V 257", 0.8), ("M 700 149 V 257", 2.6)]:
        g, body = packet(path_d, EMBER, 4.6, begin, r=4)
        p.append(f"<defs>{g}</defs>{body}")
        p.append(ping(700 if begin > 2 else 560, 257, GREEN[t], r=3.5,
                      delay=begin + 3.2))
    p.append(f'<g class="r d10">'
             + micro(48, 316, f"{fmt(d['alive'])} of {fmt(d['tested'])} tested "
                              f"survive — {d['survival_t2a']:.1f}% end-to-end · "
                              f"dead entries are never published", t,
                     color=ACC[t])
             + "</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_tiers(t: str, d: dict) -> str:
    W, H = 1200, 300
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"))]
    p.append(micro(48, 48, "quality tiers — scored, handshake-checked", t))
    p.append(micro(1152, 48, "gold ≥ 80 · silver ≥ 50 · bronze ≥ 20", t,
                   anchor="end"))
    ordered = [("gold", d["by_tier"]["gold"], d["thresholds"]["gold"]),
               ("silver", d["by_tier"]["silver"], d["thresholds"]["silver"]),
               ("bronze", d["by_tier"]["bronze"], d["thresholds"]["bronze"])]
    for i, (tier, count, thr) in enumerate(ordered):
        x, y = 48 + i * 380, 76
        color = TIER_COLORS[tier][t]
        pct = count / d["alive"] * 100
        p.append(f'<g class="r d{i + 3}">' + panel(x, y, 344, 188, t))
        if i == 0:
            p.append(f'<rect x="{x + 1.25}" y="{y + 1.25}" width="341.5" '
                     f'height="185.5" rx="15.5" fill="none" '
                     f'stroke="url(#bg-{t})" stroke-width="1.8"/>')
        mcx, mcy = x + 58, y + 66
        p.append(f'<circle cx="{mcx}" cy="{mcy}" r="32" fill="none" '
                 f'stroke="{color}" stroke-opacity=".5" stroke-width="1.3" '
                 f'stroke-dasharray="5 9" class="sp" '
                 f'style="transform-origin:{mcx}px {mcy}px"/>')
        p.append(f'<circle cx="{mcx}" cy="{mcy}" r="23" fill="{color}" '
                 f'fill-opacity=".14" stroke="{color}" stroke-width="1.5"/>')
        p.append(f'<rect x="{mcx - 5}" y="{mcy - 5}" width="10" height="10" '
                 f'rx="2" fill="{color}" transform="rotate(45 {mcx} {mcy})"/>')
        if i == 0:
            p.append(f'<path d="{star4(x + 100, y + 26, 6)}" fill="{color}" class="tk"/>'
                     f'<path d="{star4(x + 20, y + 104, 5)}" fill="{color}" class="tk ta"/>'
                     f'<path d="{star4(x + 96, y + 112, 4)}" fill="{color}" class="tk tb"/>')
        p.append(text_el(x + 104, y + 78, fmt(count), 44, color, weight=800))
        p.append(micro(x + 104, y + 104, f"score ≥ {thr}", t, color=TEXT[t]))
        p.append(f'<rect x="{x + 28}" y="{y + 128}" width="288" height="6" rx="3" '
                 f'fill="{HAIR[t]}" fill-opacity="{HAIR_O[t] * .8}"/>')
        p.append(f'<rect x="{x + 28}" y="{y + 128}" width="{288 * pct / 100:.1f}" '
                 f'height="6" rx="3" fill="{color}" class="gw d{i + 5}"/>')
        p.append(micro(x + 28, y + 162, f"{pct:.1f}% of alive proxies", t))
        p.append("</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_countries(t: str, d: dict) -> str:
    W, H = 1200, 470
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"))]
    p.append(micro(48, 48, "where the alive exits live", t))
    p.append(micro(1152, 48, f"{d['countries']} countries · literal-IP geo "
                             f"via the ip2asn table", t, anchor="end"))
    top = d["top_countries"][:12]
    vmax = top[0][1]
    bx, bw = 104, 940
    bar_colors = [ACC2[t], CORAL, MAGENTA]
    for i, (cc, n) in enumerate(top):
        y = 84 + i * 28
        fill = 940 * n / vmax
        p.append(f'<g class="r d{min(i + 2, 12)}">'
                 f'<rect x="48" y="{y - 4}" width="44" height="18" rx="9" '
                 f'fill="{PANEL[t]}" fill-opacity="{PANEL_O[t]}" '
                 f'stroke="{HAIR[t]}" stroke-opacity="{HAIR_O[t]}" '
                 f'stroke-width="1"/>'
                 + mono(70, y + 9, cc, t, size=10.5, anchor="middle",
                        color=TEXT[t], spacing=1.5)
                 + f'<rect x="{bx}" y="{y}" width="{bw}" height="10" rx="5" '
                   f'fill="{HAIR[t]}" fill-opacity="{HAIR_O[t] * .35}"/>'
                 + (grad_rect(bx, y, fill, 10, 5, t, f"bg-{t}",
                              cls=f"gw d{min(i + 4, 12)}")
                    if i == 0 else
                    f'<rect x="{bx}" y="{y}" width="{fill:.1f}" height="10" '
                    f'rx="5" fill="{bar_colors[i % 3]}" '
                    f'fill-opacity="{max(.85 - i * .045, .4):.2f}" '
                    f'class="gw d{min(i + 4, 12)}"/>')
                 + mono(1152, y + 9, str(n), t, size=11.5, anchor="end",
                        color=TEXT[t])
                 + "</g>")
        if i == 0:
            p.append(ping(bx + fill, y + 5, ACC[t], r=4))
    p.append(f'<g class="r d10">'
             + micro(48, 450, f"+ {d['countries'] - len(top)} more countries — "
                              f"data/out/by-country/<ISO2>.txt (combined) · "
                              f"<ISO2>/<type>.txt (per-type split)", t)
             + "</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_protocols(t: str, d: dict) -> str:
    W, H = 1200, 330
    cx, cy, r, sw = 330, 190, 95, 26
    protos = [("http", d["by_type"]["http"]), ("socks5", d["by_type"]["socks5"]),
              ("socks4", d["by_type"]["socks4"])]
    total = sum(v for _, v in protos)
    colors = PROTO_COLORS[t]
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"))]
    p.append(f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{HAIR[t]}" '
             f'stroke-opacity="{HAIR_O[t] * .35}" stroke-width="{sw}"/>')
    cum = 0.0
    for i, (name, v) in enumerate(protos):
        frac = v / total
        a0, a1 = cum * 360 + 2.4, (cum + frac) * 360 - 2.4
        p.append(f'<path d="{arc_path(cx, cy, r, a0, a1)}" fill="none" '
                 f'stroke="{colors[i]}" stroke-width="{sw}" pathLength="100" '
                 f'stroke-linecap="butt" class="dd" '
                 f'style="animation-delay:{.15 + i * .25:.2f}s"/>')
        cum += frac
    hl = arc_path(cx, cy, r, 0, 42)
    p.append(f'<path d="{hl}" fill="none" stroke="url(#bg-{t})" '
             f'stroke-opacity=".32" stroke-width="{sw}" class="sp" '
             f'style="transform-origin:{cx}px {cy}px;animation-duration:10s"/>')
    p.append(f'<g class="r d4">'
             + text_el(cx, cy + 2, fmt(total), 42, TEXT[t], weight=800,
                       anchor="middle", cls="bt")
             + micro(cx, cy + 28, "alive", t, anchor="middle")
             + "</g>")
    p.append(micro(560, 100, "protocol mix — measured by real handshake", t))
    p.append(micro(1152, 100, "confirmed type never guessed — first working "
                              "protocol wins", t, anchor="end"))
    for i, (name, v) in enumerate(protos):
        y = 150 + i * 56
        p.append(f'<g class="r d{i + 5}">'
                 + ping(568, y - 6, colors[i], r=6, delay=.3 * i)
                 + text_el(588, y, name.upper(), 19, TEXT[t], weight=700,
                           spacing=1.2)
                 + mono(588, y + 24, f"{fmt(v)} · {v / total * 100:.1f}%", t,
                        size=11.5)
                 + hairline(560, y + 40, 1152, y + 40, t, opacity=HAIR_O[t] * .5)
                 + "</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_architecture(t: str, d: dict) -> str:
    W, H = 1200, 420
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"))]
    p.append(micro(48, 48, "pipeline — seven stages, one entrypoint", t))
    p.append(mono(1152, 48, "python3 -m yuel.pipeline run", t, size=11.5,
                  anchor="end", color=ACC[t], spacing=1.2))
    stages = [("collect", f'{d["sources"]} sources', "public lists, parsed per format"),
              ("normalize", f'{fmt(d["unique"])} unique', "connection-identity dedupe"),
              ("validate", f'{fmt(d["tested"])} tested', "real socks/http handshakes"),
              ("score", f'p50 {d["score_stats"]["p50"]}', "latency · success · freshness"),
              ("geo", f'{d["countries"]} countries', "ip2asn country lookup"),
              ("publish", f'{fmt(d["alive"])} alive', "data/out/ contract · atomic swap")]
    pw, ph, gapx, gapy = 344, 140, 36, 20
    pos = [(48 + (i % 3) * (pw + gapx), 76 + (i // 3) * (ph + gapy))
           for i in range(6)]
    for i, ((stage, value, desc), (x, y)) in enumerate(zip(stages, pos)):
        last = i == len(stages) - 1
        p.append(f'<g class="r d{i + 2}">' + panel(x, y, pw, ph, t))
        if last:
            p.append(f'<rect x="{x + 1.25}" y="{y + 1.25}" width="{pw - 2.5}" '
                     f'height="{ph - 2.5}" rx="15.5" fill="none" '
                     f'stroke="url(#bg-{t})" stroke-width="1.8"/>')
        dotc = f"url(#bg-{t})" if last else ACC2[t]
        p.append(f'<rect x="{x + 26}" y="{y + 24}" width="10" height="10" rx="3" '
                 f'fill="{dotc}" class="gq" style="animation-delay:{i * .3:.1f}s"/>')
        p.append(micro(x + 48, y + 34, stage, t))
        p.append(text_el(x + 26, y + 86, value, 24,
                         f"url(#bg-{t})" if last else TEXT[t], weight=800))
        p.append(mono(x + 26, y + 116, desc, t, size=10.5))
        p.append("</g>")
    row1_c, row2_c, ptop, pbot = 146, 306, 76 + ph, 236
    for a, b in ((0, 1), (1, 2)):
        x1, x2 = pos[a][0] + pw + 6, pos[b][0] - 6
        p.append(hairline(x1, row1_c, x2, row1_c, t, width=1.5, dashed=True,
                          animate=True, opacity=.7))
        p.append(f'<path d="M {x2 - 5} {row1_c - 5} L {x2} {row1_c} '
                 f'L {x2 - 5} {row1_c + 5}" fill="none" stroke="{HAIR[t]}" '
                 f'stroke-opacity=".7" stroke-width="1.5"/>')
    p.append(f'<path d="M {pos[2][0] + pw / 2} {pbot} V {pbot + 10} '
             f'H {pos[3][0] + pw / 2} V {pbot + 20 - 10}" fill="none" '
             f'stroke="{HAIR[t]}" stroke-opacity=".7" stroke-width="1.5" '
             f'stroke-dasharray="3 9" class="mh"/>')
    for a, b in ((3, 4), (4, 5)):
        x1, x2 = pos[a][0] + pw + 6, pos[b][0] - 6
        p.append(hairline(x1, row2_c, x2, row2_c, t, width=1.5, dashed=True,
                          animate=True, opacity=.7))
        p.append(f'<path d="M {x2 - 5} {row2_c - 5} L {x2} {row2_c} '
                 f'L {x2 - 5} {row2_c + 5}" fill="none" stroke="{HAIR[t]}" '
                 f'stroke-opacity=".7" stroke-width="1.5"/>')
    snake = (f"M {pos[0][0] + pw / 2} {row1_c} H {pos[2][0] + pw / 2} "
             f"V {pbot + 10} H {pos[3][0] + pw / 2} V {row2_c} "
             f"H {pos[5][0] + pw / 2}")
    g, body = packet(snake, EMBER, 7.5, 0.0, r=4.5)
    p.append(f"<defs>{g}</defs>{body}")
    for begin in (1.2, 2.4, 3.6):
        g, body = packet(snake, VIOLET if t == "dark" else ACC2, 7.5, begin, r=3)
        p.append(f"<defs>{g}</defs>{body}")
    p.append(f'<g class="r d9">'
             + micro(48, 404, "fail-loud · atomic publish · runs every 30 "
                              "minutes on github actions", t)
             + mono(1152, 404, "exit 0 = every stage green", t, size=10.5,
                    anchor="end", color=ACC2[t])
             + "</g>")
    p.append("</svg>")
    return "\n".join(p)


def card_divider(t: str, d: dict | None = None) -> str:
    W, H = 1200, 64
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"), rx=18)]
    p.append(hairline(300, 32, 900, 32, t, opacity=.35))
    p.append(grad_rect(440, 29.5, 320, 5, 2.5, t, f"bg-{t}"))
    g, body = packet("M 440 32 H 760", ACC[t], 3.4, 0.0, r=4)
    p.append(f"<defs>{g}</defs>{body}")
    p.append(f'<rect x="428" y="26" width="11" height="11" rx="2.5" '
             f'fill="url(#bg-{t})" transform="rotate(45 433.5 31.5)" '
             f'class="gq"/>')
    p.append("</svg>")
    return "\n".join(p)


def _wave_path(y: float, x0: float, amp: float, period: float, w: int) -> str:
    x = x0
    d = [f"M {x} {y}"]
    while x < w + period * 2:
        d.append(f"Q {x + period / 4} {y - amp} {x + period / 2} {y} "
                 f"T {x + period} {y}")
        x += period
    return " ".join(d)


def card_footer(t: str, d: dict | None = None) -> str:
    W, H = 1200, 110
    p = [card_open(t, W, H, brand_grad(t, f"bg-{t}"), rx=18)]
    p.append(hairline(48, 26, 1152, 26, t, opacity=.5, dashed=True, animate=True))
    if d:
        line = f"YUEL · last run {d['stamp']} · regenerated by scripts/render_assets.py"
    else:
        line = "YUEL · plain socks4 / socks5 / http — verified alive every run"
    p.append(f'<g class="r d2">'
             + mono(600, 52, line, t, size=12.5, anchor="middle", color=TEXT[t])
             + micro(600, 76, "artifacts: data/out/all.json · "
                              "by-country/<ISO2>.json · "
                              "by-tier/<tier>.json · run-summary.json",
                     t, anchor="middle")
             + "</g>")
    for cls, y, amp, op, x0 in (("wv", 94, 4, .3, 0), ("wv wb", 100, 5, .2, -60),
                                ("wv wc", 106, 6, .12, -110)):
        stroke = f"url(#bg-{t})" if cls == "wv" else HAIR[t]
        p.append(f'<path d="{_wave_path(y, x0, amp, 130, W)}" fill="none" '
                 f'stroke="{stroke}" stroke-opacity="{op}" stroke-width="2" '
                 f'class="{cls}"/>')
    for cx, cy, dl in ((210, 90, 0), (640, 98, -1.3), (1020, 88, -2.2)):
        p.append(f'<circle cx="{cx}" cy="{cy}" r="2.5" fill="{ACC[t]}" '
                 f'opacity=".6" class="tk" style="animation-delay:{dl}s"/>')
    p.append("</svg>")
    return "\n".join(p)
