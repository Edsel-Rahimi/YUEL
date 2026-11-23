#!/usr/bin/env python3
"""Generate the animated README assets under assets/motion/{dark,light}/.

Pure-Python, stdlib only, same convention as render_assets.py: every asset
renders in two color schemes and GitHub picks one per color-scheme via
<picture>.  Animations are plain CSS keyframes inside each SVG (GitHub serves
README images as <img>, which keeps CSS animation alive) and all of them
switch off under prefers-reduced-motion.
"""

from __future__ import annotations

import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "motion"

DARK = {
    "bg0": "#1f1b2b", "bg1": "#2e2a3b", "panel": "#262233",
    "ink": "#f4efe9", "dim": "#a49fb5", "hair": "rgba(244,239,233,0.18)",
    "orange": "#f4732c", "amber": "#f4a12c", "violet": "#8b5cf6",
    "gold": "#e8b23c", "glow": "rgba(244,115,44,0.35)",
    "stroke": "rgba(244,239,233,0.30)",
}
LIGHT = {
    "bg0": "#f6f1e9", "bg1": "#efe7da", "panel": "#fffdf8",
    "ink": "#2b2537", "dim": "#6f687f", "hair": "rgba(43,37,55,0.18)",
    "orange": "#e35a17", "amber": "#d98a10", "violet": "#7c3aed",
    "gold": "#b57e12", "glow": "rgba(227,90,23,0.25)",
    "stroke": "rgba(43,37,55,0.35)",
}

STYLE = """
.pt{animation:pt 8s linear infinite}
@keyframes pt{0%{transform:translateY(0);opacity:0}15%{opacity:.9}100%{transform:translateY(-260px);opacity:0}}
.sweep{animation:sw 6.5s ease-in-out infinite}
@keyframes sw{0%,55%{transform:translateX(-620px) skewX(-18deg)}100%{transform:translateX(1240px) skewX(-18deg)}}
.wv{animation:wv 11s ease-in-out infinite alternate}
.w2{animation-duration:16s}
@keyframes wv{to{transform:translateX(-120px)}}
.spin{transform-box:fill-box;transform-origin:center;animation:sp 7s linear infinite}
.rev{animation-direction:reverse}
@keyframes sp{to{transform:rotate(360deg)}}
.beat{transform-box:fill-box;transform-origin:center;animation:bt 2.4s ease-in-out infinite}
@keyframes bt{0%,100%{transform:scale(1)}12%{transform:scale(1.12)}24%{transform:scale(.98)}36%{transform:scale(1)}}
.glow{animation:gw 3.2s ease-in-out infinite}
@keyframes gw{50%{opacity:.4}}
.dash{stroke-dasharray:7 9;animation:dsh 1.4s linear infinite}
@keyframes dsh{to{stroke-dashoffset:-32}}
.pk{animation:pk 3.2s linear infinite}
.p2{animation-delay:1.1s}.p3{animation-delay:2.2s}
@keyframes pk{0%{transform:translateX(0);opacity:0}8%{opacity:1}92%{opacity:1}100%{transform:translateX(var(--d,880px));opacity:0}}
.pls{transform-box:fill-box;transform-origin:center;animation:pls 2.6s ease-out infinite}
@keyframes pls{0%{transform:scale(.6);opacity:.85}100%{transform:scale(2.4);opacity:0}}
.flt{animation:flt 5.5s ease-in-out infinite}
@keyframes flt{50%{transform:translateY(-6px)}}
.rise{animation:rs .9s cubic-bezier(.2,.7,.2,1) both}
.r2{animation-delay:.15s}.r3{animation-delay:.3s}.r4{animation-delay:.45s}.r5{animation-delay:.6s}.r6{animation-delay:.75s}.r7{animation-delay:.9s}.r8{animation-delay:1.05s}
@keyframes rs{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:translateY(0)}}
.blink{animation:bl 1.1s steps(2) infinite}
@keyframes bl{50%{opacity:0}}
@media (prefers-reduced-motion:reduce){*{animation:none!important}}
"""


def defs(p: dict) -> str:
    return f"""<defs>
<linearGradient id="gTitle" x1="0" y1="0" x2="1" y2="0">
  <stop offset="0" stop-color="{p['orange']}"/><stop offset=".55" stop-color="{p['amber']}"/><stop offset="1" stop-color="{p['violet']}"/>
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
  <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".8"/><stop offset="1" stop-color="#fff" stop-opacity="0"/>
</linearGradient>
<radialGradient id="gOrL" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(60 40) scale(560 320)">
  <stop offset="0" stop-color="{p['orange']}" stop-opacity=".5"/><stop offset="1" stop-color="{p['orange']}" stop-opacity="0"/>
</radialGradient>
<radialGradient id="gOrR" cx="0" cy="0" r="1" gradientUnits="userSpaceOnUse" gradientTransform="translate(1140 40) scale(560 320)">
  <stop offset="0" stop-color="{p['violet']}" stop-opacity=".5"/><stop offset="1" stop-color="{p['violet']}" stop-opacity="0"/>
</radialGradient>
<filter id="fGlow" x="-50%" y="-50%" width="200%" height="200%"><feGaussianBlur stdDeviation="7"/></filter>
</defs>"""


def y_mark(x: int, y: int, s: float, p: dict) -> str:
    """The YUEL brand mark: rounded square + gradient Y, redrawn as vectors."""
    r = 26 * s
    return f"""<g transform="translate({x} {y})">
<rect x="{-46*s:.0f}" y="{-46*s:.0f}" width="{92*s:.0f}" height="{92*s:.0f}" rx="{r:.0f}" fill="{p['panel']}" stroke="{p['hair']}"/>
<path d="M {-17*s:.0f} {-24*s:.0f} L 0 {-2*s:.0f} L {17*s:.0f} {-24*s:.0f} M 0 {-2*s:.0f} L 0 {24*s:.0f}"
  fill="none" stroke="url(#gTitle)" stroke-width="{9*s:.1f}" stroke-linecap="round" stroke-linejoin="round"/>
</g>"""


def hero(p: dict) -> str:
    parts = []
    for i in range(14):  # rising particles
        x = 60 + i * 82 + (i * 37 % 40)
        d = 6 + (i % 5) * 1.3
        parts.append(
            f'<circle cx="{x}" cy="{330 + (i * 53 % 60)}" r="{2 + i % 3}" fill="{p["orange"] if i % 3 else p["violet"]}" '
            f'class="pt" style="animation-duration:{d:.1f}s;animation-delay:{-i * .9:.1f}s"/>'
        )
    waves = "".join(
        f'<path d="M -140 {y} q 75 -26 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0 t 150 0" '
        f'fill="none" stroke="{p["violet"] if k % 2 else p["orange"]}" stroke-opacity="{.22 - k * .05}" stroke-width="1.6" '
        f'class="wv {"w2" if k else ""}" style="animation-duration:{11 + k * 4}s"/>'
        for k, y in enumerate((392, 404, 416))
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="440" viewBox="0 0 1200 440" role="img" aria-label="YUEL — live plain proxies">
<style>{STYLE}</style>
{defs(p)}
<clipPath id="clip"><rect width="1200" height="440"/></clipPath>
<rect width="1200" height="440" fill="url(#gBg)"/>
<rect width="1200" height="440" fill="url(#gOrL)"/>
<rect width="1200" height="440" fill="url(#gOrR)"/>
<g clip-path="url(#clip)">{''.join(parts)}{waves}</g>
<g class="rise">{y_mark(134, 118, 1.0, p)}</g>
<g class="spin rev" opacity=".85"><circle cx="134" cy="118" r="72" fill="none" stroke="{p['hair']}" stroke-width="1.4" stroke-dasharray="10 14"/></g>
<g class="spin"><circle cx="134" cy="118" r="86" fill="none" stroke="{p['hair']}" stroke-width="1" stroke-dasharray="3 9"/></g>
<g class="rise r2" opacity=".9">
  <circle cx="330" cy="86" r="4" fill="{p['orange']}"/><circle cx="330" cy="86" r="4" fill="{p['orange']}" class="pls"/>
</g>
<text x="356" y="92" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="19" letter-spacing="6" fill="{p['dim']}" class="rise r2">PLAIN-PROXY INTELLIGENCE</text>
<g class="rise r3">
  <text x="60" y="240" font-family="Arial,Helvetica,sans-serif" font-weight="900" font-size="128" letter-spacing="10" fill="url(#gTitle)">YUEL</text>
  <g class="sweep" opacity=".9"><rect x="60" y="128" width="70" height="128" fill="url(#gShine)" transform="skewX(-18)"/></g>
</g>
<g class="rise r4">
  <text x="64" y="292" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="21" letter-spacing="3" fill="{p['ink']}">live proxies · scored · tiered · geo-tagged</text>
</g>
<g class="rise r5">
  <text x="64" y="330" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="16" letter-spacing="2" fill="{p['dim']}">socks5 / socks4 / http — refreshed every 30 minutes, straight from CI</text>
</g>
<g class="rise r6">
  <circle cx="74" cy="374" r="6" fill="#6fdc8c"/><circle cx="74" cy="374" r="6" fill="#6fdc8c" class="pls"/>
  <text x="92" y="380" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="16" letter-spacing="2" fill="{p['dim']}">pipeline healthy — last run committed to <tspan fill="{p['orange']}">data/out/</tspan></text>
</g>
<g class="rise r7">
  <rect x="880" y="330" width="260" height="58" rx="29" fill="none" stroke="{p['orange']}" stroke-width="1.6"/>
  <circle cx="912" cy="359" r="7" fill="{p['orange']}" class="beat"/>
  <text x="932" y="366" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="17" letter-spacing="3" fill="{p['orange']}">VIEW LIVE DASHBOARD</text>
</g>
</svg>"""


def divider(p: dict) -> str:
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="30" viewBox="0 0 1200 30" role="img" aria-label="divider">
<style>{STYLE}</style>
{defs(p)}
<rect x="0" y="14" width="1200" height="2" rx="1" fill="url(#gLine)"/>
<g class="pk"><g transform="translate(-10 3)"><path d="M11 0 5 11h5l-1 9 8-12h-5z" fill="{p['amber']}"/></g></g>
<g class="pk p2" style="--d:1000px"><circle cx="0" cy="15" r="4" fill="{p['violet']}"/></g>
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
        nodes.append(f"""<g class="rise r{i + 1}">
  <rect x="{x - 62:.0f}" y="{y - 44}" width="124" height="88" rx="16" fill="{p['panel']}" stroke="{p['orange'] if last else p['hair']}"/>
  <circle cx="{x:.0f}" cy="{y - 44}" r="17" fill="{p['bg1']}" stroke="{p['orange'] if last else p['hair']}"/>
  <text x="{x:.0f}" y="{y - 38}" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="15" fill="{p['orange'] if last else p['ink']}">{i + 1}</text>
  <text x="{x:.0f}" y="{y + 4}" text-anchor="middle" font-family="Arial,Helvetica,sans-serif" font-weight="700" font-size="19" fill="{p['ink']}">{name}</text>
  <text x="{x:.0f}" y="{y + 27}" text-anchor="middle" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="11.5" fill="{p['dim']}">{sub}</text>
</g>""")
        if not last:
            lines.append(
                f'<line x1="{gap * (i + 1) + 62:.0f}" y1="{y}" x2="{gap * (i + 2) - 62:.0f}" y2="{y}" stroke="{p["stroke"]}" stroke-width="1.6" class="dash"/>'
            )
            packets.append(
                f'<g class="pk p{i % 3 + 1}" style="--d:{gap * 2:.0f}px">'
                f'<circle cx="{x + 62:.0f}" cy="{y}" r="4.5" fill="{p["amber"]}"/></g>'
            )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-label="YUEL pipeline — seven stages">
<style>{STYLE}</style>
{defs(p)}
<rect width="{w}" height="{h}" fill="url(#gBg)"/>
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
{y_mark(106, 62, 0.52, p)}
<text x="160" y="56" font-family="Arial,Helvetica,sans-serif" font-weight="900" font-size="44" letter-spacing="8" fill="url(#gTitle)">YUEL</text>
<text x="160" y="86" font-family="ui-monospace,Menlo,Consolas,monospace" font-size="14.5" letter-spacing="1.5" fill="{p['dim']}">free · open · plain-text proxies — built for chaining consumers</text>
<g class="glow"><rect x="160" y="100" width="360" height="2" rx="1" fill="url(#gLine)"/></g>
<circle cx="106" cy="112" r="4" fill="#6fdc8c" class="beat"/>
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
