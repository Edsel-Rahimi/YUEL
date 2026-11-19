"""Tests for the rolling check-history persistence layer (stage 4)."""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from yuel import history


NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)


def event(ok: bool, days_ago: float = 0.0, latency: float | None = 100.0) -> dict:
    from datetime import timedelta

    utc = NOW - timedelta(days=days_ago)
    return {"utc": utc.isoformat(timespec="seconds"), "ok": ok, "latency_ms": latency}


class RecordTests(unittest.TestCase):
    def test_appends_and_orders(self):
        hist = history.load_history(Path("nonexistent.json"))
        n = history.record_events(
            hist,
            {"a|1|": event(True), "b|2|": event(False)},
        )
        self.assertEqual(n, 2)
        self.assertEqual(hist["identities"]["a|1|"]["events"][0]["ok"], True)
        self.assertEqual(hist["identities"]["b|2|"]["events"][0]["ok"], False)

    def test_cap_keeps_most_recent(self):
        hist = history.load_history(Path("nonexistent.json"))
        # one identity, 15 events recorded sequentially (oldest first, all past)
        for i in range(15):
            history.record_events(hist, {"cap|8080|": event(True, days_ago=14 - i)})
        events_list = hist["identities"]["cap|8080|"]["events"]
        self.assertEqual(len(events_list), history.DEFAULT_MAX_ENTRIES)
        # kept the MOST RECENT 10 (days_ago 9..0), dropped the oldest
        self.assertEqual(events_list[-1]["utc"], event(True, days_ago=0)["utc"])
        self.assertEqual(events_list[0]["utc"], event(True, days_ago=9)["utc"])

    def test_stats_consecutive_streaks(self):
        hist = history.load_history(Path("nonexistent.json"))
        # timeline: ok, ok, fail, ok  (oldest → newest)
        for i, ok in enumerate([True, True, False, True]):
            history.record_events(hist, {"s|1|": event(ok, days_ago=4 - i)})
        stats = history.history_stats(hist["identities"]["s|1|"])
        self.assertEqual(stats["total_events"], 4)
        self.assertEqual(stats["success_rate"], 0.75)
        self.assertEqual(stats["consecutive_successes"], 1)
        self.assertEqual(stats["consecutive_failures"], 0)
        # trailing failures
        hist2 = history.load_history(Path("nonexistent.json"))
        for i, ok in enumerate([True, False, False]):
            history.record_events(hist2, {"f|1|": event(ok, days_ago=3 - i)})
        stats2 = history.history_stats(hist2["identities"]["f|1|"])
        self.assertEqual(stats2["consecutive_failures"], 2)
        self.assertEqual(stats2["consecutive_successes"], 0)

    def test_empty_stats(self):
        stats = history.history_stats({"events": []})
        self.assertIsNone(stats["success_rate"])
        self.assertEqual(stats["total_events"], 0)
        self.assertIsNone(stats["last_utc"])


class PruneTests(unittest.TestCase):
    def test_stale_identities_pruned(self):
        hist = history.load_history(Path("nonexistent.json"))
        history.record_events(
            hist,
            {
                "fresh|1|": event(True, days_ago=0.1),
                "old|2|": event(True, days_ago=30),
            },
        )
        pruned = history.prune(hist, NOW, inactivity_days=7)
        self.assertEqual(pruned, 1)
        self.assertIn("fresh|1|", hist["identities"])
        self.assertNotIn("old|2|", hist["identities"])

    def test_events_without_timestamp_pruned(self):
        hist = {"schema_version": 1, "identities": {"broken|1|": {"events": []}}}
        pruned = history.prune(hist, NOW, inactivity_days=7)
        self.assertEqual(pruned, 1)
        self.assertEqual(hist["identities"], {})


class PersistenceTests(unittest.TestCase):
    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            hist = history.load_history(path)
            history.record_events(hist, {"a|1|": event(True, latency=42.5)})
            history.save_history(path, hist)
            loaded = history.load_history(path)
            self.assertEqual(
                loaded["identities"]["a|1|"]["events"][0]["latency_ms"], 42.5
            )
            self.assertIsNotNone(loaded["updated_utc"])

    def test_corrupt_file_degrades_to_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text("{not json", encoding="utf-8")
            hist = history.load_history(path)
            self.assertEqual(hist["identities"], {})
            self.assertEqual(hist["schema_version"], 1)

    def test_wrong_schema_version_degrades_to_fresh(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            path.write_text(
                json.dumps({"schema_version": 99, "identities": {}}),
                encoding="utf-8",
            )
            hist = history.load_history(path)
            self.assertEqual(hist["identities"], {})

    def test_save_is_atomic_no_temp_residue(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "history.json"
            hist = history.load_history(path)
            history.record_events(hist, {"a|1|": event(True)})
            history.save_history(path, hist)
            residue = [p.name for p in Path(tmp).iterdir() if p.name != "history.json"]
            self.assertEqual(residue, [])
            # and the file is valid JSON
            json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
