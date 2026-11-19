"""YUEL pipeline orchestrator and CLI entrypoint.

Usage::

    python -m yuel.pipeline collect   [--sources PATH] [--data-dir PATH]
    python -m yuel.pipeline normalize [--data-dir PATH]
    python -m yuel.pipeline run       [--sources PATH] [--data-dir PATH]

``run`` executes every implemented stage in order and stops at the first
failing stage, so a stage failure can never corrupt previously written
output. Later stages (validate, score, geo, publish) are appended to the
chain as they land; see README.md for the architecture and the output file
contract.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from . import __version__, collect, normalize
from . import config as config_mod


@dataclass
class StageResult:
    name: str
    ok: bool
    detail: str
    outputs: list[Path] = field(default_factory=list)


def stage_collect(cfg_path: Path, data_dir: Path) -> StageResult:
    """Stage 1: fetch all configured sources and extract endpoints."""
    try:
        cfg = config_mod.load_sources(cfg_path)
    except config_mod.ConfigError as exc:
        return StageResult("collect", False, f"config error: {exc}")

    report = collect.run_collect(cfg)
    totals = report["totals"]

    out_dir = data_dir / "collected"
    out_dir.mkdir(parents=True, exist_ok=True)
    endpoints_path = out_dir / "endpoints_raw.json"
    report_path = out_dir / "collect_report.json"

    endpoints_path.write_text(
        json.dumps(report["endpoints"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_on_disk = {k: v for k, v in report.items() if k != "endpoints"}
    report_on_disk["endpoints_file"] = endpoints_path.name
    report_path.write_text(
        json.dumps(report_on_disk, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    detail = (
        f"{totals['sources_ok']}/{totals['sources_enabled']} sources ok, "
        f"{totals['endpoints_parsed']} endpoints parsed "
        f"({totals['endpoints_failed']} malformed rejected)"
    )
    return StageResult("collect", True, detail, [endpoints_path, report_path])


def stage_normalize(cfg_path: Path, data_dir: Path) -> StageResult:
    """Stage 2: dedupe stage-1 output by connection identity."""
    collected_path = data_dir / "collected" / "endpoints_raw.json"
    if not collected_path.exists():
        return StageResult(
            "normalize", False, f"stage-1 output not found: {collected_path} "
            "(run collect first)"
        )
    try:
        endpoints = json.loads(collected_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return StageResult("normalize", False, f"cannot read stage-1 output: {exc}")
    if not isinstance(endpoints, list):
        return StageResult(
            "normalize", False, f"stage-1 output is not a JSON list: {collected_path}"
        )

    normalized, report = normalize.normalize_endpoints(endpoints)

    out_dir = data_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    endpoints_path = out_dir / "endpoints_normalized.json"
    report_path = out_dir / "normalize_report.json"

    endpoints_path.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_on_disk = dict(report)
    report_on_disk["endpoints_file"] = endpoints_path.name
    report_path.write_text(
        json.dumps(report_on_disk, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    detail = (
        f"{report['output']['endpoints_out']} unique endpoints "
        f"(from {report['input']['endpoints_in']}, "
        f"{report['output']['duplicates_collapsed']} duplicates collapsed, "
        f"{report['input']['invalid_dropped']} invalid dropped)"
    )
    return StageResult("normalize", True, detail, [endpoints_path, report_path])


def run_pipeline(cfg_path: Path, data_dir: Path, stage_names: tuple[str, ...]) -> int:
    """Run the selected stages in order; stop at the first failure.

    Each stage writes its own output only after it succeeds, so a failing
    stage leaves any earlier stage's files intact.
    """
    stages = {
        "collect": stage_collect,
        "normalize": stage_normalize,
    }
    for name in stage_names:
        result = stages[name](cfg_path, data_dir)
        tag = "OK" if result.ok else "FAIL"
        print(f"[{tag}] {result.name}: {result.detail}")
        for output in result.outputs:
            print(f"       wrote {output}")
        if not result.ok:
            print(f"[run] stopped at stage '{result.name}'")
            return 1
    return 0


def _add_common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sources",
        default=None,
        help="path to sources JSON (default: config/sources.json, "
        "override with $YUEL_SOURCES)",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="directory for stage output (default: data/, "
        "override with $YUEL_DATA_DIR)",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="yuel",
        description="YUEL — automated public proxy/VPN endpoint monitoring pipeline",
    )
    parser.add_argument("--version", action="version", version=f"yuel {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("collect", "run stage 1 only (fetch sources and extract endpoints)"),
        ("normalize", "run stage 2 only (dedupe stage-1 output)"),
        ("run", "run all implemented stages in order"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        _add_common_args(sub)
    args = parser.parse_args(argv)

    cfg_path = (
        Path(args.sources) if args.sources else config_mod.default_sources_path()
    )
    data_dir = Path(args.data_dir) if args.data_dir else config_mod.default_data_dir()

    stage_chain = {
        "collect": ("collect",),
        "normalize": ("normalize",),
        "run": ("collect", "normalize"),
    }[args.command]
    return run_pipeline(cfg_path, data_dir, stage_chain)


if __name__ == "__main__":
    sys.exit(main())
