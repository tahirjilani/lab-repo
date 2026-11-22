"""HTTP smoke tests through FastAPI (skipped if fastapi/httpx aren't installed)."""
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")
from fastapi.testclient import TestClient  # noqa: E402

from server.app import create_app  # noqa: E402
from server.config import Settings  # noqa: E402
from server.service import WalletService  # noqa: E402
from server.stepup import stepup_message  # noqa: E402


@pytest.fixture
def client(clock):
    return TestClient(create_app(WalletService(Settings(mock_verdict="none"), clock=clock)))


def test_full_flow_over_http(client, device):
    r = client.post("/api/login", json={"username": "tahir", "password": "x", "devicePublicKey": device.public_b64},
                    headers=device.headers())
    assert r.status_code == 200
    device.session = r.json()["sessionToken"]

    assert client.get("/api/balance", headers=device.headers()).json()["balanceCents"] == 245_000

    r = client.post("/api/transfers", json=device.transfer_body(cents=20_000), headers=device.headers())
    out = r.json()
    assert r.status_code == 200 and out["decision"] == "step_up"

    ch = out["challenge"]
    sig = device.sign(stepup_message(ch["id"], ch["nonce"], out["requestHash"]))
    r = client.post(f"/api/transfers/{out['transferId']}/confirm", json={"challengeId": ch["id"], "signature": sig},
                    headers=device.headers())
    assert r.json()["decision"] == "allow" and r.json()["balanceCents"] == 225_000


def test_requests_and_responses_are_logged(client, device, caplog):
    import logging
    caplog.set_level(logging.INFO, logger="demowallet.http")
    client.post("/api/login", json={"username": "t", "password": "hunter2", "devicePublicKey": device.public_b64})
    client.get("/api/balance")  # no session → 401, logged as a warning
    assert "→ #1 POST /api/login" in caplog.text and "← #1 200 POST /api/login" in caplog.text
    assert "← #2 401 GET /api/balance" in caplog.text
    assert "hunter2" not in caplog.text


def test_errors_use_the_apps_error_shape(client, device):
    r = client.get("/api/balance")
    assert r.status_code == 401 and "error" in r.json()
    r = client.post("/api/login", content=b"not json", headers={"content-type": "application/json"})
    assert r.status_code == 400 and r.json() == {"error": "Body must be JSON."}


def test_agent_token_and_lab_endpoints(client, device):
    device.session = client.post("/api/login", json={"username": "t", "password": "x",
                                                     "devicePublicKey": device.public_b64}).json()["sessionToken"]
    r = client.post("/api/agent-tokens", json={"agentId": "demowallet-assistant/1.0", "maxAmountCents": 5_000},
                    headers=device.headers("user"))
    assert r.status_code == 200 and r.json()["agentToken"].startswith("dwat1.")
    assert client.post("/api/lab/mock-verdict", json={"profile": "device_ok"}).json() == {"mockVerdict": "device_ok"}
    assert client.get("/api/lab/status").json()["mockVerdict"] == "device_ok"
    assert client.get("/healthz").json() == {"ok": True}
