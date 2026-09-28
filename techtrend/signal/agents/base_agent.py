from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentResult:
    ok: bool
    detail: dict[str, Any]


class BaseAgent:
    def run(self) -> AgentResult:  # pragma: no cover (interface)
        raise NotImplementedError
