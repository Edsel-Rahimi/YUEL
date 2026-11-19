"""YUEL — automated public proxy/VPN endpoint monitoring pipeline.

Stage-based pipeline:

    1. collect    fetch public sources, extract endpoint URIs   (implemented)
    2. normalize  dedupe by connection identity, drop invalid   (planned)
    3. validate   TCP prefilter + xray/sing-box live checks     (planned)
    4. score      weighted quality formula, gold/silver/bronze  (planned)
    5. geo        country split via public IP-to-ASN table      (planned)
    6. publish    machine-readable output files + history       (planned)
    7. automate   orchestration + GitHub Actions schedule       (planned)

This is a fresh, independently written codebase — it shares no code with
any other project.
"""

__version__ = "0.1.0"
