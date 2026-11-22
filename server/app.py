"""FastAPI shell. Run from the repo root:

    uvicorn server.app:app --host 127.0.0.1 --port 8000

The emulator reaches it at http://10.0.2.2:8000 (gradle property demowallet.apiBaseUrl).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from .config import Settings
from .http_log import HttpLogMiddleware
from .service import ApiError, WalletService

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def create_app(service: Optional[WalletService] = None) -> FastAPI:
    svc = service or WalletService(Settings.from_env())
    app = FastAPI(title="DemoWallet lab server", version="1.0",
                  description="Server-side risk engine for the DSC Europe lab: the client collects, the server decides.")
    app.state.service = svc
    s = svc.settings
    if s.log_http != "off":
        app.add_middleware(HttpLogMiddleware, mode=s.log_http, max_chars=s.log_http_max_chars)

    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse({"error": exc.message}, status_code=exc.status)

    async def body(request: Request) -> Any:
        try:
            return await request.json()
        except Exception:
            raise ApiError(400, "Body must be JSON.") from None

    def headers(request: Request) -> Dict[str, str]:
        return {k.lower(): v for k, v in request.headers.items()}

    @app.post("/api/login")
    async def login(request: Request):
        return svc.login(await body(request), headers(request))

    @app.get("/api/balance")
    async def balance(request: Request):
        return svc.balance(headers(request))

    @app.post("/api/agent-tokens")
    async def agent_tokens(request: Request):
        return svc.mint_agent_token(await body(request), headers(request))

    @app.post("/api/transfers")
    async def transfers(request: Request):
        # Threadpool: in google mode this makes a blocking call to the Play Integrity API.
        return await run_in_threadpool(svc.submit_transfer, await body(request), headers(request))

    @app.post("/api/transfers/{transfer_id}/confirm")
    async def confirm(transfer_id: str, request: Request):
        return svc.confirm(transfer_id, await body(request), headers(request))

    # ── lab helpers (no auth: localhost lab server only) ──
    @app.get("/api/lab/status")
    async def lab_status():
        return svc.status()

    @app.post("/api/lab/mock-verdict")
    async def lab_mock_verdict(request: Request):
        return svc.set_mock_profile(await body(request))

    @app.get("/api/lab/decisions")
    async def lab_decisions():
        return {"decisions": list(svc.decisions)[:50]}

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    return app


app = create_app()
