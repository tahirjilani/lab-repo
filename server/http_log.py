"""Console logging of every request and response, with secrets redacted.

    → #3 POST /api/transfers  actor=assistant agent=demowallet-assistant/1.0
      X-RASP: v=1;root=0;emu=1;dbg=0;sig=1;hook=0;ts=...
      { ...request body... }
    ← #3 200 POST /api/transfers  14.2 ms
      { ...response body... }

DW_LOG_HTTP = pretty (default) | compact (one line each) | off
DW_LOG_HTTP_MAX_CHARS = 6000 (longer bodies are cut)

Passwords and session tokens are hidden; signatures, keys, integrity and agent tokens
are shortened to their first characters + length. Plain ASGI, no framework imports.
"""
from __future__ import annotations

import json
import logging
import time
from itertools import count
from typing import Any, Callable, Dict, List, Optional

log = logging.getLogger("demowallet.http")

HIDDEN = {"password", "sessionToken"}
SHORTENED = {"devicePublicKey", "signature", "token", "agentToken"}
SKIP_PATHS = {"/healthz", "/favicon.ico", "/docs", "/redoc", "/openapi.json"}
MODES = ("pretty", "compact", "off")


def shorten(value: str, keep: int = 12) -> str:
    return value if len(value) <= keep + 3 else f"{value[:keep]}…({len(value)} chars)"


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in HIDDEN and v:
                out[k] = "***"
            elif k in SHORTENED and isinstance(v, str):
                out[k] = shorten(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    return obj


def redact_headers(headers: Dict[str, str]) -> Dict[str, str]:
    out = {}
    auth = headers.get("authorization")
    if auth:
        out["Authorization"] = "Bearer ***" if auth.lower().startswith("bearer ") else "***"
    if headers.get("x-agent-token"):
        out["X-Agent-Token"] = shorten(headers["x-agent-token"])
    if headers.get("x-rasp"):
        out["X-RASP"] = headers["x-rasp"]
    return out


def render_body(raw: bytes, pretty: bool, max_chars: int) -> str:
    if not raw:
        return ""
    try:
        data = redact(json.loads(raw))
        text = json.dumps(data, indent=2 if pretty else None, ensure_ascii=False,
                          separators=None if pretty else (",", ":"))
    except (ValueError, UnicodeDecodeError):
        text = raw[:200].decode("utf-8", "replace") + ("…" if len(raw) > 200 else "")
        text = f"<non-JSON, {len(raw)} bytes> {text}"
    if len(text) > max_chars:
        text = text[:max_chars] + f"\n… ({len(text) - max_chars} more chars)"
    return text


class HttpLogMiddleware:
    def __init__(self, app: Callable, mode: str = "pretty", max_chars: int = 6000,
                 logger: Optional[logging.Logger] = None):
        if mode not in MODES:
            raise ValueError(f"DW_LOG_HTTP must be one of {MODES}")
        self.app = app
        self.mode = mode
        self.max_chars = max_chars
        self.log = logger or log
        self._ids = count(1)

    async def __call__(self, scope: dict, receive: Callable, send: Callable) -> None:
        if self.mode == "off" or scope.get("type") != "http" or scope.get("path") in SKIP_PATHS:
            await self.app(scope, receive, send)
            return

        # Read the whole request body, then replay it to the app.
        chunks: List[bytes] = []
        more = True
        while more:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            chunks.append(msg.get("body", b""))
            more = msg.get("more_body", False)
        body = b"".join(chunks)
        replayed = False

        async def replay() -> dict:
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": body, "more_body": False}
            return await receive()

        rid = next(self._ids)
        method, path = scope.get("method", "?"), scope.get("path", "?")
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        self._log_request(rid, method, path, headers, body)

        status = 0
        resp: List[bytes] = []
        started = time.perf_counter()

        async def capture(msg: dict) -> None:
            nonlocal status
            if msg["type"] == "http.response.start":
                status = msg["status"]
            elif msg["type"] == "http.response.body":
                resp.append(msg.get("body", b""))
            await send(msg)

        try:
            await self.app(scope, replay, capture)
        except Exception:
            self.log.exception("← #%d %s %s crashed", rid, method, path)
            raise
        ms = (time.perf_counter() - started) * 1000
        self._log_response(rid, method, path, status, ms, b"".join(resp))

    # ── formatting ──
    def _indent(self, text: str) -> str:
        return "\n".join("  " + line for line in text.splitlines())

    def _log_request(self, rid: int, method: str, path: str, headers: Dict[str, str], body: bytes) -> None:
        who = f"actor={headers.get('x-actor', '-')}"
        if headers.get("x-agent-id"):
            who += f" agent={headers['x-agent-id']}"
        hdrs = redact_headers(headers)
        if self.mode == "compact":
            h = " ".join(f"{k}={v}" for k, v in hdrs.items())
            self.log.info("→ #%d %s %s %s %s %s", rid, method, path, who, h,
                          render_body(body, False, self.max_chars))
            return
        lines = [f"{k}: {v}" for k, v in hdrs.items()]
        text = render_body(body, True, self.max_chars)
        if text:
            lines.append(text)
        detail = ("\n" + self._indent("\n".join(lines))) if lines else ""
        self.log.info("→ #%d %s %s  %s%s", rid, method, path, who, detail)

    def _log_response(self, rid: int, method: str, path: str, status: int, ms: float, body: bytes) -> None:
        level = logging.WARNING if status >= 400 else logging.INFO
        if self.mode == "compact":
            self.log.log(level, "← #%d %d %s %s %.1fms %s", rid, status, method, path, ms,
                         render_body(body, False, self.max_chars))
            return
        text = render_body(body, True, self.max_chars)
        self.log.log(level, "← #%d %d %s %s  %.1f ms%s", rid, status, method, path, ms,
                     ("\n" + self._indent(text)) if text else "")
