"""End-to-end flows through WalletService, using the same bodies and headers as the app."""
import pytest

from server.service import ApiError
from server.stepup import stepup_message
from server.verify import mint_mock_token, mock_payload

from .conftest import signed_in


def submit(svc, dev, actor="user", agent_token=None, **body_kw):
    return svc.submit_transfer(dev.transfer_body(actor=actor, **body_kw), dev.headers(actor, agent_token))


def delegate(svc, dev, cents=5_000, **kw):
    body = {"agentId": "demowallet-assistant/1.0", "action": "transfer", "maxAmountCents": cents, **kw}
    return svc.mint_agent_token(body, dev.headers("user"))["agentToken"]


# ── The scenario table in server/README.md ─────────────────────────────────────

@pytest.mark.parametrize("name,profile,rasp,actor,delegated,checks,integrity,expected,score", [
    ("lab2 app, no verdict",           "none",      {},                 "user",      False, None, "NOT_CONFIGURED", "step_up", 55),
    ("lab2 app, mock emulator verdict", "emulator", {},                 "user",      False, None, "NOT_CONFIGURED", "step_up", 60),
    ("verified app on emulator",       "device_ok", {},                 "user",      False, None, "NOT_CONFIGURED", "monitor", 25),
    ("verified app on a real phone",   "device_ok", {"emulator": False}, "user",     False, None, "NOT_CONFIGURED", "allow",   0),
    ("assistant, no delegation",       "device_ok", {},                 "assistant", False, None, "NOT_CONFIGURED", "step_up", 50),
    ("assistant, delegated",           "device_ok", {},                 "assistant", True,  None, "NOT_CONFIGURED", "monitor", 35),
    ("assistant, delegated, real phone", "device_ok", {"emulator": False}, "assistant", True, None, "NOT_CONFIGURED", "allow", 10),
    ("unknown app controls the phone", "controlled", {"emulator": False}, "user",    False, None, "NOT_CONFIGURED", "step_up", 30),
    ("Frida still attached in lab 2",  "emulator",  {"hooked": True},   "assistant", False, None, "NOT_CONFIGURED", "block",   100),
    ("lab1 app vs hardened server",    "emulator",  {"hooked": True},   "assistant", False, None, None,             "block",   95),
    ("lab1: client decides",           "emulator",  {"hooked": True},   "assistant", False, "",   None,             "allow",   0),
])
def test_scenarios(make_service, device, name, profile, rasp, actor, delegated, checks, integrity, expected, score):
    kw = {"mock_verdict": profile}
    if checks is not None:
        kw["checks"] = frozenset(c for c in checks.split(",") if c)
    svc = make_service(**kw)
    dev = signed_in(svc, device)
    dev.rasp.update(rasp)
    token = delegate(svc, dev) if delegated else None
    out = submit(svc, dev, actor=actor, agent_token=token, integrity=integrity)
    assert (out["decision"], out["riskScore"]) == (expected, score), (name, out["signals"])
    assert out["reason"]
    if expected in ("allow", "monitor"):
        assert out["balanceCents"] == 245_000 - 2_000
    if expected == "step_up":
        assert set(out["challenge"]) == {"id", "nonce"}


# ── Step-up ───────────────────────────────────────────────────────────────────

def stepped_up(make_service, device):
    svc = make_service(mock_verdict="none")
    dev = signed_in(svc, device)
    out = submit(svc, dev, cents=20_000)
    assert out["decision"] == "step_up"
    return svc, dev, out


def test_valid_step_up_signature_completes_transfer(make_service, device):
    svc, dev, out = stepped_up(make_service, device)
    ch = out["challenge"]
    sig = dev.sign(stepup_message(ch["id"], ch["nonce"], out["requestHash"]))
    done = svc.confirm(out["transferId"], {"challengeId": ch["id"], "signature": sig}, dev.headers())
    assert done["decision"] == "allow" and done["balanceCents"] == 225_000
    again = svc.confirm(out["transferId"], {"challengeId": ch["id"], "signature": sig}, dev.headers())
    assert again["decision"] == "block"  # one confirmation per challenge


def test_step_up_signature_over_other_transfer_is_refused(make_service, device):
    svc, dev, out = stepped_up(make_service, device)
    ch = out["challenge"]
    sig = dev.sign(stepup_message(ch["id"], ch["nonce"], "00" * 32))
    done = svc.confirm(out["transferId"], {"challengeId": ch["id"], "signature": sig}, dev.headers())
    assert done["decision"] == "block" and "signature" in done["reason"]
    assert svc.balance(dev.headers())["balanceCents"] == 245_000


def test_step_up_expires(make_service, device, clock):
    svc, dev, out = stepped_up(make_service, device)
    ch = out["challenge"]
    clock.t += 301
    sig = dev.sign(stepup_message(ch["id"], ch["nonce"], out["requestHash"]))
    assert svc.confirm(out["transferId"], {"challengeId": ch["id"], "signature": sig},
                       dev.headers())["decision"] == "block"


def test_step_up_without_device_key(make_service, device):
    svc = make_service(mock_verdict="none")
    device.public_b64 = ""
    dev = signed_in(svc, device)
    out = submit(svc, dev)
    done = svc.confirm(out["transferId"], {"challengeId": out["challenge"]["id"], "signature": "AAAA"}, dev.headers())
    assert done["decision"] == "block" and "device key" in done["reason"]


# ── Hard rules ────────────────────────────────────────────────────────────────

@pytest.mark.lab2
def test_request_hash_mismatch_is_blocked(make_service, device):
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)
    # a genuine-looking token bound to a €1 transfer, lifted onto a €200 one
    small = dev.transfer_body(cents=100)
    lifted = mint_mock_token(mock_payload("device_ok", small["clientRequestHash"], "com.demo.wallet",
                                          int(dev.clock() * 1000)))
    out = submit(svc, dev, cents=20_000, integrity="token:" + lifted)
    assert out["decision"] == "block" and "different transfer" in out["reason"]
    assert svc.balance(dev.headers())["balanceCents"] == 245_000


@pytest.mark.lab2
def test_body_altered_in_transit_is_blocked(make_service, device):
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)
    original = dev.transfer_body(cents=2_000)
    original["transfer"]["amountCents"] = 200_000  # proxy edits the amount; device hashed €20
    out = svc.submit_transfer(original, dev.headers())
    assert out["decision"] == "block"
    assert [s["code"] for s in out["signals"] if s["layer"] == "integrity"] == ["hash_mismatch"]


def test_replayed_nonce_is_blocked(make_service, device):
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)
    body = dev.transfer_body(nonce="ab" * 16)
    assert svc.submit_transfer(body, dev.headers())["decision"] == "monitor"
    again = svc.submit_transfer(body, dev.headers())
    assert again["decision"] == "block" and "already submitted" in again["reason"]


def test_funds_payee_account_rules(make_service, device):
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)
    assert submit(svc, dev, cents=999_999)["decision"] == "block"
    assert submit(svc, dev, payee="mallory")["decision"] == "block"
    body = dev.transfer_body()
    body["transfer"]["account"] = "acc-002"
    body["clientRequestHash"] = None
    assert svc.submit_transfer(body, dev.headers())["decision"] == "block"


def test_large_user_transfer_steps_up(make_service, device):
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)
    dev.rasp["emulator"] = False
    assert submit(svc, dev, cents=150_000)["decision"] == "step_up"


def test_assistant_over_delegation_steps_up_and_token_is_single_use(make_service, device):
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)
    dev.rasp["emulator"] = False
    token = delegate(svc, dev, cents=5_000, payeeId="ana")
    over = submit(svc, dev, actor="assistant", agent_token=token, cents=20_000)
    assert over["decision"] == "step_up" and "exceeds the delegated €50.00" in over["reason"]
    ok = submit(svc, dev, actor="assistant", agent_token=token, cents=2_000)
    assert ok["decision"] == "allow"
    reused = submit(svc, dev, actor="assistant", agent_token=token, cents=2_000)
    assert reused["decision"] == "step_up" and "already used" in reused["reason"]



def test_app_grant_then_assistant_transfer(make_service, device):
    """The app's flow (WalletViewModel.approveGrant): the user grants min(amount, agent limit) for one
    payee, then the assistant sends with X-Agent-Token. Emulator RASP, default agent limit €100."""
    svc = make_service(mock_verdict="device_ok")
    dev = signed_in(svc, device)

    def grant(cents):  # exactly the body HttpBackend.mintAgentToken sends
        return svc.mint_agent_token({"agentId": "demowallet-assistant/1.0", "action": "transfer",
                                     "maxAmountCents": cents, "payeeId": "ana", "ttlSeconds": 300,
                                     "currency": "EUR"}, dev.headers("user"))

    g = grant(2_000)  # "Send €20 to Ana"
    assert g["maxAmountCents"] == 2_000 and g["payeeId"] == "ana" and g["expiresAt"] - g["issuedAt"] == 300
    ok = submit(svc, dev, actor="assistant", agent_token=g["agentToken"], cents=2_000)
    assert (ok["decision"], ok["riskScore"]) == ("monitor", 35)

    g = grant(10_000)  # "Send €200 to Ana": capped at the agent limit
    over = submit(svc, dev, actor="assistant", agent_token=g["agentToken"], cents=20_000)
    assert over["decision"] == "step_up" and "exceeds the delegated €100.00" in over["reason"]

    with pytest.raises(ApiError) as e:  # the app never asks for more than the limit; the server refuses anyway
        grant(20_000)
    assert e.value.status == 400
    with pytest.raises(ApiError) as e:  # the assistant can't grant itself a token
        svc.mint_agent_token({"agentId": "demowallet-assistant/1.0", "maxAmountCents": 2_000},
                             dev.headers("assistant"))
    assert e.value.status == 403


# ── Errors and lab helpers ────────────────────────────────────────────────────

def test_errors(make_service, device):
    svc = make_service()
    with pytest.raises(ApiError) as e:
        svc.balance({})
    assert e.value.status == 401
    dev = signed_in(svc, device)
    with pytest.raises(ApiError) as e:
        svc.submit_transfer({"transfer": {"account": "acc-001"}}, dev.headers())
    assert e.value.status == 400
    with pytest.raises(ApiError) as e:
        svc.mint_agent_token({"agentId": "a", "maxAmountCents": 1}, dev.headers("assistant"))
    assert e.value.status == 403  # an agent can't delegate to itself
    with pytest.raises(ApiError) as e:
        delegate(svc, dev, cents=10_001)
    assert e.value.status == 400
    with pytest.raises(ApiError) as e:
        svc.login({"username": "", "password": ""}, {})
    assert e.value.status == 400


def test_session_expires(make_service, device, clock):
    svc = make_service()
    dev = signed_in(svc, device)
    clock.t += 12 * 3600 + 1
    with pytest.raises(ApiError):
        svc.balance(dev.headers())


def test_switch_mock_profile_at_runtime(make_service, device):
    svc = make_service(mock_verdict="emulator")
    dev = signed_in(svc, device)
    assert submit(svc, dev)["decision"] == "step_up"
    assert svc.set_mock_profile({"profile": "device_ok"}) == {"mockVerdict": "device_ok"}
    assert submit(svc, dev)["decision"] == "monitor"
    with pytest.raises(ApiError):
        svc.set_mock_profile({"profile": "rainbow"})
    assert svc.decisions[0]["decision"] == "monitor"
    with pytest.raises(ApiError) as e:
        make_service(verdict_mode="google").set_mock_profile({"profile": "none"})
    assert e.value.status == 409


def test_settings_from_env():
    from server.config import Settings
    s = Settings.from_env({"DW_SERVER_CHECKS": "", "DW_MOCK_VERDICT": "device_ok", "DW_AGENT_LIMIT_CENTS": "20000"})
    assert s.checks == frozenset() and s.mock_verdict == "device_ok" and s.agent_limit_cents == 20_000
    assert Settings.from_env({}).checks == frozenset({"integrity", "rasp", "agent"})
    with pytest.raises(ValueError):
        Settings.from_env({"DW_SERVER_CHECKS": "integrity,magic"})
