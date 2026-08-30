"""Partial translation (spec section 7).

Phase 0 wires the ``TranslationProvider`` interface end to end with the mock so the
formula-protection contract is exercised by real requests rather than only by unit tests.
The staged hint UI itself lands in Phase 2; the shapes it will call are already here.

Two guarantees enforced at this layer, not left to the provider:

* The request is a **selection**, not a document. Anything longer than
  ``max_selection_chars`` is refused — the product deliberately does not translate whole
  abstracts (spec section 3: 全文翻訳に逃げない).
* Formulas are masked before the provider sees them and restored afterwards. If a token
  does not survive, the original text is returned instead of a damaged translation.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.config import get_settings
from papermatch_api.db import get_db
from papermatch_api.models import Paper, TextSelection, Translation
from papermatch_api.providers.base import (
    ProviderUnavailable,
)
from papermatch_api.providers.base import (
    TranslationRequest as ProviderTranslationRequest,
)
from papermatch_api.providers.registry import get_translation_provider
from papermatch_api.schemas import (
    CreateTranslationRequest,
    CreateTranslationResponse,
    GenerationProvenanceOut,
    MathPlaceholderOut,
    TranslationOut,
)
from papermatch_api.security import CurrentUser
from papermatch_api.text.math_placeholders import (
    mask_math,
    restore_math,
    selection_splits_math,
    unmasked_tokens,
)

router = APIRouter(tags=["translations"])

CONTEXT_CHARS = 240


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@router.post(
    "/translations",
    response_model=CreateTranslationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_translation(
    payload: CreateTranslationRequest,
    user: CurrentUser,
    db: Annotated[Session, Depends(get_db)],
) -> CreateTranslationResponse:
    settings = get_settings()

    paper = db.execute(select(Paper).where(Paper.id == payload.paper_id)).scalar_one_or_none()
    if paper is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="paper_not_found")

    source_text = paper.abstract if payload.selection.field == "abstract" else paper.title
    start, end = payload.selection.start, payload.selection.end
    if end > len(source_text):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="selection_out_of_range"
        )

    actual = source_text[start:end]
    if actual != payload.selection.exact_text:
        # The client's offsets disagree with the stored text — most likely the abstract
        # was re-ingested at a new version. Refuse rather than translate a different span
        # than the user highlighted.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="selection_text_mismatch")

    if len(actual) > settings.max_selection_chars:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="selection_too_long",
        )

    # Spec section 21: text that may not be redistributed must not be sent to a
    # third-party provider either.
    if not paper.abstract_redistributable:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="abstract_not_redistributable"
        )

    # Checked against the whole abstract, not the excerpt: a span dragged from the middle
    # of one formula into the next is lexically valid maths on its own and would mask
    # cleanly into nonsense.
    if selection_splits_math(source_text, start, end):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selection_splits_formula",
        )

    masked = mask_math(actual)
    if masked.unbalanced:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="selection_splits_formula",
        )

    selection = TextSelection(
        user_id=user.id,
        paper_id=paper.id,
        field=payload.selection.field,
        start_offset=start,
        end_offset=end,
        exact_text=actual,
        exact_text_hash=_sha256(actual),
        context_before=source_text[max(0, start - CONTEXT_CHARS) : start],
        context_after=source_text[end : end + CONTEXT_CHARS],
    )
    db.add(selection)
    db.flush()

    provider = get_translation_provider()
    try:
        result = provider.translate(
            ProviderTranslationRequest(
                text=masked.masked_text,
                source_lang="en",
                target_lang=user.settings.locale.split("-")[0],
                style=payload.style,
                stage=payload.stage,
                context_before=selection.context_before,
                context_after=selection.context_after,
                field_id=paper.primary_field_id,
            )
        )
    except ProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="translation_unavailable"
        ) from exc

    dropped = unmasked_tokens(result.translated_text, masked.spans)
    # ``hard_words`` is a glossary stage and is not expected to echo the formulas.
    expects_full_text = payload.stage != "hard_words"
    fell_back = bool(dropped) and expects_full_text
    translated = actual if fell_back else restore_math(result.translated_text, masked.spans)

    row = Translation(
        selection_id=selection.id,
        original=actual,
        translated=translated,
        style=payload.style,
        stage=payload.stage,
        math_placeholders=[
            {"token": s.token, "latex": s.latex, "display": s.display} for s in masked.spans
        ],
        generation_provider=result.provider,
        generation_model=result.model,
        prompt_version=result.prompt_version,
        input_hash=_sha256(f"{payload.style}|{payload.stage}|{masked.masked_text}"),
    )
    db.add(row)
    db.flush()

    return CreateTranslationResponse(
        translation=TranslationOut(
            id=row.id,
            selection_id=selection.id,
            original=actual,
            translated=translated,
            style=payload.style,
            stage=payload.stage,
            math_placeholders=[
                MathPlaceholderOut(token=s.token, latex=s.latex, display=s.display)
                for s in masked.spans
            ],
            generation=GenerationProvenanceOut(
                provider=result.provider,
                model=result.model,
                prompt_version=result.prompt_version,
                input_hash=row.input_hash,
                created_at=row.created_at or datetime.now(tz=UTC),
            ),
            created_at=row.created_at or datetime.now(tz=UTC),
            fell_back_to_original=fell_back,
        )
    )
