"""
FastAPI application factory for the Contexa Local API.

The app is bound to 127.0.0.1 only — it is never exposed to external
network interfaces. All subsystems (context_store, config, etc.) are
attached to app.state by the daemon before the server starts.
"""

from __future__ import annotations

import time

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from contexa.api.routes import contexts, health, trust, sync as sync_routes
from contexa.store.context_store import NotFoundError, ChecksumError


from contextlib import asynccontextmanager

def create_app() -> FastAPI:
    """Create and configure the FastAPI application.

    The caller (daemon) is responsible for populating app.state with:
      - app.state.context_store  : ContextStore instance
      - app.state.config         : ContexaConfig instance
      - app.state.device_id      : str — this device's UUID
      - app.state.start_time     : float — unix timestamp of daemon start
      - app.state.sync_engine    : Sync_Engine instance (optional at startup)
      - app.state.trust_store    : TrustStore instance (optional at startup)
    """
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not hasattr(app.state, "start_time"):
            app.state.start_time = time.time()
        yield

    app = FastAPI(
        title="Contexa Local API",
        description="Local HTTP API for the Contexa context engine daemon",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
        lifespan=lifespan,
    )

    # Exception handlers

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        return JSONResponse(
            status_code=400,
            content={
                "error": "validation_error",
                "detail": exc.errors(),
            },
        )

    @app.exception_handler(NotFoundError)
    async def not_found_handler(request: Request, exc: NotFoundError):
        return JSONResponse(
            status_code=404,
            content={
                "error": "not_found",
                "context_id": exc.context_id,
                "detail": str(exc),
            },
        )

    @app.exception_handler(ChecksumError)
    async def checksum_error_handler(request: Request, exc: ChecksumError):
        return JSONResponse(
            status_code=500,
            content={
                "error": "integrity_error",
                "context_id": exc.context_id,
                "detail": str(exc),
            },
        )

    @app.exception_handler(HTTPException)
    async def http_exception_handler(request: Request, exc: HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "http_error", "detail": exc.detail},
        )

    @app.exception_handler(Exception)
    async def generic_error_handler(request: Request, exc: Exception):
        return JSONResponse(
            status_code=500,
            content={"error": "internal_error", "message": str(exc)},
        )

    # Routers

    app.include_router(contexts.router, tags=["contexts"])
    app.include_router(health.router, tags=["health"])
    app.include_router(trust.router, tags=["trust"])
    app.include_router(sync_routes.router, tags=["sync"])

    return app
