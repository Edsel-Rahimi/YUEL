"""Tests for stage 6 (publish): contract shape, grouping, atomic swap.

All file-based; the atomicity tests prove a failed publish never touches
previously-good output.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from yuel.publish import (
    PublishError,
    build_record,
    load_publish_config,
    stage_publish,
)


def make_geo_entry(host, port, country="IT", tier="gold", score=87.2,
                   confirmed="socks5", username="", password=""):
    entry = {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "claimed_type": "socks5",
        "country": country,
        "identity": f"{host}|{port}|{username}|{password}",
        "check": {
            "ok": True,
            "type_confirmed": confirmed,
            "method_used": "socks5",
            "latency_ms": 100.0,
            "http_status": 204,
            "checked_utc": "2026-11-19T12:00:00+00:00",
            "error": None,
        },
        "score": {"total": score, "tier": tier,
                  "components": {}, "weights_effective": {}},
        "history": {"success_rate": 1.0, "total_events": 3,
                    "consecutive_successes": 3, "consecutive_failures": 0},
    }
    return entry


def write_geo(data_dir: Path, entries: list) -> None:
    geo = data_dir / "geo"
    geo.mkdir(parents=True, exist_ok=True)
    (geo / "proxies_geo.json").write_text(
        json.dumps(entries), encoding="utf-8"
    )


def write_reports(data_dir: Path) -> None:
    collected = data_dir / "collected"
    collected.mkdir(parents=True, exist_ok=True)
    (collected / "collect_report.json").write_text(
        json.dumps({"totals": {"sources_ok": 24, "entries_parsed": 74290}}),
        encoding="utf-8",
    )
    normalized = data_dir / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    (normalized / "normalize_report.json").write_text(
        json.dumps({"output": {"proxies_out": 56670}}), encoding="utf-8"
    )
    validated = data_dir / "validated"
    validated.mkdir(parents=True, exist_ok=True)
    (validated / "validate_report.json").write_text(
        json.dumps({"handshake_check": {"tested": 150, "alive": 31}}),
        encoding="utf-8",
    )


class BuildRecordTests(unittest.TestCase):
    def test_contract_shape_with_creds(self):
        record = build_record(
            make_geo_entry("1.2.3.4", 8080, username="alice", password="s3cret")
        )
        self.assertEqual(
            record,
            {
                "ip": "1.2.3.4",
                "port": 8080,
                "type": "socks5",
                "country": "IT",
                "score": 87.2,
                "tier": "gold",
                "last_checked": "2026-11-19T12:00:00+00:00",
                "consecutive_successes": 3,
                "consecutive_failures": 0,
                "user": "alice",
                "pass": "s3cret",
            },
        )

    def test_creds_omitted_when_empty(self):
        record = build_record(make_geo_entry("5.6.7.8", 1080, country=None))
        self.assertNotIn("user", record)
        self.assertNotIn("pass", record)
        self.assertEqual(record["country"], "unclassified")

    def test_type_is_confirmed_plain_proxy_type(self):
        record = build_record(make_geo_entry("5.6.7.8", 1080, confirmed="http"))
        self.assertEqual(record["type"], "http")


class ConfigTests(unittest.TestCase):
    def test_defaults(self):
        config = load_publish_config(None)
        self.assertEqual(config["out_dir"], "out")

    def test_out_dir_override(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "publish.json"
            path.write_text(json.dumps({"schema_version": 1, "out_dir": "out2"}))
            self.assertEqual(load_publish_config(path)["out_dir"], "out2")

    def test_unsafe_out_dir_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "publish.json"
            path.write_text(json.dumps({"schema_version": 1, "out_dir": "../evil"}))
            with self.assertRaises(PublishError):
                load_publish_config(path)

    def test_bad_schema_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "publish.json"
            path.write_text(json.dumps({"schema_version": 2}))
            with self.assertRaises(PublishError):
                load_publish_config(path)


class StagePublishTests(unittest.TestCase):
    ENTRIES = [
        make_geo_entry("1.1.1.1", 8080, country="IT", tier="gold", score=90.0),
        make_geo_entry("2.2.2.2", 3128, country="IT", tier="bronze", score=25.0,
                       confirmed="http"),
        make_geo_entry("3.3.3.3", 1080, country="US", tier="silver", score=60.0),
        make_geo_entry("4.4.4.4", 1080, country=None, tier="excluded", score=5.0),
    ]

    def test_full_contract_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_geo(data_dir, self.ENTRIES)
            write_reports(data_dir)
            result = stage_publish(Path("unused"), data_dir)
            self.assertTrue(result.ok, result.detail)

            out = data_dir / "out"
            all_records = json.loads((out / "all.json").read_text(encoding="utf-8"))
            self.assertEqual(len(all_records), 4)  # all tiers incl. excluded
            self.assertEqual(
                [r["ip"] for r in all_records],
                ["1.1.1.1", "3.3.3.3", "2.2.2.2", "4.4.4.4"],  # score-desc
            )

            it = json.loads((out / "by-country" / "IT.json").read_text(encoding="utf-8"))
            self.assertEqual([r["ip"] for r in it], ["1.1.1.1", "2.2.2.2"])
            us = json.loads((out / "by-country" / "US.json").read_text(encoding="utf-8"))
            self.assertEqual([r["ip"] for r in us], ["3.3.3.3"])
            unclassified = json.loads(
                (out / "by-country" / "unclassified.json").read_text(encoding="utf-8")
            )
            # excluded-tier unclassified proxy is NOT in per-country files
            self.assertEqual(unclassified, [])

            summary = json.loads((out / "run-summary.json").read_text(encoding="utf-8"))
            self.assertEqual(summary["totals"]["sources_used"], 24)
            self.assertEqual(summary["totals"]["candidates_collected"], 74290)
            self.assertEqual(summary["totals"]["unique_normalized"], 56670)
            self.assertEqual(summary["totals"]["tested"], 150)
            self.assertEqual(summary["totals"]["validated_alive"], 31)
            self.assertEqual(summary["totals"]["published_records"], 4)
            self.assertEqual(summary["totals"]["countries"], 2)
            self.assertEqual(summary["by_tier"], {"bronze": 1, "excluded": 1,
                                                  "gold": 1, "silver": 1})

            # no staging residue
            residue = [p.name for p in data_dir.iterdir()
                       if p.name.startswith(".out")]
            self.assertEqual(residue, [])

    def test_unclassified_file_present_even_when_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_geo(data_dir, [make_geo_entry("1.1.1.1", 8080, country="IT")])
            result = stage_publish(Path("unused"), data_dir)
            self.assertTrue(result.ok, result.detail)
            unclassified = json.loads(
                (data_dir / "out" / "by-country" / "unclassified.json")
                .read_text(encoding="utf-8")
            )
            self.assertEqual(unclassified, [])

    def test_empty_run_refuses_to_publish_keeps_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            # a previously-good publish
            write_geo(data_dir, self.ENTRIES)
            write_reports(data_dir)
            first = stage_publish(Path("unused"), data_dir)
            self.assertTrue(first.ok, first.detail)
            good_all = (data_dir / "out" / "all.json").read_text(encoding="utf-8")

            # next run: everything died
            write_geo(data_dir, [])
            second = stage_publish(Path("unused"), data_dir)
            self.assertFalse(second.ok)
            self.assertIn("refusing to publish", second.detail)
            self.assertIn("previous published output left intact", second.detail)
            # old output untouched
            self.assertEqual(
                (data_dir / "out" / "all.json").read_text(encoding="utf-8"),
                good_all,
            )

    def test_failed_validation_keeps_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_geo(data_dir, self.ENTRIES)
            write_reports(data_dir)
            first = stage_publish(Path("unused"), data_dir)
            self.assertTrue(first.ok, first.detail)
            good_all = (data_dir / "out" / "all.json").read_text(encoding="utf-8")

            # next run: staging validation blows up (simulated corruption)
            with patch(
                "yuel.publish._validate_staging",
                side_effect=PublishError("staged all.json is not valid JSON"),
            ):
                write_geo(data_dir, self.ENTRIES[:1])
                second = stage_publish(Path("unused"), data_dir)
            self.assertFalse(second.ok)
            self.assertIn("previous output left intact", second.detail)
            self.assertEqual(
                (data_dir / "out" / "all.json").read_text(encoding="utf-8"),
                good_all,
            )
            # staging cleaned up
            residue = [p.name for p in data_dir.iterdir()
                       if p.name.startswith(".out")]
            self.assertEqual(residue, [])

    def test_new_run_replaces_old_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_geo(data_dir, self.ENTRIES)
            write_reports(data_dir)
            stage_publish(Path("unused"), data_dir)
            write_geo(data_dir, self.ENTRIES[:1])
            result = stage_publish(Path("unused"), data_dir)
            self.assertTrue(result.ok, result.detail)
            all_records = json.loads(
                (data_dir / "out" / "all.json").read_text(encoding="utf-8")
            )
            self.assertEqual(len(all_records), 1)
            self.assertFalse((data_dir / ".out_prev").exists())

    def test_missing_stage5_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = stage_publish(Path("unused"), Path(tmp))
            self.assertFalse(result.ok)
            self.assertIn("run geo first", result.detail)


if __name__ == "__main__":
    unittest.main()
