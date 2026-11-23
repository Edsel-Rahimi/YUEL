#!/usr/bin/env python3
"""Regenerate the animated motion set under assets/motion/{light,dark}/.

The v6 motion set (hero / divider / footer) is number-free brand art — it is
deterministic and never goes stale, so CI does not need to re-commit it. This
wrapper exists so the old entrypoint keeps working; all the real drawing code
lives in scripts/render_assets.py + scripts/yuel_design.py now.
"""

import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.exit(subprocess.call(
    [sys.executable, str(ROOT / "scripts" / "render_assets.py"), "--motion"]))
