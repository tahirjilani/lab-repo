"""Decisions and the evidence ("signals") each layer reports to the risk engine."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

ALLOW, MONITOR, STEP_UP, BLOCK = "allow", "monitor", "step_up", "block"
ORDER = {ALLOW: 0, MONITOR: 1, STEP_UP: 2, BLOCK: 3}


def stricter(a: str, b: Optional[str]) -> str:
    if b is None:
        return a
    return a if ORDER[a] >= ORDER[b] else b


@dataclass(frozen=True)
class Signal:
    """One finding. `points` feed the score; `floor` is the least strict decision it allows."""

    layer: str           # integrity | rasp | agent | context
    code: str            # stable machine name, e.g. "hash_mismatch"
    points: int = 0
    floor: Optional[str] = None
    detail: str = ""     # human-readable, ends up in the app's reason text

    def to_json(self) -> dict:
        d = {"layer": self.layer, "code": self.code, "points": self.points, "detail": self.detail}
        if self.floor:
            d["floor"] = self.floor
        return d
