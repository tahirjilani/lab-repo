"""Request/response console logging (server/http_log.py), tested as plain ASGI."""
import asyncio
import json
import logging

import pytest

from server.config import Settings
from server.http_log import HttpLogMiddleware, redact, redact_headers


def run(mw, path="/api/login", body=b"", headers=None, chunks=None):
    """Drive the middleware with one request; return (what the app saw, what the client got)."""
    parts = chunks or [body]
    incoming = [{"type": "http.request", "body": p, "more_body": i < len(parts) - 1} for i, p in enumerate(parts)]
    sent = []

    async def receive():
        return incoming.pop(0) if incoming else {"type": "http.disconnect"}

    async def send(msg):
        sent.append(msg)

    scope = {"type": "http", "method": "POST", "path": path,
             "headers": [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]}
    asyncio.run(mw(scope, receive, send))
    return sent


def echo_app(status=200, reply=None):
    seen = {}

    async def app(scope, receive, send):
        msg = await receive()
        seen["body"] = msg["body"]
        out = json.dumps(reply if reply is not None else {"ok": True}).encode()
        await send({"type": "http.response.start", "status": status, "headers": []})
        await send({"type": "http.response.body", "body": out})
    return app, seen


@pytest.fixture
def logs(caplog):
    caplog.set_level(logging.INFO, logger="demowallet.http")
    return caplog


def test_logs_request_and_response_with_secrets_redacted(logs):
    app, seen = echo_app(reply={"sessionToken": "s3cr3t-session", "account": "acc-001"})
    body = json.dumps({"username": "tahir", "password": "hunter2",
                       "devicePublicKey": "MFkwEwYHKoZIzj0CAQYIKoZIzj0DAQcDQgAE" * 3}).encode()
    sent = run(HttpLogMiddleware(app), body=body,
               headers={"Authorization": "Bearer abc.def", "X-Actor": "user", "X-RASP": "v=1;root=0;emu=1"})

    assert seen["body"] == body                      # the app still gets the untouched body
    assert sent[1]["body"] == b'{"sessionToken": "s3cr3t-session", "account": "acc-001"}'  # client too
    text = logs.text
    assert "→ #1 POST /api/login  actor=user" in text and "X-RASP: v=1;root=0;emu=1" in text
    assert "← #1 200 POST /api/login" in text and '"account": "acc-001"' in text
    for secret in ("hunter2", "s3cr3t-session", "abc.def", "KoZIzj0DAQcDQgAEMFkw"):
        assert secret not in text
    assert '"password": "***"' in text and "Bearer ***" in text and "chars)" in text


def test_multi_chunk_body_is_reassembled(logs):
    app, seen = echo_app()
    run(HttpLogMiddleware(app), chunks=[b'{"a":', b'1}'])
    assert seen["body"] == b'{"a":1}'
    assert '"a": 1' in logs.text


def test_errors_logged_as_warning_and_compact_mode(logs):
    app, _ = echo_app(status=401, reply={"error": "Not signed in"})
    run(HttpLogMiddleware(app, mode="compact"), path="/api/balance")
    [req, resp] = logs.records
    assert req.getMessage().startswith("→ #1 POST /api/balance actor=-")
    assert resp.levelno == logging.WARNING and '{"error":"Not signed in"}' in resp.getMessage()
    assert "\n" not in resp.getMessage()


def test_off_and_skipped_paths_log_nothing(logs):
    app, _ = echo_app()
    run(HttpLogMiddleware(app, mode="off"))
    run(HttpLogMiddleware(app), path="/healthz")
    assert logs.records == []


def test_long_and_non_json_bodies(logs):
    app, _ = echo_app(reply={"x": "y" * 500})
    run(HttpLogMiddleware(app, max_chars=100), body=b"not json at all")
    assert "<non-JSON, 15 bytes> not json at all" in logs.text
    assert "more chars)" in logs.text


def test_redaction_helpers():
    nested = {"integrity": {"token": "eyJ" + "A" * 400, "error": None}, "challenge": {"id": "ch-1"},
              "signals": [{"code": "x"}]}
    r = redact(nested)
    assert r["integrity"]["token"].endswith("(403 chars)") and r["challenge"] == {"id": "ch-1"}
    h = redact_headers({"authorization": "Bearer x", "x-agent-token": "dwat1." + "z" * 80, "x-actor": "user"})
    assert h == {"Authorization": "Bearer ***", "X-Agent-Token": "dwat1.zzzzzz…(86 chars)"}


def test_setting_from_env():
    assert Settings.from_env({}).log_http == "pretty"
    assert Settings.from_env({"DW_LOG_HTTP": "OFF"}).log_http == "off"
    with pytest.raises(ValueError):
        Settings.from_env({"DW_LOG_HTTP": "loud"})
