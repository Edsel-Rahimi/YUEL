"""Stage 1 — collect: fetch public plain-proxy sources and parse entries.

Scope (v0.3.0): PLAIN proxies — bare ``ip:port`` / ``ip:port:user:pass``
SOCKS4/SOCKS5/HTTP(S) servers used as chain hops — never standalone tunnel
configs (vmess/vless/trojan/...); that was the pre-0.3.0 scope and is gone.

Supported source formats (``config/sources.json``):

- ``ip:port``            — ``1.2.3.4:8080`` lines; ``#`` comments skipped
- ``ip:port:user:pass``  — ``1.2.3.4:8080:user:pass`` (password may contain ':')
- ``ip:port:country``    — ``1.2.3.4:8080:United States`` (country is a claim)
- ``user:pass@ip:port``  — ``user:pass@1.2.3.4:8080``
- ``proto-prefixed``     — ``socks5://1.2.3.4:1080`` or
                           ``socks5://1.2.3.4:1080,US,Alexandria`` (proxifly csv);
                           the URL prefix is the per-line type claim
- ``json-structured``    — JSON API rows with ip/port/protocols/country fields

Design rules (unchanged from the v0.1.0 collector):

- One dead source must never crash the run: every fetch is wrapped and the
  error is recorded per source in the run report.
- Parsing never raises: malformed lines are counted (a few samples kept for
  the report) instead of aborting the stage. Junk lines that real-world
  lists occasionally contain (``error code: 1015`` …) are just malformed
  entries.
- No deduplication here — that is stage 2 (normalize). Entries carry an
  ``identity`` key (``host|port|username|password``) which dedupe keys on.

Type/country/anonymity are *claims*: sources assert them, YUEL does not
trust them. Stage 3 measures the truth; keeping the claims next to the
measured result is a data-quality signal (flag sources whose claims
disagree with live validation).
"""

from __future__ import annotations

import json
import socket
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable

from .config import (
    CollectConfig,
    Source,
    VALID_ANONYMITY_LEVELS,
    VALID_CLAIMED_TYPES,
    DEFAULT_USER_AGENT,
)

USER_AGENT = DEFAULT_USER_AGENT

# A URL scheme prefix maps to a claimed proxy type; unknown/ambiguous
# schemes ("socks://") parse fine but carry no type claim.
_SCHEME_TO_TYPE = {
    "socks5": "socks5",
    "socks4": "socks4",
    "http": "http",
    "https": "https",
}

_HOST_RE = r"(?:\[[0-9A-Fa-f:.]+\])|(?:\d{1,3}(?:\.\d{1,3}){3})|(?:[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?)*)"
_HOST_RE_COMPILED = None  # built lazily via re below


class _ParseError(ValueError):
    """Internal: a line could not be parsed; the message becomes the reason."""


def _host_ok(host: str) -> bool:
    import re as _re

    global _HOST_RE_COMPILED
    if _HOST_RE_COMPILED is None:
        _HOST_RE_COMPILED = _re.compile(_HOST_RE)
    return _HOST_RE_COMPILED.fullmatch(host) is not None


# ---------------------------------------------------------------------------
# shared parsing helpers (carried over from the v0.1.0 collector)
# ---------------------------------------------------------------------------


def _to_port(text: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise _ParseError(f"invalid port {text!r}")
    port = int(text)
    if not 1 <= port <= 65535:
        raise _ParseError(f"port out of range: {port}")
    return port


def _split_hostport(authority: str) -> tuple[str, int]:
    """Split ``host:port`` (bracketed IPv6 allowed) into (host, port)."""
    authority = unescape(authority).strip()
    if not authority:
        raise _ParseError("missing host")
    if authority.startswith("["):
        closing = authority.find("]")
        if closing == -1:
            raise _ParseError("unterminated IPv6 literal")
        host = authority[: closing + 1]
        rest = authority[closing + 1 :]
        if not rest.startswith(":"):
            raise _ParseError("missing port after IPv6 literal")
        port = _to_port(rest[1:])
    else:
        if ":" not in authority:
            raise _ParseError(f"missing port in {authority!r}")
        host, _, port_text = authority.rpartition(":")
        if not host:
            raise _ParseError(f"missing host in {authority!r}")
        host = host.rstrip(".")  # tolerate fully-qualified "host.example.com."
        port = _to_port(port_text)
    return host, port


def _split_userinfo(core: str) -> tuple[str, str]:
    """Split ``user:pass@host:port`` into (userinfo, authority) at the last @."""
    if "@" in core:
        userinfo, _, authority = core.rpartition("@")
        if not userinfo:
            raise _ParseError("empty credentials before '@'")
        return userinfo, authority
    return "", core


def _split_creds(userinfo: str) -> tuple[str, str]:
    user, sep, password = userinfo.partition(":")
    if not user:
        raise _ParseError("empty username in credentials")
    if not sep:
        raise _ParseError("credentials missing ':' separator (need user:pass)")
    return user, password


def _clean_creds(user: str, password: str) -> tuple[str, str]:
    """Reject whitespace/control characters inside credentials."""
    for name, value in (("username", user), ("password", password)):
        if value and any(ch.isspace() or ord(ch) < 32 for ch in value):
            raise _ParseError(f"{name} contains whitespace/control characters")
    return user, password


# ---------------------------------------------------------------------------
# per-format line parsers — each returns a canonical candidate dict
# ---------------------------------------------------------------------------


def _candidate(
    host: str,
    port: int,
    username: str,
    password: str,
    claimed_type: str | None,
    claimed_country: str | None,
    claimed_anonymity: str | None,
) -> dict[str, Any]:
    return {
        "host": host,
        "port": port,
        "username": username,
        "password": password,
        "claimed_type": claimed_type,
        "claimed_country": claimed_country,
        "claimed_anonymity": claimed_anonymity,
    }


def _parse_ip_port(line: str, source: Source) -> dict[str, Any]:
    host, port = _split_hostport(line)
    return _candidate(
        host, port, "", "", source.claimed_type, None, source.claimed_anonymity
    )


def _parse_ip_port_user_pass(line: str, source: Source) -> dict[str, Any]:
    parts = line.split(":", 3)
    if len(parts) == 2:
        # tolerate cred-less lines inside a cred format
        host, port = _split_hostport(line)
        return _candidate(
            host, port, "", "", source.claimed_type, None,
            source.claimed_anonymity,
        )
    if len(parts) != 4:
        raise _ParseError(f"expected ip:port:user:pass, got {len(parts)} fields")
    host, port = _split_hostport(parts[0] + ":" + parts[1])
    user, password = _clean_creds(parts[2], parts[3])
    return _candidate(
        host, port, user, password, source.claimed_type, None,
        source.claimed_anonymity,
    )


def _parse_ip_port_country(line: str, source: Source) -> dict[str, Any]:
    parts = line.split(":", 2)
    if len(parts) not in (2, 3):
        raise _ParseError(f"expected ip:port[:country], got {len(parts)} fields")
    host, port = _split_hostport(parts[0] + ":" + parts[1])
    country = parts[2].strip() if len(parts) == 3 else None
    return _candidate(
        host, port, "", "", source.claimed_type, country or None,
        source.claimed_anonymity,
    )


def _parse_user_pass_at_host_port(line: str, source: Source) -> dict[str, Any]:
    userinfo, authority = _split_userinfo(line)
    host, port = _split_hostport(authority)
    user, password = _clean_creds(*_split_creds(userinfo))
    return _candidate(
        host, port, user, password, source.claimed_type, None,
        source.claimed_anonymity,
    )


def _parse_proto_prefixed(line: str, source: Source) -> dict[str, Any]:
    first, _, extra_cols = line.partition(",")
    url = first.strip()
    _, _, body = url.partition("://")
    if not _:
        raise _ParseError("line has no protocol:// prefix")
    scheme = url.partition("://")[0].lower()
    core = body.split("/", 1)[0].strip()
    userinfo, authority = _split_userinfo(core)
    host, port = _split_hostport(authority)
    username, password = ("", "")
    if userinfo:
        username, password = _clean_creds(*_split_creds(userinfo))
    claimed_type = _SCHEME_TO_TYPE.get(scheme) or source.claimed_type
    country = None
    if extra_cols:
        cols = [c.strip() for c in extra_cols.split(",")]
        if cols and cols[0]:
            country = cols[0]
    return _candidate(
        host, port, username, password, claimed_type, country,
        source.claimed_anonymity,
    )


def _parse_json_document(text: str, source: Source) -> list[dict[str, Any]]:
    """Parse a JSON-structured API document into candidates.

    Expected shape (geonode-style): ``{"data": [ {...}, ... ]}`` with a
    plain top-level list also accepted. Records need ``ip`` and ``port``;
    ``protocols`` (list) / ``protocol`` / ``country`` / ``anonymityLevel``
    are optional claims. Invalid records are reported as failures by the
    caller via the returned candidates only — a record that cannot yield
    host+port is skipped silently *unless* nothing parses at all.
    """
    try:
        document = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _ParseError(f"document is not valid JSON ({exc.msg})") from exc

    if isinstance(document, dict):
        records = document.get("data", document.get("results", []))
    else:
        records = document
    if not isinstance(records, list):
        raise _ParseError("JSON document has no record list")

    candidates: list[dict[str, Any]] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        host = str(record.get("ip", "") or "").strip()
        if not host:
            continue
        try:
            port = _to_port(str(record.get("port", "")))
        except _ParseError:
            continue
        protocols = record.get("protocols") or []
        if not protocols and record.get("protocol"):
            protocols = [record["protocol"]]
        protocols = [
            str(p).lower() for p in protocols if str(p).lower() in _SCHEME_TO_TYPE
        ]
        claimed_type = protocols[0] if len(protocols) == 1 else source.claimed_type
        country = record.get("country")
        anonymity = record.get("anonymityLevel") or record.get("anonymity")
        anonymity = str(anonymity).lower() if anonymity else None
        if anonymity not in VALID_ANONYMITY_LEVELS:
            anonymity = None
        candidates.append(
            _candidate(host, port, "", "", claimed_type, country, anonymity)
        )
    if not candidates:
        raise _ParseError("JSON document yielded no parsable records")
    return candidates


_LINE_PARSERS = {
    "ip:port": _parse_ip_port,
    "ip:port:user:pass": _parse_ip_port_user_pass,
    "ip:port:country": _parse_ip_port_country,
    "user:pass@ip:port": _parse_user_pass_at_host_port,
    "proto-prefixed": _parse_proto_prefixed,
}


# ---------------------------------------------------------------------------
# identity + validation (public — stage 2 reuses these)
# ---------------------------------------------------------------------------


def proxy_identity(proxy: dict[str, Any]) -> str:
    """Stable connection identity — the key stage 2 (normalize) dedupes on.

    Same host + port + credentials = same effective target. Host is
    lowercased with a trailing root dot dropped; credentials are part of the
    identity because ``ip:port`` with different creds is a different access
    path to the same server.
    """
    return "|".join(
        (
            str(proxy["host"]).lower().rstrip("."),
            str(proxy["port"]),
            str(proxy.get("username", "")),
            str(proxy.get("password", "")),
        )
    )


def validate_proxy(proxy: dict[str, Any]) -> tuple[bool, str | None]:
    """Public candidate sanity check, reused by stage 2 (normalize)."""
    host = str(proxy.get("host", ""))
    if not host or not _host_ok(host):
        return False, f"invalid host {host!r}"
    octets = host.split(".")
    if len(octets) == 4 and all(o.isdigit() for o in octets):
        if any(int(o) > 255 for o in octets):
            return False, f"invalid IPv4 address {host!r}"
    port = proxy.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return False, f"invalid port {port!r}"
    for key in ("username", "password"):
        value = str(proxy.get(key, ""))
        if any(ch.isspace() or ord(ch) < 32 for ch in value):
            return False, f"{key} contains whitespace/control characters"
    claimed_type = proxy.get("claimed_type")
    if claimed_type is not None and claimed_type not in VALID_CLAIMED_TYPES:
        return False, f"invalid claimed_type {claimed_type!r}"
    return True, None


def parse_entry(
    line: str, source: Source
) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one source line into a canonical candidate dict.

    Returns ``(proxy, None)`` on success or ``(None, reason)`` on failure.
    Never raises — a single malformed line must not kill the run.
    """
    try:
        cleaned = unescape(line).strip()
        if not cleaned or cleaned.startswith("#"):
            return None, None  # comments / blanks are not failures
        parser = _LINE_PARSERS.get(source.format)
        if parser is None:
            raise _ParseError(f"format {source.format!r} has no line parser")
        proxy = parser(cleaned, source)
    except _ParseError as exc:
        return None, str(exc)
    except Exception as exc:  # last-resort guard
        return None, f"unexpected parse error: {type(exc).__name__}: {exc}"
    ok, reason = validate_proxy(proxy)
    if not ok:
        return None, reason or "validation failed"
    proxy["source"] = source.id
    proxy["identity"] = proxy_identity(proxy)
    return proxy, None


# ---------------------------------------------------------------------------
# fetching (carried over from the v0.1.0 collector)
# ---------------------------------------------------------------------------


def fetch_url(
    url: str,
    timeout_seconds: int,
    max_bytes: int,
    user_agent: str = USER_AGENT,
) -> tuple[int, bytes]:
    """Fetch a URL and return ``(http_status, raw_bytes)``. Raises on failure."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": user_agent, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", 0) or 0)
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response exceeds max_bytes ({max_bytes})")
    return status, data


# ---------------------------------------------------------------------------
# per-source processing and the stage report
# ---------------------------------------------------------------------------


@dataclass
class SourceResult:
    """Outcome of fetching + parsing one source (also when it failed)."""

    source: Source
    ok: bool = False
    http_status: int | None = None
    bytes_read: int = 0
    lines_read: int = 0
    entries_parsed: int = 0
    entries_failed: int = 0
    failure_samples: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_seconds: float = 0.0
    proxies: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.source.id,
            "format": self.source.format,
            "url": self.source.url,
            "ok": self.ok,
            "http_status": self.http_status,
            "bytes_read": self.bytes_read,
            "lines_read": self.lines_read,
            "entries_parsed": self.entries_parsed,
            "entries_failed": self.entries_failed,
            "failure_samples": self.failure_samples,
            "error": self.error,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


def process_source(
    source: Source,
    cfg: CollectConfig,
    fetch: Callable[..., tuple[int, bytes]] = fetch_url,
) -> SourceResult:
    """Fetch one source and parse its proxy entries. Never raises."""
    result = SourceResult(source=source)
    started = time.monotonic()

    def done() -> SourceResult:
        result.elapsed_seconds = time.monotonic() - started
        return result

    try:
        status, data = fetch(
            source.url, cfg.timeout_seconds, cfg.max_bytes, cfg.user_agent
        )
    except urllib.error.HTTPError as exc:
        result.error = f"HTTP {exc.code}: {exc.reason}"
        return done()
    except urllib.error.URLError as exc:
        result.error = f"URL error: {exc.reason}"
        return done()
    except (TimeoutError, socket.timeout):
        result.error = "timed out"
        return done()
    except (ConnectionError, OSError, ValueError) as exc:
        result.error = f"{type(exc).__name__}: {exc}"
        return done()

    result.http_status = status
    result.bytes_read = len(data)
    text = data.decode("utf-8", errors="replace")

    def record(proxy: dict[str, Any] | None, reason: str | None, line: str) -> None:
        if proxy is None:
            if reason is None:
                return  # comment / blank line — not a failure
            result.entries_failed += 1
            if len(result.failure_samples) < 5:
                result.failure_samples.append(f"{line[:80]} -> {reason}")
            return
        result.proxies.append(proxy)
        result.entries_parsed += 1

    if source.format == "json-structured":
        try:
            candidates = _parse_json_document(text, source)
        except _ParseError as exc:
            result.entries_failed += 1
            result.failure_samples.append(str(exc))
            result.ok = True  # fetch worked; content was unusable
            return done()
        for candidate in candidates:
            ok, reason = validate_proxy(candidate)
            if not ok:
                record(None, reason, json.dumps(candidate)[:80])
                continue
            candidate["source"] = source.id
            candidate["identity"] = proxy_identity(candidate)
            record(candidate, None, "")
    else:
        lines = text.splitlines()
        result.lines_read = len(lines)
        parser = _LINE_PARSERS[source.format]
        for line in lines:
            proxy, reason = parse_entry(line, source)
            record(proxy, reason, line)

    result.ok = True
    return done()


def run_collect(
    cfg: CollectConfig,
    fetch: Callable[..., tuple[int, bytes]] = fetch_url,
    max_workers: int | None = None,
) -> dict[str, Any]:
    """Fetch every enabled source concurrently and build the stage report."""
    enabled = [s for s in cfg.sources if s.enabled]
    workers = max_workers or max(1, min(cfg.fetch_concurrency, len(enabled) or 1))
    results: list[SourceResult] = []
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(process_source, s, cfg, fetch): s for s in enabled}
        for future, source in futures.items():
            try:
                results.append(future.result())
            except Exception as exc:  # defensive belt-and-braces
                results.append(
                    SourceResult(source=source, error=f"worker crashed: {exc}")
                )
    proxies: list[dict[str, Any]] = []
    for result in results:
        proxies.extend(result.proxies)

    return {
        "stage": "collect",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "timeout_seconds": cfg.timeout_seconds,
            "max_bytes": cfg.max_bytes,
            "fetch_concurrency": cfg.fetch_concurrency,
        },
        "sources": [r.as_dict() for r in sorted(results, key=lambda r: r.source.id)],
        "disabled_sources": [
            {"id": s.id, "url": s.url, "notes": s.notes}
            for s in cfg.sources
            if not s.enabled
        ],
        "totals": {
            "sources_enabled": len(enabled),
            "sources_ok": sum(1 for r in results if r.ok),
            "sources_failed": sum(1 for r in results if not r.ok),
            "entries_parsed": len(proxies),
            "entries_failed": sum(r.entries_failed for r in results),
        },
        "proxies": proxies,
    }
