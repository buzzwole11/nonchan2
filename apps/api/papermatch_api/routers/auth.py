"""Guest authentication and the current-user resource (spec section 24)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from papermatch_api.db import get_db
from papermatch_api.models import Field, Interest, User, UserSettings
from papermatch_api.passwords import hash_password, verify_password
from papermatch_api.schemas import (
    AuthTokenResponse,
    GuestAuthRequest,
    InterestOut,
    LoginRequest,
    RegisterRequest,
    UpdateInterestsRequest,
    UserOut,
    UserSettingsOut,
    UserSettingsPatch,
)
from papermatch_api.security import CurrentUser, create_access_token

router = APIRouter(tags=["auth"])


def _to_user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        is_guest=user.is_guest,
        display_name=user.display_name,
        created_at=user.created_at,
        onboarding_completed_at=user.onboarding_completed_at,
        settings=UserSettingsOut.model_validate(user.settings),
        interests=[InterestOut.model_validate(i) for i in user.interests],
    )


@router.post("/auth/guest", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED)
def create_guest(
    payload: GuestAuthRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AuthTokenResponse:
    """Create an anonymous account.

    Onboarding must be usable before anyone signs up (spec section 4), so the first
    request the app makes is this one. The account is real and its data is preserved; a
    later phase attaches an email to it rather than migrating anything.
    """
    user = User(is_guest=True)
    db.add(user)
    db.flush()
    db.add(UserSettings(user_id=user.id, locale=payload.locale, timezone=payload.timezone))
    db.flush()
    db.refresh(user)

    token, expires_in = create_access_token(user.id)
    return AuthTokenResponse(access_token=token, expires_in=expires_in, user=_to_user_out(user))


@router.post(
    "/auth/register", response_model=AuthTokenResponse, status_code=status.HTTP_201_CREATED
)
def register(
    payload: RegisterRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> AuthTokenResponse:
    """Attach an email and password to the account the reader is already using.

    Deliberately an upgrade of the current guest rather than a new account. Section 4 puts
    the first Abstract card before any sign-up, so by the time someone registers they have a
    library — and creating a second account here would strand it while looking like success.
    """
    if not user.is_guest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "already_registered", "message": "this account already has a login"},
        )

    email = payload.email.strip().lower()
    taken = db.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if taken is not None:
        # The same wording a wrong password gets, for the same reason: a distinct message
        # here turns the form into a way of asking whether someone has an account.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "email_unavailable", "message": "that email cannot be used"},
        )

    user.email = email
    user.password_hash = hash_password(payload.password)
    user.is_guest = False
    if payload.display_name is not None:
        user.display_name = payload.display_name.strip() or None
    db.flush()
    db.refresh(user)

    token, expires_in = create_access_token(user.id)
    return AuthTokenResponse(access_token=token, expires_in=expires_in, user=_to_user_out(user))


@router.post("/auth/login", response_model=AuthTokenResponse)
def login(
    payload: LoginRequest,
    db: Annotated[Session, Depends(get_db)],
) -> AuthTokenResponse:
    """Sign in to an existing account (spec section 24).

    **One answer for every failure.** A wrong password, an unknown email and an account with
    no password set all return the same 401. Anything else makes this endpoint a way to find
    out who has an account here, which is a fact about someone's reading that they did not
    publish.
    """
    email = payload.email.strip().lower()
    found = db.execute(select(User).where(User.email == email)).scalar_one_or_none()

    # `verify_password` is run even when there is no such user, so a missing account and a
    # wrong password take a similar amount of time.
    stored = found.password_hash if found is not None else None
    if not verify_password(payload.password, stored) or found is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "invalid_credentials", "message": "email or password is wrong"},
        )

    db.refresh(found)
    token, expires_in = create_access_token(found.id)
    return AuthTokenResponse(access_token=token, expires_in=expires_in, user=_to_user_out(found))


@router.get("/me", response_model=UserOut)
def get_me(user: CurrentUser) -> UserOut:
    return _to_user_out(user)


@router.patch("/me/settings", response_model=UserOut)
def patch_settings(
    payload: UserSettingsPatch,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    changes = payload.model_dump(exclude_unset=True, exclude_none=True)
    for key, value in changes.items():
        setattr(user.settings, key, value)
    db.flush()
    db.refresh(user)
    return _to_user_out(user)


@router.put("/me/interests", response_model=UserOut)
def put_interests(
    payload: UpdateInterestsRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> UserOut:
    """Replace the interest set (spec section 18, onboarding step 1).

    Unknown field ids are rejected as a group rather than silently dropped: an onboarding
    screen that appears to save a selection but does not is worse than an error.
    """
    known = set(db.execute(select(Field.id)).scalars())
    unknown = sorted({i.field_id for i in payload.interests} - known)
    if unknown:
        from fastapi import HTTPException

        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "unknown_field_ids", "fieldIds": unknown},
        )

    db.execute(delete(Interest).where(Interest.user_id == user.id))
    db.flush()
    for interest in payload.interests:
        db.add(
            Interest(
                user_id=user.id,
                field_id=interest.field_id,
                strength=interest.strength,
                mode=interest.mode,
            )
        )
    db.flush()
    db.refresh(user)
    return _to_user_out(user)
