"""YUEL — automated plain SOCKS4/SOCKS5/HTTP proxy monitoring pipeline.

YUEL collects bare proxy servers (``ip:port`` / ``ip:port:user:pass``)
published by public list sources, validates them with real protocol
handshakes, and will score/geo-split/publish them for proxy-chaining
consumers. It deliberately does NOT handle tunnel configs (vmess, vless,
trojan, ss, hysteria2, tuic) — those are standalone VPN endpoints, a
different product (pre-0.3.0 scope, removed).

Stage-based pipeline:

    1. collect    fetch list sources, parse plain-proxy entries  (implemented)
    2. normalize  dedupe by connection identity, drop invalid   (implemented)
    3. validate   TCP prefilter + real SOCKS5/SOCKS4/HTTP       (implemented)
                  handshakes, confirm the working protocol
    4. score      weighted formula: latency, success rate,      (planned)
                  freshness, anonymity level
    5. geo        country split via public IP-to-country table  (planned)
    6. publish    per-country machine-readable proxy files      (planned)
    7. automate   orchestration + GitHub Actions schedule       (planned)

This is a fresh, independently written codebase — it shares no code with
any other project.
"""

__version__ = "0.3.0"
