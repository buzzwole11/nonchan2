"""Health and readiness (spec sections 24, 25).

The response reports each provider separately so the client can say *why* a feed is
degraded instead of showing a generic failure.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from papermatch_api.config import get_settings
from papermatch_api.db import get_db
from papermatch_api.providers.registry import health_snapshot
from papermatch_api.schemas import DatabaseHealthOut, HealthResponse, ProviderHealthOut

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health(db: Annotated[Session, Depends(get_db)]) -> HealthResponse:
    settings = get_settings()

    connected = False
    revision: str | None = None
    try:
        db.execute(text("SELECT 1"))
        connected = True
    except SQLAlchemyError:
        # A database that is down is a degraded state, not a 500: cached content on the
        # client is still usable and the client needs to be told which part failed.
        connected = False

    if connected:
        # Reported separately, inside a savepoint. An un-migrated database is still a
        # reachable database, and on PostgreSQL a failed statement poisons the enclosing
        # transaction — so a missing alembic_version table must not take the rest of the
        # request down with it.
        try:
            with db.begin_nested():
                row = db.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
                revision = row[0] if row else None
        except SQLAlchemyError:
            revision = None

    providers = {
        label: ProviderHealthOut(healthy=health.healthy, detail=health.detail)
        for label, health in health_snapshot().items()
    }
    all_healthy = connected and all(p.healthy for p in providers.values())

    return HealthResponse(
        status="ok" if all_healthy else "degraded",
        version=settings.api_version,
        providers=providers,
        database=DatabaseHealthOut(connected=connected, migration_revision=revision),
    )
