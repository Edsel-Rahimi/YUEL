"""Stage 5 — geo: IP→country classification via a public IP-to-country table.

Table choice — **iptoasn.com ``ip2asn-v4.tsv.gz``**: free, public-domain,
refreshed daily, one gzip TSV with simple ``[start, end, AS, country, ASname]``
rows, no registration. The lookup itself is isolated in :class:`GeoTable`
(constructed from TSV text) so the data source can be swapped later by
changing only the fetch + parse glue; ``table_url`` and ``refresh_hours``
live in ``config/geo.json``.

Behavior:

- The table is downloaded **once per refresh window** (default 72 h) and
  cached at ``data/cache/geo/ip2asn-v4.tsv.gz`` — not on every run.
- A failed download degrades gracefully: a stale cache is still used (with
  a warning recorded in the report); with no cache at all every proxy is
  marked ``unclassified`` and the stage still succeeds — geo never crashes
  the pipeline.
- Only literal IPv4 hosts are classified. Domain-hosted proxies and IPv6
  hosts are explicitly ``unclassified`` — never guessed.
"""

from __future__ import annotations

import bisect
import copy
import gzip
import json
import os
import tempfile
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from .stage import StageResult

DEFAULT_CONFIG = {
    "schema_version": 1,
    "table_url": "https://iptoasn.com/data/ip2asn-v4.tsv.gz",
    "cache_dir": "cache/geo",
    "refresh_hours": 72,
    "fetch_timeout_seconds": 180,
    "max_bytes": 50_000_000,
}

USER_AGENT = "YUEL-geo/0.5 (+https://github.com/Edsel-Rahimi/YUEL)"
UNCLASSIFIED = "unclassified"


class GeoConfigError(ValueError):
    """Invalid geo-stage configuration."""


def default_geo_config_path() -> Path:
    """Geo config location: $YUEL_GEO_CONFIG, else <repo>/config/geo.json."""
    env = os.environ.get("YUEL_GEO_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "config" / "geo.json"


def load_geo_config(path: Path | None) -> dict[str, Any]:
    """Load config/geo.json over built-in defaults; strict validation."""
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None and Path(path).exists():
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise GeoConfigError(f"cannot read {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise GeoConfigError(f"{path} is not a JSON object")
        if loaded.get("schema_version") != 1:
            raise GeoConfigError(
                f"unsupported schema_version: {loaded.get('schema_version')!r}"
            )
        for key in ("table_url", "cache_dir", "refresh_hours",
                    "fetch_timeout_seconds", "max_bytes"):
            if key in loaded:
                config[key] = loaded[key]
    if not str(config["table_url"]).startswith(("http://", "https://")):
        raise GeoConfigError("table_url must be an http(s) URL")
    for key in ("refresh_hours", "fetch_timeout_seconds", "max_bytes"):
        if not isinstance(config[key], (int, float)) or config[key] <= 0:
            raise GeoConfigError(f"{key} must be a number > 0")
    return config


# ---------------------------------------------------------------------------
# the swappable lookup core
# ---------------------------------------------------------------------------


def ip_to_int(ip: str) -> int | None:
    """Parse a literal IPv4 address into its integer form; None if not one."""
    parts = str(ip).strip().split(".")
    if len(parts) != 4:
        return None
    value = 0
    for part in parts:
        if not part.isdigit() or (len(part) > 1 and part[0] == "0"):
            return None
        octet = int(part)
        if octet > 255:
            return None
        value = (value << 8) | octet
    return value


@dataclass
class GeoTable:
    """Sorted IP-range → country table with bisect lookup."""

    ranges: list[tuple[int, int, str]]  # (start_int, end_int, country)

    @classmethod
    def from_tsv(cls, text: str) -> "GeoTable":
        """Parse iptoasn-style TSV: ``start\\tend\\tAS\\tcountry\\tASname``.

        Invalid rows (non-numeric bounds, missing country) are skipped —
        one bad line never invalidates the table.
        """
        ranges: list[tuple[int, int, str]] = []
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 4:
                continue
            try:
                start = int(cols[0])
                end = int(cols[1])
            except ValueError:
                continue
            country = cols[3].strip().upper()
            if end < start or len(country) != 2 or not country.isalpha():
                continue
            ranges.append((start, end, country))
        ranges.sort(key=lambda r: r[0])
        return cls(ranges=ranges)

    def lookup(self, ip: str) -> str | None:
        """Country for a literal IPv4, or None when not covered by any range."""
        ip_int = ip_to_int(ip)
        if ip_int is None:
            return None
        starts = [r[0] for r in self.ranges]
        index = bisect.bisect_right(starts, ip_int) - 1
        if index < 0:
            return None
        start, end, country = self.ranges[index]
        if start <= ip_int <= end:
            return country
        return None


# ---------------------------------------------------------------------------
# fetch + cache with graceful degradation
# ---------------------------------------------------------------------------


def fetch_table(url: str, timeout_seconds: float, max_bytes: int) -> bytes:
    """Download the (gzipped) table. Module-level seam, patched in tests."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        data = response.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError(f"table exceeds max_bytes ({max_bytes})")
    return data


def _cache_age_hours(cache_path: Path, now_ts: float) -> float:
    try:
        return max(0.0, (now_ts - cache_path.stat().st_mtime) / 3600)
    except OSError:
        return float("inf")


def _table_from_cache(cache_path: Path) -> GeoTable | None:
    try:
        return GeoTable.from_tsv(
            gzip.decompress(cache_path.read_bytes()).decode("utf-8", "replace")
        )
    except (OSError, gzip.BadGzipFile, UnicodeDecodeError):
        return None


def load_table(
    config: dict[str, Any],
    cache_path: Path,
    fetch: Callable[..., bytes] = fetch_table,
) -> tuple[GeoTable | None, dict[str, Any]]:
    """Return ``(table, info)`` — never raises on network/parse failure.

    ``info`` carries what happened: ``source`` (downloaded / cache-fresh /
    cache-stale / none), ``age_hours``, ``warning`` (None or a string the
    stage report can surface), ``ranges`` (row count).
    """
    now_ts = time.time()
    info: dict[str, Any] = {"warning": None, "age_hours": None, "ranges": 0}

    def finish(table: GeoTable | None, source: str) -> tuple[GeoTable | None, dict]:
        info["source"] = source
        info["ranges"] = len(table.ranges) if table else 0
        return table, info

    age = _cache_age_hours(cache_path, now_ts)
    if age != float("inf") and age < config["refresh_hours"]:
        table = _table_from_cache(cache_path)
        if table is not None and table.ranges:
            info["age_hours"] = round(age, 1)
            return finish(table, "cache-fresh")

    try:
        blob = fetch(
            config["table_url"],
            config["fetch_timeout_seconds"],
            config["max_bytes"],
        )
        text = gzip.decompress(blob).decode("utf-8", "replace")
        table = GeoTable.from_tsv(text)
        if not table.ranges:
            raise ValueError("table contains no valid ranges")
    except Exception as exc:  # network/gzip/parse — all degrade the same way
        if age != float("inf"):
            table = _table_from_cache(cache_path)
            if table is not None and table.ranges:
                info["age_hours"] = round(age, 1)
                info["warning"] = (
                    f"table refresh failed ({type(exc).__name__}: {exc}); "
                    f"using stale cache ({info['age_hours']}h old)"
                )
                return finish(table, "cache-stale")
        info["warning"] = (
            f"IP-to-country table unavailable ({type(exc).__name__}: {exc}); "
            "all proxies will be unclassified this run"
        )
        return finish(None, "none")

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(cache_path.parent), prefix=".geo-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(blob)
        os.replace(tmp_name, cache_path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    info["age_hours"] = 0.0
    return finish(table, "downloaded")


# ---------------------------------------------------------------------------
# stage entrypoint
# ---------------------------------------------------------------------------


def stage_geo(
    cfg_path: Path,
    data_dir: Path,
    geo_cfg_path: Path | None = None,
    fetch: Callable[..., bytes] = fetch_table,
    **_: Any,
) -> StageResult:
    """Stage 5: attach a country (or ``unclassified``) to every scored proxy."""
    scored_path = data_dir / "scored" / "proxies_scored.json"
    if not scored_path.exists():
        return StageResult(
            "geo",
            False,
            f"stage-4 output not found: {scored_path} (run score first)",
        )
    try:
        proxies = json.loads(scored_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return StageResult("geo", False, f"cannot read stage-4 output: {exc}")
    if not isinstance(proxies, list):
        return StageResult("geo", False, "stage-4 output is not a JSON list")

    try:
        config = load_geo_config(geo_cfg_path or default_geo_config_path())
    except GeoConfigError as exc:
        return StageResult("geo", False, f"config error: {exc}")

    cache_path = data_dir / config["cache_dir"] / "ip2asn-v4.tsv.gz"
    table, table_info = load_table(config, cache_path, fetch=fetch)

    classified = 0
    unclassified = 0
    domain_or_ipv6 = 0
    not_in_table = 0
    by_country: dict[str, int] = {}
    geo_proxies = []
    for proxy in proxies:
        entry = dict(proxy)
        country = UNCLASSIFIED
        ip_int = ip_to_int(proxy.get("host", ""))
        if ip_int is None:
            domain_or_ipv6 += 1  # domain host or IPv6 literal — never guessed
        elif table is not None:
            match = table.lookup(proxy["host"])
            if match:
                country = match
                classified += 1
            else:
                not_in_table += 1
        if country == UNCLASSIFIED:
            unclassified += 1
        else:
            by_country[country] = by_country.get(country, 0) + 1
        entry["country"] = country
        geo_proxies.append(entry)

    out_dir = data_dir / "geo"
    out_dir.mkdir(parents=True, exist_ok=True)
    geo_path = out_dir / "proxies_geo.json"
    report_path = out_dir / "geo_report.json"
    geo_path.write_text(
        json.dumps(geo_proxies, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report = {
        "stage": "geo",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "table_url": config["table_url"],
            "refresh_hours": config["refresh_hours"],
        },
        "table": table_info,
        "input": {"proxies": len(proxies)},
        "classified": classified,
        "unclassified": unclassified,
        "unclassified_reasons": {
            "domain_or_ipv6_host": domain_or_ipv6,
            "not_in_table": not_in_table if table is not None else 0,
            "table_unavailable": 0 if table is not None else len(proxies),
        },
        "by_country": dict(sorted(by_country.items(), key=lambda kv: -kv[1])),
        "geo_file": geo_path.name,
    }
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )

    detail = (
        f"classified {classified}/{len(proxies)} proxies across "
        f"{len(by_country)} countries ({table_info.get('source')} table, "
        f"{table_info.get('ranges')} ranges)"
    )
    if table_info.get("warning"):
        detail += f"; WARNING: {table_info['warning']}"
    return StageResult("geo", True, detail, [geo_path, report_path])
