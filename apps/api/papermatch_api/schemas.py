"""Pydantic request/response models.

Field names are camelCase on the wire to match ``packages/shared-types`` while staying
snake_case in Python; ``alias_generator`` does the conversion in one place.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic.alias_generators import to_camel

from papermatch_api import vocab


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


def _in_vocab(key: str) -> Any:
    """Validator factory rejecting values outside a shared vocabulary.

    ``None`` passes through untouched so the same factory works for the optional fields
    of a PATCH body, where "absent" and "invalid" are different things.
    """

    def validate(value: str | None) -> str | None:
        if value is None:
            return None
        if not vocab.is_valid(key, value):
            allowed = ", ".join(vocab.values(key))
            raise ValueError(f"must be one of: {allowed}")
        return value

    return validate


# ------------------------------------------------------------------------ provenance


class SourceProvenanceOut(CamelModel):
    source_provider: str
    acquired_at: datetime
    source_url: str
    license_id: str | None
    license_url: str | None
    abstract_redistributable: bool
    cache_policy: str


class GenerationProvenanceOut(CamelModel):
    provider: str
    model: str
    prompt_version: str
    input_hash: str
    created_at: datetime


# ----------------------------------------------------------------------------- auth


class GuestAuthRequest(CamelModel):
    locale: str = "ja-JP"
    timezone: str = "Asia/Tokyo"


class UserSettingsOut(CamelModel):
    locale: str
    timezone: str
    color_scheme: str
    english_level: str
    math_level: str
    exploration: str
    translation_style: str
    initial_translation_stage: str
    metric_signature: str
    unit_system: str
    canvas_style: str
    reduce_motion: bool
    haptics_enabled: bool
    high_contrast: bool
    offline_prefetch_count: int
    reshow_after_days: int
    allow_selections_for_model_improvement: bool


class UserSettingsPatch(CamelModel):
    """Every field optional: PATCH updates only what is supplied."""

    locale: str | None = None
    timezone: str | None = None
    color_scheme: Literal["system", "light", "dark"] | None = None
    english_level: str | None = None
    math_level: str | None = None
    exploration: str | None = None
    translation_style: str | None = None
    initial_translation_stage: str | None = None
    metric_signature: str | None = None
    unit_system: str | None = None
    canvas_style: str | None = None
    reduce_motion: bool | None = None
    haptics_enabled: bool | None = None
    high_contrast: bool | None = None
    offline_prefetch_count: int | None = Field(default=None, ge=0, le=200)
    reshow_after_days: int | None = Field(default=None, ge=0, le=3650)
    allow_selections_for_model_improvement: bool | None = None

    _v_english = field_validator("english_level")(_in_vocab("englishLevel"))
    _v_math = field_validator("math_level")(_in_vocab("mathLevel"))
    _v_exploration = field_validator("exploration")(_in_vocab("explorationLevel"))
    _v_style = field_validator("translation_style")(_in_vocab("translationStyle"))
    _v_stage = field_validator("initial_translation_stage")(_in_vocab("translationStage"))
    _v_metric = field_validator("metric_signature")(_in_vocab("metricSignature"))
    _v_units = field_validator("unit_system")(_in_vocab("unitSystem"))
    _v_canvas = field_validator("canvas_style")(_in_vocab("canvasStyle"))


class InterestIn(CamelModel):
    field_id: str
    strength: float = Field(default=1.0, ge=0.0, le=1.0)
    mode: str = "main"

    _v_mode = field_validator("mode")(_in_vocab("interestMode"))


class InterestOut(CamelModel):
    field_id: str
    strength: float
    mode: str


class UpdateInterestsRequest(CamelModel):
    interests: list[InterestIn] = Field(max_length=200)


class UserOut(CamelModel):
    id: uuid.UUID
    is_guest: bool
    display_name: str | None
    created_at: datetime
    onboarding_completed_at: datetime | None
    settings: UserSettingsOut
    interests: list[InterestOut]


class AuthTokenResponse(CamelModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user: UserOut


# --------------------------------------------------------------------------- fields


class FieldLabel(CamelModel):
    en: str
    ja: str


class FieldOut(CamelModel):
    id: str
    parent_id: str | None
    label: FieldLabel
    color: str
    paper_count: int = 0


class FieldsResponse(CamelModel):
    fields: list[FieldOut]


# --------------------------------------------------------------------------- papers


class AuthorOut(CamelModel):
    name: str
    external_id: str | None = None
    affiliation: str | None = None


class PaperIdentifierOut(CamelModel):
    kind: str
    value: str


class AbstractSegmentOut(CamelModel):
    start: int
    end: int
    section: str
    detected_by: str
    confidence: float


class PaperOut(CamelModel):
    id: uuid.UUID
    canonical_id: str
    identifiers: list[PaperIdentifierOut]
    title: str
    abstract: str
    abstract_segments: list[AbstractSegmentOut] = Field(default_factory=list)
    authors: list[AuthorOut]
    year: int
    venue: str | None
    paper_types: list[str]
    primary_field_id: str | None
    field_weights: dict[str, float]
    open_access: str
    retraction_status: str
    version: str | None
    english_level: str
    math_density: float
    equation_count: int
    estimated_reading_minutes: float
    source_url: str
    pdf_url: str | None
    provenance: SourceProvenanceOut


class PaperListResponse(CamelModel):
    papers: list[PaperOut]
    next_cursor: str | None = None


# --------------------------------------------------------------------- translations


class SelectionIn(CamelModel):
    field: Literal["abstract", "title"] = "abstract"
    start: int = Field(ge=0)
    end: int = Field(gt=0)
    exact_text: str

    @field_validator("exact_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("selection must not be empty")
        return value

    @model_validator(mode="after")
    def _ordered_offsets(self) -> SelectionIn:
        if self.end <= self.start:
            raise ValueError("selection end must be greater than start")
        return self


class CreateTranslationRequest(CamelModel):
    paper_id: uuid.UUID
    selection: SelectionIn
    style: str = "natural"
    stage: str = "natural"

    _v_style = field_validator("style")(_in_vocab("translationStyle"))
    _v_stage = field_validator("stage")(_in_vocab("translationStage"))


class MathPlaceholderOut(CamelModel):
    token: str
    latex: str
    display: bool


class TranslationOut(CamelModel):
    id: uuid.UUID
    selection_id: uuid.UUID | None
    original: str
    translated: str
    style: str
    stage: str
    math_placeholders: list[MathPlaceholderOut]
    generation: GenerationProvenanceOut
    created_at: datetime
    #: True when the provider damaged a formula and the original was shown instead.
    fell_back_to_original: bool = False


class CreateTranslationResponse(CamelModel):
    translation: TranslationOut


# --------------------------------------------------------------------------- health


class ProviderHealthOut(CamelModel):
    healthy: bool
    detail: str | None = None


class DatabaseHealthOut(CamelModel):
    connected: bool
    migration_revision: str | None = None


class HealthResponse(CamelModel):
    status: Literal["ok", "degraded"]
    version: str
    providers: dict[str, ProviderHealthOut]
    database: DatabaseHealthOut


# ---------------------------------------------------------------------------- error


class ErrorBody(CamelModel):
    code: str
    message: str
    details: dict[str, list[str]] | None = None


class ErrorResponse(CamelModel):
    error: ErrorBody


def error_response(code: str, message: str, **details: Any) -> dict[str, Any]:
    body = ErrorResponse(error=ErrorBody(code=code, message=message, details=details or None))
    return body.model_dump(by_alias=True, exclude_none=True)
