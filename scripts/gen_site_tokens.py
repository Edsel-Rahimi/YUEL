#!/usr/bin/env python3
"""Generate docs/tokens.css from assets/tokens.json.

tokens.json is the single source of truth for every color / spacing / type
value on the site; this script flattens the design-token file into CSS
custom properties so the site's CSS never invents a value of its own.
Re-run after editing tokens.json:  python3 scripts/gen_site_tokens.py
"""
from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
TOKENS = REPO / "assets" / "tokens.json"
OUT = REPO / "docs" / "tokens.css"

# semantic tokens map 1:1 into the two themes
SEMANTIC = ("bg-canvas", "bg-surface", "bg-raised", "bg-sunken",
            "bg-highlight", "bg-inverse", "text-primary", "text-secondary",
            "text-muted", "text-inverse", "text-on-brand", "border-subtle",
            "border-default", "border-strong")


def value(node) -> str:
    if isinstance(node, dict) and "$value" in node:
        return node["$value"]
    return node


def main() -> None:
    tokens = json.loads(TOKENS.read_text(encoding="utf-8"))
    lines = [
        "/* GENERATED from assets/tokens.json by scripts/gen_site_tokens.py",
        "   — do not edit by hand; edit the token file and regenerate. */",
        ":root {",
    ]
    # flat scales: --yuel-primary-500, --yuel-plum-900, …
    for scale, steps in tokens["color"].items():
        if scale in ("origin", "semantic"):
            continue
        for step, node in steps.items():
            lines.append(f"  --yuel-{scale}-{step}: {value(node)};")
    # origin palette
    for name, node in tokens["color"]["origin"].items():
        lines.append(f"  --yuel-{name.replace('_', '-')}: {value(node)};")
    # gradients (comma values need special handling in var() use — kept whole)
    for name, node in tokens["gradient"].items():
        if isinstance(node, dict):
            lines.append(f"  --yuel-grad-{name}: {value(node)};")
    # typography
    ff = tokens["typography"]["fontFamily"]
    lines.append(f"  --yuel-font-display: {value(ff['display'])};")
    lines.append(f"  --yuel-font-body: {value(ff['body'])};")
    lines.append(f"  --yuel-font-mono: {value(ff['mono'])};")
    for name, style in tokens["typography"]["textStyle"].items():
        style = value(style)
        if not isinstance(style, dict) or "fontSize" not in style:
            continue  # alias/reference entries
        fs = value(style["fontSize"])
        lines.append(f"  --yuel-type-{name}-size: {fs};")
        lines.append(f"  --yuel-type-{name}-lh: {value(style['lineHeight'])};")
        lines.append(f"  --yuel-type-{name}-ls: {value(style['letterSpacing'])};")
        lines.append(f"  --yuel-type-{name}-weight: {value(style['fontWeight'])};")
    # radius + spacing
    for name, node in tokens["radius"].items():
        lines.append(f"  --yuel-radius-{name}: {value(node)}px;")
    for name, node in tokens["spacing"].items():
        lines.append(f"  --yuel-space-{name}: {value(node)}px;")
    lines.append("}")

    # semantic colors per theme (manual override) + OS-preference fallbacks.
    # app.js sets data-theme only when the user manually toggles; without it
    # the :root:not([data-theme]) blocks follow the OS preference.
    def theme_vars(theme: str) -> list[str]:
        out = []
        for key in SEMANTIC:
            out.append(f"  --yuel-{key}: "
                       f"{value(tokens['semantic'][theme][key])};")
        for name, node in tokens["shadow"][theme].items():
            out.append(f"  --yuel-shadow-{name}: {value(node)};")
        return out

    for theme in ("light", "dark"):
        lines.append(f"[data-theme=\"{theme}\"] {{")
        lines.extend(theme_vars(theme))
        lines.append("}")
    for theme in ("light", "dark"):
        lines.append(f"@media (prefers-color-scheme: {theme}) {{")
        lines.append("  :root:not([data-theme]) {")
        lines.extend(theme_vars(theme))
        lines.append("  }")
        lines.append("}")

    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {OUT} ({len(lines)} lines)")


if __name__ == "__main__":
    main()
