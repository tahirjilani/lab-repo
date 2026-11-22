"""Mint a mock Play Integrity token for curl demos and tests (mock verdict mode only).

    python -m server.mock_token --profile device_ok --canonical "v1|acc-001|ana|20000|EUR|00ff|assistant"
    python -m server.mock_token --profile emulator --hash e71ee40e...

Bind it to one transfer, then send it with a DIFFERENT transfer to see hash_mismatch.
"""
from __future__ import annotations

import argparse
import time

from .config import MOCK_PROFILES
from .verify import mint_mock_token, mock_payload, sha256_hex


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--profile", choices=[m for m in MOCK_PROFILES if m != "none"], default="device_ok")
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--hash", help="request hash (lowercase hex SHA-256 of the canonical transfer)")
    g.add_argument("--canonical", help="canonical transfer string, hashed for you")
    p.add_argument("--package", default="com.demo.wallet")
    a = p.parse_args()
    h = a.hash or sha256_hex(a.canonical)
    print(mint_mock_token(mock_payload(a.profile, h, a.package, int(time.time() * 1000))))


if __name__ == "__main__":
    main()
