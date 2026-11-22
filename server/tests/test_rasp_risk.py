from server.rasp import assess_rasp, from_body, parse_header
from server.risk import decide, explain, score
from server.signals import ALLOW, BLOCK, MONITOR, STEP_UP, Signal

NOW_MS = 1_800_000_000_000


def test_header_parses_like_the_app():
    r = parse_header("v=1;root=0;emu=1;dbg=0;sig=1;hook=1;ts=42")
    assert (r.rooted, r.emulator, r.debugger, r.signature_valid, r.hooked, r.collected_at_ms) == \
           (False, True, False, True, True, 42)
    assert parse_header("v=2;root=1") is None and parse_header("") is None


def test_body_requires_booleans():
    assert from_body({"rooted": "no"}) is None
    r = from_body({"rooted": False, "emulator": False, "debugger": False, "signatureValid": True,
                   "hooked": True, "details": ["maps:frida-agent"], "collectedAtMillis": NOW_MS})
    assert r.hooked and r.details == ("maps:frida-agent",)


def codes(signals):
    return [s.code for s in signals]


def test_rasp_signals():
    hdr = parse_header(f"v=1;root=0;emu=1;dbg=0;sig=1;hook=1;ts={NOW_MS}")
    assert codes(assess_rasp(None, hdr, NOW_MS, 120)) == ["hooked", "emulator"]
    clean = parse_header(f"v=1;root=0;emu=0;dbg=0;sig=1;hook=0;ts={NOW_MS}")
    assert codes(assess_rasp(clean, clean, NOW_MS, 120)) == ["clean"]
    assert codes(assess_rasp(clean, hdr, NOW_MS, 120))[0] == "header_mismatch"
    assert "stale" in codes(assess_rasp(clean, None, NOW_MS + 121_000, 120))
    assert codes(assess_rasp(None, None, NOW_MS, 120)) == ["missing"]


def s(layer, pts, floor=None, detail="x"):
    return Signal(layer, "c", pts, floor, detail)


def test_score_takes_worst_per_layer_and_sums_layers():
    assert score([s("integrity", 35), s("integrity", 30), s("rasp", 25)]) == 60
    assert score([s("integrity", 60), s("rasp", 60)]) == 100


def test_bands_and_floors():
    assert decide([s("rasp", 24)]) == (ALLOW, 24)
    assert decide([s("rasp", 25)]) == (MONITOR, 25)
    assert decide([s("rasp", 50)]) == (STEP_UP, 50)
    assert decide([s("rasp", 40), s("integrity", 50)]) == (BLOCK, 90)
    assert decide([s("rasp", 0, STEP_UP)])[0] == STEP_UP
    assert decide([s("context", 0, BLOCK)])[0] == BLOCK


def test_explain():
    sig = [Signal("rasp", "emulator", 25, None, "Running on an emulator.")]
    assert explain(MONITOR, sig) == "logged for review: running on an emulator"
    sig = [Signal("integrity", "missing", 30, STEP_UP, "No integrity verdict (NOT_CONFIGURED)."),
           Signal("agent", "no_delegation", 25, STEP_UP, "The assistant has no delegation token for this.")]
    assert explain(STEP_UP, sig) == ("Confirm it's you: No integrity verdict (NOT_CONFIGURED); "
                                     "The assistant has no delegation token for this.")
