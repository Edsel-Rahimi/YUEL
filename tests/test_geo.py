"""Tests for stage 5 (geo): fixture-table lookup, cache/refresh, degradation.

All tests use a tiny in-memory TSV fixture (gzip-compressed for the fetch
seam) — never the real multi-MB table, and never the network.
"""

from __future__ import annotations

import gzip
import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from yuel.geo import (
    GeoConfigError,
    GeoTable,
    load_geo_config,
    load_table,
    stage_geo,
)

FIXTURE_TSV = (
    "# comment line\n"
    "16777216\t16777471\tAS1\tUS\tTest One\n"      # 1.0.0.0 – 1.0.0.255
    "16777472\t16778239\tAS2\tAU\tTest Two\n"      # 1.0.1.0 – 1.0.3.255
    "67174657\t67174657\tAS3\tIT\tTest Three\n"    # 4.1.1.1 exactly
)
FIXTURE_GZ = gzip.compress(FIXTURE_TSV.encode("utf-8"))


def make_scored(host, port, identity=None):
    return {
        "host": host,
        "port": port,
        "username": "",
        "password": "",
        "claimed_type": "socks5",
        "identity": identity or f"{host}|{port}||",
        "score": {"total": 50.0, "tier": "silver"},
        "history": {"consecutive_successes": 1, "consecutive_failures": 0},
    }


class IpToIntTests(unittest.TestCase):
    def test_valid(self):
        from yuel.geo import ip_to_int

        self.assertEqual(ip_to_int("1.0.0.0"), 16777216)
        self.assertEqual(ip_to_int("255.255.255.255"), 4294967295)

    def test_invalid(self):
        from yuel.geo import ip_to_int

        for bad in ("999.1.1.1", "abc", "1.2.3", "1.2.3.4.5", "01.2.3.4", "[::1]"):
            self.assertIsNone(ip_to_int(bad), bad)


class GeoTableTests(unittest.TestCase):
    def setUp(self):
        self.table = GeoTable.from_tsv(FIXTURE_TSV)

    def test_inside_range(self):
        self.assertEqual(self.table.lookup("1.0.0.55"), "US")
        self.assertEqual(self.table.lookup("1.0.2.128"), "AU")

    def test_boundaries_inclusive(self):
        self.assertEqual(self.table.lookup("1.0.0.0"), "US")
        self.assertEqual(self.table.lookup("1.0.0.255"), "US")
        self.assertEqual(self.table.lookup("1.0.1.0"), "AU")
        self.assertEqual(self.table.lookup("1.0.3.255"), "AU")

    def test_gap_outside_any_range(self):
        # 2.0.0.0 lies between the fixture ranges → not covered
        self.assertIsNone(self.table.lookup("2.0.0.0"))
        self.assertIsNone(self.table.lookup("255.255.255.255"))

    def test_single_ip_range_exact_match(self):
        self.assertEqual(self.table.lookup("4.1.1.1"), "IT")

    def test_below_first_range(self):
        self.assertIsNone(self.table.lookup("0.0.0.1"))

    def test_domain_and_ipv6_never_matched(self):
        self.assertIsNone(self.table.lookup("proxy.example.com"))
        self.assertIsNone(self.table.lookup("[2001:db8::1]"))

    def test_invalid_lines_skipped_and_unsorted_input_sorted(self):
        messy = (
            "not an int\tnope\tAS\tUS\tx\n"
            "10\t5\tAS\tUS\tnegative\n"          # end < start
            "1\t2\tAS\tUSA\tthree-letter\n"      # bad country code
            "3\t4\tAS\n"                          # too few columns
            "1000\t2000\tAS9\tDE\tok\n"
        )
        table = GeoTable.from_tsv(messy)
        self.assertEqual(table.ranges, [(1000, 2000, "DE")])
        # integer 1000 = 0.0.3.232 — inside the DE range
        self.assertEqual(table.lookup("0.0.3.232"), "DE")


class LoadTableTests(unittest.TestCase):
    def _config(self, refresh_hours=72):
        return {
            "table_url": "https://example.com/ip2asn-v4.tsv.gz",
            "cache_dir": "cache/geo",
            "refresh_hours": refresh_hours,
            "fetch_timeout_seconds": 5,
            "max_bytes": 1000000,
        }

    def test_download_when_no_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache/geo/ip2asn-v4.tsv.gz"
            table, info = load_table(
                self._config(), cache, fetch=lambda *a: FIXTURE_GZ
            )
            self.assertEqual(info["source"], "downloaded")
            self.assertIsNotNone(table)
            self.assertEqual(table.lookup("1.0.0.55"), "US")
            self.assertTrue(cache.exists())

    def test_fresh_cache_skips_fetch(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache/geo/ip2asn-v4.tsv.gz"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(FIXTURE_GZ)
            calls = []

            def fetch(*args):
                calls.append(args)
                return FIXTURE_GZ

            table, info = load_table(self._config(), cache, fetch=fetch)
            self.assertEqual(info["source"], "cache-fresh")
            self.assertEqual(calls, [])
            self.assertIsNotNone(table)

    def test_stale_cache_used_when_fetch_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache/geo/ip2asn-v4.tsv.gz"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(FIXTURE_GZ)
            old = time.time() - 100 * 3600
            os.utime(cache, (old, old))  # 100h old > 72h refresh window

            def failing_fetch(*args):
                raise OSError("network down")

            table, info = load_table(self._config(), cache, fetch=failing_fetch)
            self.assertEqual(info["source"], "cache-stale")
            self.assertIn("stale cache", info["warning"])
            self.assertIsNotNone(table)
            self.assertEqual(table.lookup("1.0.0.55"), "US")

    def test_no_cache_and_fetch_fails_degrades_to_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache/geo/ip2asn-v4.tsv.gz"

            def failing_fetch(*args):
                raise OSError("network down")

            table, info = load_table(self._config(), cache, fetch=failing_fetch)
            self.assertIsNone(table)
            self.assertEqual(info["source"], "none")
            self.assertIn("unclassified", info["warning"])

    def test_corrupt_cache_refetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "cache/geo/ip2asn-v4.tsv.gz"
            cache.parent.mkdir(parents=True)
            cache.write_bytes(b"this is not gzip")
            table, info = load_table(
                self._config(), cache, fetch=lambda *a: FIXTURE_GZ
            )
            self.assertEqual(info["source"], "downloaded")
            self.assertIsNotNone(table)


class ConfigTests(unittest.TestCase):
    def test_defaults_without_file(self):
        config = load_geo_config(None)
        self.assertIn("iptoasn.com", config["table_url"])
        self.assertEqual(config["refresh_hours"], 72)

    def test_file_overrides_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "geo.json"
            path.write_text(
                json.dumps({"schema_version": 1, "refresh_hours": 24}),
                encoding="utf-8",
            )
            config = load_geo_config(path)
        self.assertEqual(config["refresh_hours"], 24)
        self.assertIn("iptoasn.com", config["table_url"])

    def test_bad_config_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "geo.json"
            path.write_text(
                json.dumps({"schema_version": 1, "table_url": "ftp://x"}),
                encoding="utf-8",
            )
            with self.assertRaises(GeoConfigError):
                load_geo_config(path)


class StageGeoTests(unittest.TestCase):
    def _run(self, data_dir, proxies, fetch):
        scored = data_dir / "scored"
        scored.mkdir(parents=True, exist_ok=True)
        (scored / "proxies_scored.json").write_text(
            json.dumps(proxies), encoding="utf-8"
        )
        cfg = data_dir / "geo.json"
        cfg.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "table_url": "https://example.com/ip2asn-v4.tsv.gz",
                    "refresh_hours": 72,
                }
            ),
            encoding="utf-8",
        )
        return stage_geo(Path("unused"), data_dir, geo_cfg_path=cfg, fetch=fetch)

    def test_classification_and_unclassified(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            proxies = [
                make_scored("1.0.0.55", 8080),        # US
                make_scored("1.0.2.10", 3128),        # AU
                make_scored("2.0.0.1", 1080),         # gap → unclassified
                make_scored("proxy.example.com", 80), # domain → unclassified
                make_scored("[2001:db8::1]", 1080),   # IPv6 → unclassified
            ]
            result = self._run(data_dir, proxies, lambda *a: FIXTURE_GZ)
            self.assertTrue(result.ok, result.detail)
            geo = json.loads(
                (data_dir / "geo" / "proxies_geo.json").read_text(encoding="utf-8")
            )
            countries = {e["identity"]: e["country"] for e in geo}
            self.assertEqual(countries["1.0.0.55|8080||"], "US")
            self.assertEqual(countries["1.0.2.10|3128||"], "AU")
            self.assertEqual(countries["2.0.0.1|1080||"], "unclassified")
            self.assertEqual(countries["proxy.example.com|80||"], "unclassified")
            self.assertEqual(countries["[2001:db8::1]|1080||"], "unclassified")
            report = json.loads(
                (data_dir / "geo" / "geo_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(report["classified"], 2)
            self.assertEqual(report["unclassified"], 3)
            self.assertEqual(
                report["unclassified_reasons"]["domain_or_ipv6_host"], 2
            )
            self.assertEqual(report["unclassified_reasons"]["not_in_table"], 1)
            self.assertEqual(report["table"]["source"], "downloaded")
            self.assertEqual(report["by_country"], {"AU": 1, "US": 1})

    def test_graceful_degradation_when_table_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            proxies = [make_scored("1.0.0.55", 8080)]

            def failing_fetch(*args):
                raise OSError("network down")

            result = self._run(data_dir, proxies, failing_fetch)
            self.assertTrue(result.ok, result.detail)  # never crashes
            self.assertIn("WARNING", result.detail)
            geo = json.loads(
                (data_dir / "geo" / "proxies_geo.json").read_text(encoding="utf-8")
            )
            self.assertEqual(geo[0]["country"], "unclassified")
            report = json.loads(
                (data_dir / "geo" / "geo_report.json").read_text(encoding="utf-8")
            )
            self.assertEqual(
                report["unclassified_reasons"]["table_unavailable"], 1
            )
            self.assertTrue(report["table"]["warning"])

    def test_missing_stage4_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = stage_geo(Path("unused"), Path(tmp))
            self.assertFalse(result.ok)
            self.assertIn("run score first", result.detail)


if __name__ == "__main__":
    unittest.main()
