"""Server settings, read from DW_* environment variables (see server/README.md)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import FrozenSet, Mapping, Optional

LAYERS = ("integrity", "rasp", "agent")
VERDICT_MODES = ("mock", "google")
MOCK_PROFILES = ("emulator", "device_ok", "basic", "controlled", "none")


@dataclass
class Settings:
    # "mock": no Google Cloud needed. "google": decode real tokens via the Play Integrity API.
    verdict_mode: str = "mock"
    # Mock mode, when the app sends no token: which verdict to simulate (switchable at runtime).
    mock_verdict: str = "emulator"
    package_name: str = "com.demo.wallet"
    verdict_max_age_s: int = 300
    rasp_max_age_s: int = 120
    # Server-side layers that count. Empty = "the client decides" (Lab 1 before hardening).
    checks: FrozenSet[str] = frozenset(LAYERS)
    # No `integrity` field in the body counts as a missing verdict (an attacker can just omit it).
    integrity_required: bool = True
    agent_limit_cents: int = 10_000      # deck slide 18 agent limit: €100 (app: demowallet.agentLimitCents)
    user_limit_cents: int = 100_000      # €1,000: user transfers above this step up
    agent_token_default_ttl_s: int = 300
    agent_token_max_ttl_s: int = 600
    agent_token_secret: bytes = field(default_factory=lambda: secrets.token_bytes(32))
    starting_balance_cents: int = 245_000
    challenge_ttl_s: int = 300
    session_ttl_s: int = 12 * 3600
    # Console logging of requests/responses (server/http_log.py): pretty | compact | off
    log_http: str = "pretty"
    log_http_max_chars: int = 6000

    def __post_init__(self) -> None:
        if self.log_http not in ("pretty", "compact", "off"):
            raise ValueError("DW_LOG_HTTP must be pretty, compact or off")
        if self.verdict_mode not in VERDICT_MODES:
            raise ValueError(f"DW_VERDICT_MODE must be one of {VERDICT_MODES}")
        if self.mock_verdict not in MOCK_PROFILES:
            raise ValueError(f"DW_MOCK_VERDICT must be one of {MOCK_PROFILES}")
        unknown = set(self.checks) - set(LAYERS)
        if unknown:
            raise ValueError(f"DW_SERVER_CHECKS: unknown layer(s) {sorted(unknown)}; use {LAYERS}")

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "Settings":
        e = os.environ if env is None else env

        def num(name: str, default: int) -> int:
            return int(e.get(name, default))

        checks_raw = e.get("DW_SERVER_CHECKS")
        checks = (
            frozenset(LAYERS)
            if checks_raw is None
            else frozenset(c.strip() for c in checks_raw.split(",") if c.strip() and c.strip() != "none")
        )
        secret = e.get("DW_AGENT_TOKEN_SECRET")
        kwargs = {}
        if secret:
            kwargs["agent_token_secret"] = secret.encode()
        return cls(
            verdict_mode=e.get("DW_VERDICT_MODE", "mock"),
            mock_verdict=e.get("DW_MOCK_VERDICT", "emulator"),
            package_name=e.get("DW_PACKAGE_NAME", "com.demo.wallet"),
            verdict_max_age_s=num("DW_VERDICT_MAX_AGE_SECONDS", 300),
            rasp_max_age_s=num("DW_RASP_MAX_AGE_SECONDS", 120),
            checks=checks,
            integrity_required=e.get("DW_INTEGRITY_REQUIRED", "1") not in ("0", "false", "no"),
            agent_limit_cents=num("DW_AGENT_LIMIT_CENTS", 10_000),
            user_limit_cents=num("DW_USER_LIMIT_CENTS", 100_000),
            agent_token_default_ttl_s=num("DW_AGENT_TOKEN_TTL_SECONDS", 300),
            agent_token_max_ttl_s=num("DW_AGENT_TOKEN_MAX_TTL_SECONDS", 600),
            starting_balance_cents=num("DW_STARTING_BALANCE_CENTS", 245_000),
            log_http=e.get("DW_LOG_HTTP", "pretty").strip().lower(),
            log_http_max_chars=num("DW_LOG_HTTP_MAX_CHARS", 6000),
            **kwargs,
        )
