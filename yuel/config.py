"""Configuration loading and validation for the YUEL pipeline.

The source list lives in ``config/sources.json`` (data, not code) so it can
grow over time without touching the collector. This module loads it, validates
the schema strictly enough to catch typos early, and resolves the default
paths (both overridable through environment variables).
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

VALID_SOURCE_TYPES = ("raw_http", "telegram_preview")
DEFAULT_TIMEOUT_SECONDS = 20
DEFAULT_MAX_BYTES = 8_000_000  # 8 MiB per source fetch
DEFAULT_FETCH_CONCURRENCY = 6

_SOURCE_ID_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


class ConfigError(ValueError):
    """Raised when a configuration file does not match the expected schema."""


@dataclass
class Source:
    """One configured public source to collect from."""

    id: str
    type: str
    url: str
    enabled: bool = True
    tags: list[str] = field(default_factory=list)
    note: str = ""


@dataclass
class CollectConfig:
    """Parsed sources file plus collection defaults."""

    sources: list[Source]
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    max_bytes: int = DEFAULT_MAX_BYTES
    fetch_concurrency: int = DEFAULT_FETCH_CONCURRENCY


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def load_sources(path: str | os.PathLike[str]) -> CollectConfig:
    """Load and validate a sources JSON file.

    Schema::

        {
          "schema_version": 1,
          "defaults": {"timeout_seconds": 20, "max_bytes": 8000000,
                       "fetch_concurrency": 6},
          "sources": [
            {"id": "my-source", "type": "raw_http" | "telegram_preview",
             "url": "https://...", "enabled": true,
             "tags": ["..."], "note": "why this source exists"}
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

        source_type = entry.get("type")
        _require(
            source_type in VALID_SOURCE_TYPES,
            f"{ctx}.type ({source_type!r}) must be one of {VALID_SOURCE_TYPES}",
        )

        url = entry.get("url")
        _require(
            isinstance(url, str) and url.startswith(("http://", "https://")),
            f"{ctx}.url must be an http(s) URL",
        )

        enabled = entry.get("enabled", True)
        _require(isinstance(enabled, bool), f"{ctx}.enabled must be a boolean")

        tags = entry.get("tags", [])
        _require(
            isinstance(tags, list) and all(isinstance(t, str) for t in tags),
            f"{ctx}.tags must be a list of strings",
        )

        note = entry.get("note", "")
        _require(isinstance(note, str), f"{ctx}.note must be a string")

        sources.append(
            Source(
                id=source_id,
                type=source_type,
                url=url,
                enabled=enabled,
                tags=tags,
                note=note,
            )
        )

    defaults = raw.get("defaults", {})
    _require(isinstance(defaults, dict), "'defaults' must be an object when present")

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
