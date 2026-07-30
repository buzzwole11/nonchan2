"""Minimal authentication (spec section 28, Phase 0: 認証の最小実装).

Phase 0 issues guest tokens only. There is no password, no email verification and no
refresh flow yet — but the token shape, the dependency and the 401 behaviour are the ones
later phases keep, so adding real accounts does not change any call site.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.config import Settings, get_settings
from papermatch_api.db import get_db
from papermatch_api.models import User

TOKEN_TYPE = "bearer"
_bearer = HTTPBearer(auto_error=False)


def create_access_token(user_id: uuid.UUID, settings: Settings | None = None) -> tuple[str, int]:
    """Return ``(token, expires_in_seconds)``."""
    settings = settings or get_settings()
    now = datetime.now(tz=UTC)
    expires_in = settings.guest_token_ttl_seconds
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expires_in)).timestamp()),
        "typ": "access",
    }
    token = jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)
    return token, expires_in


def decode_access_token(token: str, settings: Settings | None = None) -> uuid.UUID:
    settings = settings or get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="token_expired"
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token"
        ) from exc

    subject = payload.get("sub")
    if not isinstance(subject, str):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token")
    try:
        return uuid.UUID(subject)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid_token"
        ) from exc


def current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    db: Annotated[Session, Depends(get_db)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing_bearer_token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    user_id = decode_access_token(credentials.credentials)
    user = db.execute(select(User).where(User.id == user_id)).scalar_one_or_none()
    if user is None:
        # The token decoded but its subject is gone — treat as unauthenticated rather
        # than leaking that the account once existed.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown_subject")
    return user


CurrentUser = Annotated[User, Depends(current_user)]
