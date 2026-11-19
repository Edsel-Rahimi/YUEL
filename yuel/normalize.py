"""Stage 2 — normalize: dedupe by connection identity, emit a canonical list.

Input:  ``data/collected/proxies_raw.json`` — the stage-1 output (one JSON
        array of canonical proxy dicts, one entry per parsed source line, so
        the same server usually appears many times, once per source that
        published it).
Output: ``data/normalized/proxies_normalized.json`` — one JSON array with
        **one entry per effective connection target**, plus
        ``data/normalized/normalize_report.json`` for auditability.

Rules:
- Dedupe key is :func:`yuel.collect.proxy_identity` —
  ``host|port|username|password`` with the host lowercased. This is
  *effective connection identity*, not literal string equality: the same
  server published by many sources collapses to one entry, but the same
  server with *different credentials* stays separate (different access
  path, possibly different permission level).
- The representative entry kept for each identity is chosen deterministically
  (most non-null claims first, then a canonical JSON dump as tie-break) so
  runs are reproducible byte-for-byte.
- Claims (type / country / anonymity) are MERGED across duplicates: when all
  members agree, the merged entry carries the agreed value; when they
  disagree, the claim is set to ``null`` and the identity is flagged in
  ``claim_conflicts`` — stage 3 records the *measured* type anyway, so a
  conflict is a data-quality signal about the sources, never a crash.
- Every duplicate contributes its source id to the merged ``sources`` list
  (sorted, unique), so "how many independent lists carried this server" is
  visible downstream — that signal feeds the freshness/score stages later.
- Rows that fail the stage-1 sanity checks (defensive re-check) are dropped,
  counted, and sampled in the report.

The stage never raises on bad input rows: malformed rows are recorded as
invalid, not fatal.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .collect import proxy_identity, validate_proxy

MAX_INVALID_SAMPLES = 5
MAX_TOP_DUPLICATES = 5

_CLAIM_KEYS = ("claimed_type", "claimed_country", "claimed_anonymity")
_CONFLICT_NAMES = {"claimed_type": "type", "claimed_country": "country",
                   "claimed_anonymity": "anonymity"}


def _member_sort_key(proxy: dict[str, Any]) -> tuple:
    """Deterministic "richest first" ordering for choosing a representative."""
    claim_count = sum(1 for key in _CLAIM_KEYS if proxy.get(key) is not None)
    return (
        claim_count,
        1 if proxy.get("username") else 0,
        json.dumps(proxy, sort_keys=True, ensure_ascii=False),
    )


def _row_is_malformed(proxy: Any) -> str | None:
    """Cheap structural pre-check before the full validation; None = fine."""
    if not isinstance(proxy, dict):
        return "row is not an object"
    for key in ("host", "port"):
        if key not in proxy:
            return f"row missing '{key}'"
    return None


def _merge_claims(members: list[dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Merge claim fields across duplicates; disagreement -> null + flag."""
    merged: dict[str, Any] = {}
    conflicts: list[str] = []
    for key in _CLAIM_KEYS:
        distinct = sorted(
            {json.dumps(m.get(key), sort_keys=True) for m in members},
            key=lambda s: (s == "null", s),  # prefer a real value over null
        )
        values = [json.loads(s) for s in distinct]
        real = [v for v in values if v is not None]
        if len({json.dumps(v, sort_keys=True) for v in real}) <= 1:
            # all present values identical (or none at all)
            merged[key] = real[0] if real else None
        else:
            merged[key] = None
            conflicts.append(_CONFLICT_NAMES[key])
    return merged, conflicts


def normalize_proxies(
    proxies: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Dedupe a stage-1 proxy list into the canonical normalized list.

    Returns ``(normalized, report)``. Never raises on malformed rows.
    """
    groups: dict[str, list[dict[str, Any]]] = {}
    invalid = 0
    invalid_samples: list[str] = []

    for proxy in proxies:
        malformed = _row_is_malformed(proxy)
        if malformed is None:
            ok, reason = validate_proxy(proxy)
            malformed = None if ok else (reason or "validation failed")
        if malformed is not None:
            invalid += 1
            if len(invalid_samples) < MAX_INVALID_SAMPLES:
                preview = json.dumps(proxy, ensure_ascii=False)[:120]
                invalid_samples.append(f"{preview} -> {malformed}")
            continue
        identity = proxy.get("identity") or proxy_identity(proxy)
        groups.setdefault(identity, []).append(proxy)

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
        claims, conflicts = _merge_claims(members)
        normalized.append(
            {
                "host": representative["host"],
                "port": representative["port"],
                "username": representative.get("username") or "",
                "password": representative.get("password") or "",
                "claimed_type": claims["claimed_type"],
                "claimed_country": claims["claimed_country"],
                "claimed_anonymity": claims["claimed_anonymity"],
                "identity": identity,
                "sources": sources,
                "claim_conflicts": conflicts,
            }
        )

    top_duplicates.sort(key=lambda d: d["count"], reverse=True)
    by_claimed_type: dict[str, int] = {}
    with_creds = 0
    conflict_count = 0
    for entry in normalized:
        key = entry["claimed_type"] or "unknown"
        by_claimed_type[key] = by_claimed_type.get(key, 0) + 1
        if entry["username"]:
            with_creds += 1
        if entry["claim_conflicts"]:
            conflict_count += 1

    report = {
        "stage": "normalize",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "input": {"proxies_in": len(proxies), "invalid_dropped": invalid},
        "output": {
            "proxies_out": len(normalized),
            "duplicates_collapsed": duplicates_collapsed,
            "with_credentials": with_creds,
            "claim_conflicts": conflict_count,
        },
        "by_claimed_type": dict(sorted(by_claimed_type.items())),
        "invalid_samples": invalid_samples,
        "top_duplicates": top_duplicates[:MAX_TOP_DUPLICATES],
    }
    return normalized, report
