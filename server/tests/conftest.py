import base64
import secrets

import pytest
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

from server.config import Settings
from server.service import WalletService

NOW = 1_800_000_000.0  # fixed clock, seconds

# Lab 2 switch. False on main (the solution). lab2-start sets it to True: the LAB 2 checks in
# server/verify.py are the exercise there, so tests marked `lab2` are skipped by `pytest server`
# and run with `pytest server --lab2` once you've filled in the TODOs (they're your checker).
LAB2_IS_EXERCISE = True


def pytest_addoption(parser):
    parser.addoption("--lab2", action="store_true", default=False,
                     help="run the Lab 2 tests (the checks you write in server/verify.py)")


def pytest_configure(config):
    config.addinivalue_line("markers", "lab2: needs the LAB 2 checks in server/verify.py")


def pytest_collection_modifyitems(config, items):
    if not LAB2_IS_EXERCISE or config.getoption("--lab2"):
        return
    skip = pytest.mark.skip(reason="Lab 2 exercise: fill in the LAB 2 TODOs in server/verify.py, "
                                   "then run `pytest server --lab2` (docs/lab2.md)")
    for item in items:
        if item.get_closest_marker("lab2"):  # not item.keywords: that also matches a folder named lab2
            item.add_marker(skip)


class Clock:
    def __init__(self, t: float = NOW):
        self.t = t

    def __call__(self) -> float:
        return self.t


class Device:
    """Plays the app: builds bodies and headers exactly like HttpBackend.kt, signs step-ups."""

    def __init__(self, clock: Clock):
        self.clock = clock
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.public_b64 = base64.b64encode(self.key.public_key().public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)).decode()
        self.rasp = dict(rooted=False, emulator=True, debugger=False, signatureValid=True, hooked=False)
        self.session = None

    def rasp_body(self):
        return {**self.rasp, "details": [], "collectedAtMillis": int(self.clock() * 1000)}

    def rasp_header(self):
        r = self.rasp
        b = lambda v: "1" if v else "0"  # noqa: E731
        return (f"v=1;root={b(r['rooted'])};emu={b(r['emulator'])};dbg={b(r['debugger'])};"
                f"sig={b(r['signatureValid'])};hook={b(r['hooked'])};ts={int(self.clock() * 1000)}")

    def headers(self, actor="user", agent_token=None):
        h = {"x-rasp": self.rasp_header(), "x-actor": actor}
        if actor == "assistant":
            h["x-agent-id"] = "demowallet-assistant/1.0"
        if agent_token:
            h["x-agent-token"] = agent_token
        if self.session:
            h["authorization"] = f"Bearer {self.session}"
        return h

    def transfer_body(self, payee="ana", cents=2_000, actor="user", integrity="NOT_CONFIGURED", nonce=None,
                      client_hash=None):
        from server.verify import Transfer
        t = {"account": "acc-001", "payeeId": payee, "amountCents": cents, "currency": "EUR",
             "nonce": nonce or secrets.token_hex(16), "actor": actor}
        body = {"transfer": t, "clientRequestHash": client_hash or Transfer.from_json(t).request_hash(),
                "rasp": self.rasp_body()}
        if integrity is not None:
            body["integrity"] = ({"token": integrity[6:], "error": None} if integrity.startswith("token:")
                                 else {"token": None, "error": integrity})
        return body

    def sign(self, message: bytes) -> str:
        return base64.b64encode(self.key.sign(message, ec.ECDSA(hashes.SHA256()))).decode()


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def make_service(clock):
    def make(**overrides):
        return WalletService(Settings(**overrides), clock=clock)
    return make


@pytest.fixture
def device(clock):
    return Device(clock)


def signed_in(svc, device):
    device.session = svc.login({"username": "tahir", "password": "x", "devicePublicKey": device.public_b64},
                               {})["sessionToken"]
    return device
