"""Tests for the proxy clients (SOCKS5/SOCKS4/HTTP) against fake servers.

Each fake server is a real TCP listener speaking just enough protocol to
exercise the client handshake path, including authentication, so the tests
stay offline.
"""

from __future__ import annotations

import base64
import socket
import struct
import threading
import time
import unittest

from yuel.proxy_client import (
    http_proxy_get,
    probe_http_connect,
    probe_socks4,
    probe_socks5,
)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise OSError("closed")
        buf.extend(chunk)
    return bytes(buf)


def _read_http_request(sock: socket.socket) -> bytes:
    buf = bytearray()
    while b"\r\n\r\n" not in buf:
        chunk = sock.recv(4096)
        if not chunk:
            break
        buf.extend(chunk)
    return bytes(buf)


class _Server(threading.Thread):
    """Base: accept loop + per-connection worker in daemon threads."""

    def __init__(self):
        super().__init__(daemon=True)
        self.listener = socket.socket()
        self.listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen(8)
        self.listener.settimeout(3)
        self.port = self.listener.getsockname()[1]
        self._stop = threading.Event()

    def run(self):
        while not self._stop.is_set():
            try:
                conn, _ = self.listener.accept()
            except socket.timeout:
                continue  # idle gap — keep accepting, do NOT exit the loop
            except OSError:
                return
            threading.Thread(target=self._handle, args=(conn,), daemon=True).start()

    def stop(self):
        self._stop.set()
        try:
            self.listener.close()
        except OSError:
            pass

    def _handle(self, conn):
        try:
            conn.settimeout(3)
            self.serve(conn)
        except OSError:
            pass
        finally:
            try:
                conn.close()
            except OSError:
                pass


class _Socks5Server(_Server):
    """Scriptable SOCKS5 server: no-auth or mandatory user/pass auth."""

    def __init__(self, require_auth=False, auth=(b"u", b"p"), connect_ok=True,
                 silent=False):
        super().__init__()
        self.require_auth = require_auth
        self.auth = auth
        self.connect_ok = connect_ok
        self.silent = silent
        self.last_methods = None
        self.last_auth = None
        self.last_request_atyp = None

    def serve(self, conn):
        header = _recv_exact(conn, 2)
        methods = _recv_exact(conn, header[1])
        self.last_methods = methods
        if self.require_auth:
            if b"\x02" not in methods:
                conn.sendall(b"\x05\xff")
                return
            conn.sendall(b"\x05\x02")
            ver = _recv_exact(conn, 1)[0]  # RFC 1929: VER first
            if ver != 0x01:
                return  # malformed auth sub-negotiation; drop the connection
            ulen = _recv_exact(conn, 1)[0]
            user = _recv_exact(conn, ulen)
            plen = _recv_exact(conn, 1)[0]
            pwd = _recv_exact(conn, plen)
            self.last_auth = (user, pwd)
            if (user, pwd) != self.auth:
                conn.sendall(b"\x01\x01")
                return
            conn.sendall(b"\x01\x00")
        else:
            conn.sendall(b"\x05\x00")
        req = _recv_exact(conn, 4)
        self.last_request_atyp = req[3]
        if not self.connect_ok:
            conn.sendall(b"\x05\x05\x00\x01" + b"\x00" * 6)
            return
        atyp = req[3]
        if atyp == 1:
            _recv_exact(conn, 4 + 2)
        elif atyp == 4:
            _recv_exact(conn, 16 + 2)
        elif atyp == 3:
            dlen = _recv_exact(conn, 1)[0]
            _recv_exact(conn, dlen + 2)
        conn.sendall(b"\x05\x00\x00\x01" + b"\x00" * 4 + struct.pack(">H", 1))
        if self.silent:
            time.sleep(2.0)
            return
        conn.recv(4096)
        conn.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
        time.sleep(0.05)


class _Socks4Server(_Server):
    def __init__(self, granted=True):
        super().__init__()
        self.granted = granted
        self.last_port = None
        self.last_ip = None
        self.last_userid = None

    def serve(self, conn):
        head = _recv_exact(conn, 8)
        self.last_port = struct.unpack(">H", head[2:4])[0]
        self.last_ip = head[4:8]
        rest = bytearray()
        while not rest.endswith(b"\x00"):
            rest.extend(_recv_exact(conn, 1))
        self.last_userid = bytes(rest[:-1])
        conn.sendall(
            b"\x00\x5a" + b"\x00" * 6 if self.granted else b"\x00\x5b" + b"\x00" * 6
        )
        if self.granted:
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            time.sleep(0.05)


class _HttpProxyServer(_Server):
    """Scriptable HTTP proxy: plain GET, CONNECT, or CONNECT-only."""

    def __init__(self, mode="get", auth=None):
        super().__init__()
        self.mode = mode  # get | connect | connect_only | reject_auth
        self.auth = auth  # expected (user, pass) or None
        self.last_request = b""
        self.last_connect_target = None

    def serve(self, conn):
        request = _read_http_request(conn)
        self.last_request = request
        first_line = request.split(b"\r\n", 1)[0].decode("latin-1")
        if self.mode == "connect_only" and first_line.startswith("GET"):
            conn.sendall(b"HTTP/1.1 405 Method Not Allowed\r\n\r\n")
            return
        if self.auth is not None:
            expected = base64.b64encode(
                f"{self.auth[0]}:{self.auth[1]}".encode()
            ).decode()
            if f"Basic {expected}".encode() not in request:
                conn.sendall(
                    b"HTTP/1.1 407 Proxy Authentication Required\r\n\r\n"
                )
                return
        if first_line.startswith("CONNECT"):
            self.last_connect_target = first_line.split()[1]
            if self.mode == "reject_auth":
                conn.sendall(b"HTTP/1.1 403 Forbidden\r\n\r\n")
                return
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            conn.recv(4096)
            conn.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            time.sleep(0.05)
        elif first_line.startswith("GET"):
            conn.sendall(b"HTTP/1.1 200 OK\r\nConnection: close\r\n\r\n")
            time.sleep(0.05)
        else:
            conn.sendall(b"HTTP/1.1 400 Bad Request\r\n\r\n")


TARGET = "http://example.com/generate_204"


class ProbeSocks5Tests(unittest.TestCase):
    def _probe(self, server, timeout=5.0, **kwargs):
        return probe_socks5("127.0.0.1", server.port, TARGET, timeout, **kwargs)

    def test_no_auth_ok(self):
        server = _Socks5Server()
        server.start()
        try:
            result = self._probe(server)
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.http_status, 204)
        self.assertGreaterEqual(result.latency_ms, 0.0)
        self.assertEqual(server.last_methods, b"\x00")  # client offers no-auth only

    def test_with_auth_ok(self):
        server = _Socks5Server(require_auth=True)
        server.start()
        try:
            result = self._probe(server, username="u", password="p")
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(server.last_auth, (b"u", b"p"))

    def test_bad_password_rejected(self):
        server = _Socks5Server(require_auth=True)
        server.start()
        try:
            result = self._probe(server, username="u", password="wrong")
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIn("authentication failed", result.error)

    def test_auth_required_but_no_creds_offered(self):
        server = _Socks5Server(require_auth=True)
        server.start()
        try:
            result = self._probe(server)
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIn("none of the offered", result.error)

    def test_connect_failure_reply(self):
        server = _Socks5Server(connect_ok=False)
        server.start()
        try:
            result = self._probe(server)
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIn("connection refused", result.error)

    def test_silent_server_times_out(self):
        server = _Socks5Server(silent=True)
        server.start()
        try:
            result = self._probe(server, timeout=0.5)
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIsNotNone(result.error)

    def test_no_proxy_listening(self):
        server = _Socks5Server()
        dead_port = server.port
        server.stop()
        result = probe_socks5("127.0.0.1", dead_port, TARGET, 0.5)
        self.assertFalse(result.ok)


class ProbeSocks4Tests(unittest.TestCase):
    def test_ok_with_literal_ip_target(self):
        server = _Socks4Server()
        server.start()
        try:
            result = probe_socks4(
                "127.0.0.1", server.port, "http://9.8.7.6:80/x", 5.0
            )
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(server.last_port, 80)
        self.assertEqual(server.last_ip, socket.inet_pton(socket.AF_INET, "9.8.7.6"))

    def test_rejected_reply(self):
        server = _Socks4Server(granted=False)
        server.start()
        try:
            result = probe_socks4(
                "127.0.0.1", server.port, "http://9.8.7.6:80/x", 5.0
            )
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIn("rejected or failed", result.error)

    def test_domain_target_resolved_locally(self):
        server = _Socks4Server()
        server.start()
        try:
            result = probe_socks4(
                "127.0.0.1", server.port, "http://localhost:80/x", 5.0
            )
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)  # localhost resolves to 127.0.0.1
        self.assertEqual(server.last_ip, socket.inet_pton(socket.AF_INET, "127.0.0.1"))


class HttpProxyGetTests(unittest.TestCase):
    def test_plain_get_ok(self):
        server = _HttpProxyServer(mode="get")
        server.start()
        try:
            result = http_proxy_get("127.0.0.1", server.port, TARGET, 5.0)
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.http_status, 200)
        request = server.last_request.decode("latin-1")
        self.assertIn("GET http://example.com:80/generate_204 HTTP/1.1", request)
        self.assertIn("Host: example.com", request)

    def test_proxy_authorization_sent(self):
        server = _HttpProxyServer(mode="get", auth=("carol", "pw"))
        server.start()
        try:
            ok = http_proxy_get(
                "127.0.0.1", server.port, TARGET, 5.0, "carol", "pw"
            )
        finally:
            server.stop()
        self.assertTrue(ok.ok, ok.error)
        self.assertIn("Proxy-Authorization: Basic", server.last_request.decode())

    def test_407_without_creds(self):
        server = _HttpProxyServer(mode="get", auth=("carol", "pw"))
        server.start()
        try:
            result = http_proxy_get("127.0.0.1", server.port, TARGET, 5.0)
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIn("407", result.error)


class HttpProxyConnectTests(unittest.TestCase):
    def test_connect_tunnel_ok(self):
        server = _HttpProxyServer(mode="connect")
        server.start()
        try:
            result = probe_http_connect("127.0.0.1", server.port, TARGET, 5.0)
        finally:
            server.stop()
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.http_status, 204)
        self.assertEqual(server.last_connect_target, "example.com:80")

    def test_connect_with_auth(self):
        server = _HttpProxyServer(mode="connect", auth=("dave", "secret"))
        server.start()
        try:
            ok = probe_http_connect(
                "127.0.0.1", server.port, TARGET, 5.0, "dave", "secret"
            )
        finally:
            server.stop()
        self.assertTrue(ok.ok, ok.error)

    def test_connect_auth_missing(self):
        server = _HttpProxyServer(mode="connect", auth=("dave", "secret"))
        server.start()
        try:
            result = probe_http_connect("127.0.0.1", server.port, TARGET, 5.0)
        finally:
            server.stop()
        self.assertFalse(result.ok)
        self.assertIn("407", result.error)


if __name__ == "__main__":
    unittest.main()
