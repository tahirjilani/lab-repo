"""RASP evidence from the app: header X-RASP on every request, full report in the transfer body.

The client only reports; this module turns the report into risk signals.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

from .signals import STEP_UP, Signal

FLAGS = ("rooted", "emulator", "debugger", "signature_valid", "hooked")


@dataclass(frozen=True)
class Rasp:
    rooted: bool
    emulator: bool
    debugger: bool
    signature_valid: bool
    hooked: bool
    collected_at_ms: int = 0
    details: Tuple[str, ...] = ()

    def flags(self) -> Tuple[bool, ...]:
        return tuple(getattr(self, f) for f in FLAGS)


def parse_header(value: Optional[str]) -> Optional[Rasp]:
    """v=1;root=0;emu=1;dbg=0;sig=1;hook=0;ts=1731350000000  (sig=1 means VALID)."""
    if not value:
        return None
    m = {}
    for part in value.split(";"):
        k, sep, v = part.partition("=")
        if sep and k:
            m[k.strip()] = v.strip()
    if m.get("v") != "1":
        return None
    try:
        ts = int(m.get("ts", "0"))
    except ValueError:
        ts = 0
    return Rasp(rooted=m.get("root") == "1", emulator=m.get("emu") == "1", debugger=m.get("dbg") == "1",
                signature_valid=m.get("sig") == "1", hooked=m.get("hook") == "1", collected_at_ms=ts)


def from_body(d: Any) -> Optional[Rasp]:
    if not isinstance(d, dict):
        return None
    keys = ("rooted", "emulator", "debugger", "signatureValid", "hooked")
    if not all(isinstance(d.get(k), bool) for k in keys):
        return None
    ts = d.get("collectedAtMillis")
    details = d.get("details") if isinstance(d.get("details"), list) else []
    return Rasp(rooted=d["rooted"], emulator=d["emulator"], debugger=d["debugger"],
                signature_valid=d["signatureValid"], hooked=d["hooked"],
                collected_at_ms=ts if isinstance(ts, int) and not isinstance(ts, bool) else 0,
                details=tuple(str(x)[:80] for x in details[:20]))


def _sig(code: str, points: int, floor: Optional[str], detail: str) -> Signal:
    return Signal("rasp", code, points, floor, detail)


def assess_rasp(body: Optional[Rasp], header: Optional[Rasp], now_ms: int, max_age_s: int) -> List[Signal]:
    r = body or header
    if r is None:
        return [_sig("missing", 25, None, "No device signals sent.")]
    out: List[Signal] = []
    if body and header and body.flags() != header.flags():
        out.append(_sig("header_mismatch", 20, STEP_UP, "Device signals in header and body disagree."))
    if r.hooked:
        out.append(_sig("hooked", 40, STEP_UP, "Instrumentation detected on the device."))
    if not r.signature_valid:
        out.append(_sig("signature_invalid", 40, STEP_UP, "App signature doesn't match."))
    if r.debugger:
        out.append(_sig("debugger", 30, STEP_UP, "Debugger attached."))
    if r.rooted:
        out.append(_sig("rooted", 30, None, "Device appears rooted."))
    if r.emulator:
        out.append(_sig("emulator", 25, None, "Running on an emulator."))
    age = now_ms - r.collected_at_ms
    if age > max_age_s * 1000 or age < -60_000:
        out.append(_sig("stale", 10, None, "Device signals are stale."))
    return out or [_sig("clean", 0, None, "No device flags.")]
