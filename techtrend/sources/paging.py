"""Explicit page completion shared by academic source clients."""
from dataclasses import dataclass, field


@dataclass
class WorksBatch:
    """Records consumed without truncating a page; cap does not imply coverage."""
    records: list[dict] = field(default_factory=list)
    next_cursor: str | None = "*"
    complete: bool = False
    reported_total: int | None = None
    pages: int = 0
