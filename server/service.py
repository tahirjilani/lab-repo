"""DemoWallet lab backend logic, framework-free (app.py is a thin FastAPI shell around it).

Endpoints mirror the app's wire contract (android/.../backend/Backend.kt):
  POST /api/login · GET /api/balance · POST /api/transfers · POST /api/transfers/{id}/confirm
plus POST /api/agent-tokens (user delegates to an agent) and lab helpers.
State is in memory: one lab account (acc-001), reset on restart.
"""
from __future__ import annotations

import logging
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Set

from . import rasp as rasp_mod
from .agent_tokens import AgentGrant, AgentTokens, assess_agent
from .config import MOCK_PROFILES, Settings
from .risk import decide, explain
from .signals import ALLOW, BLOCK, MONITOR, STEP_UP, Signal
from .stepup import stepup_message, verify_signature
from .verify import GoogleDecoder, InvalidTransfer, MockDecoder, Transfer, assess_integrity

log = logging.getLogger("demowallet")

ACCOUNT = "acc-001"
PAYEES = {"ana": "Ana", "ben": "Ben", "chloe": "Chloé"}


class ApiError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass
class _Session:
    account: str
    display_name: str
    device_key: str
    expires: float


@dataclass
class _Pending:
    session_token: str
    transfer: Transfer
    challenge_id: str
    challenge_nonce: str
    expires: float


def eur(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    c = abs(cents)
    return f"{sign}€{c // 100:,}.{c % 100:02d}"


class WalletService:
    def __init__(self, settings: Settings, decoder: Any = None, clock: Callable[[], float] = time.time):
        self.settings = settings
        self.clock = clock
        if decoder is None:
            decoder = MockDecoder() if settings.verdict_mode == "mock" else GoogleDecoder(settings.package_name)
        self.decoder = decoder
        self.mock_profile = settings.mock_verdict
        self.tokens = AgentTokens(settings.agent_token_secret, default_ttl_s=settings.agent_token_default_ttl_s,
                                  max_ttl_s=settings.agent_token_max_ttl_s,
                                  limit_cents=settings.agent_limit_cents, clock=clock)
        self._lock = threading.RLock()
        self._sessions: Dict[str, _Session] = {}
        self._balances: Dict[str, int] = {ACCOUNT: settings.starting_balance_cents}
        self._nonces: Set[str] = set()
        self._pending: Dict[str, _Pending] = {}
        self.decisions: Deque[dict] = deque(maxlen=200)
        if settings.verdict_mode == "mock":
            log.warning("Play Integrity MOCK mode (profile=%s): lab only, mock tokens are unsigned.", self.mock_profile)

    # ── helpers ──
    def _now_ms(self) -> int:
        return int(self.clock() * 1000)

    def _session(self, headers: Mapping[str, str]) -> _Session:
        auth = headers.get("authorization", "")
        token = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        s = self._sessions.get(token)
        if not s or s.expires < self.clock():
            raise ApiError(401, "Not signed in (missing or expired session).")
        return s

    @staticmethod
    def _token(headers: Mapping[str, str]) -> str:
        return headers.get("authorization", "")[7:].strip()

    # ── endpoints ──
    def login(self, body: Any, headers: Mapping[str, str]) -> dict:
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.")
        user, pw = str(body.get("username") or "").strip(), str(body.get("password") or "")
        if not user or not pw:
            raise ApiError(400, "Enter any username and password.")
        key = body.get("devicePublicKey") or ""
        if not isinstance(key, str):
            raise ApiError(400, "devicePublicKey must be a string.")
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._sessions[token] = _Session(ACCOUNT, user, key, self.clock() + self.settings.session_ttl_s)
        return {"sessionToken": token, "account": ACCOUNT, "displayName": user}

    def balance(self, headers: Mapping[str, str]) -> dict:
        s = self._session(headers)
        with self._lock:
            return {"account": s.account, "balanceCents": self._balances[s.account], "currency": "EUR"}

    def mint_agent_token(self, body: Any, headers: Mapping[str, str]) -> dict:
        s = self._session(headers)
        if headers.get("x-actor", "user") != "user":
            raise ApiError(403, "Only the user can delegate to an agent.")
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.")
        try:
            token, grant = self.tokens.mint(
                account=s.account, agent_id=body.get("agentId"), action=body.get("action", "transfer"),
                max_amount_cents=body.get("maxAmountCents"), ttl_s=body.get("ttlSeconds"),
                payee_id=body.get("payeeId"), currency=body.get("currency", "EUR"))
        except ValueError as e:
            raise ApiError(400, str(e)) from None
        return {"agentToken": token, **grant.to_json()}

    def submit_transfer(self, body: Any, headers: Mapping[str, str]) -> dict:
        s = self._session(headers)
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.")
        try:
            t = Transfer.from_json(body.get("transfer"))
        except InvalidTransfer as e:
            raise ApiError(400, str(e)) from None
        now_ms = self._now_ms()
        tx_id = "tx-" + secrets.token_hex(4)
        cfg = self.settings
        signals: List[Signal] = []
        grant: Optional[AgentGrant] = None

        with self._lock:
            # Context: rules that hold whatever the layers say.
            if t.account != s.account:
                signals.append(Signal("context", "account_mismatch", 0, BLOCK, "Transfer is for another account."))
            if t.nonce in self._nonces:
                signals.append(Signal("context", "replay", 0, BLOCK, "This transfer was already submitted."))
            if t.payee_id not in PAYEES:
                signals.append(Signal("context", "unknown_payee", 0, BLOCK, f"Unknown payee {t.payee_id}."))
            if t.amount_cents > self._balances[s.account]:
                signals.append(Signal("context", "insufficient_funds", 0, BLOCK,
                                      f"Insufficient funds for {eur(t.amount_cents)}."))
            if t.actor == "user" and t.amount_cents > cfg.user_limit_cents:
                signals.append(Signal("context", "user_limit", 0, STEP_UP,
                                      f"Transfers above {eur(cfg.user_limit_cents)} need confirmation."))

            if "integrity" in cfg.checks:
                signals += assess_integrity(
                    body.get("integrity"), t, body.get("clientRequestHash"), self.decoder,
                    mode=cfg.verdict_mode, mock_profile=self.mock_profile, package_name=cfg.package_name,
                    max_age_s=cfg.verdict_max_age_s, required=cfg.integrity_required, now_ms=now_ms)
            if "rasp" in cfg.checks:
                signals += rasp_mod.assess_rasp(rasp_mod.from_body(body.get("rasp")),
                                                rasp_mod.parse_header(headers.get("x-rasp")),
                                                now_ms, cfg.rasp_max_age_s)
            if "agent" in cfg.checks:
                agent_signals, grant = assess_agent(
                    body_actor=t.actor, header_actor=headers.get("x-actor"),
                    header_agent_id=headers.get("x-agent-id"), token=headers.get("x-agent-token"),
                    account=s.account, payee_id=t.payee_id, amount_cents=t.amount_cents,
                    currency=t.currency, tokens=self.tokens)
                signals += agent_signals

            decision, score = decide(signals)
            if decision != BLOCK:
                self._nonces.add(t.nonce)
                if grant:
                    self.tokens.consume(grant)

            out: Dict[str, Any] = {"decision": decision, "transferId": tx_id, "riskScore": score,
                                   "requestHash": t.request_hash(),
                                   "signals": [x.to_json() for x in signals]}
            payee = PAYEES.get(t.payee_id, t.payee_id)
            if decision in (ALLOW, MONITOR):
                self._balances[s.account] -= t.amount_cents
                note = explain(decision, signals)
                out["reason"] = f"Sent {eur(t.amount_cents)} to {payee}" + (f" ({note})." if note else ".")
                out["balanceCents"] = self._balances[s.account]
            elif decision == STEP_UP:
                ch_id, ch_nonce = "ch-" + secrets.token_hex(4), secrets.token_hex(16)
                self._pending[tx_id] = _Pending(self._token(headers), t, ch_id, ch_nonce,
                                                self.clock() + cfg.challenge_ttl_s)
                out["reason"] = explain(decision, signals)
                out["challenge"] = {"id": ch_id, "nonce": ch_nonce}
            else:
                out["reason"] = explain(decision, signals)
            self._record(tx_id, t, decision, score, signals)
            return out

    def confirm(self, transfer_id: str, body: Any, headers: Mapping[str, str]) -> dict:
        s = self._session(headers)
        if not isinstance(body, dict):
            raise ApiError(400, "Body must be a JSON object.")

        def blocked(reason: str) -> dict:
            log.info("confirm %s → block: %s", transfer_id, reason)
            return {"decision": BLOCK, "transferId": transfer_id, "reason": reason}

        with self._lock:
            p = self._pending.get(transfer_id)
            if not p or p.session_token != self._token(headers):
                return blocked("No pending confirmation for this transfer.")
            del self._pending[transfer_id]  # one attempt per challenge
            if p.expires < self.clock():
                return blocked("Confirmation expired. Start the transfer again.")
            if body.get("challengeId") != p.challenge_id:
                return blocked("Challenge mismatch.")
            if not s.device_key:
                return blocked("No device key registered. Set a screen lock, then sign in again.")
            msg = stepup_message(p.challenge_id, p.challenge_nonce, p.transfer.request_hash())
            if not verify_signature(s.device_key, msg, body.get("signature")):
                return blocked("Confirmation signature invalid.")
            if p.transfer.amount_cents > self._balances[s.account]:
                return blocked("Insufficient funds.")
            self._balances[s.account] -= p.transfer.amount_cents
            payee = PAYEES.get(p.transfer.payee_id, p.transfer.payee_id)
            log.info("confirm %s → allow (step-up signature valid)", transfer_id)
            return {"decision": ALLOW, "transferId": transfer_id,
                    "reason": f"Confirmed. Sent {eur(p.transfer.amount_cents)} to {payee}.",
                    "balanceCents": self._balances[s.account]}

    # ── lab helpers ──
    def set_mock_profile(self, body: Any) -> dict:
        if self.settings.verdict_mode != "mock":
            raise ApiError(409, "Only available in mock verdict mode.")
        profile = body.get("profile") if isinstance(body, dict) else None
        if profile not in MOCK_PROFILES:
            raise ApiError(400, f"profile must be one of {MOCK_PROFILES}")
        self.mock_profile = profile
        log.warning("Mock verdict profile → %s", profile)
        return {"mockVerdict": profile}

    def status(self) -> dict:
        c = self.settings
        return {"verdictMode": c.verdict_mode, "mockVerdict": self.mock_profile if c.verdict_mode == "mock" else None,
                "checks": sorted(c.checks), "integrityRequired": c.integrity_required,
                "agentLimitCents": c.agent_limit_cents, "userLimitCents": c.user_limit_cents}

    def _record(self, tx_id: str, t: Transfer, decision: str, score: int, signals: List[Signal]) -> None:
        codes = ",".join(f"{x.layer}.{x.code}" for x in signals if x.points or x.floor) or "-"
        log.info("%s %s %s %s→%s score=%d decision=%s [%s]", tx_id, t.actor, eur(t.amount_cents),
                 t.account, t.payee_id, score, decision, codes)
        self.decisions.appendleft({"transferId": tx_id, "actor": t.actor, "amountCents": t.amount_cents,
                                   "payeeId": t.payee_id, "decision": decision, "riskScore": score,
                                   "signals": [x.to_json() for x in signals], "atMillis": self._now_ms()})
