"""Tests for config loading/validation — pure logic, no network."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yuel.config import ConfigError, load_sources

VALID = {
    "schema_version": 1,
    "defaults": {"timeout_seconds": 10, "max_bytes": 1000, "fetch_concurrency": 2},
    "sources": [
        {
            "id": "src-a",
            "type": "raw_http",
            "url": "https://example.com/a.txt",
            "tags": ["test"],
        },
        {
            "id": "src-b",
            "type": "telegram_preview",
            "url": "https://t.me/s/example",
            "enabled": False,
            "note": "off on purpose",
        },
    ],
}


def write_tmp(config: dict) -> Path:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "sources.json"
        path.write_text(json.dumps(config), encoding="utf-8")
        # load_sources reads lazily, so re-open outside the context via str
        loaded = load_sources(path)
    return loaded  # type: ignore[return-value]


class LoadSourcesTests(unittest.TestCase):
    def test_valid_config_loads(self):
        cfg = write_tmp(VALID)
        self.assertEqual([s.id for s in cfg.sources], ["src-a", "src-b"])
        self.assertEqual(cfg.timeout_seconds, 10)
        self.assertEqual(cfg.max_bytes, 1000)
        self.assertEqual(cfg.fetch_concurrency, 2)
        self.assertTrue(cfg.sources[0].enabled)  # enabled defaults to True
        self.assertFalse(cfg.sources[1].enabled)
        self.assertEqual(cfg.sources[1].note, "off on purpose")

    def test_defaults_apply_when_absent(self):
        cfg = write_tmp({"sources": VALID["sources"]})
        self.assertEqual(cfg.timeout_seconds, 20)
        self.assertEqual(cfg.max_bytes, 8_000_000)
        self.assertEqual(cfg.fetch_concurrency, 6)

    def test_missing_file_raises(self):
        with self.assertRaises(ConfigError):
            load_sources("/nonexistent/sources.json")

    def test_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ConfigError):
                load_sources(path)

    def test_duplicate_ids_rejected(self):
        config = json.loads(json.dumps(VALID))
        config["sources"][1]["id"] = "src-a"
        with self.assertRaises(ConfigError):
            write_tmp(config)

    def test_bad_type_rejected(self):
        config = json.loads(json.dumps(VALID))
        config["sources"][0]["type"] = "rss"
        with self.assertRaises(ConfigError):
            write_tmp(config)

    def test_bad_url_rejected(self):
        config = json.loads(json.dumps(VALID))
        config["sources"][0]["url"] = "ftp://example.com/a.txt"
        with self.assertRaises(ConfigError):
            write_tmp(config)

    def test_bad_id_rejected(self):
        config = json.loads(json.dumps(VALID))
        config["sources"][0]["id"] = "Bad ID!"
        with self.assertRaises(ConfigError):
            write_tmp(config)

    def test_empty_sources_rejected(self):
        with self.assertRaises(ConfigError):
            write_tmp({"sources": []})


if __name__ == "__main__":
    unittest.main()
