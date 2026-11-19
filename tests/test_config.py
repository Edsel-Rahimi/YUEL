"""Tests for sources-file loading (schema v2 — plain-proxy scope)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from yuel.config import ConfigError, load_sources

VALID = {
    "schema_version": 2,
    "defaults": {
        "timeout_seconds": 15,
        "max_bytes": 1000000,
        "fetch_concurrency": 4,
        "user_agent": "test-agent/1.0",
    },
    "sources": [
        {
            "id": "src-a",
            "url": "https://example.com/list.txt",
            "format": "ip:port",
            "claimed_type": "socks5",
            "claimed_country": False,
            "claimed_anonymity": None,
            "enabled": True,
            "notes": "test source",
        },
        {
            "id": "src-b",
            "url": "https://example.com/other.csv",
            "format": "proto-prefixed",
            "claimed_type": None,
            "claimed_country": True,
            "enabled": False,
        },
    ],
}


def write_config(tmp: str, data: dict) -> Path:
    path = Path(tmp) / "sources.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


class LoadSourcesTests(unittest.TestCase):
    def test_valid_file_loads(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_sources(write_config(tmp, VALID))
        self.assertEqual(len(cfg.sources), 2)
        self.assertEqual(cfg.timeout_seconds, 15)
        self.assertEqual(cfg.max_bytes, 1000000)
        self.assertEqual(cfg.fetch_concurrency, 4)
        self.assertEqual(cfg.user_agent, "test-agent/1.0")
        self.assertEqual(cfg.sources[0].format, "ip:port")
        self.assertEqual(cfg.sources[0].claimed_type, "socks5")
        self.assertFalse(cfg.sources[1].enabled)
        self.assertEqual(cfg.sources[1].claimed_type, None)

    def test_claim_defaults_filled(self):
        data = {
            "schema_version": 2,
            "sources": [
                {"id": "a", "url": "https://example.com/x", "format": "ip:port"}
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cfg = load_sources(write_config(tmp, data))
        self.assertIsNone(cfg.sources[0].claimed_type)
        self.assertFalse(cfg.sources[0].claimed_country)
        self.assertIsNone(cfg.sources[0].claimed_anonymity)
        self.assertTrue(cfg.sources[0].enabled)

    def test_schema_version_2_required(self):
        data = dict(VALID)
        data["schema_version"] = 1
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_sources(write_config(tmp, data))
        self.assertIn("schema_version", str(ctx.exception))

    def test_invalid_format_rejected(self):
        data = json.loads(json.dumps(VALID))
        data["sources"][0]["format"] = "ssr-uris"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_sources(write_config(tmp, data))
        self.assertIn("format", str(ctx.exception))

    def test_invalid_claimed_type_rejected(self):
        data = json.loads(json.dumps(VALID))
        data["sources"][0]["claimed_type"] = "ssr"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_sources(write_config(tmp, data))
        self.assertIn("claimed_type", str(ctx.exception))

    def test_invalid_claimed_anonymity_rejected(self):
        data = json.loads(json.dumps(VALID))
        data["sources"][0]["claimed_anonymity"] = "ultra"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_sources(write_config(tmp, data))
        self.assertIn("claimed_anonymity", str(ctx.exception))

    def test_claimed_country_must_be_bool(self):
        data = json.loads(json.dumps(VALID))
        data["sources"][0]["claimed_country"] = "yes"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_sources(write_config(tmp, data))

    def test_duplicate_ids_rejected(self):
        data = json.loads(json.dumps(VALID))
        data["sources"][1]["id"] = "src-a"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_sources(write_config(tmp, data))
        self.assertIn("duplicate", str(ctx.exception))

    def test_non_http_url_rejected(self):
        data = json.loads(json.dumps(VALID))
        data["sources"][0]["url"] = "ftp://example.com/x"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_sources(write_config(tmp, data))

    def test_empty_sources_rejected(self):
        data = json.loads(json.dumps(VALID))
        data["sources"] = []
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError):
                load_sources(write_config(tmp, data))

    def test_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ConfigError) as ctx:
                load_sources(Path(tmp) / "nope.json")
        self.assertIn("not found", str(ctx.exception))

    def test_real_config_file_loads(self):
        from yuel.config import default_sources_path

        cfg = load_sources(default_sources_path())
        enabled = [s for s in cfg.sources if s.enabled]
        self.assertGreaterEqual(len(enabled), 20)
        formats = {s.format for s in cfg.sources}
        self.assertTrue(
            formats
            <= {
                "ip:port",
                "ip:port:user:pass",
                "ip:port:country",
                "user:pass@ip:port",
                "proto-prefixed",
                "json-structured",
            }
        )
        ids = [s.id for s in cfg.sources]
        for expected in (
            "thespeedx-socks5",
            "proxifly-all",
            "vpslab-all",
            "b0ba67-http",
            "geonode-api",
            "proxyscrape-socks5",
        ):
            self.assertIn(expected, ids)


if __name__ == "__main__":
    unittest.main()
