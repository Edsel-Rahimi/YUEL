"""Tests for stage 4 (score): components, weight renormalization, tiers.

The formula cases below are hand-picked with the expected score/tier
computed BY HAND in the assertion comment, so the test pins the math, not
just "it ran".
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from yuel.score import (
    ScoreConfigError,
    anonymity_component_value,
    combine,
    freshness_component_value,
    latency_component_values,
    load_score_config,
    stage_score,
    success_component_value,
    tier_for,
)

NOW = datetime(2026, 11, 19, 12, 0, 0, tzinfo=timezone.utc)
DEFAULT_WEIGHTS = {"latency": 0.40, "success": 0.30, "freshness": 0.15, "anonymity": 0.15}
DEFAULT_TIERS = {"gold": 80, "silver": 50, "bronze": 20}


class LatencyComponentTests(unittest.TestCase):
    def test_percentile_rank_ordering(self):
        # [100, 500, 2000] ms → fastest 100, middle 50, slowest 0
        scores = latency_component_values([100.0, 500.0, 2000.0])
        self.assertEqual(scores, [100.0, 50.0, 0.0])

    def test_ties_share_rank(self):
        # two proxies at 100 ms are equally "fastest" relative to 500 ms
        scores = latency_component_values([100.0, 100.0, 500.0])
        self.assertEqual(scores, [100.0, 100.0, 0.0])

    def test_all_equal_latencies_score_equal(self):
        self.assertEqual(latency_component_values([50.0, 50.0, 50.0]), [100.0, 100.0, 100.0])

    def test_single_proxy_gets_100(self):
        self.assertEqual(latency_component_values([987.6]), [100.0])

    def test_empty(self):
        self.assertEqual(latency_component_values([]), [])


class FreshnessComponentTests(unittest.TestCase):
    def test_age_zero_is_100(self):
        self.assertEqual(
            freshness_component_value(NOW.isoformat(timespec="seconds"), NOW, 24), 100.0
        )

    def test_half_window_is_50(self):
        checked = (NOW - timedelta(hours=12)).isoformat(timespec="seconds")
        self.assertEqual(freshness_component_value(checked, NOW, 24), 50.0)

    def test_beyond_window_is_0(self):
        checked = (NOW - timedelta(hours=48)).isoformat(timespec="seconds")
        self.assertEqual(freshness_component_value(checked, NOW, 24), 0.0)

    def test_naive_timestamp_treated_as_utc(self):
        checked = (NOW - timedelta(hours=6)).isoformat(timespec="seconds")
        self.assertEqual(freshness_component_value(checked, NOW, 24), 75.0)


class SuccessComponentTests(unittest.TestCase):
    def test_rate_from_enough_events(self):
        stats = {"success_rate": 0.75, "total_events": 4}
        self.assertEqual(success_component_value(stats, min_events=2), 75.0)

    def test_unavailable_below_min_events(self):
        stats = {"success_rate": 1.0, "total_events": 1}
        self.assertIsNone(success_component_value(stats, min_events=2))

    def test_unavailable_without_events(self):
        stats = {"success_rate": None, "total_events": 0}
        self.assertIsNone(success_component_value(stats, min_events=2))


class AnonymityComponentTests(unittest.TestCase):
    def test_known_levels(self):
        values = {"elite": 100, "anonymous": 70, "transparent": 30}
        self.assertEqual(anonymity_component_value("elite", values), 100)
        self.assertEqual(anonymity_component_value("anonymous", values), 70)
        self.assertEqual(anonymity_component_value("transparent", values), 30)

    def test_unknown_claim_unavailable(self):
        self.assertIsNone(anonymity_component_value(None, {"elite": 100}))
        self.assertIsNone(anonymity_component_value("mystery", {"elite": 100}))


class CombineTests(unittest.TestCase):
    def test_all_available_exact_math(self):
        # latency 100, success 50, fresh 100, anon 30 with default weights
        # = .40*100 + .30*50 + .15*100 + .15*30 = 40 + 15 + 15 + 4.5 = 74.5
        score, eff = combine(
            {"latency": 100.0, "success": 50.0, "freshness": 100.0, "anonymity": 30.0},
            DEFAULT_WEIGHTS,
        )
        self.assertEqual(score, 74.5)
        self.assertAlmostEqual(sum(eff.values()), 1.0, places=3)
        self.assertEqual(eff, {"latency": 0.4, "success": 0.3, "freshness": 0.15,
                               "anonymity": 0.15})

    def test_renormalization_when_components_missing(self):
        # only latency + freshness available: weights renormalize over .40+.15
        # = 100*(.40/.55) + 100*(.15/.55) = 100 → gold for a fast fresh proxy
        score, eff = combine({"latency": 100.0, "success": None,
                              "freshness": 100.0, "anonymity": None},
                             DEFAULT_WEIGHTS)
        self.assertEqual(score, 100.0)
        self.assertAlmostEqual(eff["latency"], 0.40 / 0.55, places=3)
        self.assertAlmostEqual(eff["freshness"], 0.15 / 0.55, places=3)
        self.assertNotIn("success", eff)

    def test_no_available_components(self):
        score, eff = combine(
            {"latency": None, "success": None, "freshness": None, "anonymity": None},
            DEFAULT_WEIGHTS,
        )
        self.assertIsNone(score)
        self.assertEqual(eff, {})


class TierTests(unittest.TestCase):
    def test_default_thresholds(self):
        self.assertEqual(tier_for(80.0, DEFAULT_TIERS), "gold")
        self.assertEqual(tier_for(79.9, DEFAULT_TIERS), "silver")
        self.assertEqual(tier_for(50.0, DEFAULT_TIERS), "silver")
        self.assertEqual(tier_for(20.0, DEFAULT_TIERS), "bronze")
        self.assertEqual(tier_for(19.9, DEFAULT_TIERS), "excluded")
        self.assertEqual(tier_for(None, DEFAULT_TIERS), "excluded")

    def test_custom_thresholds(self):
        tiers = {"gold": 90, "silver": 60, "bronze": 30}
        self.assertEqual(tier_for(80.0, tiers), "silver")
        self.assertEqual(tier_for(29.9, tiers), "excluded")


class ConfigTests(unittest.TestCase):
    def test_defaults_load_without_file(self):
        config = load_score_config(None)
        self.assertEqual(config["tiers"], DEFAULT_TIERS)
        self.assertEqual(config["weights"]["latency"], 0.40)

    def test_file_overrides_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "tiers": {"gold": 90, "silver": 60, "bronze": 30},
                        "weights": {"latency": 0.5, "success": 0.5,
                                    "freshness": 0.0, "anonymity": 0.0},
                    }
                ),
                encoding="utf-8",
            )
            config = load_score_config(path)
        self.assertEqual(config["tiers"]["gold"], 90)
        self.assertEqual(config["weights"]["latency"], 0.5)
        self.assertEqual(config["freshness_window_hours"], 24)  # default survives

    def test_bad_tier_ordering_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.json"
            path.write_text(
                json.dumps({"schema_version": 1,
                            "tiers": {"gold": 30, "silver": 50, "bronze": 80}}),
                encoding="utf-8",
            )
            with self.assertRaises(ScoreConfigError):
                load_score_config(path)

    def test_bad_weights_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.json"
            path.write_text(
                json.dumps({"schema_version": 1,
                            "weights": {"latency": -1, "success": 1,
                                        "freshness": 1, "anonymity": 1}}),
                encoding="utf-8",
            )
            with self.assertRaises(ScoreConfigError):
                load_score_config(path)

    def test_bad_schema_version_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "score.json"
            path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
            with self.assertRaises(ScoreConfigError):
                load_score_config(path)


def make_validated_entry(host, port, latency, ok=True, anonymity=None,
                         checked_utc=None, identity=None):
    # default checked_utc = real now so the freshness component is exactly
    # 100 regardless of when the test runs (stage uses datetime.now())
    identity = identity or f"{host}|{port}||"
    return {
        "host": host,
        "port": port,
        "username": "",
        "password": "",
        "claimed_type": "socks5",
        "claimed_anonymity": anonymity,
        "identity": identity,
        "sources": ["src-a"],
        "check": {
            "ok": ok,
            "type_confirmed": "socks5" if ok else None,
            "method_used": "socks5" if ok else None,
            "latency_ms": latency,
            "http_status": 204 if ok else None,
            "checked_utc": checked_utc
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "error": None,
        },
    }


class StageScoreTests(unittest.TestCase):
    def _run_stage(self, data_dir, proxies, config_extra=None):
        validated = data_dir / "validated"
        validated.mkdir(parents=True, exist_ok=True)
        (validated / "proxies_validated.json").write_text(
            json.dumps(proxies), encoding="utf-8"
        )
        cfg = None
        if config_extra:
            cfg = data_dir / "score.json"
            cfg.write_text(
                json.dumps({"schema_version": 1, **config_extra}),
                encoding="utf-8",
            )
        return stage_score(Path("unused"), data_dir, score_cfg_path=cfg)

    def test_hand_picked_tiers(self):
        # A: elite + fastest + fresh, no history yet (1 event) —
        #    available weights = latency .40 + freshness .15 + anonymity .15
        #    → score = 100*(.40/.70) + 100*(.15/.70) + 100*(.15/.70) = 100 → gold
        # B: no anonymity claim, no history, SLOWEST + fresh —
        #    available = latency .40 + freshness .15
        #    → score = 0*(.40/.55) + 100*(.15/.55) = 27.27 → bronze
        #    (0.0 latency is an available VALUE, not a missing component)
        # C: dead proxy → never scored
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            proxies = [
                make_validated_entry("1.1.1.1", 1000, 50.0, anonymity="elite"),
                make_validated_entry("2.2.2.2", 2000, 900.0, anonymity=None),
                make_validated_entry("3.3.3.3", 3000, 100.0, ok=False),
            ]
            result = self._run_stage(data_dir, proxies)
            self.assertTrue(result.ok, result.detail)
            scored = json.loads(
                (data_dir / "scored" / "proxies_scored.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(len(scored), 2)  # dead proxy excluded
            by_host = {e["host"]: e for e in scored}
            a = by_host["1.1.1.1"]
            self.assertEqual(a["score"]["components"]["latency"], 100.0)
            self.assertEqual(a["score"]["components"]["anonymity"], 100)
            self.assertIsNone(a["score"]["components"]["success"])
            self.assertEqual(a["score"]["total"], 100.0)
            self.assertEqual(a["score"]["tier"], "gold")
            self.assertEqual(a["history"]["total_events"], 1)
            self.assertEqual(a["history"]["consecutive_successes"], 1)
            b = by_host["2.2.2.2"]
            self.assertEqual(b["score"]["components"]["latency"], 0.0)
            self.assertIsNone(b["score"]["components"]["anonymity"])
            self.assertEqual(b["score"]["total"], 27.27)
            self.assertEqual(b["score"]["tier"], "bronze")

    def test_success_component_from_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            # pre-seed history: proxy 9.9.9.9 has ok, ok in the past
            hist = {"schema_version": 1, "identities": {"9.9.9.9|777||": {
                "events": [
                    {"utc": (NOW - timedelta(days=1)).isoformat(timespec="seconds"),
                     "ok": True, "latency_ms": 100.0},
                    {"utc": (NOW - timedelta(days=2)).isoformat(timespec="seconds"),
                     "ok": True, "latency_ms": 100.0},
                ]
            }}}
            hist_path = data_dir / "history" / "check_history.json"
            hist_path.parent.mkdir(parents=True)
            hist_path.write_text(json.dumps(hist), encoding="utf-8")
            proxies = [
                make_validated_entry("9.9.9.9", 777, 100.0),
                make_validated_entry("8.8.8.8", 888, 500.0),
            ]
            result = self._run_stage(data_dir, proxies)
            self.assertTrue(result.ok, result.detail)
            scored = json.loads(
                (data_dir / "scored" / "proxies_scored.json").read_text(
                    encoding="utf-8"
                )
            )
            by_host = {e["host"]: e for e in scored}
            a = by_host["9.9.9.9"]
            # 3 events now (2 prior + this run), all ok → success 100
            self.assertEqual(a["history"]["total_events"], 3)
            self.assertEqual(a["score"]["components"]["success"], 100.0)
            # two equal latencies → both latency 100; all-100 components → 100
            self.assertEqual(a["score"]["total"], 100.0)
            self.assertEqual(a["score"]["tier"], "gold")
            b = by_host["8.8.8.8"]
            # slowest of two → latency 0; fresh 100, success unavailable
            # score = 0*(.4/.55) + 100*(.15/.55) = 27.27 → bronze
            self.assertEqual(b["score"]["components"]["success"], None)
            self.assertEqual(b["score"]["total"], 27.27)
            self.assertEqual(b["score"]["tier"], "bronze")

    def test_history_persisted_and_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            hist = {"schema_version": 1, "identities": {
                "stale|1|": {"events": [
                    {"utc": (NOW - timedelta(days=30)).isoformat(timespec="seconds"),
                     "ok": False, "latency_ms": None}
                ]}
            }}
            hist_path = data_dir / "history" / "check_history.json"
            hist_path.parent.mkdir(parents=True)
            hist_path.write_text(json.dumps(hist), encoding="utf-8")
            proxies = [make_validated_entry("5.5.5.5", 80, 100.0, ok=False)]
            result = self._run_stage(data_dir, proxies)
            self.assertTrue(result.ok, result.detail)
            saved = json.loads(hist_path.read_text(encoding="utf-8"))
            self.assertNotIn("stale|1|", saved["identities"])
            self.assertIn("5.5.5.5|80||", saved["identities"])
            report = json.loads(
                (data_dir / "scored" / "score_report.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(report["history"]["identities_pruned"], 1)
            self.assertEqual(report["tier_distribution"]["excluded"], 0)
            # dead-only run: nothing scored
            self.assertEqual(report["input"]["alive"], 0)

    def test_missing_stage3_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = stage_score(Path("unused"), Path(tmp))
            self.assertFalse(result.ok)
            self.assertIn("run validate first", result.detail)


if __name__ == "__main__":
    unittest.main()
