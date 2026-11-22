"""Step-up confirmation: the device signs the challenge and the transfer hash with its
Keystore key (biometric-bound, see auth/DeviceKey.kt); we verify with the public key
registered at login.
"""
from __future__ import annotations

import base64
import binascii
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import load_der_public_key


def stepup_message(challenge_id: str, challenge_nonce: str, request_hash: str) -> bytes:
    return f"stepup|v1|{challenge_id}|{challenge_nonce}|{request_hash}".encode("utf-8")


def verify_signature(public_key_b64: str, message: bytes, signature_b64: Any) -> bool:
    """public key: base64 X.509 SubjectPublicKeyInfo (P-256); signature: base64 DER ECDSA-SHA256."""
    if not isinstance(signature_b64, str) or not signature_b64:
        return False
    try:
        key = load_der_public_key(base64.b64decode(public_key_b64, validate=True))
        sig = base64.b64decode(signature_b64, validate=True)
    except (ValueError, binascii.Error):
        return False
    if not isinstance(key, ec.EllipticCurvePublicKey) or key.curve.name != "secp256r1":
        return False
    try:
        key.verify(sig, message, ec.ECDSA(hashes.SHA256()))
        return True
    except InvalidSignature:
        return False
