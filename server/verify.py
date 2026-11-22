"""Lab 2, server side: check that a Play Integrity verdict vouches for THIS transfer.

The app hashes the canonical transfer, asks Play Integrity for a token bound to that
hash (standard request, setRequestHash) and sends token + transfer. Here we:

  1. rebuild the canonical string from the body and hash it ourselves,
  2. decode the token (Google's API, or the mock decoder in the lab),
  3. reject if the package or the bound hash don't match, or the verdict is stale,
  4. turn the device/app/environment verdicts into risk signals.

A missing or errored token is evidence too: it scores as a failed verdict and steps
up — it never passes silently and never blocks on its own.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .signals import BLOCK, STEP_UP, Signal

CANONICAL_VERSION = "v1"
ACTORS = ("user", "assistant")


class InvalidTransfer(ValueError):
    """The body isn't a well-formed transfer (HTTP 400)."""


@dataclass(frozen=True)
class Transfer:
    account: str
    payee_id: str
    amount_cents: int
    currency: str
    nonce: str
    actor: str

    @classmethod
    def from_json(cls, d: Any) -> "Transfer":
        if not isinstance(d, dict):
            raise InvalidTransfer("transfer must be an object")
        try:
            t = cls(
                account=d["account"], payee_id=d["payeeId"], amount_cents=d["amountCents"],
                currency=d.get("currency", "EUR"), nonce=d["nonce"], actor=d["actor"],
            )
        except KeyError as e:
            raise InvalidTransfer(f"transfer.{e.args[0]} is required") from None
        for name in ("account", "payee_id", "currency", "nonce", "actor"):
            v = getattr(t, name)
            if not isinstance(v, str) or not v or "|" in v:
                raise InvalidTransfer(f"transfer.{name} must be a non-empty string without '|'")
        if isinstance(t.amount_cents, bool) or not isinstance(t.amount_cents, int) or t.amount_cents <= 0:
            raise InvalidTransfer("transfer.amountCents must be a positive integer")
        if t.actor not in ACTORS:
            raise InvalidTransfer(f"transfer.actor must be one of {ACTORS}")
        return t

    def canonical(self) -> str:
        """Must match Transfer.canonical() in the app: v1|account|payee|cents|currency|nonce|actor."""
        return "|".join([CANONICAL_VERSION, self.account, self.payee_id, str(self.amount_cents),
                         self.currency, self.nonce, self.actor])

    def request_hash(self) -> str:
        return sha256_hex(self.canonical())


def sha256_hex(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ── Decoders ────────────────────────────────────────────────────────────────────

class DecodeError(Exception):
    pass


def _b64url_decode(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


class MockDecoder:
    """Lab only. A mock token is "mock." + base64url(JSON payload in Google's decoded shape).

    It is NOT signed: anyone can forge one. That is the point of showing it next to
    the real decoder — the trust comes from Google decoding the token, not from its shape.
    """

    PREFIX = "mock."

    def decode(self, token: str) -> Dict[str, Any]:
        if not token.startswith(self.PREFIX):
            raise DecodeError("not a mock token (real Play Integrity tokens need DW_VERDICT_MODE=google)")
        try:
            payload = json.loads(_b64url_decode(token[len(self.PREFIX):]))
        except Exception:
            raise DecodeError("mock token is not base64url JSON") from None
        if not isinstance(payload, dict):
            raise DecodeError("mock token payload must be an object")
        return payload


def mint_mock_token(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":")).encode()
    return MockDecoder.PREFIX + base64.urlsafe_b64encode(raw).decode().rstrip("=")


class GoogleDecoder:
    """Decodes real tokens with playintegrity.googleapis.com (service-account credentials).

    Credentials come from GOOGLE_APPLICATION_CREDENTIALS (a service account in the Cloud
    project linked to the app in Play Console). Needs `google-auth` and `requests`.
    """

    SCOPE = "https://www.googleapis.com/auth/playintegrity"
    URL = "https://playintegrity.googleapis.com/v1/{package}:decodeIntegrityToken"

    def __init__(self, package_name: str, session: Any = None):
        self.package_name = package_name
        self._session = session

    def _http(self) -> Any:
        if self._session is None:
            import google.auth  # optional dependency, only for google mode
            from google.auth.transport.requests import AuthorizedSession

            creds, _ = google.auth.default(scopes=[self.SCOPE])
            self._session = AuthorizedSession(creds)
        return self._session

    def decode(self, token: str) -> Dict[str, Any]:
        if token.startswith(MockDecoder.PREFIX):
            raise DecodeError("mock token refused in google mode")
        try:
            r = self._http().post(self.URL.format(package=self.package_name),
                                  json={"integrityToken": token}, timeout=10)
        except Exception as e:
            raise DecodeError(f"Play Integrity API unreachable ({type(e).__name__})") from None
        if r.status_code != 200:
            raise DecodeError(f"Play Integrity API returned HTTP {r.status_code}")
        payload = (r.json() or {}).get("tokenPayloadExternal")
        if not isinstance(payload, dict):
            raise DecodeError("Play Integrity API response has no tokenPayloadExternal")
        return payload


# ── Mock verdict profiles ───────────────────────────────────────────────────────

def mock_payload(profile: str, request_hash: str, package_name: str, now_ms: int) -> Optional[Dict[str, Any]]:
    """The verdict Google would plausibly return, for when the lab app can't get a token.

    emulator   : sideloaded app on an emulator — no device label, unrecognized, unlicensed
                 (what attendees really get; step-1 summary headline 1)
    device_ok  : Play-installed app on a certified, locked device
    basic      : rooted-but-passing phone — only MEETS_BASIC_INTEGRITY
    controlled : device_ok, but an unknown app can control the device (accessibility agent)
    none       : no verdict at all → treated as missing
    """
    if profile == "none":
        return None
    ok = profile in ("device_ok", "controlled")
    labels = {"emulator": [], "basic": ["MEETS_BASIC_INTEGRITY"]}.get(
        profile, ["MEETS_BASIC_INTEGRITY", "MEETS_DEVICE_INTEGRITY"])
    payload: Dict[str, Any] = {
        "requestDetails": {"requestPackageName": package_name, "requestHash": request_hash,
                           "timestampMillis": str(now_ms)},
        "appIntegrity": {"appRecognitionVerdict": "PLAY_RECOGNIZED" if profile != "emulator" else "UNRECOGNIZED_VERSION",
                         "packageName": package_name},
        "deviceIntegrity": {"deviceRecognitionVerdict": labels},
        "accountDetails": {"appLicensingVerdict": "LICENSED" if ok or profile == "basic" else "UNLICENSED"},
        "testingDetails": {"isTestingResponse": True, "mockProfile": profile},
    }
    if profile == "controlled":
        payload["environmentDetails"] = {"appAccessRiskVerdict": {"appsDetected": ["KNOWN_INSTALLED", "UNKNOWN_CONTROLLING"]}}
    return payload


# ── Verdict → signals ───────────────────────────────────────────────────────────

def _sig(code: str, points: int, floor: Optional[str], detail: str) -> Signal:
    return Signal("integrity", code, points, floor, detail)


def check_payload(payload: Dict[str, Any], expected_hash: str, package_name: str,
                  max_age_s: int, now_ms: int) -> List[Signal]:
    rd = payload.get("requestDetails") or {}

    # ── LAB 2: the three checks that make the token mean something ──
    if rd.get("requestPackageName") != package_name:
        return [_sig("package_mismatch", 0, BLOCK, "Integrity token was issued for another app.")]
    if not hmac.compare_digest(str(rd.get("requestHash") or ""), expected_hash):
        return [_sig("hash_mismatch", 0, BLOCK, "Integrity token is bound to a different transfer.")]
    out: List[Signal] = []
    try:
        age_ms = now_ms - int(rd.get("timestampMillis"))
    except (TypeError, ValueError):
        age_ms = None
    if age_ms is None or age_ms > max_age_s * 1000 or age_ms < -60_000:
        out.append(_sig("stale", 30, STEP_UP, "Integrity verdict is missing a fresh timestamp."))
    # ── end LAB 2 ──

    app = (payload.get("appIntegrity") or {}).get("appRecognitionVerdict", "UNEVALUATED")
    if app != "PLAY_RECOGNIZED":
        out.append(_sig("app_unrecognized", 30, STEP_UP, f"App not recognized by Google Play ({app})."))

    labels = (payload.get("deviceIntegrity") or {}).get("deviceRecognitionVerdict") or []
    if "MEETS_DEVICE_INTEGRITY" in labels or "MEETS_STRONG_INTEGRITY" in labels:
        pass
    elif "MEETS_BASIC_INTEGRITY" in labels:
        out.append(_sig("device_basic", 20, None, "Device only meets basic integrity."))
    else:
        out.append(_sig("device_none", 35, STEP_UP, "Device fails integrity (no device label)."))

    if (payload.get("accountDetails") or {}).get("appLicensingVerdict") == "UNLICENSED":
        out.append(_sig("unlicensed", 5, None, "App wasn't installed from Google Play."))

    env = payload.get("environmentDetails") or {}
    apps = set((env.get("appAccessRiskVerdict") or {}).get("appsDetected") or [])
    if "UNKNOWN_CONTROLLING" in apps:
        out.append(_sig("unknown_controlling", 30, STEP_UP,
                        "An app from outside Google Play can control the device."))
    elif apps & {"UNKNOWN_OVERLAYS", "UNKNOWN_CAPTURING"}:
        out.append(_sig("unknown_capturing", 15, None,
                        "An app from outside Google Play can overlay or capture the screen."))
    pp = {"POSSIBLE_RISK": 5, "MEDIUM_RISK": 10, "HIGH_RISK": 15}.get(env.get("playProtectVerdict", ""))
    if pp:
        out.append(_sig("play_protect", pp, None, f"Play Protect: {env['playProtectVerdict']}."))
    level = ((payload.get("deviceIntegrity") or {}).get("recentDeviceActivity") or {}).get("deviceActivityLevel")
    act = {"LEVEL_3": 10, "LEVEL_4": 20}.get(level or "")
    if act:
        out.append(_sig("device_activity", act, None, f"Unusually many integrity requests from this device ({level})."))

    if not any(s.points or s.floor for s in out):
        out.append(_sig("verified", 0, None, "Device and app verified."))
    if (payload.get("testingDetails") or {}).get("isTestingResponse"):
        out.append(_sig("testing_response", 0, None, "Verdict is a test response."))
    return out


def assess_integrity(integrity: Optional[Dict[str, Any]], transfer: Transfer, client_hash: Optional[str],
                     decoder: Any, *, mode: str, mock_profile: str, package_name: str,
                     max_age_s: int, required: bool, now_ms: Optional[int] = None) -> List[Signal]:
    """Signals for the integrity layer of one transfer request."""
    now_ms = int(time.time() * 1000) if now_ms is None else now_ms
    expected = transfer.request_hash()

    if integrity is None:
        if not required:
            return [_sig("not_sent", 0, None, "No integrity verdict sent (not required).")]
        return [_sig("missing", 30, STEP_UP, "No integrity verdict sent.")]
    if not isinstance(integrity, dict):
        return [_sig("missing", 30, STEP_UP, "Integrity field is malformed.")]

    token = integrity.get("token")
    if not token:
        if mode == "mock" and mock_profile != "none":
            # Simulate the token the device would have got: bound to the hash IT computed.
            # If the body was altered in transit, that no longer matches our recomputed hash.
            bound = client_hash if isinstance(client_hash, str) and client_hash else expected
            payload = mock_payload(mock_profile, bound, package_name, now_ms)
        else:
            err = str(integrity.get("error") or "unknown").split(":")[0][:40]
            return [_sig("missing", 30, STEP_UP, f"No integrity verdict ({err}).")]
    else:
        try:
            payload = decoder.decode(str(token))
        except DecodeError as e:
            return [_sig("token_invalid", 30, STEP_UP, f"Integrity token rejected: {e}.")]
    return check_payload(payload, expected, package_name, max_age_s, now_ms)
