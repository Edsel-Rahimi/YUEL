"""Stage 2 — normalize: dedupe by connection identity, emit a canonical list.

Input:  ``data/collected/endpoints_raw.json`` — the stage-1 output (one JSON
        array of canonical endpoint dicts, one entry per extracted URI, so
        the same node usually appears many times, once per source that
        published it).
Output: ``data/normalized/endpoints_normalized.json`` — one JSON array with
        **one entry per effective connection target**, plus
        ``data/normalized/normalize_report.json`` for auditability.

Rules:
- Dedupe key is :func:`yuel.collect.endpoint_identity` —
  ``scheme|host|port|secret`` with the host lowercased. This is *effective
  connection identity*, not literal string equality: the same node with
  reordered query parameters, different display tags, or different sources
  collapses to one entry.
- The representative entry kept for each identity is chosen deterministically
  (richest metadata first — most params, most extras, longest name; ties
  broken by a canonical JSON dump so runs are reproducible byte-for-byte).
- Every duplicate contributes its source id to the merged ``sources`` list
  (sorted, unique), so "how many independent lists carried this node" is
  visible downstream — that signal feeds the freshness/score stages later.
- Entries that fail the stage-1 sanity checks (defensive re-check) are
  dropped and counted, with a few samples kept in the report.

The stage never raises on bad input rows: malformed rows are recorded as
invalid, not fatal.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .collect import endpoint_identity, validate_endpoint

MAX_INVALID_SAMPLES = 5
MAX_TOP_DUPLICATES = 5


def _member_sort_key(endpoint: dict[str, Any]) -> tuple:
    """Deterministic "richest first" ordering for choosing a representative."""
    return (
        len(endpoint.get("params") or {}),
        len(endpoint.get("extra") or {}),
        len(str(endpoint.get("name") or "")),
        json.dumps(endpoint, sort_keys=True, ensure_ascii=False),
    )


def _row_is_malformed(endpoint: Any) -> str | None:
    """Cheap structural pre-check before the full validation; None = fine."""
    if not isinstance(endpoint, dict):
        return "row is not an object"
    for key in ("scheme", "host", "port"):
        if key not in endpoint:
            return f"row missing '{key}'"
    return None


def normalize_endpoints(
    endpoints: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dedupe a stage-1 endpoint list into the canonical normalized list.

    Returns ``(normalized, report)``. Never raises on malformed rows.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    invalid = 0
    invalid_samples: list[str] = []

    for endpoint in endpoints:
        malformed = _row_is_malformed(endpoint)
        if malformed is None:
            ok, reason = validate_endpoint(endpoint)
            malformed = None if ok else (reason or "validation failed")
        if malformed is not None:
            invalid += 1
            if len(invalid_samples) < MAX_INVALID_SAMPLES:
                preview = json.dumps(endpoint, ensure_ascii=False)[:120]
                invalid_samples.append(f"{preview} -> {malformed}")
            continue
        identity = endpoint.get("identity") or endpoint_identity(endpoint)
        groups.setdefault(identity, []).append(endpoint)

    normalized: list[dict[str, Any]] = []
    duplicates_collapsed = 0
    top_duplicates: list[dict[str, Any]] = []

    for identity in sorted(groups):
        members = groups[identity]
        if len(members) > 1:
            duplicates_collapsed += len(members) - 1
            top_duplicates.append({"identity": identity, "count": len(members)})
        representative = max(members, key=_member_sort_key)
        sources = sorted({m["source"] for m in members if m.get("source")})
        normalized.append(
            {
                "scheme": representative["scheme"],
                "host": representative["host"],
                "port": representative["port"],
                "secret": representative["secret"],
                "params": representative.get("params") or {},
                "name": representative.get("name") or "",
                "extra": representative.get("extra") or {},
                "identity": identity,
                "sources": sources,
            }
        )

    top_duplicates.sort(key=lambda d: d["count"], reverse=True)
    by_scheme: dict[str, int] = {}
    for entry in normalized:
        by_scheme[entry["scheme"]] = by_scheme.get(entry["scheme"], 0) + 1

    report = {
        "stage": "normalize",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {"endpoints_in": len(endpoints), "invalid_dropped": invalid},
        "output": {
            "endpoints_out": len(normalized),
            "duplicates_collapsed": duplicates_collapsed,
        },
        "by_scheme": dict(sorted(by_scheme.items())),
        "invalid_samples": invalid_samples,
        "top_duplicates": top_duplicates[:MAX_TOP_DUPLICATES],
    }
    return normalized, report
