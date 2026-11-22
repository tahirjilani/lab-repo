import pytest

from server.agent_tokens import AgentTokenError, AgentTokens, assess_agent
from server.signals import BLOCK, STEP_UP

AGENT = "demowallet-assistant/1.0"


@pytest.fixture
def tokens(clock):
    return AgentTokens(b"k" * 32, default_ttl_s=300, max_ttl_s=600, limit_cents=10_000, clock=clock)


def mint(tokens, **kw):
    args = dict(account="acc-001", agent_id=AGENT, action="transfer", max_amount_cents=5_000)
    args.update(kw)
    return tokens.mint(**args)[0]


def assess(tokens, token, amount=2_000, payee="ana", agent_id=AGENT, actor="assistant", header_actor="assistant"):
    return assess_agent(body_actor=actor, header_actor=header_actor, header_agent_id=agent_id, token=token,
                        account="acc-001", payee_id=payee, amount_cents=amount, currency="EUR", tokens=tokens)


def test_roundtrip_and_claims(tokens, clock):
    token, grant = tokens.mint(account="acc-001", agent_id=AGENT, action="transfer", max_amount_cents=5_000,
                               payee_id="ana", ttl_s=120)
    assert token.startswith("dwat1.")
    g = tokens.verify(token)
    assert g == grant and g.exp == int(clock()) + 120 and g.payee_id == "ana"


@pytest.mark.parametrize("kw,msg", [
    ({"max_amount_cents": 10_001}, "agent limit"),
    ({"max_amount_cents": 0}, "agent limit"),
    ({"ttl_s": 601}, "ttlSeconds"),
    ({"ttl_s": 0}, "ttlSeconds"),
    ({"action": "delete_account"}, "action"),
    ({"agent_id": ""}, "agentId"),
])
def test_mint_enforces_scope_limits(tokens, kw, msg):
    with pytest.raises(ValueError, match=msg):
        mint(tokens, **kw)


def test_tampered_token_fails_signature(tokens):
    head, body, mac = mint(tokens).split(".")
    with pytest.raises(AgentTokenError) as e:
        tokens.verify(f"{head}.{body[:-2]}xx.{mac}")
    assert e.value.code in ("bad_signature", "malformed")
    other = AgentTokens(b"z" * 32, default_ttl_s=300, max_ttl_s=600, limit_cents=10_000)
    with pytest.raises(AgentTokenError, match="signature"):
        other.verify(mint(tokens))


def test_expiry(tokens, clock):
    token = mint(tokens, ttl_s=60)
    clock.t += 59
    tokens.verify(token)
    clock.t += 1
    with pytest.raises(AgentTokenError, match="expired"):
        tokens.verify(token)


def test_in_scope_is_delegated(tokens):
    signals, grant = assess(tokens, mint(tokens))
    assert [s.code for s in signals] == ["delegated"] and grant is not None


def test_single_use(tokens):
    token = mint(tokens)
    _, grant = assess(tokens, token)
    tokens.consume(grant)
    [s], g = assess(tokens, token)
    assert s.code == "token_already_used" and s.floor == STEP_UP and g is None


@pytest.mark.parametrize("kw,fragment", [
    ({"amount": 5_001}, "exceeds the delegated €50.00"),
    ({"payee": "ben"}, "limited to payee ana"),
    ({"agent_id": "evil-agent/9"}, "presented by evil-agent/9"),
])
def test_out_of_scope_steps_up(tokens, kw, fragment):
    [s], g = assess(tokens, mint(tokens, payee_id="ana"), **kw)
    # the grant comes back anyway so the caller burns it: single use, in scope or not
    assert s.code == "out_of_scope" and s.floor == STEP_UP and fragment in s.detail and g is not None


def test_balance_token_cannot_move_money(tokens):
    [s], _ = assess(tokens, mint(tokens, action="balance.read", max_amount_cents=0))
    assert s.code == "out_of_scope" and "not transfers" in s.detail


def test_forged_and_foreign_tokens_block(tokens):
    [s], _ = assess(tokens, "dwat1.e30.AAAA")
    assert s.floor == BLOCK
    foreign = mint(tokens, account="acc-999")
    [s], _ = assess(tokens, foreign)
    assert (s.code, s.floor) == ("token_wrong_account", BLOCK)


def test_assistant_without_token_steps_up(tokens):
    [s], _ = assess(tokens, None)
    assert (s.code, s.floor) == ("no_delegation", STEP_UP)


def test_user_actor_and_mismatched_header(tokens):
    [s], _ = assess(tokens, None, actor="user", header_actor="user")
    assert s.code == "user" and s.points == 0
    signals, _ = assess(tokens, None, actor="assistant", header_actor="user")
    assert "actor_mismatch" in {x.code for x in signals}
