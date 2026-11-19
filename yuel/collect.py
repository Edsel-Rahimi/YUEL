"""Stage 1 — collect: fetch public sources and extract endpoint URIs.

Supported schemes: ``vmess``, ``vless``, ``trojan``, ``ss`` (SIP002 and the
legacy whole-base64 form), ``hysteria2`` (including the ``hy2://`` alias) and
``tuic``. ``ssr://`` is deliberately not supported (deprecated protocol).

Design rules:
- One dead source must never crash the run: every fetch is wrapped and the
  error is recorded per source in the run report.
- Extraction is regex based and tolerant of real-world noise: HTML-escaped
  text (Telegram web previews), trailing punctuation glued to tokens,
  base64 with wrong padding / urlsafe alphabets, and whole-document base64
  subscription blobs (a file that is a single base64 line).
- Parsing never raises: malformed URIs are counted (a few samples are kept
  for the report) instead of aborting the stage.
- No deduplication here — that is stage 2 (normalize). Entries already carry
  an ``identity`` key computed by :func:`endpoint_identity`, which is what
  dedupe will key on: same host + port + secret is the same effective target
  even when query parameters are reordered or the display tag differs.
"""

from __future__ import annotations

import base64
import binascii
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html import unescape
from typing import Any, Callable

from .config import CollectConfig, Source

USER_AGENT = "YUEL-collector/0.1 (+https://github.com/Edsel-Rahimi/YUEL)"

SCHEME_ALIASES = {"hy2": "hysteria2"}
SUPPORTED_SCHEMES = ("vmess", "vless", "trojan", "ss", "hysteria2", "tuic")

# A URI token may contain almost anything except whitespace and characters
# that commonly wrap URIs in HTML/Markdown (quotes, angle brackets, backticks,
# parentheses/braces, pipes, asterisks, commas). Bracketed IPv6 literals keep
# their square brackets; '#' is kept so the display tag stays attached.
_URI_RE = re.compile(
    r"\b(?:vmess|vless|trojan|ss|hysteria2|hy2|tuic)://[^\s<>\"'`,|*{}()\\]+"
)

_HOST_RE = re.compile(
    r"(?:\[[0-9A-Fa-f:.]+\])"
    r"|(?:\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})"
    r"|(?:[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9_-]{0,61}[A-Za-z0-9])?)*)"
)
_UUID_RE = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)
_B64_CHARSET_RE = re.compile(r"[A-Za-z0-9+/]+")
_B64_DOCUMENT_RE = re.compile(r"[A-Za-z0-9+/=\s]+")
# Punctuation that real-world lists glue to URI tokens ("vmess://xxx)." etc).
_B64_STRIP_CHARS = ",.;:)]}\"'"

_SCRIPT_STYLE_RE = re.compile(r"(?is)<(script|style)\b.*?</\1\s*>")

_VMESS_PARAM_KEYS = (
    "net", "type", "path", "host", "tls", "sni", "alpn", "fp", "scy", "altn",
    "peers", "verify_cert", "headers",
)


class _ParseError(ValueError):
    """Internal: a URI could not be parsed; the message becomes the reason."""


# ---------------------------------------------------------------------------
# base64 helpers
# ---------------------------------------------------------------------------


def _b64_decode(payload: str) -> str:
    """Decode base64 text to UTF-8, tolerating urlsafe alphabets, missing
    padding, stray whitespace, and up to two trailing junk characters.

    Raises ValueError when no decoding attempt succeeds.
    """
    cleaned = "".join(payload.split()).strip(_B64_STRIP_CHARS)
    for candidate in (cleaned, cleaned[:-1], cleaned[:-2]):
        if not candidate:
            continue
        normalized = candidate.replace("-", "+").replace("_", "/").rstrip("=")
        if not _B64_CHARSET_RE.fullmatch(normalized):
            continue
        padded = normalized + "=" * (-len(normalized) % 4)
        try:
            raw = base64.b64decode(padded, validate=True)
            return raw.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError):
            continue
    raise ValueError("not valid base64")


def _looks_like_base64_document(text: str) -> bool:
    """True when the whole document is plausibly a base64 subscription body."""
    compact = "".join(text.split())
    if len(compact) < 64 or len(compact) % 4 != 0:
        return False
    return _B64_DOCUMENT_RE.fullmatch(compact) is not None


# ---------------------------------------------------------------------------
# extraction
# ---------------------------------------------------------------------------


def _collect_unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def extract_uris(text: str) -> tuple[list[str], str]:
    """Extract endpoint URIs from a raw document.

    Returns ``(uris, mode)``. ``mode`` is ``"text"`` normally, or
    ``"base64"`` when the document is a whole-body base64 subscription blob
    that only yields URIs after decoding. Literal duplicates are removed and
    order is preserved.
    """
    uris = _collect_unique(_URI_RE.findall(text))
    if uris:
        return uris, "text"
    if _looks_like_base64_document(text):
        try:
            decoded = _b64_decode(text)
        except ValueError:
            decoded = None
        if decoded:
            return _collect_unique(_URI_RE.findall(decoded)), "base64"
    return [], "text"


# ---------------------------------------------------------------------------
# URI parsing
# ---------------------------------------------------------------------------


def _split_fragment(body: str) -> tuple[str, str]:
    """Split off the ``#fragment`` (node display name); returns (core, name)."""
    if "#" in body:
        core, _, fragment = body.partition("#")
        return core, urllib.parse.unquote(unescape(fragment))
    return body, ""


def _parse_query(query_string: str) -> dict[str, str]:
    return dict(urllib.parse.parse_qsl(unescape(query_string), keep_blank_values=True))


def _to_port(text: str) -> int:
    text = text.strip()
    if not text.isdigit():
        raise _ParseError(f"invalid port {text!r}")
    port = int(text)
    if not 1 <= port <= 65535:
        raise _ParseError(f"port out of range: {port}")
    return port


def _split_hostport(core: str) -> tuple[str, str, int]:
    """Split ``[userinfo@]host:port[/path]`` into (userinfo, host, port).

    Handles bracketed IPv6 literals and userinfo that itself contains '@'
    (split at the *last* '@').
    """
    core = unescape(core).strip()
    if not core:
        raise _ParseError("empty authority")
    if "@" in core:
        userinfo, _, authority = core.rpartition("@")
    else:
        userinfo, authority = "", core
    authority = authority.split("/", 1)[0].strip()
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
            raise _ParseError("missing port")
        host, _, port_text = authority.rpartition(":")
        if not host:
            raise _ParseError(f"missing host in {authority!r}")
        host = host.rstrip(".")  # tolerate fully-qualified "host.example.com."
        port = _to_port(port_text)
    return userinfo, host, port


def _parse_vmess(uri: str) -> dict[str, Any]:
    """Parse ``vmess://<base64(JSON)>`` — the v2fly sharing format."""
    _, _, body = uri.partition("://")
    core, fragment_name = _split_fragment(body)
    token = core.split("?", 1)[0]
    try:
        text = _b64_decode(token)
    except ValueError as exc:
        raise _ParseError(f"vmess payload is not decodable base64 ({exc})") from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise _ParseError(f"vmess payload is not JSON ({exc.msg})") from exc
    if not isinstance(payload, dict):
        raise _ParseError("vmess payload is not a JSON object")

    host = str(payload.get("add", "") or "").strip()
    if not host:
        raise _ParseError("vmess payload missing 'add' (host)")
    port_raw = payload.get("port")
    if port_raw is None or str(port_raw).strip() == "":
        raise _ParseError("vmess payload missing 'port'")
    try:
        port = _to_port(str(port_raw))
    except _ParseError:
        raise _ParseError(f"vmess port invalid: {port_raw!r}") from None
    secret = str(payload.get("id", "") or "").strip()
    if not secret:
        raise _ParseError("vmess payload missing 'id' (uuid)")

    params = {}
    for key in _VMESS_PARAM_KEYS:
        value = payload.get(key)
        if value not in (None, ""):
            params[key] = str(value)

    aid_raw = payload.get("aid")
    if aid_raw is None:
        aid_raw = payload.get("alterId", 0)
    try:
        alter_id = int(str(aid_raw))
    except ValueError:
        alter_id = 0

    extra: dict[str, Any] = {"alter_id": alter_id}
    reserved = {"v", "ps", "add", "port", "id", "aid", "alterId", *_VMESS_PARAM_KEYS}
    leftover = {
        str(k): v
        for k, v in payload.items()
        if k not in reserved and v not in (None, "")
    }
    if leftover:
        extra["fields"] = leftover

    name = str(payload.get("ps", "") or "") or fragment_name
    return {
        "scheme": "vmess",
        "host": host,
        "port": port,
        "secret": secret,
        "params": params,
        "name": name,
        "extra": extra,
    }


def _split_ss_userinfo(userinfo: str) -> tuple[str, str]:
    """Return (method, password) from an ss userinfo segment.

    Accepts the base64-encoded ``method:password`` form (SIP002) and the
    plain ``method:password`` form used by the 2022 ciphers. Base64 never
    contains ':', so a raw ':' is checked first.
    """
    text = userinfo
    if ":" not in text:
        try:
            text = _b64_decode(userinfo)
        except ValueError as exc:
            raise _ParseError(
                "ss userinfo is neither method:password nor decodable base64"
            ) from exc
    if ":" not in text:
        raise _ParseError("ss userinfo missing method:password separator")
    method, _, password = text.partition(":")
    if not method:
        raise _ParseError("ss userinfo missing cipher method")
    return method, password


def _parse_ss(uri: str) -> dict[str, Any]:
    """Parse ss:// in SIP002 form or the legacy whole-base64 form."""
    _, _, body = uri.partition("://")
    core, fragment_name = _split_fragment(body)
    query: dict[str, str] = {}
    if "?" in core:
        core, _, query_string = core.partition("?")
        query = _parse_query(query_string)
    if "@" in core:
        userinfo, host, port = _split_hostport(core)
    else:
        # Legacy form: everything is base64 of method:password@host:port.
        try:
            text = _b64_decode(core)
        except ValueError as exc:
            raise _ParseError(f"ss payload is not decodable ({exc})") from exc
        if "@" not in text:
            raise _ParseError("ss legacy payload has no @host:port part")
        userinfo, host, port = _split_hostport(text)
    method, password = _split_ss_userinfo(userinfo)
    return {
        "scheme": "ss",
        "host": host,
        "port": port,
        "secret": password,
        "params": {k.lower(): v for k, v in query.items()},
        "name": fragment_name,
        "extra": {"method": method},
    }


def _parse_userinfo_style(scheme: str, uri: str) -> dict[str, Any]:
    """Parse vless/trojan/hysteria2/tuic URIs.

    Shape: ``scheme://[secret@]host:port?params#name``. hysteria2 also
    accepts the auth in a ``?auth=`` query parameter instead of userinfo.
    """
    _, _, body = uri.partition("://")
    core, fragment_name = _split_fragment(body)
    query: dict[str, str] = {}
    if "?" in core:
        core, _, query_string = core.partition("?")
        query = _parse_query(query_string)
    userinfo, host, port = _split_hostport(core)
    params = {k.lower(): v for k, v in query.items()}
    extra: dict[str, Any] = {}
    if scheme == "tuic":
        uuid, sep, password = userinfo.partition(":")
        if not sep:
            raise _ParseError("tuic userinfo must be uuid:password")
        secret = uuid
        extra["password"] = password
    elif scheme == "hysteria2":
        secret = userinfo or params.get("auth", "")
        if not secret:
            raise _ParseError(
                "hysteria2 endpoint has no auth (need userinfo or ?auth=)"
            )
    else:
        secret = userinfo
    return {
        "scheme": scheme,
        "host": host,
        "port": port,
        "secret": secret,
        "params": params,
        "name": fragment_name,
        "extra": extra,
    }


def endpoint_identity(endpoint: dict[str, Any]) -> str:
    """Stable connection identity, the key stage 2 (normalize) will dedupe on.

    Same host + port + secret = same effective target, regardless of query
    parameter order or display tag. Host is lowercased (DNS names are
    case-insensitive, and a trailing root dot is dropped); the scheme stays
    in the key because one host:port can legitimately speak two protocols.
    """
    return "|".join(
        (
            str(endpoint["scheme"]),
            str(endpoint["host"]).lower().rstrip("."),
            str(endpoint["port"]),
            str(endpoint.get("secret", "")),
        )
    )


def validate_endpoint(endpoint: dict[str, Any]) -> tuple[bool, str | None]:
    """Public endpoint sanity check, reused by stage 2 (normalize)."""
    scheme = endpoint["scheme"]
    host = str(endpoint.get("host", ""))
    if not host or not _HOST_RE.fullmatch(host):
        return False, f"invalid host {host!r}"
    octets = host.split(".")
    if len(octets) == 4 and all(o.isdigit() for o in octets):
        if any(int(o) > 255 for o in octets):
            return False, f"invalid IPv4 address {host!r}"
    port = endpoint.get("port")
    if not isinstance(port, int) or not 1 <= port <= 65535:
        return False, f"invalid port {port!r}"
    secret = str(endpoint.get("secret", ""))
    if scheme in ("vmess", "vless", "tuic") and not _UUID_RE.fullmatch(secret):
        return False, f"invalid {scheme} uuid {secret!r}"
    if scheme == "trojan" and not secret:
        return False, "trojan endpoint missing password"
    if scheme == "hysteria2" and not secret:
        return False, "hysteria2 endpoint missing auth"
    if scheme == "ss":
        if not str(endpoint.get("extra", {}).get("method", "")):
            return False, "ss endpoint missing cipher method"
        if not secret:
            return False, "ss endpoint missing password"
    return True, None


def parse_endpoint(uri: str) -> tuple[dict[str, Any] | None, str | None]:
    """Parse one endpoint URI into the canonical dict.

    Returns ``(endpoint, None)`` on success or ``(None, reason)`` on failure.
    Never raises — a single malformed URI must not kill the run.
    """
    try:
        raw_scheme = uri.partition("://")[0].lower()
        scheme = SCHEME_ALIASES.get(raw_scheme, raw_scheme)
        if scheme not in SUPPORTED_SCHEMES:
            return None, f"unsupported scheme {raw_scheme!r}"
        if scheme == "vmess":
            endpoint = _parse_vmess(uri)
        elif scheme == "ss":
            endpoint = _parse_ss(uri)
        else:
            endpoint = _parse_userinfo_style(scheme, uri)
    except _ParseError as exc:
        return None, str(exc)
    except Exception as exc:  # last-resort guard
        return None, f"unexpected parse error: {type(exc).__name__}: {exc}"
    ok, reason = validate_endpoint(endpoint)
    if not ok:
        return None, reason or "validation failed"
    endpoint["identity"] = endpoint_identity(endpoint)
    return endpoint, None


# ---------------------------------------------------------------------------
# fetching
# ---------------------------------------------------------------------------


def fetch_url(url: str, timeout_seconds: int, max_bytes: int) -> tuple[int, bytes]:
    """Fetch a URL and return ``(http_status, raw_bytes)``. Raises on failure."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "*/*"},
    )
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        status = int(getattr(response, "status", 0) or 0)
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"response exceeds max_bytes ({max_bytes})")
    return status, data


def _strip_telegram_chrome(page_html: str) -> str:
    """Remove <script>/<style> blocks from a t.me/s page before extraction."""
    return _SCRIPT_STYLE_RE.sub(" ", page_html)


# ---------------------------------------------------------------------------
# per-source processing and the stage report
# ---------------------------------------------------------------------------


@dataclass
class SourceResult:
    """Outcome of fetching + extracting one source (also when it failed)."""

    source: Source
    ok: bool = False
    http_status: int | None = None
    bytes_read: int = 0
    mode: str = "text"
    uris_found: int = 0
    endpoints_parsed: int = 0
    endpoints_failed: int = 0
    failure_samples: list[str] = field(default_factory=list)
    error: str | None = None
    elapsed_seconds: float = 0.0
    endpoints: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.source.id,
            "type": self.source.type,
            "url": self.source.url,
            "tags": self.source.tags,
            "ok": self.ok,
            "http_status": self.http_status,
            "bytes_read": self.bytes_read,
            "mode": self.mode,
            "uris_found": self.uris_found,
            "endpoints_parsed": self.endpoints_parsed,
            "endpoints_failed": self.endpoints_failed,
            "failure_samples": self.failure_samples,
            "error": self.error,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
        }


def process_source(
    source: Source,
    cfg: CollectConfig,
    fetch: Callable[[str, int, int], tuple[int, bytes]] = fetch_url,
) -> SourceResult:
    """Fetch one source and parse its endpoints. Never raises."""
    result = SourceResult(source=source)
    started = time.monotonic()

    def done() -> SourceResult:
        result.elapsed_seconds = time.monotonic() - started
        return result

    try:
        status, data = fetch(source.url, cfg.timeout_seconds, cfg.max_bytes)
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
    if source.type == "telegram_preview":
        text = _strip_telegram_chrome(text)

    uris, mode = extract_uris(text)
    result.mode = mode
    result.uris_found = len(uris)
    for uri in uris:
        endpoint, reason = parse_endpoint(uri)
        if endpoint is None:
            result.endpoints_failed += 1
            if len(result.failure_samples) < 5:
                result.failure_samples.append(f"{uri[:80]} -> {reason}")
            continue
        endpoint["source"] = source.id
        result.endpoints.append(endpoint)
        result.endpoints_parsed += 1
    result.ok = True
    return done()


def run_collect(
    cfg: CollectConfig,
    fetch: Callable[[str, int, int], tuple[int, bytes]] = fetch_url,
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
    endpoints: list[dict[str, Any]] = []
    for result in results:
        endpoints.extend(result.endpoints)

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
            {"id": s.id, "url": s.url, "note": s.note}
            for s in cfg.sources
            if not s.enabled
        ],
        "totals": {
            "sources_enabled": len(enabled),
            "sources_ok": sum(1 for r in results if r.ok),
            "sources_failed": sum(1 for r in results if not r.ok),
            "uris_found": sum(r.uris_found for r in results),
            "endpoints_parsed": len(endpoints),
            "endpoints_failed": sum(r.endpoints_failed for r in results),
        },
        "endpoints": endpoints,
    }
