"""FastAPI application entry point."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from papermatch_api import __version__
from papermatch_api.config import get_settings
from papermatch_api.routers import (
    auth,
    canvas,
    equations,
    feed,
    fields,
    health,
    learn,
    notifications,
    papers,
    saved,
    translations,
)
from papermatch_api.schemas import error_response

logger = logging.getLogger("papermatch")

#: Origins on a private network (RFC 1918 and link-local), any port. Used only in
#: development — see ``create_app``. Deliberately not a blanket ``.*``: a development
#: machine also browses the public internet, and a page out there should not be able to
#: read a developer's local corpus and session.
PRIVATE_LAN_ORIGIN = (
    r"^https?://("
    r"10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|169\.254\.\d{1,3}\.\d{1,3}"
    r"|[a-zA-Z0-9-]+\.local"
    r")(:\d+)?$"
)


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "papermatch-api starting",
        extra={
            "environment": settings.environment,
            "paperProvider": settings.paper_provider,
            "translationProvider": settings.translation_provider,
        },
    )
    yield


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="PaperMatch API",
        version=__version__,
        description=(
            "Abstract discovery, partial translation and provenance-tracked paper metadata. "
            "See PaperMatch_SPEC.md section 24 for the full surface."
        ),
        lifespan=lifespan,
    )

    # In development the Expo dev server may be opened from another device on the same
    # network — a phone checking layouts on a real screen — and that arrives as a private-LAN
    # origin the fixed list cannot name in advance. The regex is added only outside
    # production-like environments, so a deployed API still answers the configured origins
    # and nothing else. Native builds are unaffected either way: CORS is a browser rule.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
        allow_origin_regex=None if settings.is_production_like else PRIVATE_LAN_ORIGIN,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # One error shape for every failure, so the client has a single path to handle
    # (spec section 24: 応答には provenance、license、feature flags、verification status を含める —
    # and the error case needs to be just as predictable).
    @app.exception_handler(RequestValidationError)
    async def _validation_error(_request: Request, exc: RequestValidationError) -> JSONResponse:
        details: dict[str, list[str]] = {}
        for error in exc.errors():
            location = ".".join(str(part) for part in error["loc"][1:]) or "body"
            details.setdefault(location, []).append(error["msg"])
        return JSONResponse(
            status_code=422,
            content=error_response("validation_error", "Request validation failed", **details),
        )

    @app.exception_handler(HTTPException)
    async def _http_error(_request: Request, exc: HTTPException) -> JSONResponse:
        detail: Any = exc.detail
        if isinstance(detail, dict):
            code = str(detail.get("code", "http_error"))
            message = str(detail.get("message", code))
            extras = {k: [str(v)] for k, v in detail.items() if k not in {"code", "message"}}
        else:
            code = str(detail)
            message = str(detail)
            extras = {}
        return JSONResponse(
            status_code=exc.status_code,
            content=error_response(code, message, **extras),
            headers=exc.headers,
        )

    for router in (
        health.router,
        auth.router,
        fields.router,
        papers.router,
        feed.router,
        saved.router,
        translations.router,
        learn.router,
        equations.router,
        canvas.router,
        notifications.router,
    ):
        app.include_router(router)

    return app


app = create_app()
