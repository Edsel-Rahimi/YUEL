"""Tests for the pipeline orchestrator (file-based, no network)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yuel.pipeline import stage_normalize


class ImportWiringTests(unittest.TestCase):
    def test_stage_validate_importable_from_pipeline(self):
        # regression: run_pipeline's stage chain references the name directly
        from yuel.pipeline import stage_validate

        self.assertTrue(callable(stage_validate))


def make_collected_dir(data_dir: Path, proxies: list) -> Path:
    collected = data_dir / "collected"
    collected.mkdir(parents=True)
    (collected / "proxies_raw.json").write_text(
        json.dumps(proxies), encoding="utf-8"
    )
    return data_dir


def make_proxy(**overrides) -> dict:
    fields = {
        "host": "1.2.3.4",
        "port": 8080,
        "username": "",
        "password": "",
        "claimed_type": "socks5",
        "claimed_country": None,
        "claimed_anonymity": None,
        "identity": "1.2.3.4|8080||",
        "source": "src-a",
    }
    fields.update(overrides)
    return fields


class StageNormalizeTests(unittest.TestCase):
    def test_writes_normalized_output(self):
        proxies = [
            make_proxy(source="src-a"),
            make_proxy(source="src-b", claimed_type=None),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = make_collected_dir(Path(tmp), proxies)
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
            (collected / "proxies_raw.json").write_text("{not json", encoding="utf-8")
            result = stage_normalize(Path("unused"), data_dir)
            self.assertFalse(result.ok)
            self.assertIn("cannot read", result.detail)

    def test_fails_gracefully_on_non_list_input(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            collected = data_dir / "collected"
            collected.mkdir(parents=True)
            (collected / "proxies_raw.json").write_text('{"a": 1}', encoding="utf-8")
            result = stage_normalize(Path("unused"), data_dir)
            self.assertFalse(result.ok)
            self.assertIn("not a JSON list", result.detail)


if __name__ == "__main__":
    unittest.main()
