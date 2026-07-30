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
from papermatch_api.routers import auth, fields, health, papers, translations
from papermatch_api.schemas import error_response

logger = logging.getLogger("papermatch")


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

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allow_origins,
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

    for router in (health.router, auth.router, fields.router, papers.router, translations.router):
        app.include_router(router)

    return app


app = create_app()
