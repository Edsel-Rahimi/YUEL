"""Rolling per-identity check history (stage 4 persistence layer).

One JSON file — ``data/history/check_history.json`` — records, for every
proxy identity (``host|port|user|pass``), the outcome of each validate-stage
check across pipeline runs:

```json
{
  "schema_version": 1,
  "updated_utc": "2026-11-19T12:00:00+00:00",
  "identities": {
    "1.2.3.4|8080||": {
      "events": [
        {"utc": "2026-11-19T11:30:00+00:00", "ok": true, "latency_ms": 412.7}
      ]
    }
  }
}
```

Design rules:

- Events are appended oldest → newest and **capped**: only the most recent
  ``max_entries_per_identity`` events are kept, so the file cannot grow
  unbounded per identity.
- Identities whose newest event is older than ``inactivity_days`` are
  **pruned** — a proxy that has not been seen in a week stops occupying the
  history file. (The next run re-adds it with a fresh event if it reappears.)
- The success-rate component of the score needs ``min_events_for_success``
  events before it is considered meaningful (a proxy checked once as alive
  is not "reliable" yet); that threshold lives in the score config, not here
  — this module only stores facts.
- A missing or corrupt history file never crashes the stage: it degrades to
  an empty history (previous run-to-run continuity is lost, not correctness).
- ``save_history`` is atomic (temp file + ``os.replace``) so a crashed run
  can never leave a half-written history behind.
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

HISTORY_SCHEMA_VERSION = 1
DEFAULT_MAX_ENTRIES = 10
DEFAULT_INACTIVITY_DAYS = 7


def load_history(path: Path) -> dict[str, Any]:
    """Load the history file; missing/corrupt → fresh empty structure."""
    try:
        raw = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _fresh()
    if not isinstance(raw, dict) or raw.get("schema_version") != HISTORY_SCHEMA_VERSION:
        return _fresh()
    identities = raw.get("identities")
    if not isinstance(identities, dict):
        return _fresh()
    cleaned: dict[str, Any] = {}
    for identity, entry in identities.items():
        if not isinstance(entry, dict) or not isinstance(entry.get("events"), list):
            continue
        events = [
            e
            for e in entry["events"]
            if isinstance(e, dict) and isinstance(e.get("ok"), bool) and e.get("utc")
        ]
        events.sort(key=lambda e: str(e["utc"]))
        cleaned[str(identity)] = {"events": events}
    updated = raw.get("updated_utc")
    result = _fresh(identities=cleaned)
    if isinstance(updated, str) and updated:
        result["updated_utc"] = updated
    return result


def _fresh(identities: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "schema_version": HISTORY_SCHEMA_VERSION,
        "updated_utc": None,
        "identities": identities or {},
    }


def record_events(
    history: dict[str, Any],
    events: dict[str, dict[str, Any]],
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> int:
    """Append one event per identity; returns how many events were recorded.

    ``events`` maps identity → ``{"utc": iso, "ok": bool, "latency_ms": float}``
    (all events are treated as belonging to the same run).
    """
    recorded = 0
    for identity, event in events.items():
        entry = history["identities"].setdefault(identity, {"events": []})
        entry["events"].append(
            {"utc": event["utc"], "ok": bool(event["ok"]),
             "latency_ms": event.get("latency_ms")}
        )
        entry["events"].sort(key=lambda e: str(e["utc"]))
        if len(entry["events"]) > max_entries:
            entry["events"] = entry["events"][-max_entries:]
        recorded += 1
    return recorded


def prune(history: dict[str, Any], now_utc: datetime, inactivity_days: float) -> int:
    """Drop identities not seen within ``inactivity_days``; returns the count."""
    cutoff = now_utc - timedelta(days=inactivity_days)
    stale = []
    for identity, entry in history["identities"].items():
        events = entry.get("events") or []
        if not events:
            stale.append(identity)
            continue
        try:
            last = datetime.fromisoformat(str(events[-1]["utc"]))
        except ValueError:
            stale.append(identity)
            continue
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if last < cutoff:
            stale.append(identity)
    for identity in stale:
        history["identities"].pop(identity, None)
    return len(stale)


def history_stats(identity_entry: dict[str, Any]) -> dict[str, Any]:
    """Derived facts for one identity: success rate + trailing streaks."""
    events = identity_entry.get("events") or []
    total = len(events)
    successes = sum(1 for e in events if e.get("ok"))
    consecutive_successes = 0
    for event in reversed(events):
        if not event.get("ok"):
            break
        consecutive_successes += 1
    consecutive_failures = 0
    for event in reversed(events):
        if event.get("ok"):
            break
        consecutive_failures += 1
    return {
        "success_rate": round(successes / total, 4) if total else None,
        "total_events": total,
        "consecutive_successes": consecutive_successes,
        "consecutive_failures": consecutive_failures,
        "last_utc": str(events[-1]["utc"]) if events else None,
    }


def save_history(path: Path, history: dict[str, Any]) -> None:
    """Atomically write the history file (temp file + os.replace)."""
    path = Path(path)
    history["updated_utc"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(path.parent), prefix=".history-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(history, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
