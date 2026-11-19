"""Configuration loading and validation for the YUEL pipeline.

The source list lives in ``config/sources.json`` (data, not code) so it can
grow over time without touching the collector. This module loads it, validates
the schema strictly enough to catch typos early, and resolves the default
paths (both overridable through environment variables).

Scope note (v0.3.0): YUEL collects PLAIN proxies — bare ``ip:port`` /
``ip:port:user:pass`` SOCKS4/SOCKS5/HTTP(S) servers used as chain hops —
never standalone tunnel configs (vmess/vless/trojan/...). The ``format``
field tells the collector which line shape a source uses; the ``claimed_*``
fields record what the source ASSERTS about each entry (type, country,
anonymity) so stage 3 can later compare claims against its own live
validation results as a data-quality signal.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_FORMATS = (
    "ip:port",            # 1.2.3.4:8080 (optionally with #-comments)
    "ip:port:user:pass",  # 1.2.3.4:8080:user:pass
    "ip:port:country",    # 1.2.3.4:8080:United States
    "user:pass@ip:port",  # user:pass@1.2.3.4:8080
    "proto-prefixed",     # socks5://1.2.3.4:1080[,US,City] / http://...,CSV columns
    "json-structured",    # JSON API with per-record fields (ip, port, protocols, ...)
)
VALID_CLAIMED_TYPES = ("socks4", "socks5", "http", "https")
VALID_ANONYMITY_LEVELS = ("transparent", "anonymous", "elite")
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_BYTES = 20_000_000  # 20 MiB per source fetch (b0ba67 http.txt ~2 MB)
DEFAULT_FETCH_CONCURRENCY = 6
DEFAULT_USER_AGENT = "YUEL-collector/0.3 (+https://github.com/Edsel-Rahimi/YUEL)"

_SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


class ConfigError(ValueError):
    """Raised when a configuration file does not match the expected schema."""


@dataclass
class Source:
    """One configured public source of plain proxy entries."""

    id: str
    url: str
    format: str
    claimed_type: str | None = None
    claimed_country: bool = False
    claimed_anonymity: str | None = None
    enabled: bool = True
    notes: str = ""


@dataclass
class CollectConfig:
    """Parsed sources file plus collection defaults."""

    sources: list[Source]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_MAX_BYTES
    fetch_concurrency: int = DEFAULT_FETCH_CONCURRENCY
    user_agent: str = DEFAULT_USER_AGENT


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def load_sources(path: str | os.PathLike[str]) -> CollectConfig:
    """Load and validate a sources JSON file.

    Schema::

        {
          "schema_version": 2,
          "defaults": {"timeout_seconds": 20, "max_bytes": 20000000,
                       "fetch_concurrency": 6, "user_agent": "..."},
          "sources": [
            {"id": "my-source",
             "url": "https://...",
             "format": "ip:port" | "ip:port:user:pass" | "ip:port:country"
                     | "user:pass@ip:port" | "proto-prefixed"
                     | "json-structured",
             "claimed_type": "socks5" | "socks4" | "http" | "https" | null,
             "claimed_country": true | false,
             "claimed_anonymity": "transparent" | "anonymous" | "elite" | null,
             "enabled": true,
             "notes": "when added / verified, quirks"}
          ]
        }
    """
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ConfigError(f"sources file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ConfigError(f"sources file is not valid JSON: {path}: {exc}") from exc

    _require(isinstance(raw, dict), "sources file must be a JSON object")
    _require(
        raw.get("schema_version") == 2,
        f"unsupported sources schema_version: {raw.get('schema_version')!r} "
        "(expected 2 — plain-proxy scope)",
    )
    entries = raw.get("sources")
    _require(
        isinstance(entries, list) and bool(entries),
        "'sources' must be a non-empty list",
    )

    seen: set[str] = set()
    sources: list[Source] = []
    for index, entry in enumerate(entries):
        ctx = f"sources[{index}]"
        _require(isinstance(entry, dict), f"{ctx} must be an object")

        source_id = entry.get("id")
        _require(
            isinstance(source_id, str) and bool(source_id),
            f"{ctx}.id must be a non-empty string",
        )
        _require(
            _SOURCE_ID_RE.fullmatch(source_id) is not None,
            f"{ctx}.id ({source_id!r}) may only contain lowercase a-z, digits, "
            "'-' and '_'",
        )
        _require(source_id not in seen, f"duplicate source id: {source_id}")
        seen.add(source_id)

        url = entry.get("url")
        _require(
            isinstance(url, str) and url.startswith(("http://", "https://")),
            f"{ctx}.url must be an http(s) URL",
        )

        fmt = entry.get("format")
        _require(
            fmt in VALID_FORMATS,
            f"{ctx}.format ({fmt!r}) must be one of {VALID_FORMATS}",
        )

        claimed_type = entry.get("claimed_type")
        _require(
            claimed_type is None or claimed_type in VALID_CLAIMED_TYPES,
            f"{ctx}.claimed_type ({claimed_type!r}) must be null or one of "
            f"{VALID_CLAIMED_TYPES}",
        )

        claimed_country = entry.get("claimed_country", False)
        _require(
            isinstance(claimed_country, bool),
            f"{ctx}.claimed_country must be a boolean",
        )

        claimed_anonymity = entry.get("claimed_anonymity")
        _require(
            claimed_anonymity is None or claimed_anonymity in VALID_ANONYMITY_LEVELS,
            f"{ctx}.claimed_anonymity ({claimed_anonymity!r}) must be null or one "
            f"of {VALID_ANONYMITY_LEVELS}",
        )

        enabled = entry.get("enabled", True)
        _require(isinstance(enabled, bool), f"{ctx}.enabled must be a boolean")

        notes = entry.get("notes", "")
        _require(isinstance(notes, str), f"{ctx}.notes must be a string")

        sources.append(
            Source(
                id=source_id,
                url=url,
                format=fmt,
                claimed_type=claimed_type,
                claimed_country=claimed_country,
                claimed_anonymity=claimed_anonymity,
                enabled=enabled,
                notes=notes,
            )
        )

    defaults = raw.get("defaults", {})
    _require(isinstance(defaults, dict), "'defaults' must be an object when present")
    user_agent = defaults.get("user_agent", DEFAULT_USER_AGENT)
    _require(isinstance(user_agent, str) and bool(user_agent),
             "defaults.user_agent must be a non-empty string")

    return CollectConfig(
        sources=sources,
        timeout_seconds=_positive_int(
            defaults.get("timeout_seconds", DEFAULT_TIMEOUT_SECONDS),
            "defaults.timeout_seconds",
        ),
        max_bytes=_positive_int(
            defaults.get("max_bytes", DEFAULT_MAX_BYTES),
            "defaults.max_bytes",
        ),
        fetch_concurrency=_positive_int(
            defaults.get("fetch_concurrency", DEFAULT_FETCH_CONCURRENCY),
            "defaults.fetch_concurrency",
        ),
        user_agent=user_agent,
    )


def _positive_int(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise ConfigError(f"{name} must be an integer, got {value!r}") from exc
    if number <= 0:
        raise ConfigError(f"{name} must be positive, got {number}")
    return number


def default_sources_path() -> Path:
    """Sources file location: $YUEL_SOURCES, else <repo>/config/sources.json."""
    env = os.environ.get("YUEL_SOURCES")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "config" / "sources.json"


def default_data_dir() -> Path:
    """Output root: $YUEL_DATA_DIR, else <repo>/data/."""
    env = os.environ.get("YUEL_DATA_DIR")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "data"
