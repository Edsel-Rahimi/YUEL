"""Tests for stage 1 (collect): extraction, URI parsing, identity, run logic.

All tests are pure-logic — no network access, no real engines.
"""

from __future__ import annotations

import base64
import json
import unittest
import urllib.error

from yuel import collect
from yuel.config import CollectConfig, Source

UUID = "550e8400-e29b-41d4-a716-446655440000"


def b64(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def vmess_uri(**overrides) -> str:
    payload = {
        "v": "2",
        "ps": "vm node",
        "add": "vm.example.com",
        "port": "443",
        "id": UUID,
        "aid": "0",
        "net": "ws",
        "type": "none",
        "host": "cdn.example.com",
        "path": "/ws",
        "tls": "tls",
        "sni": "sni.example.com",
    }
    payload.update(overrides)
    return "vmess://" + b64(json.dumps(payload))


class ExtractTests(unittest.TestCase):
    def test_extracts_every_supported_scheme(self):
        doc = "\n".join(
            [
                vmess_uri(),
                f"vless://{UUID}@v.example.com:443?security=tls&type=ws#vless-node",
                "trojan://pass@t.example.com:443#trojan-node",
                "ss://" + b64("aes-256-gcm:pw") + "@s.example.com:8388#ss-node",
                "ss://" + b64("chacha20-ietf-poly1305:pw@legacy.example.com:443"),
                "hysteria2://auth@h.example.com:443?sni=h.example.com#hy2",
                "hy2://auth2@h2.example.com:8443#alias",
                f"tuic://{UUID}:pass@u.example.com:443?congestion_control=bbr#tuic",
                "http://ignored.example.com/x",
                "ftp://ignored.example.com",
                "ssr://not-supported",
            ]
        )
        uris, mode = collect.extract_uris(doc)
        self.assertEqual(mode, "text")
        schemes = [u.partition("://")[0] for u in uris]
        self.assertEqual(schemes.count("vmess"), 1)
        self.assertEqual(schemes.count("vless"), 1)
        self.assertEqual(schemes.count("trojan"), 1)
        self.assertEqual(schemes.count("ss"), 2)
        self.assertEqual(schemes.count("hysteria2"), 1)
        self.assertEqual(schemes.count("hy2"), 1)
        self.assertEqual(schemes.count("tuic"), 1)
        self.assertNotIn("http", schemes)
        self.assertNotIn("ssr", schemes)

    def test_removes_literal_duplicates_preserving_order(self):
        doc = "vmess://AAAA\nvmess://BBBB\nvmess://AAAA"
        uris, _ = collect.extract_uris(doc)
        self.assertEqual(uris, ["vmess://AAAA", "vmess://BBBB"])

    def test_comma_separated_tokens_are_split(self):
        doc = "vmess://AAAA,vmess://BBBB"
        uris, _ = collect.extract_uris(doc)
        self.assertEqual(uris, ["vmess://AAAA", "vmess://BBBB"])

    def test_html_escaped_telegram_text(self):
        doc = (
            '<div class="tgme_widget_message_text">New configs'
            f'<a href="vless://{UUID}@v1.example.com:443?security=reality'
            '&amp;sni=www.example.com&amp;pbk=KEY123&amp;type=tcp'
            '#Node%20One">vless</a></div>'
        )
        uris, mode = collect.extract_uris(doc)
        self.assertEqual(mode, "text")
        self.assertEqual(len(uris), 1)
        endpoint, reason = collect.parse_endpoint(uris[0])
        self.assertIsNone(reason)
        self.assertIsNotNone(endpoint)
        self.assertEqual(endpoint["params"]["security"], "reality")
        self.assertEqual(endpoint["params"]["sni"], "www.example.com")
        self.assertEqual(endpoint["params"]["pbk"], "KEY123")
        self.assertEqual(endpoint["name"], "Node One")

    def test_base64_subscription_blob(self):
        doc = "\n".join(
            [
                f"vless://{UUID}@a.example.com:443#one",
                "trojan://pw@b.example.com:443#two",
                "ss://" + b64("aes-256-gcm:pw") + "@c.example.com:8388#three",
            ]
        )
        blob = b64(doc)
        uris, mode = collect.extract_uris(blob)
        self.assertEqual(mode, "base64")
        self.assertEqual(len(uris), 3)

    def test_trailing_punctuation_is_stripped(self):
        doc = vmess_uri() + ")."
        endpoint, reason = collect.parse_endpoint(doc.split(",", 1)[0])
        self.assertIsNone(reason, reason)
        self.assertEqual(endpoint["host"], "vm.example.com")

    def test_empty_document(self):
        self.assertEqual(collect.extract_uris(""), ([], "text"))


class VmessTests(unittest.TestCase):
    def test_canonical_fields(self):
        endpoint, reason = collect.parse_endpoint(vmess_uri())
        self.assertIsNone(reason)
        self.assertEqual(endpoint["scheme"], "vmess")
        self.assertEqual(endpoint["host"], "vm.example.com")
        self.assertEqual(endpoint["port"], 443)
        self.assertEqual(endpoint["secret"], UUID)
        self.assertEqual(endpoint["params"]["net"], "ws")
        self.assertEqual(endpoint["params"]["path"], "/ws")
        self.assertEqual(endpoint["extra"]["alter_id"], 0)
        self.assertEqual(endpoint["name"], "vm node")

    def test_integer_port(self):
        endpoint, reason = collect.parse_endpoint(vmess_uri(port=2053))
        self.assertIsNone(reason)
        self.assertEqual(endpoint["port"], 2053)

    def test_non_json_payload_rejected(self):
        uri = "vmess://" + b64("[1, 2, 3]")
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(endpoint)
        self.assertIn("not a JSON object", reason)

    def test_missing_uuid_rejected(self):
        endpoint, reason = collect.parse_endpoint(vmess_uri(id=""))
        self.assertIsNone(endpoint)
        self.assertIn("missing 'id'", reason)

    def test_missing_host_rejected(self):
        endpoint, reason = collect.parse_endpoint(vmess_uri(add=""))
        self.assertIsNone(endpoint)
        self.assertIn("missing 'add'", reason)


class UserinfoStyleTests(unittest.TestCase):
    def test_vless_params_and_name(self):
        uri = (
            f"vless://{UUID}@v.example.com:443?security=reality&flow=xtls-rprx-vision"
            "&sni=www.example.com&type=tcp#Edge%20Node"
        )
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["scheme"], "vless")
        self.assertEqual(endpoint["secret"], UUID)
        self.assertEqual(endpoint["params"]["flow"], "xtls-rprx-vision")
        self.assertEqual(endpoint["name"], "Edge Node")

    def test_trojan_password(self):
        uri = "trojan://str0ng-pass@t.example.com:443?security=tls&sni=t.example.com#x"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["scheme"], "trojan")
        self.assertEqual(endpoint["secret"], "str0ng-pass")

    def test_tuic_splits_uuid_and_password(self):
        uri = f"tuic://{UUID}:pass-word@tu.example.io:443?congestion_control=bbr#t"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["secret"], UUID)
        self.assertEqual(endpoint["extra"]["password"], "pass-word")

    def test_tuic_without_password_rejected(self):
        endpoint, reason = collect.parse_endpoint(f"tuic://{UUID}@tu.example.io:443")
        self.assertIsNone(endpoint)
        self.assertIn("uuid:password", reason)

    def test_hysteria2_userinfo_auth(self):
        uri = "hysteria2://hunter2@hy.example.org:443?sni=hy.example.org#x"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["secret"], "hunter2")

    def test_hysteria2_query_auth_fallback(self):
        uri = "hysteria2://hy.example.org:8443/?auth=secret99&insecure=0#q"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["host"], "hy.example.org")
        self.assertEqual(endpoint["port"], 8443)
        self.assertEqual(endpoint["secret"], "secret99")

    def test_hysteria2_without_auth_rejected(self):
        endpoint, reason = collect.parse_endpoint("hysteria2://hy.example.org:443#x")
        self.assertIsNone(endpoint)
        self.assertIn("no auth", reason)

    def test_hy2_alias_normalized(self):
        endpoint, reason = collect.parse_endpoint("hy2://auth@h.example.com:8443#x")
        self.assertIsNone(reason)
        self.assertEqual(endpoint["scheme"], "hysteria2")

    def test_bad_uuid_rejected(self):
        endpoint, reason = collect.parse_endpoint("vless://not-a-uuid@v.example.com:443")
        self.assertIsNone(endpoint)
        self.assertIn("uuid", reason)

    def test_bracketed_ipv6(self):
        uri = f"vless://{UUID}@[2001:db8::1]:8443?security=tls#v6"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["host"], "[2001:db8::1]")
        self.assertEqual(endpoint["port"], 8443)

    def test_port_out_of_range_rejected(self):
        endpoint, reason = collect.parse_endpoint(f"vless://{UUID}@v.example.com:70000")
        self.assertIsNone(endpoint)
        self.assertIn("port", reason)

    def test_missing_port_rejected(self):
        endpoint, reason = collect.parse_endpoint(f"vless://{UUID}@v.example.com")
        self.assertIsNone(endpoint)
        self.assertIn("port", reason)


class SsTests(unittest.TestCase):
    def test_sip002_base64_userinfo(self):
        uri = "ss://" + b64("aes-256-gcm:pw123") + "@s.example.com:8388#node"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["scheme"], "ss")
        self.assertEqual(endpoint["extra"]["method"], "aes-256-gcm")
        self.assertEqual(endpoint["secret"], "pw123")
        self.assertEqual(endpoint["port"], 8388)

    def test_plain_2022_userinfo(self):
        uri = "ss://2022-blake3-aes-256-gcm:OURSECRET@10.0.0.1:8388#x"
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["extra"]["method"], "2022-blake3-aes-256-gcm")
        self.assertEqual(endpoint["secret"], "OURSECRET")

    def test_legacy_whole_base64(self):
        uri = "ss://" + b64("aes-128-gcm:secretpw@198.51.100.7:8388")
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(endpoint["host"], "198.51.100.7")
        self.assertEqual(endpoint["port"], 8388)
        self.assertEqual(endpoint["extra"]["method"], "aes-128-gcm")
        self.assertEqual(endpoint["secret"], "secretpw")

    def test_plugin_query_preserved(self):
        uri = (
            "ss://" + b64("aes-256-gcm:pw")
            + "@s.example.com:8388/?plugin=obfs-local%3Bobfs%3Dhttp#p"
        )
        endpoint, reason = collect.parse_endpoint(uri)
        self.assertIsNone(reason)
        self.assertEqual(
            endpoint["params"]["plugin"], "obfs-local;obfs=http"
        )

    def test_userinfo_without_method_rejected(self):
        endpoint, reason = collect.parse_endpoint("ss://nopassword@s.example.com:8388")
        self.assertIsNone(endpoint)
        self.assertIsNotNone(reason)

    def test_unparseable_rejected(self):
        endpoint, reason = collect.parse_endpoint("ss://@@@@@")
        self.assertIsNone(endpoint)
        self.assertIsNotNone(reason)


class IdentityTests(unittest.TestCase):
    def test_same_target_reorders_params_to_same_identity(self):
        e1, _ = collect.parse_endpoint(
            f"vless://{UUID}@V.Example.com:443?security=reality&sni=a.com&pbk=KEY#t1"
        )
        e2, _ = collect.parse_endpoint(
            f"vless://{UUID}@v.example.com.:443?pbk=KEY&security=reality&sni=a.com#other-tag"
        )
        self.assertEqual(e1["identity"], e2["identity"])
        self.assertEqual(
            collect.endpoint_identity(e1), collect.endpoint_identity(e2)
        )

    def test_different_secret_is_different_identity(self):
        e1, _ = collect.parse_endpoint(f"vless://{UUID}@v.example.com:443#a")
        e2, _ = collect.parse_endpoint(
            f"vless://{UUID.replace('5', '6', 1)}@v.example.com:443#a"
        )
        self.assertNotEqual(e1["identity"], e2["identity"])

    def test_scheme_part_of_identity(self):
        e1, _ = collect.parse_endpoint("trojan://pw@t.example.com:443#a")
        e2, _ = collect.parse_endpoint(f"vless://{UUID}@t.example.com:443#a")
        self.assertNotEqual(e1["identity"], e2["identity"])

    def test_identity_shape(self):
        endpoint, _ = collect.parse_endpoint(vmess_uri())
        self.assertEqual(
            endpoint["identity"],
            f"vmess|vm.example.com|443|{UUID}",
        )


class ParseNeverRaisesTests(unittest.TestCase):
    def test_corpus_of_garbage_never_raises(self):
        garbage = [
            "",
            "vmess://",
            "vmess://@@@@",
            "vmess://e30=",
            "ss://",
            "ss://@@@@@",
            "vless://",
            f"vless://@:0",
            "tuic://::::@host:1",
            "hysteria2://",
            "hy2://@[:8443",
            "vmess://" + "A" * 5000,
            "vless://" + UUID + "@host with space:443",
            "trojan://p@[bad:ipv6]:443",
        ]
        for item in garbage:
            endpoint, reason = collect.parse_endpoint(item)
            self.assertIsNone(endpoint, item)
            self.assertTrue(reason, item)

    def test_unsupported_scheme(self):
        endpoint, reason = collect.parse_endpoint("socks5://1.2.3.4:1080")
        self.assertIsNone(endpoint)
        self.assertIn("unsupported scheme", reason)


class RunCollectTests(unittest.TestCase):
    """run_collect error handling, using a fake fetcher (no network)."""

    GOOD_DOC = "\n".join(
        [
            f"vless://{UUID}@a.example.com:443#one",
            "trojan://pw@b.example.com:443#two",
            "vless://broken@b.example.com:443#bad",
        ]
    )

    def _config(self):
        return CollectConfig(
            sources=[
                Source(id="dead", type="raw_http", url="https://dead.invalid/x"),
                Source(id="good", type="raw_http", url="https://good.invalid/x"),
                Source(id="disabled-src", type="raw_http",
                       url="https://off.invalid/x", enabled=False),
            ],
            timeout_seconds=5,
            max_bytes=1000,
            fetch_concurrency=2,
        )

    def test_dead_source_recorded_not_fatal(self):
        def fake_fetch(url, timeout_seconds, max_bytes):
            if "dead" in url:
                raise urllib.error.URLError("connection refused")
            return 200, self.GOOD_DOC.encode("utf-8")

        report = collect.run_collect(self._config(), fetch=fake_fetch)

        by_id = {s["id"]: s for s in report["sources"]}
        self.assertFalse(by_id["dead"]["ok"])
        self.assertIn("URL error", by_id["dead"]["error"])
        self.assertTrue(by_id["good"]["ok"])
        self.assertEqual(by_id["good"]["endpoints_parsed"], 2)
        self.assertEqual(by_id["good"]["endpoints_failed"], 1)
        self.assertTrue(by_id["good"]["failure_samples"])

        self.assertEqual(report["totals"]["sources_enabled"], 2)
        self.assertEqual(report["totals"]["sources_ok"], 1)
        self.assertEqual(report["totals"]["sources_failed"], 1)
        self.assertEqual(report["totals"]["endpoints_parsed"], 2)
        self.assertEqual(len(report["disabled_sources"]), 1)
        self.assertEqual(report["disabled_sources"][0]["id"], "disabled-src")

        for endpoint in report["endpoints"]:
            self.assertEqual(endpoint["source"], "good")
            self.assertIn("identity", endpoint)

    def test_worker_crash_recorded_not_fatal(self):
        def fake_fetch(url, timeout_seconds, max_bytes):
            if "dead" in url:
                return None  # breaks the unpacking -> simulates a worker crash
            return 200, self.GOOD_DOC.encode("utf-8")

        report = collect.run_collect(self._config(), fetch=fake_fetch)
        by_id = {s["id"]: s for s in report["sources"]}
        self.assertFalse(by_id["dead"]["ok"])
        self.assertTrue(by_id["dead"]["error"].startswith("worker crashed"))
        self.assertEqual(report["totals"]["sources_ok"], 1)

    def test_http_error_and_timeout_variants(self):
        def fake_fetch(url, timeout_seconds, max_bytes):
            if "dead" in url:
                raise urllib.error.HTTPError(url, 404, "not found", None, None)
            raise TimeoutError("too slow")

        report = collect.run_collect(self._config(), fetch=fake_fetch)
        by_id = {s["id"]: s for s in report["sources"]}
        self.assertIn("HTTP 404", by_id["dead"]["error"])
        self.assertEqual(by_id["good"]["error"], "timed out")
        self.assertEqual(report["totals"]["endpoints_parsed"], 0)


if __name__ == "__main__":
    unittest.main()
