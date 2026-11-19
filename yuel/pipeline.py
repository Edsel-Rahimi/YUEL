"""YUEL pipeline orchestrator and CLI entrypoint.

    Usage::

        python -m yuel.pipeline collect   [--sources PATH] [--data-dir PATH]
        python -m yuel.pipeline normalize [--data-dir PATH]
        python -m yuel.pipeline validate  [--data-dir PATH] [--limit N]
                                          [--prefilter-only] [--validate-config PATH]
        python -m yuel.pipeline score     [--data-dir PATH] [--score-config PATH]
        python -m yuel.pipeline run       [--sources PATH] [--data-dir PATH]

    ``run`` executes every implemented stage in order and stops at the first
    failing stage, so a stage failure can never corrupt previously written
    output. Later stages (geo, publish) are appended to the chain as they
    land; see README.md for the architecture and the output file contract.

    Scope (v0.3.0): plain SOCKS4/SOCKS5/HTTP proxies for chaining — stage 1
    parses bare ip:port entries from list sources, stage 2 dedupes them by
    connection identity, stage 3 confirms them with real protocol handshakes.
    """

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__, collect, geo, normalize, publish, score, validate
from . import config as config_mod
from .geo import stage_geo  # noqa: F401 — re-exported for CLI/chain
from .publish import stage_publish  # noqa: F401 — re-exported for CLI/chain
from .score import stage_score  # noqa: F401 — re-exported for CLI/chain
from .stage import StageResult
from .validate import stage_validate  # noqa: F401 — re-exported for CLI/chain

__all__ = ["StageResult", "stage_collect", "stage_normalize", "stage_validate",
           "stage_score", "stage_geo", "stage_publish", "run_pipeline", "main"]


def stage_collect(cfg_path: Path, data_dir: Path, **_: Any) -> StageResult:
    """Stage 1: fetch all configured sources and parse proxy entries."""
    try:
        cfg = config_mod.load_sources(cfg_path)
    except config_mod.ConfigError as exc:
        return StageResult("collect", False, f"config error: {exc}")

    report = collect.run_collect(cfg)
    totals = report["totals"]

    out_dir = data_dir / "collected"
    out_dir.mkdir(parents=True, exist_ok=True)
    proxies_path = out_dir / "proxies_raw.json"
    report_path = out_dir / "collect_report.json"

    proxies_path.write_text(
        json.dumps(report["proxies"], indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_on_disk = {k: v for k, v in report.items() if k != "proxies"}
    report_on_disk["proxies_file"] = proxies_path.name
    report_path.write_text(
        json.dumps(report_on_disk, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    detail = (
        f"{totals['sources_ok']}/{totals['sources_enabled']} sources ok, "
        f"{totals['entries_parsed']} proxies parsed "
        f"({totals['entries_failed']} malformed rejected)"
    )
    return StageResult("collect", True, detail, [proxies_path, report_path])


def stage_normalize(cfg_path: Path, data_dir: Path, **_: Any) -> StageResult:
    """Stage 2: dedupe stage-1 output by connection identity."""
    collected_path = data_dir / "collected" / "proxies_raw.json"
    if not collected_path.exists():
        return StageResult(
            "normalize", False, f"stage-1 output not found: {collected_path} "
            "(run collect first)"
        )
    try:
        proxies = json.loads(collected_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return StageResult("normalize", False, f"cannot read stage-1 output: {exc}")
    if not isinstance(proxies, list):
        return StageResult(
            "normalize", False, f"stage-1 output is not a JSON list: {collected_path}"
        )

    normalized, report = normalize.normalize_proxies(proxies)

    out_dir = data_dir / "normalized"
    out_dir.mkdir(parents=True, exist_ok=True)
    proxies_path = out_dir / "proxies_normalized.json"
    report_path = out_dir / "normalize_report.json"

    proxies_path.write_text(
        json.dumps(normalized, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_on_disk = dict(report)
    report_on_disk["proxies_file"] = proxies_path.name
    report_path.write_text(
        json.dumps(report_on_disk, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    detail = (
        f"{report['output']['proxies_out']} unique proxies "
        f"(from {report['input']['proxies_in']}, "
        f"{report['output']['duplicates_collapsed']} duplicates collapsed, "
        f"{report['input']['invalid_dropped']} invalid dropped)"
    )
    return StageResult("normalize", True, detail, [proxies_path, report_path])


def run_pipeline(
    cfg_path: Path,
    data_dir: Path,
    stage_names: tuple[str, ...],
    stage_kwargs: dict[str, dict[str, Any]] | None = None,
) -> int:
    """Run the selected stages in order; stop at the first failure.

    Each stage writes its own output only after it succeeds, so a failing
    stage leaves any earlier stage's files intact.
    """
    stages = {
        "collect": stage_collect,
        "normalize": stage_normalize,
        "validate": stage_validate,
        "score": stage_score,
        "geo": stage_geo,
        "publish": stage_publish,
    }
    extra = stage_kwargs or {}
    for name in stage_names:
        result = stages[name](cfg_path, data_dir, **extra.get(name, {}))
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
        description="YUEL — automated plain SOCKS4/SOCKS5/HTTP proxy monitoring "
        "pipeline (collect → normalize → validate → score → geo → publish)",
    )
    parser.add_argument("--version", action="version", version=f"yuel {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (
        ("collect", "run stage 1 only (fetch sources and parse proxy entries)"),
        ("normalize", "run stage 2 only (dedupe stage-1 output)"),
        ("validate", "run stage 3 only (TCP prefilter + handshake checks)"),
        ("score", "run stage 4 only (weighted scoring + rolling history)"),
        ("geo", "run stage 5 only (IP→country classification)"),
        ("publish", "run stage 6 only (atomic per-country output contract)"),
        ("run", "run all implemented stages in order"),
    ):
        sub = subparsers.add_parser(name, help=help_text)
        _add_common_args(sub)
        if name == "validate":
            sub.add_argument(
                "--limit",
                type=int,
                default=None,
                help="live-check only the first N prefilter survivors "
                "(demo/small runs; full run by default)",
            )
            sub.add_argument(
                "--prefilter-only",
                action="store_true",
                help="skip the handshake check entirely (TCP reachability only)",
            )
            sub.add_argument(
                "--validate-config",
                default=None,
                help="path to validate config (default: config/validate.json)",
            )
        if name == "score":
            sub.add_argument(
                "--score-config",
                default=None,
                help="path to score config (default: config/score.json)",
            )
        if name == "geo":
            sub.add_argument(
                "--geo-config",
                default=None,
                help="path to geo config (default: config/geo.json)",
            )
        if name == "publish":
            sub.add_argument(
                "--publish-config",
                default=None,
                help="path to publish config (default: config/publish.json)",
            )
    args = parser.parse_args(argv)

    cfg_path = (
        Path(args.sources) if args.sources else config_mod.default_sources_path()
    )
    data_dir = Path(args.data_dir) if args.data_dir else config_mod.default_data_dir()

    stage_chain = {
        "collect": ("collect",),
        "normalize": ("normalize",),
        "validate": ("validate",),
        "score": ("score",),
        "geo": ("geo",),
        "publish": ("publish",),
        "run": ("collect", "normalize", "validate", "score", "geo", "publish"),
    }[args.command]
    stage_kwargs: dict[str, dict[str, Any]] = {}
    if args.command == "validate":
        stage_kwargs["validate"] = {
            "limit": args.limit,
            "prefilter_only": args.prefilter_only,
            "validate_cfg_path": (
                Path(args.validate_config) if args.validate_config else None
            ),
        }
    elif args.command == "score":
        stage_kwargs["score"] = {
            "score_cfg_path": (
                Path(args.score_config) if args.score_config else None
            ),
        }
    elif args.command == "geo":
        stage_kwargs["geo"] = {
            "geo_cfg_path": (
                Path(args.geo_config) if args.geo_config else None
            ),
        }
    elif args.command == "publish":
        stage_kwargs["publish"] = {
            "publish_cfg_path": (
                Path(args.publish_config) if args.publish_config else None
            ),
        }
    elif args.command == "run":
        stage_kwargs["validate"] = {
            "validate_cfg_path": (
                Path(args.validate_config)
                if getattr(args, "validate_config", None)
                else None
            ),
            "score_cfg_path": (
                Path(args.score_config)
                if getattr(args, "score_config", None)
                else None
            ),
            "geo_cfg_path": (
                Path(args.geo_config)
                if getattr(args, "geo_config", None)
                else None
            ),
            "publish_cfg_path": (
                Path(args.publish_config)
                if getattr(args, "publish_config", None)
                else None
            ),
        }
    return run_pipeline(cfg_path, data_dir, stage_chain, stage_kwargs)


if __name__ == "__main__":
    sys.exit(main())
