"""Stage 3 — validate: TCP prefilter + direct protocol handshake checks.

Input:  ``data/normalized/proxies_normalized.json`` (stage 2 output).
Output: ``data/validated/proxies_validated.json`` — every *tested* candidate
        with its ``check`` verdict, plus ``data/validated/validate_report.json``.

Scope (v0.3.0): plain SOCKS4/SOCKS5/HTTP(S) proxies. No engine binaries are
involved — validation is a raw socket client in-process (much lighter than
the pre-0.3.0 tunnel-config engine approach):

1. **Prefilter** — one plain TCP connect per unique ``host:port`` (a large
   worker pool; endpoints sharing a target are only checked once).
   Unreachable targets never reach the handshake pass.
2. **Handshake pass** — for each survivor, in the order implied by its
   *claimed* type:
   - ``socks5``  → real SOCKS5 greeting + optional RFC 1929 auth + CONNECT
   - ``socks4``  → real SOCKS4 CONNECT (target resolved to IPv4 locally)
   - ``http``    → plain proxied GET (absolute-URI), then CONNECT fallback
   - ``https``   → CONNECT tunnel first, then proxied GET
   - unknown     → SOCKS5 first, then HTTP GET, then HTTP CONNECT
   The FIRST strategy that returns a real HTTP status < 400 through the
   proxy wins; the protocol that actually worked is recorded as
   ``type_confirmed`` (a declared type is a claim, not a truth).
3. **Claim calibration** — the report compares each source's claimed type
   against the measured type (agree / disagree / claim-unknown), so sources
   whose claims frequently disagree with live validation can be flagged
   later as a data-quality signal.

Success/latency/timeout/concurrency discipline is unchanged from the
v0.2.0 engine-based stage: bounded worker pool, per-attempt socket timeouts,
never-raises checks, latency percentiles, failure samples. Since no process
is spawned, there is nothing to clean up beyond sockets.
"""

from __future__ import annotations

import copy
import json
import os
import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .proxy_client import (
    http_proxy_get,
    probe_http_connect,
    probe_socks4,
    probe_socks5,
)
from .stage import StageResult

DEFAULT_CONFIG = {
    "schema_version": 1,
    "prefilter": {"timeout_seconds": 3, "workers": 128},
    "probe": {
        "url": "http://www.gstatic.com/generate_204",
        "timeout_seconds": 8,
    },
    "workers": 100,
}

MAX_FAILURE_SAMPLES = 5

# strategies to try, in order, keyed by the CLAIMED type
STRATEGIES_BY_CLAIM: dict[str | None, tuple[str, ...]] = {
    "socks5": ("socks5",),
    "socks4": ("socks4",),
    "http": ("http_get", "http_connect"),
    "https": ("http_connect", "http_get"),
    None: ("socks5", "http_get", "http_connect"),
}

_METHOD_TO_CONFIRMED = {
    "socks5": "socks5",
    "socks4": "socks4",
    "http_get": "http",
    "http_connect": "http",
}


class ValidateConfigError(ValueError):
    """Invalid validate-stage configuration."""


def default_validate_config_path() -> Path:
    """Validate config location: $YUEL_VALIDATE_CONFIG, else
    <repo>/config/validate.json (so the stage works from any CWD)."""
    env = os.environ.get("YUEL_VALIDATE_CONFIG")
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent / "config" / "validate.json"


def load_validate_config(path: Path | None) -> dict[str, Any]:
    """Load config/validate.json over the built-in defaults.

    Raises ValidateConfigError on malformed files; a missing file is fine
    (pure defaults — plain-proxy validation needs no pinned assets).
    """
    config = copy.deepcopy(DEFAULT_CONFIG)
    if path is not None and Path(path).exists():
        try:
            loaded = json.loads(Path(path).read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise ValidateConfigError(f"cannot read {path}: {exc}") from exc
        if not isinstance(loaded, dict):
            raise ValidateConfigError(f"{path} is not a JSON object")
        schema = loaded.get("schema_version")
        if schema != 1:
            raise ValidateConfigError(f"unsupported schema_version: {schema!r}")
        for key in ("prefilter", "probe"):
            if isinstance(loaded.get(key), dict):
                config[key].update(loaded[key])
        if "workers" in loaded:
            config["workers"] = loaded["workers"]
    if not isinstance(config["workers"], int) or config["workers"] < 1:
        raise ValidateConfigError(f"invalid workers: {config['workers']!r}")
    if str(config["probe"].get("url", "")).startswith("https://"):
        raise ValidateConfigError("probe url must be plain http (no TLS hop)")
    return config


# ---------------------------------------------------------------------------
# pass 1 — TCP prefilter (kept from the v0.2.0 stage)
# ---------------------------------------------------------------------------


@dataclass
class PrefilterResult:
    targets: int = 0
    passed: set[str] = field(default_factory=set)  # "host|port"
    failed: int = 0
    failure_samples: list[str] = field(default_factory=list)
    elapsed_seconds: float = 0.0


def _tcp_probe(host: str, port: int, timeout_seconds: float) -> str | None:
    """One TCP connect; None = reachable, str = failure reason."""
    try:
        sock = socket.create_connection((host, port), timeout=timeout_seconds)
        sock.close()
        return None
    except OSError as exc:
        return f"{type(exc).__name__}: {exc}"


def prefilter(
    proxies: list[dict[str, Any]], timeout_seconds: float, workers: int
) -> PrefilterResult:
    """TCP-connect every unique host:port; return which pairs are reachable."""
    targets: set[tuple[str, int]] = {
        (str(proxy["host"]).strip("[]").lower(), int(proxy["port"]))
        for proxy in proxies
    }
    result = PrefilterResult(targets=len(targets))
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(_tcp_probe, host, port, timeout_seconds): (host, port)
            for host, port in targets
        }
        for future in as_completed(futures):
            host, port = futures[future]
            error = future.result()
            if error is None:
                result.passed.add(f"{host}|{port}")
            else:
                result.failed += 1
                if len(result.failure_samples) < MAX_FAILURE_SAMPLES:
                    result.failure_samples.append(f"{host}:{port} {error}")
    result.elapsed_seconds = round(time.monotonic() - start, 2)
    return result


# ---------------------------------------------------------------------------
# pass 2 — handshake validation (no engines; direct protocol clients)
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    identity: str
    claimed_type: str | None
    ok: bool = False
    type_confirmed: str | None = None
    method_used: str | None = None
    latency_ms: float | None = None
    http_status: int | None = None
    error: str | None = None


def _run_strategy(
    method: str,
    proxy: dict[str, Any],
    probe_url: str,
    timeout_seconds: float,
) -> Any:
    """Dispatch one handshake attempt; returns proxy_client.ProbeResult."""
    host = str(proxy["host"]).strip("[]")
    port = int(proxy["port"])
    username = str(proxy.get("username") or "") or None
    password = str(proxy.get("password") or "") or None
    if method == "socks5":
        return probe_socks5(host, port, probe_url, timeout_seconds, username, password)
    if method == "socks4":
        return probe_socks4(host, port, probe_url, timeout_seconds, username)
    if method == "http_get":
        return http_proxy_get(
            host, port, probe_url, timeout_seconds, username, password
        )
    if method == "http_connect":
        return probe_http_connect(
            host, port, probe_url, timeout_seconds, username, password
        )
    raise ValueError(f"unknown validation method {method!r}")


def check_proxy(
    proxy: dict[str, Any],
    probe_url: str,
    timeout_seconds: float,
) -> CheckResult:
    """Validate one candidate with real protocol handshakes. Never raises.

    Strategies run in claim order; the first tunnel that returns an HTTP
    status < 400 through the proxy confirms the working protocol.
    """
    claimed = proxy.get("claimed_type")
    if claimed not in STRATEGIES_BY_CLAIM:
        claimed = None  # defensive: unknown claim behaves as unknown type
    result = CheckResult(
        identity=proxy["identity"], claimed_type=proxy.get("claimed_type")
    )
    errors: list[str] = []
    for method in STRATEGIES_BY_CLAIM[claimed]:
        probe = _run_strategy(method, proxy, probe_url, timeout_seconds)
        if probe.ok and probe.http_status is not None and probe.http_status < 400:
            result.ok = True
            result.type_confirmed = _METHOD_TO_CONFIRMED[method]
            result.method_used = method
            result.latency_ms = (
                round(probe.latency_ms, 1) if probe.latency_ms is not None else None
            )
            result.http_status = probe.http_status
            return result
        errors.append(f"{method}: {probe.error or f'HTTP {probe.http_status}'}")
    result.error = "; ".join(errors)
    return result


def claim_agreement(
    claimed_type: str | None, confirmed_type: str | None, method_used: str | None
) -> str:
    """Compare what the source asserted with what the handshake measured."""
    if claimed_type is None:
        return "unknown"
    if confirmed_type == claimed_type:
        return "agree"
    if (
        claimed_type == "https"
        and confirmed_type == "http"
        and method_used == "http_connect"
    ):
        return "agree"
    return "disagree"


def _percentile(sorted_values: list[float], q: float) -> float | None:
    """Linear-interpolation percentile over an ascending list."""
    if not sorted_values:
        return None
    pos = q * (len(sorted_values) - 1)
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    frac = pos - lo
    return round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac, 1)


def run_checks(
    proxies: list[dict[str, Any]],
    config: dict[str, Any],
    progress_every: int = 0,
) -> list[CheckResult]:
    """Handshake-check proxies with a bounded worker pool. Never raises."""
    if not proxies:
        return []
    probe_url = config["probe"]["url"]
    timeout = config["probe"]["timeout_seconds"]
    results: list[CheckResult] = []
    with ThreadPoolExecutor(max_workers=config["workers"]) as pool:
        futures = [
            pool.submit(check_proxy, proxy, probe_url, timeout) for proxy in proxies
        ]
        for index, future in enumerate(as_completed(futures), start=1):
            results.append(future.result())
            if progress_every and index % progress_every == 0:
                alive = sum(1 for r in results if r.ok)
                print(
                    f"       checked {index}/{len(proxies)} ({alive} alive so far)",
                    flush=True,
                )
    return results


# ---------------------------------------------------------------------------
# stage entrypoint
# ---------------------------------------------------------------------------


def stage_validate(
    cfg_path: Path,
    data_dir: Path,
    validate_cfg_path: Path | None = None,
    limit: int | None = None,
    prefilter_only: bool = False,
    **_: Any,
) -> StageResult:
    """Stage 3: prefilter + handshake validation of the normalized list."""
    normalized_path = data_dir / "normalized" / "proxies_normalized.json"
    if not normalized_path.exists():
        return StageResult(
            "validate",
            False,
            f"stage-2 output not found: {normalized_path} (run normalize first)",
        )
    try:
        proxies = json.loads(normalized_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        return StageResult("validate", False, f"cannot read stage-2 output: {exc}")
    if not isinstance(proxies, list):
        return StageResult(
            "validate", False, f"stage-2 output is not a JSON list: {normalized_path}"
        )

    try:
        config = load_validate_config(
            validate_cfg_path or default_validate_config_path()
        )
    except ValidateConfigError as exc:
        return StageResult("validate", False, f"config error: {exc}")

    out_dir = data_dir / "validated"
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "validate_report.json"

    pre = prefilter(
        proxies,
        config["prefilter"]["timeout_seconds"],
        config["prefilter"]["workers"],
    )
    survivors = [
        proxy
        for proxy in proxies
        if f"{str(proxy['host']).strip('[]').lower()}|{int(proxy['port'])}"
        in pre.passed
    ]

    report: dict[str, Any] = {
        "stage": "validate",
        "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": {
            "probe_url": config["probe"]["url"],
            "probe_timeout_seconds": config["probe"]["timeout_seconds"],
            "workers": config["workers"],
            "prefilter_workers": config["prefilter"]["workers"],
        },
        "prefilter": {
            "unique_targets": pre.targets,
            "passed": len(pre.passed),
            "failed": pre.failed,
            "timeout_seconds": config["prefilter"]["timeout_seconds"],
            "elapsed_seconds": pre.elapsed_seconds,
            "failure_samples": pre.failure_samples,
        },
    }

    if prefilter_only:
        report["handshake_check"] = {
            "skipped": True,
            "prefilter_survivors": len(survivors),
            "limit": limit,
        }
        report_path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        detail = (
            f"prefilter: {len(pre.passed)}/{pre.targets} unique targets "
            f"reachable ({pre.failed} dead); survivors={len(survivors)} "
            f"(handshake check skipped)"
        )
        return StageResult("validate", True, detail, [report_path])

    selected = survivors if limit is None else survivors[:limit]
    results = run_checks(selected, config, progress_every=200)

    check_by_identity = {result.identity: result for result in results}
    validated = []
    for proxy in selected:
        entry = dict(proxy)
        check = check_by_identity.get(proxy["identity"])
        entry["check"] = (
            {
                "ok": check.ok,
                "type_confirmed": check.type_confirmed,
                "method_used": check.method_used,
                "latency_ms": check.latency_ms,
                "http_status": check.http_status,
                "checked_utc": report["run_utc"],
                "error": check.error,
            }
            if check
            else {"ok": False, "error": "no check result"}
        )
        validated.append(entry)

    alive_results = [r for r in results if r.ok]
    latencies = sorted(
        r.latency_ms for r in alive_results if r.latency_ms is not None
    )
    failure_samples = [f"{r.identity} {r.error}" for r in results if not r.ok][
        :MAX_FAILURE_SAMPLES
    ]

    by_confirmed: dict[str, int] = {}
    by_claim: dict[str, int] = {}
    claim_calibration = {"agree": 0, "disagree": 0, "unknown": 0}
    for r in results:
        if r.ok:
            key = r.type_confirmed or "?"
            by_confirmed[key] = by_confirmed.get(key, 0) + 1
        claim_key = r.claimed_type or "unknown"
        by_claim[claim_key] = by_claim.get(claim_key, 0) + 1
        if r.ok:
            agreement = claim_agreement(
                r.claimed_type, r.type_confirmed, r.method_used
            )
            claim_calibration[agreement] += 1

    report["handshake_check"] = {
        "skipped": False,
        "survivors": len(survivors),
        "limit": limit,
        "tested": len(results),
        "alive": len(alive_results),
        "dead": len(results) - len(alive_results),
        "latency_ms": {
            "min": min(latencies) if latencies else None,
            "p50": _percentile(latencies, 0.5),
            "p90": _percentile(latencies, 0.9),
            "max": max(latencies) if latencies else None,
        },
        "alive_by_confirmed_type": dict(sorted(by_confirmed.items())),
        "tested_by_claimed_type": dict(sorted(by_claim.items())),
        "claim_calibration": claim_calibration,
        "failure_samples": failure_samples,
    }

    proxies_path = out_dir / "proxies_validated.json"
    proxies_path.write_text(
        json.dumps(validated, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    detail = (
        f"prefilter {len(pre.passed)}/{pre.targets} targets reachable, "
        f"tested {len(results)}, alive {len(alive_results)}"
    )
    if latencies:
        detail += f" (p50 {_percentile(latencies, 0.5)} ms)"
    return StageResult("validate", True, detail, [proxies_path, report_path])
