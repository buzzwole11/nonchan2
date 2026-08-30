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
from papermatch_api.passwords import MIN_PASSWORD_LENGTH


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
    #: Section 26's プリセット.
    notification_preset: str


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
    notification_preset: str | None = None

    _v_english = field_validator("english_level")(_in_vocab("englishLevel"))
    _v_math = field_validator("math_level")(_in_vocab("mathLevel"))
    _v_exploration = field_validator("exploration")(_in_vocab("explorationLevel"))
    _v_style = field_validator("translation_style")(_in_vocab("translationStyle"))
    _v_stage = field_validator("initial_translation_stage")(_in_vocab("translationStage"))
    _v_notification = field_validator("notification_preset")(_in_vocab("notificationPreset"))
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


# ----------------------------------------------------------------------------- feed


class FeedItemOut(CamelModel):
    paper: PaperOut
    #: Vocabulary values from `feedReason` (spec section 6).
    reasons: list[str]
    #: Already localised short sentence. Never a bare score.
    reason_text: str
    position: int
    #: Which of the 70/20/10 pools this card came from (spec section 16).
    pool: str
    #: Score components, so a surprising ranking can be explained rather than guessed at.
    score_breakdown: dict[str, float]


class MathCardTeaserOut(CamelModel):
    """One maths card offered beside the feed (spec section 10).

    Not a `FeedItemOut`: it is a different kind of thing and must look like one. Carrying
    the paper's title is what lets the client say *why* this reader is seeing it — "from a
    paper you saved" — rather than presenting the card as an advertisement.
    """

    card_id: uuid.UUID
    card_type: str
    title: str
    level: str
    provenance_kind: str
    paper_id: uuid.UUID
    paper_title: str


class FeedResponse(CamelModel):
    items: list[FeedItemOut]
    next_cursor: str | None = None
    #: True when a provider was unavailable and this page is served from cache.
    degraded: bool = False
    #: At most one, first page only, at most every 7 days (spec section 10: 低頻度).
    math_card: MathCardTeaserOut | None = None


# ---------------------------------------------------------------------------- saved


class SavedPaperOut(CamelModel):
    paper_id: uuid.UUID
    reasons: list[str]
    status: str
    priority: int
    notes: str | None
    saved_at: datetime
    last_visited_at: datetime | None


class SavedEntryOut(CamelModel):
    saved_paper: SavedPaperOut
    paper: PaperOut


class SavedListResponse(CamelModel):
    saved: list[SavedEntryOut]
    next_cursor: str | None = None
    total: int


class SearchHitOut(CamelModel):
    """One row from the reader's library, with why it came back.

    `matchedField` exists for the same reason a feed card carries its reason (section 6):
    a hit whose cause is invisible looks like the search is guessing, and the reader cannot
    tell a title match from a word buried in an abstract.
    """

    saved_paper: SavedPaperOut
    paper: PaperOut
    matched_field: str


class SearchResponse(CamelModel):
    query: str
    hits: list[SearchHitOut]
    #: True when the query was empty — the client shows the library rather than "no results".
    empty_query: bool = False


class SavePaperRequest(CamelModel):
    reasons: list[str] = Field(default_factory=list, max_length=10)
    notes: str | None = Field(default=None, max_length=4000)

    @field_validator("reasons")
    @classmethod
    def _valid_reasons(cls, value: list[str]) -> list[str]:
        for reason in value:
            if not vocab.is_valid("saveReason", reason):
                raise ValueError(f"must be one of: {', '.join(vocab.values('saveReason'))}")
        return value


class UpdateSavedRequest(CamelModel):
    status: str | None = None
    reasons: list[str] | None = Field(default=None, max_length=10)
    notes: str | None = Field(default=None, max_length=4000)
    priority: int | None = Field(default=None, ge=0, le=100)

    _v_status = field_validator("status")(_in_vocab("savedStatus"))

    @field_validator("reasons")
    @classmethod
    def _valid_reasons(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        for reason in value:
            if not vocab.is_valid("saveReason", reason):
                raise ValueError(f"must be one of: {', '.join(vocab.values('saveReason'))}")
        return value


class SavedPaperResponse(CamelModel):
    saved_paper: SavedPaperOut
    paper: PaperOut


# ------------------------------------------------------------------ impressions/actions


class ImpressionIn(CamelModel):
    paper_id: uuid.UUID
    position: int = Field(default=0, ge=0)
    feed_context: str = Field(default="discover", max_length=64)
    dwell_ms: int | None = Field(default=None, ge=0, le=86_400_000)


class CreateImpressionsRequest(CamelModel):
    impressions: list[ImpressionIn] = Field(min_length=1, max_length=100)


class CreateImpressionsResponse(CamelModel):
    recorded: int


class CreateActionRequest(CamelModel):
    type: str
    paper_id: uuid.UUID | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    _v_type = field_validator("type")(_in_vocab("actionType"))


class ActionOut(CamelModel):
    id: uuid.UUID
    type: str
    paper_id: uuid.UUID | None
    created_at: datetime
    undone: bool
    undoes_action_id: uuid.UUID | None
    payload: dict[str, Any]


class ActionResponse(CamelModel):
    action: ActionOut
    #: Present when the action changed the saved library, so the client can update it
    #: without a second request.
    saved: SavedPaperOut | None = None


class UndoResponse(CamelModel):
    undo: ActionOut
    undone_action_id: uuid.UUID
    #: The paper is eligible for the feed again; the client can re-insert the card.
    restored_paper_id: uuid.UUID | None


# ------------------------------------------------------------------------ learning


class ExpressionOut(CamelModel):
    id: uuid.UUID
    kind: str
    phrase: str
    meaning: str
    examples: list[str]
    source_paper_id: uuid.UUID | None
    context: str | None
    created_at: datetime
    review_count: int
    last_reviewed_at: datetime | None
    next_review_at: datetime | None


class CreateExpressionRequest(CamelModel):
    phrase: str = Field(min_length=1, max_length=600)
    meaning: str = Field(default="", max_length=2000)
    #: Omitted means "work it out from the phrase" (word / collocation / pattern / sentence).
    kind: str | None = None
    #: The sentence it came from, so the entry keeps its context (spec section 9).
    context: str | None = Field(default=None, max_length=4000)
    source_paper_id: uuid.UUID | None = None
    example: str | None = Field(default=None, max_length=4000)

    _v_kind = field_validator("kind")(_in_vocab("expressionKind"))


class ExpressionListResponse(CamelModel):
    expressions: list[ExpressionOut]
    total: int
    #: How many are ready to be seen again right now.
    due_count: int


class ExpressionResponse(CamelModel):
    expression: ExpressionOut
    created: bool


class ReviewRequest(CamelModel):
    outcome: str

    _v_outcome = field_validator("outcome")(_in_vocab("reviewOutcome"))


class ReviewQueueResponse(CamelModel):
    """Spec section 9: 数日後に保存論文の表現を1件提示 — a nudge, not a queue to grind."""

    due: list[ExpressionOut]
    total_due: int


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


# ------------------------------------------------------------------------- equations


class EquationSymbolOut(CamelModel):
    """Spec section 10, 記号タップ: この論文での意味 / 一般的な意味 / 単位 / 適用スコープ."""

    symbol: str
    local_meaning: str
    general_meaning: str | None
    unit: str | None
    scope: str
    provenance_kind: str


class EquationOut(CamelModel):
    """Spec section 11: LaTeX is the record. There is no image field, by design.

    ``renderable`` is the server's verdict on whether this string may be handed to the
    WebView renderer. When it is false the client falls back to showing ``latex`` as
    source with a link to the paper, which is what section 11 prescribes — so the string
    travels either way, and the decision is not left to the client (section 25).
    """

    id: uuid.UUID
    paper_id: uuid.UUID
    latex: str
    equation_number: str | None
    section: str | None
    display: bool
    provenance_kind: str
    verification_status: str
    renderable: bool
    refusal_reasons: list[str]
    symbols: list[EquationSymbolOut]


class DerivationStepOut(CamelModel):
    """One transformation, with what is known about it attached.

    ``verificationStatus`` is not decoration: section 12 hides anything unverified by
    default, and ``evidence`` records which check produced the status so a reader can see
    what was actually done rather than trusting the word.
    """

    id: uuid.UUID
    from_equation_id: uuid.UUID
    to_equation_id: uuid.UUID
    latex: str
    operation: str
    rationale: str
    verification_status: str
    provenance_kind: str
    renderable: bool
    evidence: dict[str, Any] | None


class MathCardOut(CamelModel):
    card_type: str
    title: str
    level: str
    review_status: str
    provenance_kind: str
    body: dict[str, Any]
    id: uuid.UUID


class ReportRequest(CamelModel):
    """A reader saying something on a maths card looks wrong (spec sections 12, 27)."""

    reason: str
    #: Which part. Absent means the card as a whole; the two are mutually exclusive.
    step_id: uuid.UUID | None = None
    equation_id: uuid.UUID | None = None
    #: The reader's own words. A pointer, not a discussion.
    detail: str | None = Field(default=None, max_length=500)

    @field_validator("reason")
    @classmethod
    def _valid_reason(cls, value: str) -> str:
        if not vocab.is_valid("reportReason", value):
            raise ValueError(f"must be one of: {', '.join(vocab.values('reportReason'))}")
        return value


class ReportResponse(CamelModel):
    """What actually happened — not a promise that someone will look at it."""

    reason: str
    #: What the report was filed against, so the client can mark that control as reported.
    entity_type: str
    entity_id: uuid.UUID
    #: True when this replaced the reader's earlier report of the same problem.
    already_reported: bool


class MathCardDetailResponse(CamelModel):
    """Everything Focus Mode needs in one round trip (spec section 10).

    The tabs 記号 / 構造 / 導出 / 意味 are views onto the same fetched card, not separate
    requests: a tab that is empty for a beat after the tap undercuts the one thing this
    screen is for.
    """

    card: MathCardOut
    equations: list[EquationOut]
    steps: list[DerivationStepOut]
    #: Steps withheld because no check passed (spec section 12). Reported as a count so
    #: the UI can say that something exists rather than pretending the derivation is
    #: complete.
    hidden_step_count: int


class MathCardListResponse(CamelModel):
    cards: list[MathCardOut]
    total: int


class EquationListResponse(CamelModel):
    equations: list[EquationOut]


# ---------------------------------------------------------------- canvas (section 13)


class CanvasTileOut(CamelModel):
    """One tile on the plane.

    Carries the paper itself rather than only its id: the Canvas draws a title at close
    zoom and needs the field weights to colour the tile, and a second round trip per tile
    to fetch those would make the plane arrive in pieces.
    """

    entity_type: str
    entity_id: uuid.UUID
    x: float
    y: float
    cluster_id: str | None
    #: 0..1, already log-compressed (spec section 13: サイズは対数圧縮).
    weight: float
    #: True when the reader dragged this tile; a re-layout must not move it.
    user_override: bool
    #: When the reader saved it, for section 13's 年月スライダーで保存履歴を再生.
    saved_at: datetime
    #: For a `math_card` tile: the anchoring paper — the saved paper the card belongs to —
    #: so colour and cluster still come from the reader's own library. For a `paper` tile,
    #: simply the paper.
    paper: PaperOut
    #: Present only on `math_card` tiles (spec section 10: Canvas上の独立タイル).
    math_card: MathCardTeaserOut | None = None


class CanvasResponse(CamelModel):
    tiles: list[CanvasTileOut]
    #: Which placement algorithm produced these coordinates (section 13).
    layout_version: str


class PaperRelationOut(CamelModel):
    """One relation, with the evidence that produced it (spec section 17).

    `evidence` is not debug output. Section 17 requires citation direction, publication
    order, the mention and the model to be kept, and the client shows them: a reader told
    that one paper is foundational to another is entitled to see on what basis. `basis`
    names which rule fired, so the UI can say "cited in the references" rather than printing
    a confidence number at someone.
    """

    relation_type: str
    confidence: float
    #: Which kind of evidence produced the label: `citation`, `mention` or `similarity`.
    basis: str
    evidence: dict[str, Any]
    paper: PaperOut


class PaperRelationsResponse(CamelModel):
    paper_id: uuid.UUID
    relations: list[PaperRelationOut]


class ReadingStepOut(CamelModel):
    """One stop on a reading route (spec section 17).

    `labelKey` is an i18n key, never prose — section 25 keeps UI strings on the client.
    `held` is the load-bearing field: true means the app has this content, false means the
    step is "open the paper and look", and the client must not render the two the same way.
    """

    kind: str
    label_key: str
    held: bool
    section: str | None = None
    start: int | None = None
    end: int | None = None
    equation_id: uuid.UUID | None = None
    equation_number: str | None = None
    detail: str | None = None


class ReadingRouteOut(CamelModel):
    purpose: str
    steps: list[ReadingStepOut]
    #: What this route could not cover, so the client can say so instead of implying
    #: the route is the whole paper.
    missing: list[str]


class ReadingPathResponse(CamelModel):
    paper_id: uuid.UUID
    routes: list[ReadingRouteOut]


class EquationNodeOut(CamelModel):
    equation_id: uuid.UUID
    latex: str
    equation_number: str | None
    section: str | None
    provenance_kind: str
    verification_status: str


class EquationEdgeOut(CamelModel):
    """One dependency between equations, and what recorded it.

    `kind` is `defines` (a symbol used here was defined there) or `derives` (a transformation
    step). Nothing is inferred from two equations resembling each other — an edge is a
    mathematical claim, and sharing a letter is not evidence for one.
    """

    from_equation_id: uuid.UUID
    to_equation_id: uuid.UUID
    kind: str
    #: The symbol, for `defines`; the operation, for `derives`.
    label: str
    verification_status: str
    provenance_kind: str


class EquationGraphResponse(CamelModel):
    paper_id: uuid.UUID
    nodes: list[EquationNodeOut]
    edges: list[EquationEdgeOut]
    #: Equations with no edge, named so the client can say why they stand alone.
    isolated: list[uuid.UUID]


class RegisterRequest(CamelModel):
    """Attach a login to the guest account already in use (spec section 24)."""

    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=MIN_PASSWORD_LENGTH, max_length=200)
    display_name: str | None = Field(default=None, max_length=120)

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, value: str) -> str:
        # Not a full grammar — those reject valid addresses. Just enough to catch a
        # transposed field, which is the mistake that actually happens.
        if "@" not in value.strip(" "):
            raise ValueError("email must contain @")
        return value


class LoginRequest(CamelModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=200)


class MoveTileRequest(CamelModel):
    x: float
    y: float


class ExplanationItemOut(CamelModel):
    """One piece of Before-you-read or Why-it-matters material (spec section 8).

    `source` says where it came from — `abstract` and `taxonomy` are things we hold,
    `model` is generated. The distinction is carried per item rather than per section
    because the two arrive mixed: a term lifted from the abstract and a gloss written for it
    are different kinds of claim, and section 0 requires the reader to be able to tell.
    """

    kind: str
    title: str
    detail: str | None = None
    source: str = "model"
    field_id: str | None = None


class ExplanationSectionOut(CamelModel):
    kind: str
    #: Empty for `before_you_read`; one of section 8's four readings otherwise.
    audience: str = ""
    items: list[ExplanationItemOut] = []
    #: Why there is nothing here, when there is nothing here. Section 8's material is
    #: 強制表示しない, so an empty section is a normal outcome and the reason is what stops
    #: it reading as a fault.
    unavailable_reason: str | None = None
    #: Always `ai_explanation`. Sent so the client never has to infer it from the endpoint.
    provenance_kind: str = "ai_explanation"
    generation_provider: str = ""
    generation_model: str = ""
    prompt_version: str = ""


class PaperExplanationResponse(CamelModel):
    paper_id: uuid.UUID
    before_you_read: ExplanationSectionOut
    why_it_matters: list[ExplanationSectionOut]


class NotificationOut(CamelModel):
    """One inbox entry (spec section 26). Written under the reader's preset; see
    `services/notification_inbox`."""

    id: uuid.UUID
    category: str
    title: str
    body: str
    entity_type: str | None
    entity_id: str | None
    created_at: datetime
    read_at: datetime | None


class NotificationListResponse(CamelModel):
    notifications: list[NotificationOut]
    #: For the tab badge — computed server-side so every client agrees.
    unread_count: int
