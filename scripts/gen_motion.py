#!/usr/bin/env python3
"""Generate the animated README assets under assets/motion/{dark,light}/.

Pure-Python, stdlib only, same convention as render_assets.py: every asset
renders in two color schemes and GitHub picks one per color-scheme via
<picture>.  Animations are CSS keyframes + SMIL inside each SVG (GitHub serves
README images as <img>, which keeps both alive; the brand logo is embedded as
a base64 data URI because <img>-loaded SVGs cannot load external files) and
all motion switches off under prefers-reduced-motion.
"""

from __future__ import annotations

import base64
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "motion"

LOGO_COLOR = base64.b64encode((ROOT / "assets" / "brand" / "yuel-mark-color.png").read_bytes()).decode()
LOGO_WHITE = base64.b64encode((ROOT / "assets" / "brand" / "yuel-mark-white.png").read_bytes()).decode()

DARK = {
    "bg0": "#1f1b2b", "bg1": "#2e2a3b", "panel": "#262233",
    "ink": "#f4efe9", "dim": "#a49fb5", "hair": "rgba(244,239,233,0.18)",
    "orange": "#f4732c", "amber": "#f4a12c", "violet": "#8b5cf6",
    "glow": "rgba(244,115,44,0.45)", "vglow": "rgba(139,92,246,0.35)",
    "stroke": "rgba(244,239,233,0.30)", "logo": LOGO_COLOR,
}
LIGHT = {
    "bg0": "#f6f1e9", "bg1": "#efe7da", "panel": "#fffdf8",
    "ink": "#2b2537", "dim": "#6f687f", "hair": "rgba(43,37,55,0.18)",
    "orange": "#e35a17", "amber": "#d98a10", "violet": "#7c3aed",
    "glow": "rgba(227,90,23,0.30)", "vglow": "rgba(124,58,237,0.25)",
    "stroke": "rgba(43,37,55,0.35)", "logo": LOGO_WHITE,
}

# Rich keyframe library: orbit, breathe, scan, shimmer, waves, blobs…
STYLE = """
.pt{animation:pt 8s linear infinite}
@keyframes pt{0%{transform:translateY(0);opacity:0}15%{opacity:.9}100%{transform:translateY(-300px);opacity:0}}
.orb{transform-box:fill-box;transform-origin:center;animation:orb 9s linear infinite}
.o2{animation-duration:14s;animation-direction:reverse}
.o3{animation-duration:22s}
@keyframes orb{to{transform:rotate(360deg)}}
.breathe{transform-box:fill-box;transform-origin:center;animation:br 4.2s ease-in-out infinite}
@keyframes br{0%,100%{transform:scale(1);opacity:1}50%{transform:scale(1.05);opacity:.85}}
.sweep{animation:sw 6.5s ease-in-out infinite}
@keyframes sw{0%,58%{transform:translateX(-640px) skewX(-18deg)}100%{transform:translateX(1300px) skewX(-18deg)}}
.scan{animation:sc 7s cubic-bezier(.4,0,.6,1) infinite}
@keyframes sc{0%{transform:translateY(-10px);opacity:0}12%{opacity:1}88%{opacity:1}100%{transform:translateY(300px);opacity:0}}
.wv{animation:wv 11s ease-in-out infinite alternate}
.w2{animation-duration:16s}.w3{animation-duration:23s}
@keyframes wv{to{transform:translateX(-150px)}}
.spin{transform-box:fill-box;transform-origin:center;animation:sp 7s linear infinite}
.rev{animation-direction:reverse}
@keyframes sp{to{transform:rotate(360deg)}}
.beat{transform-box:fill-box;transform-origin:center;animation:bt 2.4s ease-in-out infinite}
@keyframes bt{0%,100%{transform:scale(1)}12%{transform:scale(1.16)}24%{transform:scale(.97)}36%{transform:scale(1)}}
.glow{animation:gw 3.2s ease-in-out infinite}
@keyframes gw{50%{opacity:.35}}
.dash{stroke-dasharray:7 9;animation:dsh 1.4s linear infinite}
@keyframes dsh{to{stroke-dashoffset:-32}}
.pk{animation:pk 3.2s linear infinite}
.p2{animation-delay:1.1s}.p3{animation-delay:2.2s}
@keyframes pk{0%{transform:translateX(0);opacity:0}8%{opacity:1}92%{opacity:1}100%{transform:translateX(var(--d,880px));opacity:0}}
.pls{transform-box:fill-box;transform-origin:center;animation:pls 2.6s ease-out infinite}
@keyframes pls{0%{transform:scale(.6);opacity:.85}100%{transform:scale(2.6);opacity:0}}
.flt{animation:flt 5.5s ease-in-out infinite}
.f2{animation-delay:-2.7s}
@keyframes flt{50%{transform:translateY(-9px)}}
.rise{animation:rs .9s cubic-bezier(.2,.7,.2,1) both}
.r2{animation-delay:.15s}.r3{animation-delay:.3s}.r4{animation-delay:.45s}.r5{animation-delay:.6s}.r6{animation-delay:.75s}.r7{animation-delay:.9s}.r8{animation-delay:1.05s}
@keyframes rs{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}
.blink{animation:bl 1.1s steps(2) infinite}
@keyframes bl{50%{opacity:0}}
.grid{animation:gd 3.4s linear infinite}
@keyframes gd{to{stroke-dashoffset:-44}}
.hue{animation:hue 9s linear infinite}
@keyframes hue{0%,100%{filter:hue-rotate(0deg)}50%{filter:hue-rotate(18deg)}}
.skew{animation:skw 12s ease-in-out infinite alternate}
@keyframes skw{from{transform:translateX(0)}to{transform:translateX(-360px)}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def defs(p: dict) -> str:
    return f"""<defs>
<linearGradient id="gTitle" x1="0" y1="0" x2="1" y2="1">
  <stop offset="0" stop-color="{p['orange']}">
    <animate attributeName="stop-color" values="{p['orange']};{p['amber']};{p['violet']};{p['orange']}" dur="9s" repeatCount="indefinite"/>
  </stop>
  <stop offset=".55" stop-color="{p['amber']}">
    <animate attributeName="stop-color" values="{p['amber']};{p['violet']};{p['orange']};{p['amber']}" dur="9s" repeatCount="indefinite"/>
  </stop>
  <stop offset="1" stop-color="{p['violet']}">
    <animate attributeName="stop-color" values="{p['violet']};{p['orange']};{p['amber']};{p['violet']}" dur="9s" repeatCount="indefinite"/>
  </stop>
</linearGradient>
<linearGradient id="gLine" x1="0" y1="0" x2="1" y2="0">
  <stop offset="0" stop-color="{p['orange']}" stop-opacity="0"/>
  <stop offset=".3" stop-color="{p['orange']}"/><stop offset=".55" stop-color="{p['amber']}"/>
  <stop offset=".8" stop-color="{p['violet']}"/><stop offset="1" stop-color="{p['violet']}" stop-opacity="0"/>
</linearGradient>
<linearGradient id="gBg" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="{p['bg0']}"/><stop offset=".6" stop-color="{p['bg1']}"/><stop offset="1" stop-color="{p['bg0']}"/>
</linearGradient>
<linearGradient id="gShine" x1="0" y1="0" x2="1" y2="0">
  <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".85"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
</linearGradient>
<linearGradient id="gBeam" x1="0" y1="0" x2="0" y2="1">
  <stop offset="0" stop-color="{p['orange']}" stop-opacity="0"/>
  <stop offset=".5" stop-color="{p['orange']}" stop-opacity=".55"/>
  <stop offset="1" stop-color="{p['orange']}" stop-opacity="0"/>
</linearGradient>
<radialGradient id="gOrL" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(60 40) scale(620 360)">
  <stop offset="0" stop-color="{p['orange']}" stop-opacity=".5"><animate attributeName="stop-opacity" values=".5;.9;.5" dur="6s" repeatCount="indefinite"/></stop>
  <stop offset="1" stop-color="{p['orange']}" stop-opacity="0"/>
</radialGradient>
<radialGradient id="gOrR" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1140 40) scale(620 360)">
  <stop offset="0" stop-color="{p['violet']}" stop-opacity=".5"><animate attributeName="stop-opacity" values=".5;.9;.5" dur="7.5s" repeatCount="indefinite"/></stop>
  <stop offset="1" stop-color="{p['violet']}" stop-opacity="0"/>
</radialGradient>
<filter id="fGlow" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="6"/></filter>
<filter id="fSoft" x="-60%" y="-60%" width="220%" height="220%"><feGaussianBlur stdDeviation="18"/></filter>
</defs>"""


def logo(x: int, y: int, size: int, p: dict) -> str:
    """The real brand mark, embedded so it renders inside <img>-served SVG."""
    return (f'<image x="{x}" y="{y}" width="{size}" height="{size}" '
            f'href="data:image/png;base64,{p["logo"]}" class="breathe"/>')


def orbitals(cx: int, cy: int, p: dict) -> str:
    """Nested rotating ring systems around the logo — the signature motion."""
    ring = ""
    for k, (r, dur, dots, cls) in enumerate((
        (74, 7, 5, "orb"), (92, 12, 9, "orb o2"), (112, 19, 3, "orb o3"),
    )):
        pts = "".join(
            f'<circle cx="{cx + r}" cy="{cy}" r="{4 - k // 2}" fill="{p["amber"] if j % 2 else p["orange"]}" filter="url(#fGlow)" opacity="{.9 - k * .2}"/>'
            for j in range(dots)
        )
        ring += (f'<g class="{cls}" style="animation-duration:{dur}s">{pts}</g>'
                 f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{p["hair"]}" stroke-width="1.2" stroke-dasharray="{3 + k * 2} {9 + k * 3}"/>')
    return ring


def hero(p: dict) -> str:
    parts = []
    for i in range(16):  # rising particles
        x = 60 + i * 72 + (i * 37 % 40)
        d = 6 + (i % 5) * 1.3
        parts.append(
            f'<circle cx="{x}" cy="{350 + (i * 53 % 60)}" r="{2 + i % 3}" fill="{p["orange"] if i % 3 else p["violet"]}" '
            f'class="pt" style="animation-duration:{d:.1f}s;animation-delay:{-i * .9:.1f}s"/>'
        )
    waves = "".join(
        f'<path d="M -160 {y} q 75 -26 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0" '
        f'fill="none" stroke="{p["violet"] if k % 2 else p["orange"]}" stroke-opacity="{.22 - k * .05}" stroke-width="1.6" '
        f'class="wv {"w2" if k == 1 else ("w3" if k == 2 else "")}" style="animation-duration:{11 + k * 4}s"/>'
        for k, y in enumerate((396, 408, 420))
    )
    blobs = f"""<circle cx="150" cy="140" r="110" fill="{p['orange']}" opacity=".16" filter="url(#fSoft)" class="flt"/>
<circle cx="1050" cy="300" r="130" fill="{p['violet']}" opacity=".16" filter="url(#fSoft)" class="flt f2"/>"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="440" viewBox="0 0 1200 440" role="img" aria-label="YUEL — live plain proxies">
<style>{STYLE}</style>
{defs(p)}
<clipPath id="clip"><rect width="1200" height="440"/></clipPath>
<rect width="1200" height="440" fill="url(#gBg)"/>
<rect width="1200" height="440" fill="url(#gOrL)"/>
<rect width="1200" height="440" fill="url(#gOrR)"/>
{blobs}
<g clip-path="url(#clip)">{''.join(parts)}{waves}</g>
<g class="rise">
  <circle cx="134" cy="118" r="120" fill="{p['panel']}" opacity=".65"/>
  {orbitals(134, 118, p)}
  {logo(88, 72, 92, p)}
</g>
<g class="rise r2" opacity=".9">
  <circle cx="300" cy="80" r="4" fill="{p['orange']}"/><circle cx="300" cy="80" r="4" fill="{p['orange']}" class="pls"/>
</g>
<text x="324" y="86" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="19" letter-spacing="6" fill="{p['dim']}" class="rise r2">PLAIN-PROXY INTELLIGENCE</text>
<g class="rise r3">
  <text x="60" y="252" font-family="Arial,Helvetica,sans-serif" font-weight="900" font-size="124" letter-spacing="10" fill="url(#gTitle)" class="hue">YUEL</text>
  <g class="sweep" opacity=".9"><rect x="60" y="140" width="70" height="124" fill="url(#gShine)" transform="skewX(-18)"/></g>
</g>
<g class="rise r4">
  <text x="64" y="300" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="21" letter-spacing="3" fill="{p['ink']}">live proxies · scored · tiered · geo-tagged</text>
</g>
<g class="rise r5">
  <text x="64" y="338" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="16" letter-spacing="2" fill="{p['dim']}">socks5 / socks4 / http — refreshed every 30 minutes, straight from CI</text>
</g>
<g class="rise r6">
  <circle cx="74" cy="378" r="6" fill="#6fdc8c"/><circle cx="74" cy="378" r="6" fill="#6fdc8c" class="pls"/>
  <text x="92" y="384" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="16" letter-spacing="2" fill="{p['dim']}">pipeline healthy — last run committed to <tspan fill="{p['orange']}">data/out/</tspan></text>
</g>
<g class="rise r7">
  <rect x="872" y="330" width="272" height="60" rx="30" fill="none" stroke="{p['orange']}" stroke-width="1.6"/>
  <rect x="872" y="330" width="272" height="60" rx="30" fill="none" stroke="{p['orange']}" stroke-width="1.6" class="breathe" opacity=".5"/>
  <circle cx="906" cy="360" r="7" fill="{p['orange']}" class="beat"/>
  <text x="926" y="367" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="17" letter-spacing="3" fill="{p['orange']}">VIEW LIVE DASHBOARD</text>
</g>
<rect x="0" y="60" width="1200" height="3" fill="url(#gBeam)" class="scan" clip-path="url(#clip)"/>
</svg>"""


def divider(p: dict) -> str:
    bolts = "".join(
        f'<g class="pk p{i % 3 + 1}" style="--d:1180px"><g transform="translate({-20 - i * 60} 3)">'
        f'<path d="M11 0 5 11h5l-1 9 8-12h-5z" fill="{p["amber"]}" filter="url(#fGlow)"/></g></g>'
        for i in range(3)
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="34" viewBox="0 0 1200 34" role="img" aria-label="divider">
<style>{STYLE}</style>
{defs(p)}
<rect x="0" y="16" width="1200" height="2" rx="1" fill="url(#gLine)"/>
<g class="skew" opacity=".8"><rect x="0" y="14" width="340" height="6" rx="3" fill="url(#gShine)" opacity=".25"/></g>
{bolts}
<circle cx="0" cy="17" r="4" fill="{p['violet']}" class="pk p2" style="--d:1200px"/>
</svg>"""


FLOW = [
    ("collect", "fetch + parse"),
    ("normalize", "identity dedupe"),
    ("validate", "real handshakes"),
    ("score", "weighted tiers"),
    ("geo", "IP → country"),
    ("publish", "data/out/"),
    ("automate", "CI every 30m"),
]


def flow(p: dict) -> str:
    w, h = 1200, 300
    nodes = []
    packets = []
    lines = []
    gap = w / (len(FLOW) + 1)
    for i, (name, sub) in enumerate(FLOW):
        x = gap * (i + 1)
        y = 128
        last = i == len(FLOW) - 1
        accent = p["orange"] if last else p["hair"]
        spinner = (f'<g class="spin" style="animation-duration:3.4s"><circle cx="{x:.0f}" cy="{y - 44}" r="11" fill="none" '
                   f'stroke="{p["orange"]}" stroke-width="2.4" stroke-dasharray="14 22"/></g>') if last else ""
        nodes.append(f"""<g class="rise r{i + 1}">
  <rect x="{x - 62:.0f}" y="{y - 44}" width="124" height="88" rx="16" fill="{p['panel']}" stroke="{accent}"/>
  <circle cx="{x:.0f}" cy="{y - 44}" r="17" fill="{p['bg1']}" stroke="{accent}"/>
  <text x="{x:.0f}" y="{y - 38}" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="15" fill="{p['orange'] if last else p['ink']}">{i + 1}</text>
  <text x="{x:.0f}" y="{y + 4}" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-weight="700" font-size="19" fill="{p['ink']}">{name}</text>
  <text x="{x:.0f}" y="{y + 27}" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="11.5" fill="{p['dim']}">{sub}</text>
  {spinner}
</g>""")
        if not last:
            lines.append(
                f'<line x1="{gap * (i + 1) + 62:.0f}" y1="{y}" x2="{gap * (i + 2) - 62:.0f}" y2="{y}" stroke="{p["stroke"]}" stroke-width="1.6" class="dash"/>'
            )
            packets.append(
                f'<g class="pk p{i % 3 + 1}" style="--d:{gap * 2:.0f}px">'
                f'<circle cx="{x + 62:.0f}" cy="{y}" r="4.5" fill="{p["amber"]}" filter="url(#fGlow)"/></g>'
            )
    glowline = f"""<g class="glow"><rect x="0" y="126" width="{w}" height="4" fill="{p['orange']}" opacity=".12" filter="url(#fSoft)"/></g>"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="YUEL pipeline — seven stages">
<style>{STYLE}</style>
{defs(p)}
<rect width="{w}" height="{h}" fill="url(#gBg)"/>
{glowline}
{''.join(lines)}
{''.join(nodes)}
{''.join(packets)}
<text x="{w / 2:.0f}" y="248" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="15" letter-spacing="2" fill="{p['dim']}">collect → normalize → validate → score → geo → publish → automate · <tspan fill="{p['orange']}">every stage verified against live data</tspan><tspan class="blink"> ▌</tspan></text>
</svg>"""


def footer(p: dict) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="150" viewBox="0 0 1200 150" role="img" aria-label="YUEL footer">
<style>{STYLE}</style>
{defs(p)}
<rect width="1200" height="150" fill="url(#gBg)"/>
{logo(76, 43, 56, p)}
<text x="150" y="56" font-family="Arial,Helvetica,sans-serif" font-weight="900" font-size="44" letter-spacing="8" fill="url(#gTitle)">YUEL</text>
<text x="150" y="86" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="14.5" letter-spacing="1.5" fill="{p['dim']}">free · open · plain-text proxies — built for chaining consumers</text>
<g class="glow"><rect x="150" y="100" width="360" height="2" rx="1" fill="url(#gLine)"/></g>
<g class="pk" style="--d:360px"><circle cx="150" cy="101" r="3.5" fill="{p['amber']}"/></g>
<circle cx="104" cy="112" r="4" fill="#6fdc8c" class="beat"/>
<text x="1066" y="86" text-anchor="end" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="13" letter-spacing="1" fill="{p['dim']}">MIT licensed · runs on GitHub Actions</text>
</svg>"""


ASSETS = {"hero": hero, "divider": divider, "flow": flow, "footer": footer}


def main() -> None:
    for variant, palette in (("dark", DARK), ("light", LIGHT)):
        d = OUT / variant
        d.mkdir(parents=True, exist_ok=True)
        for name, fn in ASSETS.items():
            (d / f"{name}.svg").write_text(fn(palette), encoding="utf-8")
        print(f"wrote {len(ASSETS)} assets -> {d}")


if __name__ == "__main__":
    main()
