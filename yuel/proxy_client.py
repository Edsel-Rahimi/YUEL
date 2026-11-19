"""Stdlib proxy clients used to validate plain SOCKS4/SOCKS5/HTTP proxies.

This module is the kept-and-extended v0.2.0 ``socks5.py`` (renamed for the
corrected scope): the no-auth SOCKS5 CONNECT client and the tunneled-HTTP
probe survive unchanged, with three additions for plain-proxy validation:

- SOCKS5 username/password authentication (RFC 1929, method ``0x02``)
- a SOCKS4 client (version-4 CONNECT; domains are resolved locally, since
  plain proxy lists rarely speak SOCKS4a)
- HTTP-proxy clients: a plain proxied GET (absolute-URI request line) and
  a CONNECT tunnel, both with optional ``Proxy-Authorization: Basic``

Every public probe returns :class:`ProbeResult` and never raises — stage 3
classifies each candidate by whichever protocol actually worked.
"""

from __future__ import annotations

import base64
import socket
import struct
import time
from dataclasses import dataclass
from urllib.parse import urlsplit

_SOCKS5_VERSION = 0x05
_SOCKS4_VERSION = 0x04
_AUTH_NONE = 0x00
_AUTH_USERPASS = 0x02
_AUTH_UNACCEPTABLE = 0xFF
_CMD_CONNECT = 0x01
_ATYP_IPV4 = 0x01
_ATYP_DOMAIN = 0x03
_ATYP_IPV6 = 0x04

_SOCKS5_REPLIES = {
    0: "succeeded",
    1: "general SOCKS server failure",
    2: "connection not allowed by ruleset",
    3: "network unreachable",
    4: "host unreachable",
    5: "connection refused",
    6: "TTL expired",
    7: "command not supported",
    8: "address type not supported",
}

_SOCKS4_REPLIES = {
    90: "request granted",
    91: "request rejected or failed",
    92: "request rejected: SOCKS server cannot connect to identd",
    93: "request rejected: identd reports different client id",
}


class SocksError(Exception):
    """Proxy handshake or protocol failure (never a bare socket error)."""


@dataclass
class ProbeResult:
    """Outcome of one proxied HTTP probe."""

    ok: bool
    http_status: int | None = None
    latency_ms: float | None = None
    error: str | None = None


# ---------------------------------------------------------------------------
# low-level helpers
# ---------------------------------------------------------------------------


def _encode_socks5_target(host: str, port: int) -> bytes:
    """Encode a SOCKS5 CONNECT target: IPv4, IPv6 literal, or domain."""
    host = host.strip()
    if host.startswith("[") and host.endswith("]"):
        raw = socket.inet_pton(socket.AF_INET6, host[1:-1])
        return bytes([_ATYP_IPV6]) + raw + struct.pack(">H", port)
    try:
        return (
            bytes([_ATYP_IPV4])
            + socket.inet_pton(socket.AF_INET, host)
            + struct.pack(">H", port)
        )
    except OSError:
        domain = host.encode("idna") if not host.isascii() else host.encode()
        if not 1 <= len(domain) <= 255:
            raise SocksError(f"invalid domain length: {len(domain)}") from None
        return (
            bytes([_ATYP_DOMAIN, len(domain)]) + domain + struct.pack(">H", port)
        )


def _resolve_ipv4(host: str) -> bytes:
    """Resolve a host to an IPv4 address for SOCKS4 (which has no domains)."""
    host = host.strip().strip("[]")
    try:
        socket.inet_pton(socket.AF_INET, host)
        return socket.inet_pton(socket.AF_INET, host)
    except OSError:
        pass
    try:
        infos = socket.getaddrinfo(host, None, family=socket.AF_INET)
        return socket.inet_pton(socket.AF_INET, infos[0][4][0])
    except (OSError, IndexError) as exc:
        raise SocksError(f"cannot resolve {host!r} to IPv4 for SOCKS4: {exc}") from exc


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise SocksError("connection closed while reading proxy reply")
        buf.extend(chunk)
    return bytes(buf)


def _read_status_line(sock: socket.socket) -> str:
    buf = bytearray()
    while b"\r\n" not in buf and len(buf) < 8192:
        chunk = sock.recv(1024)
        if not chunk:
            break
        buf.extend(chunk)
    line = buf.split(b"\r\n", 1)[0].decode("latin-1", "replace").strip()
    if not line.startswith("HTTP/"):
        raise SocksError(f"not an HTTP response: {line!r}")
    return line


def _parse_target_url(target_url: str) -> tuple[str, int, str]:
    """Split a probe URL into (host, port, request_path)."""
    parts = urlsplit(target_url)
    if parts.scheme != "http":
        raise SocksError(f"probe url must be http: {target_url!r}")
    host = parts.hostname
    if not host:
        raise SocksError(f"probe url has no host: {target_url!r}")
    port = parts.port or 80
    path = parts.path or "/"
    return host, port, path


def _http_request_bytes(method: str, url_target: str, host_header: str) -> bytes:
    return (
        f"{method} {url_target} HTTP/1.1\r\n"
        f"Host: {host_header}\r\n"
        f"User-Agent: YUEL-probe/0.3\r\n"
        f"Connection: close\r\n"
        f"\r\n"
    ).encode()


def _proxy_auth_header(username: str | None, password: str | None) -> str:
    if not username:
        return ""
    token = base64.b64encode(
        f"{username}:{password or ''}".encode()
    ).decode()
    return f"Proxy-Authorization: Basic {token}\r\n"


def _probe_over(sock: socket.socket, target_url: str, timeout: float) -> ProbeResult:
    """Send a GET down an established tunnel and time greeting→status-line.
    Any HTTP status >= 400 counts as a failed probe (the proxy answered,
    but the fetch through it did not succeed)."""
    host, port, path = _parse_target_url(target_url)
    start = time.monotonic()
    try:
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: YUEL-probe/0.3\r\n"
            f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        sock.sendall(request)
        sock.settimeout(timeout)
        status_line = _read_status_line(sock)
        latency_ms = (time.monotonic() - start) * 1000
        code = int(status_line.split()[1])
        if code >= 400:
            return ProbeResult(
                False, code, round(latency_ms, 1),
                f"HTTP {code} status through proxy",
            )
        return ProbeResult(True, code, round(latency_ms, 1), None)
    except (SocksError, OSError, ValueError) as exc:
        return ProbeResult(False, error=f"{type(exc).__name__}: {exc}")
    finally:
        sock.close()


# ---------------------------------------------------------------------------
# SOCKS5
# ---------------------------------------------------------------------------


def socks5_connect(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    timeout: float,
    username: str | None = None,
    password: str | None = None,
) -> socket.socket:
    """Open a CONNECT tunnel through a SOCKS5 proxy and return the socket.

    With credentials the client offers no-auth + username/password (RFC
    1929) and performs the auth sub-negotiation when the server picks it.
    Closes the socket on any failure.
    """
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        methods = [bytes([_AUTH_NONE])]
        if username:
            methods.append(bytes([_AUTH_USERPASS]))
        greeting = bytes([_SOCKS5_VERSION, len(methods)]) + b"".join(methods)
        sock.sendall(greeting)
        reply = _recv_exact(sock, 2)
        if reply[0] != _SOCKS5_VERSION:
            raise SocksError(f"unexpected SOCKS version {reply[0]}")
        method = reply[1]
        if method == _AUTH_UNACCEPTABLE:
            raise SocksError("server accepts none of the offered auth methods")
        if method == _AUTH_USERPASS:
            if not username:
                raise SocksError("server demanded auth but no credentials given")
            user = username.encode("utf-8")
            pwd = (password or "").encode("utf-8")
            sock.sendall(
                bytes([0x01, len(user)]) + user + bytes([len(pwd)]) + pwd
            )
            auth_reply = _recv_exact(sock, 2)
            if auth_reply[0] != 0x01:
                raise SocksError(f"unexpected auth version {auth_reply[0]}")
            if auth_reply[1] != 0x00:
                raise SocksError("authentication failed (bad username/password)")
        elif method != _AUTH_NONE:
            raise SocksError(f"server chose unsupported auth method {method}")

        sock.sendall(
            bytes([_SOCKS5_VERSION, _CMD_CONNECT, 0x00])
            + _encode_socks5_target(target_host, target_port)
        )
        head = _recv_exact(sock, 4)
        if head[0] != _SOCKS5_VERSION:
            raise SocksError(f"unexpected SOCKS version {head[0]}")
        if head[1] != 0x00:
            raise SocksError(
                "SOCKS5 connect failed: "
                f"{_SOCKS5_REPLIES.get(head[1], f'reply {head[1]}')}"
            )
        atyp = head[3]
        if atyp in (_ATYP_IPV4, _ATYP_IPV6):
            bound_len = 4 if atyp == _ATYP_IPV4 else 16
            _recv_exact(sock, bound_len + 2)  # bnd.addr + bnd.port
        elif atyp == _ATYP_DOMAIN:
            domain_len = _recv_exact(sock, 1)[0]
            _recv_exact(sock, domain_len + 2)
        else:
            raise SocksError(f"unknown SOCKS5 address type {atyp}")
        return sock
    except Exception:
        sock.close()
        raise


def probe_socks5(
    proxy_host: str,
    proxy_port: int,
    target_url: str,
    timeout_seconds: float,
    username: str | None = None,
    password: str | None = None,
) -> ProbeResult:
    """Fetch an HTTP URL through a SOCKS5 proxy. Never raises."""
    try:
        host, port, _ = _parse_target_url(target_url)
        sock = socks5_connect(
            proxy_host, proxy_port, host, port, timeout_seconds, username, password
        )
    except (SocksError, OSError, ValueError) as exc:
        return ProbeResult(False, error=f"{type(exc).__name__}: {exc}")
    return _probe_over(sock, target_url, timeout_seconds)


# ---------------------------------------------------------------------------
# SOCKS4
# ---------------------------------------------------------------------------


def socks4_connect(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    timeout: float,
    username: str | None = None,
) -> socket.socket:
    """Open a CONNECT tunnel through a SOCKS4 proxy (targets resolved to
    IPv4 locally). Closes the socket on any failure."""
    sock = socket.create_connection((proxy_host, proxy_port), timeout=timeout)
    try:
        ip = _resolve_ipv4(target_host)
        userid = (username or "").encode("utf-8")
        sock.sendall(
            bytes([_SOCKS4_VERSION, _CMD_CONNECT])
            + struct.pack(">H", target_port)
            + ip
            + userid
            + b"\x00"
        )
        reply = _recv_exact(sock, 8)
        if reply[0] != 0x00:
            raise SocksError(f"unexpected SOCKS4 reply byte {reply[0]}")
        status = reply[1]
        if status != 90:
            raise SocksError(
                "SOCKS4 connect failed: "
                f"{_SOCKS4_REPLIES.get(status, f'reply {status}')}"
            )
        return sock
    except Exception:
        sock.close()
        raise


def probe_socks4(
    proxy_host: str,
    proxy_port: int,
    target_url: str,
    timeout_seconds: float,
    username: str | None = None,
) -> ProbeResult:
    """Fetch an HTTP URL through a SOCKS4 proxy. Never raises."""
    try:
        host, port, _ = _parse_target_url(target_url)
        sock = socks4_connect(
            proxy_host, proxy_port, host, port, timeout_seconds, username
        )
    except (SocksError, OSError, ValueError) as exc:
        return ProbeResult(False, error=f"{type(exc).__name__}: {exc}")
    return _probe_over(sock, target_url, timeout_seconds)


# ---------------------------------------------------------------------------
# HTTP proxy (plain proxied GET + CONNECT tunnel)
# ---------------------------------------------------------------------------


def http_proxy_get(
    proxy_host: str,
    proxy_port: int,
    target_url: str,
    timeout_seconds: float,
    username: str | None = None,
    password: str | None = None,
) -> ProbeResult:
    """Fetch an HTTP URL through an HTTP proxy via an absolute-URI GET.
    Never raises."""
    try:
        host, port, path = _parse_target_url(target_url)
        sock = socket.create_connection((proxy_host, proxy_port), timeout_seconds)
    except (SocksError, OSError, ValueError) as exc:
        return ProbeResult(False, error=f"{type(exc).__name__}: {exc}")
    try:
        start = time.monotonic()
        request = (
            f"GET http://{host}:{port}{path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            f"User-Agent: YUEL-probe/0.3\r\n"
            + _proxy_auth_header(username, password)
            + f"Connection: close\r\n"
            f"\r\n"
        ).encode()
        sock.sendall(request)
        sock.settimeout(timeout_seconds)
        status_line = _read_status_line(sock)
        latency_ms = (time.monotonic() - start) * 1000
        code = int(status_line.split()[1])
        if code >= 400:
            return ProbeResult(
                False, code, round(latency_ms, 1),
                f"HTTP {code} status through proxy",
            )
        return ProbeResult(True, code, round(latency_ms, 1), None)
    except (SocksError, OSError, ValueError) as exc:
        return ProbeResult(False, error=f"{type(exc).__name__}: {exc}")
    finally:
        sock.close()


def http_proxy_connect(
    proxy_host: str,
    proxy_port: int,
    target_host: str,
    target_port: int,
    timeout_seconds: float,
    username: str | None = None,
    password: str | None = None,
) -> socket.socket:
    """Open a CONNECT tunnel through an HTTP proxy and return the socket."""
    sock = socket.create_connection((proxy_host, proxy_port), timeout_seconds)
    try:
        request = (
            f"CONNECT {target_host}:{target_port} HTTP/1.1\r\n"
            f"Host: {target_host}:{target_port}\r\n"
            + _proxy_auth_header(username, password)
            + f"\r\n"
        ).encode()
        sock.sendall(request)
        sock.settimeout(timeout_seconds)
        status_line = _read_status_line(sock)
        code = int(status_line.split()[1])
        if code != 200:
            sock.close()
            raise SocksError(f"HTTP CONNECT failed: {status_line.strip()}")
        return sock
    except Exception:
        sock.close()
        raise


def probe_http_connect(
    proxy_host: str,
    proxy_port: int,
    target_url: str,
    timeout_seconds: float,
    username: str | None = None,
    password: str | None = None,
) -> ProbeResult:
    """Fetch an HTTP URL through an HTTP proxy via CONNECT + GET. Never
    raises — probes an https-capable proxy against the http target."""
    try:
        host, port, _ = _parse_target_url(target_url)
        sock = http_proxy_connect(
            proxy_host, proxy_port, host, port, timeout_seconds, username, password
        )
    except (SocksError, OSError, ValueError) as exc:
        return ProbeResult(False, error=f"{type(exc).__name__}: {exc}")
    return _probe_over(sock, target_url, timeout_seconds)
