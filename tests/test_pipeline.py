"""Tests for the pipeline orchestrator (file-based, no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yuel.pipeline import stage_normalize

UUID = "550e8400-e29b-41d4-a716-446655440000"


def make_collected_dir(data_dir: Path, endpoints: list) -> Path:
    collected = data_dir / "collected"
    collected.mkdir(parents=True)
    (collected / "endpoints_raw.json").write_text(
        json.dumps(endpoints), encoding="utf-8"
    )
    return data_dir


class StageNormalizeTests(unittest.TestCase):
    def test_writes_normalized_output(self):
        endpoints = [
            {
                "scheme": "vless",
                "host": "v.example.com",
                "port": 443,
                "secret": UUID,
                "params": {},
                "name": "a",
                "extra": {},
                "identity": f"vless|v.example.com|443|{UUID}",
                "source": "src-a",
            },
            {
                "scheme": "vless",
                "host": "v.example.com",
                "port": 443,
                "secret": UUID,
                "params": {},
                "name": "b",
                "extra": {},
                "identity": f"vless|v.example.com|443|{UUID}",
                "source": "src-b",
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_collected_dir(Path(tmp), endpoints)
            result = stage_normalize(Path("unused"), data_dir)
            self.assertTrue(result.ok, result.detail)
            self.assertEqual(len(result.outputs), 2)

            normalized = json.loads(result.outputs[0].read_text(encoding="utf-8"))
            self.assertEqual(len(normalized), 1)
            self.assertEqual(normalized[0]["sources"], ["src-a", "src-b"])

            report = json.loads(result.outputs[1].read_text(encoding="utf-8"))
            self.assertEqual(report["stage"], "normalize")
            self.assertEqual(report["output"]["duplicates_collapsed"], 1)

    def test_fails_gracefully_when_stage1_output_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = stage_normalize(Path("unused"), Path(tmp))
            self.assertFalse(result.ok)
            self.assertIn("run collect first", result.detail)

    def test_fails_gracefully_on_corrupt_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            collected = data_dir / "collected"
            collected.mkdir(parents=True)
            (collected / "endpoints_raw.json").write_text("{not json", encoding="utf-8")
            result = stage_normalize(Path("unused"), data_dir)
            self.assertFalse(result.ok)
            self.assertIn("cannot read", result.detail)

    def test_fails_gracefully_on_non_list_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            collected = data_dir / "collected"
            collected.mkdir(parents=True)
            (collected / "endpoints_raw.json").write_text('{"a": 1}', encoding="utf-8")
            result = stage_normalize(Path("unused"), data_dir)
            self.assertFalse(result.ok)
            self.assertIn("not a JSON list", result.detail)


if __name__ == "__main__":
    unittest.main()
