"""FORGE-0 FastAPI application."""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from api.routes import investigations, repositories, system
from core.config import REPO_ROOT, Settings, get_settings
from core.database import init_db, session_scope, wait_for_database
from core.logging import configure_logging, register_secret
from sandbox.docker import WslKeepAlive, get_sandbox
from services.jobs import get_runner, recover_interrupted
from services.repositories import ensure_demo

log = logging.getLogger("forge0.api")


def _startup() -> None:
    settings = get_settings()
    for secret in (settings.resolved_meta_key, settings.openai_compat_api_key, settings.forge_api_token):
        if secret is not None:
            register_secret(secret.get_secret_value())
    wait_for_database()
    init_db()
    recovered = recover_interrupted()
    if recovered:
        log.warning("marked interrupted investigations as failed", extra={"count": recovered})
    if settings.seed_demo:
        with session_scope() as db:
            demo = ensure_demo(db)
            if demo:
                log.info("demo repository ready", extra={"repository": demo.id})


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    keepalive = WslKeepAlive(get_sandbox().docker)
    if get_settings().sandbox_wsl_keepalive:
        keepalive.start()
    _startup()
    yield
    get_runner().shutdown()
    keepalive.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_format)
    app = FastAPI(
        title="FORGE-0 API",
        version=system.VERSION,
        description="Autonomous, evidence-driven software debugging: hypotheses, sandboxed experiments, "
        "candidate patches and independent verification.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID"],
    )

    @app.middleware("http")
    async def access_log(request: Request, call_next):
        started = time.monotonic()
        response = await call_next(request)
        if not request.url.path.endswith("/stream"):
            log.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status": response.status_code,
                    "ms": round((time.monotonic() - started) * 1000, 1),
                },
            )
        return response

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:  # pragma: no cover
        log.exception("unhandled error", extra={"path": request.url.path})
        return JSONResponse({"detail": "Internal server error"}, status_code=500)

    app.include_router(system.router)
    app.include_router(repositories.router)
    app.include_router(investigations.router)
    _mount_frontend(app, settings)
    return app


def _mount_frontend(app: FastAPI, settings: Settings) -> None:
    """Serves the prebuilt dashboard (lite mode) from the API process, with SPA fallback."""
    if not settings.serve_frontend_dir:
        return
    root = Path(settings.serve_frontend_dir)
    root = (root if root.is_absolute() else REPO_ROOT / root).resolve()
    index = root / "index.html"
    if not index.is_file():
        log.warning("SERVE_FRONTEND_DIR has no index.html; run `npm run build`", extra={"dir": str(root)})
        return

    @app.get("/{path:path}", include_in_schema=False)
    def dashboard(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not Found")
        candidate = (root / path).resolve()
        if path and candidate.is_file() and root in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(index)

    log.info("serving dashboard", extra={"dir": str(root)})


app = create_app()
