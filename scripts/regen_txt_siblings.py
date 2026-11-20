#!/usr/bin/env python3
"""Backfill plain-text siblings into an already-published data/out/.

Uses exactly the same writer the publish stage uses (write_txt_files), fed
from the committed JSON files, so a repo upgraded mid-history gets the txt
contract without re-running the pipeline. CI never needs this (stage 6
writes txt into staging); it exists for local/backfill runs and as the
executable proof that the two formats agree.

Usage: python3 scripts/regen_txt_siblings.py [--data-dir data]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from yuel.publish import write_txt_files  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()
    out = Path(args.data_dir) / "out"
    summary = json.loads((out / "run-summary.json").read_text(encoding="utf-8"))
    by_country = {
        p.stem: json.loads(p.read_text(encoding="utf-8"))
        for p in sorted((out / "by-country").glob("*.json"))
    }
    by_tier = {
        tier: json.loads((out / "by-tier" / f"{tier}.json").read_text(encoding="utf-8"))
        for tier in ("gold", "silver", "bronze")
    }
    n = write_txt_files(out, by_country, by_tier, summary["generated_utc"])
    print(f"wrote {n} txt siblings under {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
