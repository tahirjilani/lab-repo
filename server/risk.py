"""The risk engine: signals in, one decision out.

  score    = sum over layers of the WORST signal in that layer (0–100)
             (a verdict's facets — no device label, unrecognized app — are one finding,
             not three; independent layers that agree do add up)
  decision = the score band, raised to the strictest `floor` any signal demands

Bands (tune these in Lab 3):  < 25 allow · < 50 monitor · < 90 step_up · ≥ 90 block
Hard rules (wrong hash/package, forged agent token, replayed nonce, no funds) are
signals with floor=block.
"""
from __future__ import annotations

from typing import Dict, Iterable, List, Tuple

from .signals import ALLOW, BLOCK, MONITOR, ORDER, STEP_UP, Signal, stricter

BANDS: Tuple[Tuple[int, str], ...] = ((25, ALLOW), (50, MONITOR), (90, STEP_UP))


def score(signals: Iterable[Signal]) -> int:
    worst: Dict[str, int] = {}
    for s in signals:
        worst[s.layer] = max(worst.get(s.layer, 0), s.points)
    return min(100, sum(worst.values()))


def band(points: int) -> str:
    for upper, decision in BANDS:
        if points < upper:
            return decision
    return BLOCK


def decide(signals: List[Signal]) -> Tuple[str, int]:
    pts = score(signals)
    decision = band(pts)
    for s in signals:
        decision = stricter(decision, s.floor)
    return decision, pts


def drivers(decision: str, signals: List[Signal], limit: int = 3) -> List[Signal]:
    """The signals worth telling the user about, strongest first."""
    relevant = [s for s in signals if s.points > 0 or s.floor]
    relevant.sort(key=lambda s: (s.floor == decision, ORDER.get(s.floor or ALLOW, 0), s.points), reverse=True)
    return relevant[:limit]


def explain(decision: str, signals: List[Signal]) -> str:
    parts = [s.detail.rstrip(".") for s in drivers(decision, signals)]
    if decision == STEP_UP:
        return "Confirm it's you: " + "; ".join(parts) + "." if parts else "Confirm it's you."
    if decision == BLOCK:
        return "Blocked: " + "; ".join(parts) + "." if parts else "Blocked."
    if decision == MONITOR:
        return "logged for review: " + ", ".join(p[0].lower() + p[1:] for p in parts if p)
    return ""
