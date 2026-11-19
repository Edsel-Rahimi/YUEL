"""Tests for stage 1 (collect): plain-proxy line parsing, identity, run logic.

All tests are pure-logic — no network access.
"""

from __future__ import annotations

import json
import unittest
import urllib.error

from yuel.collect import (
    parse_entry,
    process_source,
    proxy_identity,
    run_collect,
    validate_proxy,
)
from yuel.config import CollectConfig, Source


def make_source(**overrides) -> Source:
    fields = {
        "id": "test-src",
        "url": "https://example.com/list.txt",
        "format": "ip:port",
        "claimed_type": None,
        "claimed_country": False,
        "claimed_anonymity": None,
        "enabled": True,
        "notes": "",
    }
    fields.update(overrides)
    return Source(**fields)


class ParseIpPortTests(unittest.TestCase):
    def test_basic(self):
        proxy, reason = parse_entry("1.2.3.4:8080", make_source(claimed_type="socks5"))
        self.assertIsNone(reason)
        self.assertEqual(proxy["host"], "1.2.3.4")
        self.assertEqual(proxy["port"], 8080)
        self.assertEqual(proxy["username"], "")
        self.assertEqual(proxy["claimed_type"], "socks5")
        self.assertEqual(proxy["source"], "test-src")
        self.assertEqual(proxy["identity"], "1.2.3.4|8080||")

    def test_host_case_preserved_identity_lowercased(self):
        proxy, _ = parse_entry("Example.COM.:8080", make_source())
        self.assertEqual(proxy["host"], "Example.COM")  # kept as parsed
        self.assertEqual(proxy["identity"], "example.com|8080||")  # key lowercased

    def test_comments_and_blanks_not_failures(self):
        for line in ("# comment", "", "   ", "# Updated Proxies: 2026-11-19"):
            proxy, reason = parse_entry(line, make_source())
            self.assertIsNone(proxy)
            self.assertIsNone(reason)

    def test_domain_host(self):
        proxy, reason = parse_entry("proxy.example.com:3128", make_source())
        self.assertIsNone(reason)
        self.assertEqual(proxy["host"], "proxy.example.com")

    def test_junk_lines_rejected(self):
        for line in ("error code: 1015", "hello world", "1.2.3.4", "1.2.3.4:0",
                     "1.2.3.4:70000", "1.2.3.4:8080:extra:fields:here",
                     "999.999.999.999:80"):
            proxy, reason = parse_entry(line, make_source())
            self.assertIsNone(proxy, line)
            self.assertIsNotNone(reason, line)


class ParseCredsFormatTests(unittest.TestCase):
    def test_ip_port_user_pass(self):
        src = make_source(format="ip:port:user:pass")
        proxy, reason = parse_entry("1.2.3.4:8080:alice:s3cret", src)
        self.assertIsNone(reason)
        self.assertEqual(proxy["username"], "alice")
        self.assertEqual(proxy["password"], "s3cret")
        self.assertEqual(proxy["identity"], "1.2.3.4|8080|alice|s3cret")

    def test_password_may_contain_colons(self):
        src = make_source(format="ip:port:user:pass")
        proxy, _ = parse_entry("1.2.3.4:8080:alice:pa:ss:word", src)
        self.assertEqual(proxy["password"], "pa:ss:word")

    def test_credless_line_tolerated_in_creds_format(self):
        src = make_source(format="ip:port:user:pass", claimed_type="http")
        proxy, _ = parse_entry("5.6.7.8:3128", src)
        self.assertEqual(proxy["username"], "")
        self.assertEqual(proxy["claimed_type"], "http")

    def test_two_field_cred_line_with_single_colon_pass_rejected(self):
        # "ip:port:user" is ambiguous and malformed in this format
        src = make_source(format="ip:port:user:pass")
        proxy, reason = parse_entry("1.2.3.4:8080:alice", src)
        self.assertIsNone(proxy)
        self.assertIn("expected ip:port:user:pass", reason)

    def test_user_pass_at_host_port(self):
        src = make_source(format="user:pass@ip:port")
        proxy, reason = parse_entry("bob:pw@1.2.3.4:1080", src)
        self.assertIsNone(reason)
        self.assertEqual((proxy["host"], proxy["port"]), ("1.2.3.4", 1080))
        self.assertEqual(proxy["username"], "bob")
        self.assertEqual(proxy["password"], "pw")

    def test_whitespace_in_creds_rejected(self):
        src = make_source(format="user:pass@ip:port")
        proxy, reason = parse_entry("b ob:pw@1.2.3.4:1080", src)
        self.assertIsNone(proxy)
        self.assertIn("username", reason)


class ParseCountryAndProtoTests(unittest.TestCase):
    def test_ip_port_country(self):
        src = make_source(format="ip:port:country", claimed_type="socks5")
        proxy, reason = parse_entry("1.2.3.4:8080:United States", src)
        self.assertIsNone(reason)
        self.assertEqual(proxy["claimed_country"], "United States")
        self.assertEqual(proxy["port"], 8080)

    def test_proto_prefixed_socks5(self):
        src = make_source(format="proto-prefixed")
        proxy, reason = parse_entry("socks5://10.0.0.1:1080", src)
        self.assertIsNone(reason)
        self.assertEqual(proxy["claimed_type"], "socks5")

    def test_proto_prefixed_csv_country_city(self):
        src = make_source(format="proto-prefixed")
        proxy, reason = parse_entry("socks5://10.0.0.1:1080,US,Alexandria", src)
        self.assertIsNone(reason)
        self.assertEqual(proxy["claimed_type"], "socks5")
        self.assertEqual(proxy["claimed_country"], "US")

    def test_proto_prefixed_with_creds(self):
        src = make_source(format="proto-prefixed")
        proxy, reason = parse_entry("http://carol:pw@10.0.0.1:3128", src)
        self.assertIsNone(reason)
        self.assertEqual(proxy["username"], "carol")
        self.assertEqual(proxy["password"], "pw")
        self.assertEqual(proxy["claimed_type"], "http")

    def test_proto_prefixed_unknown_scheme_falls_back_to_source_claim(self):
        src = make_source(format="proto-prefixed", claimed_type="socks4")
        proxy, _ = parse_entry("socks://10.0.0.1:1080", src)
        self.assertEqual(proxy["claimed_type"], "socks4")

    def test_proto_prefixed_without_prefix_rejected(self):
        src = make_source(format="proto-prefixed")
        proxy, reason = parse_entry("1.2.3.4:8080", src)
        self.assertIsNone(proxy)
        self.assertIn("protocol:// prefix", reason)

    def test_source_level_anonymity_claim(self):
        src = make_source(claimed_anonymity="elite")
        proxy, _ = parse_entry("1.2.3.4:8080", src)
        self.assertEqual(proxy["claimed_anonymity"], "elite")


class ValidateProxyTests(unittest.TestCase):
    def test_bad_ipv4_octet(self):
        ok, reason = validate_proxy({"host": "1.2.3.999", "port": 8080})
        self.assertFalse(ok)
        self.assertIn("IPv4", reason)

    def test_bad_port_type(self):
        ok, reason = validate_proxy({"host": "1.2.3.4", "port": "8080"})
        self.assertFalse(ok)
        self.assertIn("port", reason)

    def test_valid_proxy(self):
        ok, reason = validate_proxy(
            {"host": "example.com", "port": 443, "username": "u", "password": "p"}
        )
        self.assertTrue(ok, reason)

    def test_bad_claimed_type(self):
        ok, reason = validate_proxy(
            {"host": "1.2.3.4", "port": 80, "claimed_type": "ssr"}
        )
        self.assertFalse(ok)
        self.assertIn("claimed_type", reason)


class IdentityTests(unittest.TestCase):
    def test_creds_are_part_of_identity(self):
        base = {"host": "1.2.3.4", "port": 8080}
        self.assertEqual(proxy_identity(base), "1.2.3.4|8080||")
        self.assertEqual(
            proxy_identity({**base, "username": "u"}),
            "1.2.3.4|8080|u|",
        )
        self.assertEqual(
            proxy_identity({**base, "username": "u", "password": "p"}),
            "1.2.3.4|8080|u|p",
        )


def fake_fetch(text: str):
    def _fetch(url, timeout, max_bytes, user_agent="x"):
        return 200, text.encode("utf-8")

    return _fetch


class ProcessSourceTests(unittest.TestCase):
    def test_line_format_source(self):
        src = make_source(claimed_type="socks5")
        cfg = CollectConfig(sources=[src])
        text = "# header\n1.2.3.4:8080\n5.6.7.8:3128\nerror code: 1015\n\n"
        result = process_source(src, cfg, fetch=fake_fetch(text))
        self.assertTrue(result.ok)
        self.assertEqual(result.entries_parsed, 2)
        self.assertEqual(result.entries_failed, 1)
        self.assertTrue(result.failure_samples)
        self.assertEqual(result.proxies[0]["claimed_type"], "socks5")

    def test_dead_fetch_recorded_not_raised(self):
        def dead_fetch(url, timeout, max_bytes, user_agent="x"):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        src = make_source()
        result = process_source(src, CollectConfig(sources=[src]), fetch=dead_fetch)
        self.assertFalse(result.ok)
        self.assertIn("404", result.error)
        self.assertEqual(result.entries_parsed, 0)

    def test_json_structured_geonode_shape(self):
        src = make_source(format="json-structured")
        cfg = CollectConfig(sources=[src])
        doc = json.dumps(
            {
                "total": 2,
                "data": [
                    {
                        "ip": "10.0.0.1",
                        "port": "1080",
                        "protocols": ["socks5"],
                        "country": "DE",
                        "anonymityLevel": "elite",
                    },
                    {
                        "ip": "10.0.0.2",
                        "port": 3128,
                        "protocols": ["http", "socks5"],
                        "country": "FR",
                    },
                ],
            }
        )
        result = process_source(src, cfg, fetch=fake_fetch(doc))
        self.assertTrue(result.ok)
        self.assertEqual(result.entries_parsed, 2)
        first, second = result.proxies
        self.assertEqual(first["claimed_type"], "socks5")
        self.assertEqual(first["claimed_country"], "DE")
        self.assertEqual(first["claimed_anonymity"], "elite")
        # ambiguous multi-protocol record: no type claim, validation decides
        self.assertIsNone(second["claimed_type"])

    def test_json_invalid_document_recorded_as_failure(self):
        src = make_source(format="json-structured")
        result = process_source(
            src, CollectConfig(sources=[src]), fetch=fake_fetch("<html>oops")
        )
        self.assertTrue(result.ok)  # fetch itself worked
        self.assertEqual(result.entries_parsed, 0)
        self.assertEqual(result.entries_failed, 1)
        self.assertIn("not valid JSON", result.failure_samples[0])


class RunCollectTests(unittest.TestCase):
    def test_disabled_sources_skipped_and_report_shape(self):
        enabled_src = make_source(id="src-on", claimed_type="http")
        disabled_src = make_source(id="src-off", enabled=False)
        cfg = CollectConfig(sources=[enabled_src, disabled_src])
        report = run_collect(
            cfg, fetch=fake_fetch("1.2.3.4:8080\n"), max_workers=1
        )
        self.assertEqual(report["totals"]["sources_enabled"], 1)
        self.assertEqual(report["totals"]["entries_parsed"], 1)
        self.assertEqual(report["disabled_sources"][0]["id"], "src-off")
        self.assertIn("proxies", report)
        self.assertEqual(report["proxies"][0]["identity"], "1.2.3.4|8080||")

    def test_worker_crash_recorded(self):
        src = make_source(id="boom")

        def crashing_fetch(url, timeout, max_bytes, user_agent="x"):
            raise RuntimeError("boom")

        cfg = CollectConfig(sources=[src])
        report = run_collect(cfg, fetch=crashing_fetch, max_workers=1)
        self.assertEqual(report["totals"]["sources_failed"], 1)
        self.assertIn("crashed", report["sources"][0]["error"])


if __name__ == "__main__":
    unittest.main()
