"""Before you read, and Why it matters (spec section 8).

Section 8 asks for two kinds of help around an abstract, and ends both with AI生成である
ことを明示する. This is where they are produced, cached and labelled.

**Cached on the input, not on the paper.** The key is a hash of exactly what was sent —
title, abstract, field, audience — together with the provider, model and prompt version. A
paper whose abstract is corrected gets a new explanation rather than keeping one written
about text that no longer exists, and a changed prompt adds rows rather than overwriting
ones a reader may already have seen.

**A provider failure is an absent section, never an error page.** Section 8 says this
material is 強制表示しない, so the paper is fully readable without it. A model that is down,
unconfigured, or unwilling to answer produces the same shape as one that answered: an empty
list with a reason. The reader is told the explanation is not available; they are never told
the app is broken, because it is not.

**Nothing here is ever `original`.** `provenance_kind` is fixed at `ai_explanation` on the
column and again here. Section 0 requires the distinction between the paper's own words and
a machine's to survive in the data model, and a column that could be set to something else
by a future caller would not.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from dataclasses import field as dataclass_field
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AbstractExplanation, Field, Paper
from papermatch_api.providers.base import ExplanationProvider, ProviderUnavailable

__all__ = [
    "AUDIENCES",
    "ExplanationResult",
    "before_you_read",
    "explanation_input",
    "input_hash",
    "why_it_matters",
]

#: Section 8's four readings, in the order the section lists them. The order is the reading
#: order in the UI, so it is fixed here rather than left to whatever the database returns.
AUDIENCES: tuple[str, ...] = ("beginner", "researcher", "application", "field_history")


@dataclass
class ExplanationResult:
    """One section's worth of explanation, and what to say when there is none."""

    kind: str
    audience: str
    items: list[dict[str, Any]] = dataclass_field(default_factory=list)
    unavailable_reason: str | None = None
    #: Always `ai_explanation`. Carried in the response so the client does not have to know
    #: which endpoints happen to return generated text (spec section 0).
    provenance_kind: str = "ai_explanation"
    generation_provider: str = ""
    generation_model: str = ""
    prompt_version: str = ""


def explanation_input(session: Session, paper: Paper, audience: str = "") -> dict[str, Any]:
    """Exactly what a provider is given — and, hashed, exactly what the cache is keyed on.

    The paper's own public metadata and nothing about the reader. Section 25 asks for
    送信内容の最小化, and who is asking makes no difference to what an abstract says.
    """
    field_label: str | None = None
    parent_label: str | None = None
    parent_id: str | None = None
    if paper.primary_field_id is not None:
        row = session.get(Field, paper.primary_field_id)
        if row is not None:
            field_label = row.label_en
            parent_id = row.parent_id
            if row.parent_id is not None:
                parent = session.get(Field, row.parent_id)
                parent_label = None if parent is None else parent.label_en

    return {
        "title": paper.title,
        "abstract": paper.abstract,
        "fieldId": paper.primary_field_id,
        "fieldLabel": field_label,
        "parentFieldId": parent_id,
        "parentFieldLabel": parent_label,
        "audience": audience,
    }


def input_hash(payload: dict[str, Any], *, provider: str, model: str, prompt_version: str) -> str:
    """A stable fingerprint of the request.

    The provider, model and prompt version are inside the hash rather than beside it: the
    same abstract explained by two different models is two different explanations, and a
    cache that ignored that would serve one under the other's label.
    """
    material = json.dumps(
        {"payload": payload, "provider": provider, "model": model, "prompt": prompt_version},
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _prompt_version(provider: ExplanationProvider) -> str:
    # Read from the module the provider came from rather than from configuration, because
    # the version has to change when the prompt does, and only the prompt's own module can
    # know that.
    module = type(provider).__module__
    from importlib import import_module

    return str(getattr(import_module(module), "PROMPT_VERSION", "unknown"))


def _generate(
    session: Session,
    provider: ExplanationProvider,
    paper: Paper,
    kind: str,
    audience: str,
) -> ExplanationResult:
    payload = explanation_input(session, paper, audience)
    provider_name = getattr(provider, "name", "unknown")
    model = str(getattr(provider, "model", "unknown"))
    prompt_version = _prompt_version(provider)
    digest = input_hash(payload, provider=provider_name, model=model, prompt_version=prompt_version)

    existing = session.execute(
        select(AbstractExplanation).where(
            AbstractExplanation.paper_id == paper.id,
            AbstractExplanation.kind == kind,
            AbstractExplanation.audience == audience,
            AbstractExplanation.prompt_version == prompt_version,
            AbstractExplanation.input_hash == digest,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return _as_result(existing)

    try:
        answer = provider.explain(kind, payload)
    except ProviderUnavailable as exc:
        # Not stored. A provider being down is a fact about today, and writing it into the
        # cache would mean the reader kept being told the explanation is unavailable long
        # after it became available.
        return ExplanationResult(
            kind=kind,
            audience=audience,
            unavailable_reason=f"説明モデルに接続できませんでした（{exc}）",
            generation_provider=provider_name,
            generation_model=model,
            prompt_version=prompt_version,
        )

    items = answer.get("items")
    row = _upsert(
        session,
        paper=paper,
        kind=kind,
        audience=audience,
        items=list(items) if isinstance(items, list) else [],
        unavailable_reason=answer.get("unavailableReason"),
        provider=provider_name,
        # The provider may report the model it actually used, which is what has to be
        # recorded — `model` above is what we asked for.
        model=str(answer.get("model") or model),
        prompt_version=prompt_version,
        digest=digest,
    )
    return _as_result(row)


def _upsert(
    session: Session,
    *,
    paper: Paper,
    kind: str,
    audience: str,
    items: list[dict[str, Any]],
    unavailable_reason: Any,
    provider: str,
    model: str,
    prompt_version: str,
    digest: str,
) -> AbstractExplanation:
    """Write the row for this (paper, kind, audience, prompt version).

    Replaces rather than adds when the same prompt version produced a different answer from
    changed input — the unique constraint says one answer per prompt version, and two would
    mean the reader could be shown either.
    """
    row = session.execute(
        select(AbstractExplanation).where(
            AbstractExplanation.paper_id == paper.id,
            AbstractExplanation.kind == kind,
            AbstractExplanation.audience == audience,
            AbstractExplanation.prompt_version == prompt_version,
        )
    ).scalar_one_or_none()
    if row is None:
        row = AbstractExplanation(paper_id=paper.id, kind=kind, audience=audience)
        session.add(row)

    row.items = items
    row.unavailable_reason = str(unavailable_reason) if unavailable_reason else None
    row.provenance_kind = "ai_explanation"
    row.generation_provider = provider
    row.generation_model = model
    row.prompt_version = prompt_version
    row.input_hash = digest
    session.flush()
    return row


def _as_result(row: AbstractExplanation) -> ExplanationResult:
    return ExplanationResult(
        kind=row.kind,
        audience=row.audience,
        items=list(row.items),
        unavailable_reason=row.unavailable_reason,
        provenance_kind=row.provenance_kind,
        generation_provider=row.generation_provider,
        generation_model=row.generation_model,
        prompt_version=row.prompt_version,
    )


def before_you_read(
    session: Session, provider: ExplanationProvider, paper: Paper
) -> ExplanationResult:
    """Background knowledge and technical terms, before the reader starts (spec section 8)."""
    return _generate(session, provider, paper, "before_you_read", "")


def why_it_matters(
    session: Session, provider: ExplanationProvider, paper: Paper
) -> list[ExplanationResult]:
    """All four of section 8's readings, in the order the section lists them.

    Each is fetched separately, and one that comes back empty does not suppress the others:
    a paper can genuinely have nothing to say to a practitioner while having a great deal to
    say to a researcher, and collapsing that into "no explanation" loses the true half.
    """
    return [
        _generate(session, provider, paper, "why_it_matters", audience) for audience in AUDIENCES
    ]


def stored_for(session: Session, paper_id: uuid.UUID) -> list[AbstractExplanation]:
    """Everything already generated for a paper, for the audit trail and for deletion."""
    return list(
        session.execute(
            select(AbstractExplanation).where(AbstractExplanation.paper_id == paper_id)
        ).scalars()
    )
