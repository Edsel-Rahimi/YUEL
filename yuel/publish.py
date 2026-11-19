"""Stage 6 — publish: the stable output contract for proxy-chaining consumers.

Input:  ``data/geo/proxies_geo.json`` (stage 5 output) plus the earlier
        stages' reports for run totals.
Output: ``data/out/`` — the ONLY directory downstream consumers should read:

    all.json                       every alive proxy, all tiers, all countries
    by-country/<ISO2>.json         one JSON array per country, tier != excluded
    by-country/unclassified.json   same shape; may be an empty array
    run-summary.json               counts for health-checking without parsing

Record shape (plain proxies ONLY — never a vmess/vless/... tunnel feed):

    {"ip": "1.2.3.4", "port": 8080, "type": "socks5", "user": "...",
     "pass": "...", "country": "IT", "score": 87.2, "tier": "gold",
     "last_checked": "2026-11-19T12:00:00+00:00",
     "consecutive_successes": 4, "consecutive_failures": 0}

``user``/``pass`` are present only when the proxy has credentials. ``tier``
keeps the stage-4 verdict; per-country files carry tier != ``excluded`` while
``all.json`` deliberately includes everything (documented interpretation of
"all tiers") so consumers can apply their own thresholds.

**Atomicity contract:** a failed or partial run never overwrites
previously-good output. The stage builds everything in a staging directory
(``data/.out_staging``), validates it (every file parses, ``all.json`` and
per-country files non-empty), and only then swaps it into ``data/out/`` with
rollback on failure. A run with **zero alive proxies** refuses to publish at
all (previous output stays intact) — an empty fleet is treated as a pipeline
health problem, not as fresh data.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .stage import StageResult

DEFAULT_CONFIG = {
    "schema_version": 1,
    "out_dir": "out",  # relative to the data dir → data/out/
}

STAGING_DIRNAME = ".out_staging"
PREVIOUS_DIRNAME = ".out_prev"


class PublishError(RuntimeError):
    """Publish validation failure; previous output stays untouched."""


def default_publish_config_path() -> Path:
    """Publish config location: $YUEL_PUBLISH_CONFIG, else
    <repo>/config/publish.json."""
    env = os.environ.get("YUEL_PUBLISH_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "config" / "publish.json"


def load_publish_config(path: Path | None) -> dict[str, Any]:
    """Load config/publish.json over built-in defaults."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None and Path(path).exists():
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise PublishError(f"cannot read {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise PublishError(f"{path} is not a JSON object")
        if loaded.get("schema_version") != 1:
            raise PublishError(
                f"unsupported schema_version: {loaded.get('schema_version')!r}"
            )
        if "out_dir" in loaded:
            config["out_dir"] = loaded["out_dir"]
    out_dir = str(config["out_dir"])
    if not out_dir or out_dir.startswith(("/", "..")):
        raise PublishError(f"out_dir must be a relative path inside data/: {out_dir!r}")
    return config


# ---------------------------------------------------------------------------
# record building (the documented contract)
# ---------------------------------------------------------------------------


def build_record(entry: dict[str, Any]) -> dict[str, Any]:
    """One published record; matches the README contract exactly."""
    check = entry.get("check") or {}
    score = entry.get("score") or {}
    stats = entry.get("history") or {}
    record: dict[str, Any] = {
        "ip": entry["host"],
        "port": entry["port"],
        "type": check.get("type_confirmed"),
        "country": entry.get("country") or "unclassified",
        "score": score.get("total"),
        "tier": score.get("tier") or "excluded",
        "last_checked": check.get("checked_utc"),
        "consecutive_successes": int(stats.get("consecutive_successes") or 0),
        "consecutive_failures": int(stats.get("consecutive_failures") or 0),
    }
    if entry.get("username"):
        record["user"] = entry["username"]
    if entry.get("password"):
        record["pass"] = entry["password"]
    return record


def _record_sort_key(record: dict[str, Any]) -> tuple:
    score = record["score"] if record["score"] is not None else -1
    return (-(score if isinstance(score, (int, float)) else -1),
            record["ip"], record["port"])


def _read_report_totals(data_dir: Path) -> dict[str, Any]:
    """Pull health-check counts from earlier stages' reports (None if absent —
    stages can be run individually without the whole chain)."""

    def _load(path: Path) -> dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    collect = _load(data_dir / "collected" / "collect_report.json")
    normalize = _load(data_dir / "normalized" / "normalize_report.json")
    validate = _load(data_dir / "validated" / "validate_report.json")
    handshake = validate.get("handshake_check") or {}
    return {
        "sources_used": (collect.get("totals") or {}).get("sources_ok"),
        "candidates_collected": (collect.get("totals") or {}).get("entries_parsed"),
        "unique_normalized": (normalize.get("output") or {}).get("proxies_out"),
        "tested": handshake.get("tested"),
        "validated_alive": handshake.get("alive"),
    }


# ---------------------------------------------------------------------------
# atomic publish machinery
# ---------------------------------------------------------------------------


def _validate_staging(staging_dir: Path, expected_records: int) -> int:
    """Validate the staged output before it replaces data/out/. Raises
    PublishError on anything that would corrupt the contract."""
    all_path = staging_dir / "all.json"
    if not all_path.exists():
        raise PublishError("staging output missing all.json")
    try:
        all_records = json.loads(all_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise PublishError(f"staged all.json is not valid JSON: {exc}") from exc
    if not isinstance(all_records, list) or len(all_records) != expected_records:
        raise PublishError(
            f"staged all.json has {len(all_records) if isinstance(all_records, list) else 'non-list'} "
            f"records; expected {expected_records}"
        )
    if not all_records:
        raise PublishError("staged all.json is empty")

    unclassified_path = staging_dir / "by-country" / "unclassified.json"
    if not unclassified_path.exists():
        raise PublishError("staging output missing by-country/unclassified.json")

    country_files = sorted((staging_dir / "by-country").glob("*.json"))
    total_country_records = 0
    for path in country_files:
        try:
            records = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PublishError(f"staged {path.name} is not valid JSON: {exc}") from exc
        if not isinstance(records, list):
            raise PublishError(f"staged {path.name} is not a JSON array")
        # contract exception: unclassified.json always exists and may be an
        # empty array; every real country file must be non-empty
        if not records and path.name != "unclassified.json":
            raise PublishError(f"staged {path.name} is empty (must not publish empty)")
        total_country_records += len(records)
    try:
        json.loads((staging_dir / "run-summary.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishError(f"staged run-summary.json unusable: {exc}") from exc
    return total_country_records


def _swap_into_place(staging_dir: Path, out_dir: Path) -> None:
    """Replace out_dir with staging_dir atomically-ish, with rollback."""
    previous = out_dir.parent / PREVIOUS_DIRNAME
    if previous.exists():
        shutil.rmtree(previous)
    had_previous = out_dir.exists()
    if had_previous:
        out_dir.rename(previous)
    try:
        staging_dir.rename(out_dir)
    except OSError:
        if had_previous and not out_dir.exists():
            previous.rename(out_dir)  # rollback: keep the good old output
        raise
    if had_previous:
        shutil.rmtree(previous)


# ---------------------------------------------------------------------------
# stage entrypoint
# ---------------------------------------------------------------------------


def stage_publish(
    cfg_path: Path,
    data_dir: Path,
    publish_cfg_path: Path | None = None,
    **_: Any,
) -> StageResult:
    """Stage 6: write the stable per-country/all/summary output atomically."""
    geo_path = data_dir / "geo" / "proxies_geo.json"
    if not geo_path.exists():
        return StageResult(
            "publish",
            False,
            f"stage-5 output not found: {geo_path} (run geo first)",
        )
    try:
        proxies = json.loads(geo_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return StageResult("publish", False, f"cannot read stage-5 output: {exc}")
    if not isinstance(proxies, list):
        return StageResult("publish", False, "stage-5 output is not a JSON list")

    try:
        config = load_publish_config(publish_cfg_path or default_publish_config_path())
    except PublishError as exc:
        return StageResult("publish", False, f"config error: {exc}")

    if not proxies:
        return StageResult(
            "publish",
            False,
            "refusing to publish: zero alive proxies this run "
            "(previous published output left intact)",
        )

    now_utc = datetime.now(timezone.utc).isoformat(timespec="seconds")
    records = [build_record(entry) for entry in proxies]
    records.sort(key=_record_sort_key)

    by_tier: dict[str, int] = {}
    for record in records:
        by_tier[record["tier"]] = by_tier.get(record["tier"], 0) + 1

    # per-country files: tier != excluded only
    by_country: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        if record["tier"] == "excluded":
            continue
        by_country.setdefault(record["country"], []).append(record)
    country_counts = {
        country: len(countries) for country, countries in sorted(by_country.items())
    }

    totals = _read_report_totals(data_dir)
    summary = {
        "generated_utc": now_utc,
        "totals": {
            **totals,
            "published_records": len(records),
            "published_by_country_records": sum(country_counts.values()),
            "countries": len(country_counts),
        },
        "by_tier": dict(sorted(by_tier.items())),
        "by_country": country_counts,
    }

    out_dir = data_dir / config["out_dir"]
    staging_dir = data_dir / STAGING_DIRNAME
    if staging_dir.exists():
        shutil.rmtree(staging_dir)
    (staging_dir / "by-country").mkdir(parents=True)

    try:
        (staging_dir / "all.json").write_text(
            json.dumps(records, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        for country, country_records in sorted(by_country.items()):
            (staging_dir / "by-country" / f"{country}.json").write_text(
                json.dumps(country_records, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
        # stable contract: unclassified.json ALWAYS exists (may be empty)
        unclassified = by_country.get("unclassified", [])
        (staging_dir / "by-country" / "unclassified.json").write_text(
            json.dumps(unclassified, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        (staging_dir / "run-summary.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        _validate_staging(staging_dir, expected_records=len(records))
        _swap_into_place(staging_dir, out_dir)
    except PublishError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return StageResult(
            "publish",
            False,
            f"publish aborted, previous output left intact: {exc}",
        )
    except OSError as exc:
        shutil.rmtree(staging_dir, ignore_errors=True)
        return StageResult(
            "publish",
            False,
            f"publish aborted (I/O error), previous output left intact: {exc}",
        )

    eligible = sum(country_counts.values())
    detail = (
        f"published {len(records)} records to data/{config['out_dir']}: "
        f"{len(country_counts)} country files ({eligible} tier-eligible, "
        f"{by_tier.get('excluded', 0)} excluded in all.json only); "
        f"tiers " + ", ".join(f"{t} {by_tier[t]}" for t in sorted(by_tier))
    )
    return StageResult(
        "publish",
        True,
        detail,
        [out_dir / "all.json", out_dir / "run-summary.json"],
    )
