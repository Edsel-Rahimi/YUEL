"""Stage 4 — score: weighted quality formula over validated proxies.

Input:  ``data/validated/proxies_validated.json`` (stage 3 output).
Output: ``data/scored/proxies_scored.json`` — alive proxies only, each with
        a ``score`` block and derived ``history`` facts — plus
        ``data/scored/score_report.json``.

Four components, each normalized to 0–100, combined with configurable
weights; **weights are re-normalized over the components that are actually
available** for each proxy, so a proxy with no anonymity claim and no
history yet is not silently penalized:

- **latency** — percentile rank of this proxy's latency *within the current
  run's alive distribution* (fastest alive proxy ≈ 100, slowest ≈ 0; ties
  share a rank; a run with a single alive proxy gives it 100). Deliberately
  relative, never a fixed arbitrary scale.
- **success rate** — from the rolling per-identity history across runs
  (:mod:`yuel.history`): ``successes / total_events`` × 100, but only once
  ``min_events_for_success`` events exist (default 2) — a proxy checked
  once as alive is not "reliable" yet, so the component stays unavailable
  and its weight is redistributed.
- **freshness** — linear decay from 100 (checked right now) to 0 at
  ``freshness_window_hours``; matters when a run re-checks only part of the
  fleet, or when scored entries are consumed later.
- **anonymity level** — ``elite`` > ``anonymous`` > ``transparent`` from the
  sources' claims (merged in stage 2); unknown → unavailable, weight
  redistributed. This replaces the old tunnel-era "protocol strength"
  component: plain proxies have no protocol tiers to rank.

Final score maps to tiers via configurable thresholds (``config/score.json``,
defaults gold ≥ 80, silver ≥ 50, bronze ≥ 20; below → ``excluded`` and kept
out of per-country publish files at stage 6).

The stage also persists history: every *tested* proxy (alive or dead) gets
this run's event appended, stale identities are pruned, and the file is
saved atomically. Dead proxies never enter the scored list — scoring only
ranks proxies that just answered through a real handshake.
"""

from __future__ import annotations

import copy
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import history as history_mod
from .stage import StageResult

DEFAULT_CONFIG = {
    "schema_version": 1,
    "weights": {"latency": 0.40, "success": 0.30, "freshness": 0.15, "anonymity": 0.15},
    "tiers": {"gold": 80, "silver": 50, "bronze": 20},
    "freshness_window_hours": 24,
    "anonymity_values": {"elite": 100, "anonymous": 70, "transparent": 30},
    "min_events_for_success": 2,
    "history": {
        "max_entries_per_identity": 10,
        "inactivity_days": 7,
    },
}

HISTORY_FILE = "data/history/check_history.json"
TIERS_ORDERED = ("gold", "silver", "bronze")


class ScoreConfigError(ValueError):
    """Invalid score-stage configuration."""


def default_score_config_path() -> Path:
    """Score config location: $YUEL_SCORE_CONFIG, else <repo>/config/score.json."""
    env = os.environ.get("YUEL_SCORE_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "config" / "score.json"


def load_score_config(path: Path | None) -> dict[str, Any]:
    """Load config/score.json over built-in defaults; strict validation."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None and Path(path).exists():
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ScoreConfigError(f"cannot read {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ScoreConfigError(f"{path} is not a JSON object")
        if loaded.get("schema_version") != 1:
            raise ScoreConfigError(
                f"unsupported schema_version: {loaded.get('schema_version')!r}"
            )
        for key in ("weights", "tiers", "anonymity_values", "history"):
            if isinstance(loaded.get(key), dict):
                config[key].update(loaded[key])
        for key in ("freshness_window_hours", "min_events_for_success"):
            if key in loaded:
                config[key] = loaded[key]
    _validate_config(config)
    return config


def _validate_config(config: dict[str, Any]) -> None:
    weights = config["weights"]
    for name in ("latency", "success", "freshness", "anonymity"):
        value = weights.get(name)
        if not isinstance(value, (int, float)) or value < 0:
            raise ScoreConfigError(f"weights.{name} must be a number >= 0")
    if all(weights[name] == 0 for name in weights):
        raise ScoreConfigError("at least one component weight must be > 0")
    tiers = config["tiers"]
    values = [tiers.get(name) for name in TIERS_ORDERED]
    if any(not isinstance(v, (int, float)) for v in values):
        raise ScoreConfigError(f"tiers must define {TIERS_ORDERED} as numbers")
    if not values[0] > values[1] > values[2] > 0:
        raise ScoreConfigError("tier thresholds must be gold > silver > bronze > 0")
    if not isinstance(config["freshness_window_hours"], (int, float)) or \
            config["freshness_window_hours"] <= 0:
        raise ScoreConfigError("freshness_window_hours must be > 0")
    if not isinstance(config["min_events_for_success"], int) or \
            config["min_events_for_success"] < 1:
        raise ScoreConfigError("min_events_for_success must be an integer >= 1")
    for level, value in config["anonymity_values"].items():
        if not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ScoreConfigError(f"anonymity_values.{level} must be 0–100")


# ---------------------------------------------------------------------------
# components
# ---------------------------------------------------------------------------


def latency_component_values(latencies: list[float]) -> list[float]:
    """Relative latency scores (0–100, higher = faster) for the alive fleet.

    Each proxy gets ``100 × (1 − strictly_faster / (n − 1))``: the fastest
    proxy scores 100, the slowest 0, ties share a rank, and a single-proxy
    run gives that proxy 100 (no distribution to compare against).
    """
    n = len(latencies)
    if n == 0:
        return []
    if n == 1:
        return [100.0]
    scores = []
    for value in latencies:
        strictly_faster = sum(1 for other in latencies if other < value)
        scores.append(round(100.0 * (1 - strictly_faster / (n - 1)), 2))
    return scores


def freshness_component_value(checked_utc: str, now_utc: datetime, window_hours: float) -> float:
    """Linear decay: 100 at age 0 → 0 at ``window_hours`` (and beyond)."""
    try:
        checked = datetime.fromisoformat(checked_utc)
    except (TypeError, ValueError):
        return 0.0
    if checked.tzinfo is None:
        checked = checked.replace(tzinfo=timezone.utc)
    age_hours = max(0.0, (now_utc - checked).total_seconds() / 3600)
    return round(100.0 * max(0.0, 1 - age_hours / window_hours), 2)


def success_component_value(stats: dict[str, Any], min_events: int) -> float | None:
    """History success rate × 100, or None until enough events exist."""
    if stats["total_events"] < min_events or stats["success_rate"] is None:
        return None
    return round(stats["success_rate"] * 100, 2)


def anonymity_component_value(claimed: str | None, values: dict[str, float]) -> float | None:
    if claimed is None:
        return None
    return values.get(str(claimed).lower())


def combine(
    components: dict[str, float | None], weights: dict[str, float]
) -> tuple[float | None, dict[str, float]]:
    """Weighted sum with re-normalization over available components.

    Returns ``(score, weights_effective)``; ``(None, {})`` when no component
    is available (weights sum to zero).
    """
    available = {name: value for name, value in components.items() if value is not None}
    weight_sum = sum(weights[name] for name in available)
    if not available or weight_sum <= 0:
        return None, {}
    weights_effective = {
        name: round(weights[name] / weight_sum, 4) for name in available
    }
    score = sum(weights_effective[name] * value for name, value in available.items())
    return round(score, 2), weights_effective


def tier_for(score: float | None, tiers: dict[str, float]) -> str:
    """Map a score to the configured tiers; below the lowest → ``excluded``."""
    if score is None:
        return "excluded"
    for name in TIERS_ORDERED:  # gold > silver > bronze by config validation
        if score >= tiers[name]:
            return name
    return "excluded"


# ---------------------------------------------------------------------------
# stage entrypoint
# ---------------------------------------------------------------------------


def stage_score(
    cfg_path: Path,
    data_dir: Path,
    score_cfg_path: Path | None = None,
    **_: Any,
) -> StageResult:
    """Stage 4: score validated proxies + persist rolling history."""
    validated_path = data_dir / "validated" / "proxies_validated.json"
    if not validated_path.exists():
        return StageResult(
            "score",
            False,
            f"stage-3 output not found: {validated_path} (run validate first)",
        )
    try:
        proxies = json.loads(validated_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return StageResult("score", False, f"cannot read stage-3 output: {exc}")
    if not isinstance(proxies, list):
        return StageResult("score", False, "stage-3 output is not a JSON list")

    try:
        config = load_score_config(score_cfg_path or default_score_config_path())
    except ScoreConfigError as exc:
        return StageResult("score", False, f"config error: {exc}")

    now_utc = datetime.now(timezone.utc)

    # --- history: record this run, prune stale identities, save atomically ---
    history_path = data_dir / "history" / "check_history.json"
    hist = history_mod.load_history(history_path)
    tested = [p for p in proxies if isinstance(p, dict) and p.get("check")]
    events = {}
    for proxy in tested:
        check = proxy["check"]
        events[proxy["identity"]] = {
            "utc": check.get("checked_utc") or now_utc.isoformat(timespec="seconds"),
            "ok": bool(check.get("ok")),
            "latency_ms": check.get("latency_ms"),
        }
    recorded = history_mod.record_events(
        hist, events, config["history"]["max_entries_per_identity"]
    )
    pruned = history_mod.prune(hist, now_utc, config["history"]["inactivity_days"])
    history_mod.save_history(history_path, hist)

    # --- score the alive subset ---
    alive = [p for p in tested if p["check"].get("ok")]
    latencies = [p["check"].get("latency_ms") for p in alive]
    has_latency = [value for value in latencies if value is not None]
    latency_scores = (
        latency_component_values(has_latency) if has_latency else []
    )
    latency_by_identity = {
        p["identity"]: score
        for p, score in zip(
            [p for p in alive if p["check"].get("latency_ms") is not None],
            latency_scores,
        )
    }

    scored = []
    tier_counts = {"gold": 0, "silver": 0, "bronze": 0, "excluded": 0}
    for proxy in alive:
        stats = history_mod.history_stats(
            hist["identities"].get(proxy["identity"], {"events": []})
        )
        components = {
            "latency": latency_by_identity.get(proxy["identity"]),
            "success": success_component_value(
                stats, config["min_events_for_success"]
            ),
            "freshness": freshness_component_value(
                proxy["check"].get("checked_utc") or now_utc.isoformat(
                    timespec="seconds"
                ),
                now_utc,
                config["freshness_window_hours"],
            ),
            "anonymity": anonymity_component_value(
                proxy.get("claimed_anonymity"), config["anonymity_values"]
            ),
        }
        score, weights_effective = combine(components, config["weights"])
        tier = tier_for(score, config["tiers"])
        tier_counts[tier] += 1
        entry = dict(proxy)
        entry["score"] = {
            "total": score,
            "tier": tier,
            "components": components,
            "weights_effective": weights_effective,
        }
        entry["history"] = {
            key: stats[key]
            for key in ("success_rate", "total_events",
                        "consecutive_successes", "consecutive_failures")
        }
        scored.append(entry)

    scored.sort(
        key=lambda e: (-(e["score"]["total"] if e["score"]["total"] is not None else -1),
                       e["identity"])
    )

    out_dir = data_dir / "scored"
    out_dir.mkdir(parents=True, exist_ok=True)
    scored_path = out_dir / "proxies_scored.json"
    report_path = out_dir / "score_report.json"
    scored_path.write_text(
        json.dumps(scored, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    total_scores = sorted(
        e["score"]["total"] for e in scored if e["score"]["total"] is not None
    )
    report = {
        "stage": "score",
        "run_utc": now_utc.isoformat(timespec="seconds"),
        "config": {
            "weights": config["weights"],
            "tiers": config["tiers"],
            "freshness_window_hours": config["freshness_window_hours"],
            "min_events_for_success": config["min_events_for_success"],
        },
        "input": {"tested": len(tested), "alive": len(alive)},
        "tier_distribution": tier_counts,
        "score_stats": {
            "min": total_scores[0] if total_scores else None,
            "p50": _percentile(total_scores, 0.5),
            "p90": _percentile(total_scores, 0.9),
            "max": total_scores[-1] if total_scores else None,
        },
        "history": {
            "identities_stored": len(hist["identities"]),
            "events_recorded": recorded,
            "identities_pruned": pruned,
            "max_entries_per_identity": config["history"]["max_entries_per_identity"],
            "inactivity_days": config["history"]["inactivity_days"],
        },
        "scored_file": scored_path.name,
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    detail = (
        f"scored {len(alive)} alive proxies: "
        + ", ".join(f"{tier} {tier_counts[tier]}" for tier in TIERS_ORDERED)
        + f", excluded {tier_counts['excluded']}"
        + f" (history: {len(hist['identities'])} identities, {pruned} pruned)"
    )
    return StageResult("score", True, detail, [scored_path, report_path])


def _percentile(sorted_values: list[float], q: float) -> float | None:
    if not sorted_values:
        return None
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac, 2)
