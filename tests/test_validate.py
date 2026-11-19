"""Tests for stage 3 (validate): prefilter, handshake checks, stage flows.

The handshake pass runs against fake in-process proxy servers (imported
from test_proxy_client), so the full prefilter → check → report flow is
exercised offline.
"""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path

from tests.test_proxy_client import _HttpProxyServer, _Socks5Server
from yuel.validate import (
    ValidateConfigError,
    check_proxy,
    claim_agreement,
    load_validate_config,
    prefilter,
    stage_validate,
)


def make_proxy(port: int, **overrides) -> dict:
    fields = {
        "host": "127.0.0.1",
        "port": port,
        "username": "",
        "password": "",
        "claimed_type": None,
        "claimed_country": None,
        "claimed_anonymity": None,
        "identity": f"127.0.0.1|{port}||",
        "sources": ["src-a"],
    }
    fields.update(overrides)
    if "identity" not in overrides:
        fields["identity"] = (
            f"{fields['host']}|{fields['port']}|"
            f"{fields['username']}|{fields['password']}"
        )
    return fields


def closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


class _Listener:
    """A real accepting TCP listener for prefilter pass-cases."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.port = self.sock.getsockname()[1]

    def close(self):
        self.sock.close()


class PrefilterTests(unittest.TestCase):
    def test_pass_and_fail_split(self):
        listener = _Listener()
        try:
            dead = closed_port()
            result = prefilter(
                [make_proxy(listener.port), make_proxy(dead)],
                timeout_seconds=1,
                workers=4,
            )
            self.assertEqual(result.targets, 2)
            self.assertEqual(result.passed, {f"127.0.0.1|{listener.port}"})
            self.assertEqual(result.failed, 1)
            self.assertTrue(result.failure_samples)
        finally:
            listener.close()

    def test_shared_host_port_checked_once(self):
        listener = _Listener()
        try:
            proxies = [
                make_proxy(listener.port, claimed_type="socks5"),
                make_proxy(listener.port, claimed_type="http", username="alice"),
            ]
            result = prefilter(proxies, timeout_seconds=1, workers=4)
            self.assertEqual(result.targets, 1)
        finally:
            listener.close()


class CheckProxyTests(unittest.TestCase):
    PROBE = "http://example.com/probe"

    def test_socks5_claim_confirmed(self):
        server = _Socks5Server()
        server.start()
        try:
            result = check_proxy(
                make_proxy(server.port, claimed_type="socks5"), self.PROBE, 5.0
            )
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.type_confirmed, "socks5")
        self.assertEqual(result.method_used, "socks5")
        self.assertEqual(result.http_status, 204)
        self.assertGreaterEqual(result.latency_ms, 0.0)

    def test_http_claim_get_path(self):
        server = _HttpProxyServer(mode="get")
        server.start()
        try:
            result = check_proxy(
                make_proxy(server.port, claimed_type="http"), self.PROBE, 5.0
            )
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.type_confirmed, "http")
        self.assertEqual(result.method_used, "http_get")

    def test_http_claim_falls_back_to_connect(self):
        # server rejects plain GET (405) but tunnels CONNECT fine
        server = _HttpProxyServer(mode="connect_only")
        server.start()
        try:
            result = check_proxy(
                make_proxy(server.port, claimed_type="http"), self.PROBE, 5.0
            )
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.type_confirmed, "http")
        self.assertEqual(result.method_used, "http_connect")

    def test_unknown_claim_tries_socks5_first(self):
        server = _Socks5Server()
        server.start()
        try:
            result = check_proxy(make_proxy(server.port), self.PROBE, 5.0)
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.method_used, "socks5")

    def test_unknown_claim_falls_back_to_http_get(self):
        # an HTTP proxy choked by the SOCKS5 attempt still serves plain GET
        server = _HttpProxyServer(mode="get")
        server.start()
        try:
            result = check_proxy(make_proxy(server.port), self.PROBE, 5.0)
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.method_used, "http_get")

    def test_credentials_forwarded_to_socks5(self):
        server = _Socks5Server(require_auth=True, auth=(b"alice", b"good"))
        server.start()
        try:
            ok = check_proxy(
                make_proxy(server.port, username="alice", password="good"),
                self.PROBE,
                5.0,
            )
            bad = check_proxy(
                make_proxy(server.port, username="alice", password="wrong"),
                self.PROBE,
                5.0,
            )
        finally:
            server.stop()
        self.assertTrue(ok.ok, ok.error)
        self.assertFalse(bad.ok)
        self.assertIn("authentication failed", bad.error)

    def test_all_strategies_fail_error_names_them(self):
        dead = closed_port()
        result = check_proxy(make_proxy(dead), self.PROBE, 0.5)
        self.assertFalse(result.ok)
        self.assertIn("socks5:", result.error)
        self.assertIn("http_get:", result.error)
        self.assertIn("http_connect:", result.error)


class ClaimAgreementTests(unittest.TestCase):
    def test_matrix(self):
        self.assertEqual(claim_agreement("socks5", "socks5", "socks5"), "agree")
        self.assertEqual(claim_agreement("http", "http", "http_get"), "agree")
        self.assertEqual(
            claim_agreement("https", "http", "http_connect"), "agree"
        )
        self.assertEqual(claim_agreement("https", "http", "http_get"), "disagree")
        self.assertEqual(claim_agreement("socks5", "http", "http_get"), "disagree")
        self.assertEqual(claim_agreement("socks4", "http", "http_get"), "disagree")
        self.assertEqual(claim_agreement(None, "socks5", "socks5"), "unknown")


class ConfigTests(unittest.TestCase):
    def test_missing_file_gives_defaults(self):
        config = load_validate_config(None)
        self.assertEqual(
            config["probe"]["url"], "http://www.gstatic.com/generate_204"
        )
        self.assertEqual(config["workers"], 100)

    def test_file_overrides_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "validate.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "workers": 7,
                        "probe": {"timeout_seconds": 4},
                    }
                ),
                encoding="utf-8",
            )
            config = load_validate_config(path)
        self.assertEqual(config["workers"], 7)
        self.assertEqual(config["probe"]["timeout_seconds"], 4)
        self.assertEqual(
            config["probe"]["url"], "http://www.gstatic.com/generate_204"
        )

    def test_bad_schema_version(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "validate.json"
            path.write_text(json.dumps({"schema_version": 2}), encoding="utf-8")
            with self.assertRaises(ValidateConfigError):
                load_validate_config(path)

    def test_https_probe_url_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "validate.json"
            path.write_text(
                json.dumps(
                    {"schema_version": 1,
                     "probe": {"url": "https://example.com/x"}}
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValidateConfigError):
                load_validate_config(path)


def write_normalized(data_dir: Path, proxies: list) -> None:
    normalized = data_dir / "normalized"
    normalized.mkdir(parents=True, exist_ok=True)
    (normalized / "proxies_normalized.json").write_text(
        json.dumps(proxies), encoding="utf-8"
    )


class StageValidateTests(unittest.TestCase):
    def test_prefilter_only_flow(self):
        listener = _Listener()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data_dir = Path(tmp)
                write_normalized(
                    data_dir, [make_proxy(listener.port), make_proxy(1)]
                )
                result = stage_validate(Path("unused"), data_dir, prefilter_only=True)
                self.assertTrue(result.ok, result.detail)
                self.assertEqual(len(result.outputs), 1)
                report = json.loads(result.outputs[0].read_text(encoding="utf-8"))
                self.assertEqual(report["prefilter"]["passed"], 1)
                self.assertTrue(report["handshake_check"]["skipped"])
                self.assertFalse(
                    (data_dir / "validated" / "proxies_validated.json").exists()
                )
        finally:
            listener.close()

    def test_full_flow_with_fake_proxies(self):
        server_a = _Socks5Server()
        server_b = _HttpProxyServer(mode="get")
        server_a.start()
        server_b.start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                data_dir = Path(tmp)
                proxies = [
                    make_proxy(server_a.port, claimed_type="socks5"),
                    make_proxy(server_b.port, claimed_type="http"),
                    make_proxy(closed_port(), claimed_type="socks5"),
                ]
                write_normalized(data_dir, proxies)
                cfg = Path(tmp) / "v.json"
                cfg.write_text(
                    json.dumps(
                        {
                            "schema_version": 1,
                            "workers": 4,
                            "probe": {
                                "url": "http://example.com/probe",
                                "timeout_seconds": 5,
                            },
                        }
                    ),
                    encoding="utf-8",
                )
                result = stage_validate(Path("unused"), data_dir, validate_cfg_path=cfg)
                self.assertTrue(result.ok, result.detail)

                validated = json.loads(
                    (data_dir / "validated" / "proxies_validated.json").read_text(
                        encoding="utf-8"
                    )
                )
                report = json.loads(
                    (data_dir / "validated" / "validate_report.json").read_text(
                        encoding="utf-8"
                    )
                )
                alive = [e for e in validated if e["check"]["ok"]]
                self.assertEqual(len(alive), 2)
                confirmed = {e["check"]["type_confirmed"] for e in alive}
                self.assertEqual(confirmed, {"socks5", "http"})
                self.assertEqual(report["handshake_check"]["alive"], 2)
                self.assertEqual(
                    report["handshake_check"]["alive_by_confirmed_type"],
                    {"http": 1, "socks5": 1},
                )
                # both alive proxies have agreeing claims
                self.assertEqual(
                    report["handshake_check"]["claim_calibration"],
                    {"agree": 2, "disagree": 0, "unknown": 0},
                )
                # the dead port was killed by the PREFILTER, so it never
                # reaches the handshake pass (design: prefilter-eliminated
                # targets live in the report only)
                self.assertEqual(report["handshake_check"]["tested"], 2)
                self.assertEqual(report["handshake_check"]["dead"], 0)
                self.assertEqual(report["prefilter"]["failed"], 1)
        finally:
            server_a.stop()
            server_b.stop()

    def test_missing_stage2_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = stage_validate(Path("unused"), Path(tmp))
            self.assertFalse(result.ok)
            self.assertIn("run normalize first", result.detail)

    def test_corrupt_stage2_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            normalized = Path(tmp) / "normalized"
            normalized.mkdir()
            (normalized / "proxies_normalized.json").write_text("{oops")
            result = stage_validate(Path("unused"), Path(tmp))
            self.assertFalse(result.ok)
            self.assertIn("cannot read", result.detail)

    def test_bad_validate_config_fails_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            write_normalized(data_dir, [make_proxy(80)])
            bad_cfg = data_dir / "bad.json"
            bad_cfg.write_text(json.dumps({"schema_version": 9}), encoding="utf-8")
            result = stage_validate(
                Path("unused"), data_dir, validate_cfg_path=bad_cfg
            )
            self.assertFalse(result.ok)
            self.assertIn("config error", result.detail)


if __name__ == "__main__":
    unittest.main()
