"""Scoped, short-lived agent tokens: the user delegates ONE kind of action to ONE agent.

    dwat1.<base64url(claims JSON)>.<base64url(HMAC-SHA256)>

claims: jti, account, agent_id, action, max_amount_cents, currency, payee_id (optional),
iat, exp. Minted only by the user (X-Actor: user), capped by the agent limit (slide 18),
single use. The assistant presents it as `X-Agent-Token` on the transfer.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import asdict, dataclass
from typing import Callable, List, Optional, Set, Tuple

from .signals import BLOCK, STEP_UP, Signal

PREFIX = "dwat1"
ACTIONS = ("transfer", "balance.read")


class AgentTokenError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class AgentGrant:
    jti: str
    account: str
    agent_id: str
    action: str
    max_amount_cents: int
    currency: str
    payee_id: Optional[str]
    iat: int
    exp: int

    def to_json(self) -> dict:
        return {"jti": self.jti, "account": self.account, "agentId": self.agent_id, "action": self.action,
                "maxAmountCents": self.max_amount_cents, "currency": self.currency, "payeeId": self.payee_id,
                "issuedAt": self.iat, "expiresAt": self.exp}


def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class AgentTokens:
    def __init__(self, secret: bytes, *, default_ttl_s: int, max_ttl_s: int, limit_cents: int,
                 clock: Callable[[], float] = time.time):
        self._secret = secret
        self.default_ttl_s = default_ttl_s
        self.max_ttl_s = max_ttl_s
        self.limit_cents = limit_cents
        self._clock = clock
        self._used: Set[str] = set()

    def _mac(self, data: bytes) -> bytes:
        return hmac.new(self._secret, data, hashlib.sha256).digest()

    def mint(self, *, account: str, agent_id: str, action: str, max_amount_cents: int,
             ttl_s: Optional[int] = None, payee_id: Optional[str] = None,
             currency: str = "EUR") -> Tuple[str, AgentGrant]:
        if not agent_id or not isinstance(agent_id, str):
            raise ValueError("agentId is required")
        if action not in ACTIONS:
            raise ValueError(f"action must be one of {ACTIONS}")
        if isinstance(max_amount_cents, bool) or not isinstance(max_amount_cents, int) or max_amount_cents < 0:
            raise ValueError("maxAmountCents must be a non-negative integer")
        if action == "transfer" and not 0 < max_amount_cents <= self.limit_cents:
            raise ValueError(f"maxAmountCents must be between 1 and the agent limit ({self.limit_cents})")
        ttl = self.default_ttl_s if ttl_s is None else ttl_s
        if isinstance(ttl, bool) or not isinstance(ttl, int) or not 0 < ttl <= self.max_ttl_s:
            raise ValueError(f"ttlSeconds must be between 1 and {self.max_ttl_s}")
        now = int(self._clock())
        grant = AgentGrant(jti=secrets.token_hex(8), account=account, agent_id=agent_id, action=action,
                           max_amount_cents=max_amount_cents, currency=currency, payee_id=payee_id,
                           iat=now, exp=now + ttl)
        body = _b64(json.dumps(asdict(grant), separators=(",", ":"), sort_keys=True).encode())
        signing_input = f"{PREFIX}.{body}".encode()
        return f"{PREFIX}.{body}.{_b64(self._mac(signing_input))}", grant

    def verify(self, token: str) -> AgentGrant:
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != PREFIX:
            raise AgentTokenError("malformed", "Agent token is malformed.")
        try:
            mac = _unb64(parts[2])
        except Exception:
            raise AgentTokenError("malformed", "Agent token is malformed.") from None
        if not hmac.compare_digest(mac, self._mac(f"{parts[0]}.{parts[1]}".encode())):
            raise AgentTokenError("bad_signature", "Agent token signature is invalid.")
        try:
            grant = AgentGrant(**json.loads(_unb64(parts[1])))
        except Exception:
            raise AgentTokenError("malformed", "Agent token claims are malformed.") from None
        if int(self._clock()) >= grant.exp:
            raise AgentTokenError("expired", "Agent token has expired.")
        if grant.jti in self._used:
            raise AgentTokenError("already_used", "Agent token was already used.")
        return grant

    def consume(self, grant: AgentGrant) -> None:
        self._used.add(grant.jti)


def _sig(code: str, points: int, floor: Optional[str], detail: str) -> Signal:
    return Signal("agent", code, points, floor, detail)


def _eur(cents: int) -> str:
    return f"€{cents // 100:,}.{cents % 100:02d}"


def assess_agent(*, body_actor: str, header_actor: Optional[str], header_agent_id: Optional[str],
                 token: Optional[str], account: str, payee_id: str, amount_cents: int, currency: str,
                 tokens: AgentTokens) -> Tuple[List[Signal], Optional[AgentGrant]]:
    """Signals for the agent-identity layer. Returns the grant to consume if the transfer goes ahead."""
    out: List[Signal] = []
    if header_actor and header_actor != body_actor:
        out.append(_sig("actor_mismatch", 20, STEP_UP,
                        f"Request says actor '{header_actor}' but the signed transfer says '{body_actor}'."))
    if body_actor != "assistant":
        return out or [_sig("user", 0, None, "Initiated by the user.")], None

    if not token:
        out.append(_sig("no_delegation", 25, STEP_UP, "The assistant has no delegation token for this."))
        return out, None
    try:
        g = tokens.verify(token)
    except AgentTokenError as e:
        forged = e.code in ("malformed", "bad_signature")
        out.append(_sig(f"token_{e.code}", 40 if forged else 30, BLOCK if forged else STEP_UP, str(e)))
        return out, None

    if g.account != account:
        out.append(_sig("token_wrong_account", 40, BLOCK, "Agent token belongs to another account."))
        return out, None
    scope: List[str] = []
    if header_agent_id != g.agent_id:
        scope.append(f"token was issued to {g.agent_id}, presented by {header_agent_id or 'an unnamed agent'}")
    if g.action != "transfer":
        scope.append(f"token allows '{g.action}', not transfers")
    if g.payee_id and g.payee_id != payee_id:
        scope.append(f"token is limited to payee {g.payee_id}")
    if g.currency != currency:
        scope.append(f"token is limited to {g.currency}")
    if amount_cents > g.max_amount_cents:
        scope.append(f"{_eur(amount_cents)} exceeds the delegated {_eur(g.max_amount_cents)}")
    if scope:
        out.append(_sig("out_of_scope", 30, STEP_UP, "Outside the assistant's delegation: " + "; ".join(scope) + "."))
        return out, None
    out.append(_sig("delegated", 10, None, f"Assistant acting within its delegation (up to {_eur(g.max_amount_cents)})."))
    return out, g
