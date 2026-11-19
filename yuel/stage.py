"""Shared stage-result type for the pipeline orchestrator.

Lives in its own module so stage implementations (``validate`` and later
stages) can import it without a circular import on ``yuel.pipeline``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class StageResult:
    """Outcome of one pipeline stage (also when it failed)."""

    name: str
    ok: bool
    detail: str
    outputs: list[Path] = field(default_factory=list)
