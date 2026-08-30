"""Whether a paper's body may enter the maths pipeline at all (spec sections 12, 21).

Section 21 states the rule without qualification: **ライセンス不明の本文断片を数式カード化
しない**. Section 12 says the same thing from the other side — the pipeline's input is
限定 to documents whose terms have been checked. So this module is a gate, and everything
downstream of it assumes the gate said yes.

**Refusal is the default.** The decision is not "is there anything forbidding this" but
"is there something permitting this". A licence nobody recognised, a licence field the
provider left empty, a record with no source URL to check the claim against — all no. That
ordering matters because the failure is silent in the wrong direction: a card built from a
body we had no right to parse looks exactly like a card built from one we did.

**A permissive metadata licence is not a permissive body licence.** arXiv's metadata is
CC0; the manuscript is under the author's chosen licence, which for the majority of arXiv
papers is arXiv's non-exclusive distribution licence. That licence lets arXiv distribute
the paper. It does not let us parse the source and republish derived formulas. It is
listed below as explicitly *refused* rather than left unknown, because "unknown" invites
someone to go and look it up and conclude it is fine.

**What "yes" permits is still narrow.** A permitted licence lets the pipeline read the body
and build cards whose formulas carry `provenance_kind='original'` and a link to the source.
It is not permission to store the body indefinitely or to show it as running text; those
are separate questions this gate does not answer.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from papermatch_api.models import AuditLog, Paper, PaperFullText
from papermatch_api.providers.base import FullTextProvider, FullTextRecord

__all__ = [
    "PERMITTED_LICENSES",
    "REFUSED_LICENSES",
    "FullTextReport",
    "LicenceDecision",
    "licence_decision",
    "load_full_texts",
    "may_build_math_cards",
    "store_full_text",
    "stored_body",
]

#: Licences whose terms permit parsing the body and publishing derived formulas with
#: attribution. Deliberately short: every entry here is a claim we are prepared to defend,
#: and a longer list is not a better one.
PERMITTED_LICENSES: frozenset[str] = frozenset(
    {
        "CC0-1.0",
        "CC-BY-4.0",
        "CC-BY-3.0",
        "CC-BY-SA-4.0",
        "CC-BY-SA-3.0",
    }
)

#: Named so the refusal can say *why* rather than "unknown licence". A reader — or a
#: maintainer wondering whether to add one to the list above — is better served by
#: "this licence forbids it" than by silence.
REFUSED_LICENSES: dict[str, str] = {
    # Redistribution rights granted to arXiv, not to us. The single most common licence on
    # arXiv, and the one most likely to be mistaken for permission.
    "arXiv-1.0": (
        "arXiv の非独占ライセンスは arXiv に配布を許すもので、第三者による再利用を許可していない"
    ),
    "arXiv-perpetual-1.0": "同上（永続版）",
    # NoDerivatives forbids the derived content this pipeline exists to produce.
    "CC-BY-ND-4.0": "改変禁止のため、変形や導出の生成ができない",
    "CC-BY-NC-ND-4.0": "改変禁止のため、変形や導出の生成ができない",
    # NonCommercial is not a refusal in itself, but this product has a commercial path
    # (section 21: 商用化前に利用規約と権利を個別確認), and a licence that would have to be
    # re-examined at that point is one to exclude now rather than to unwind later.
    "CC-BY-NC-4.0": "非商用限定のため、商用化時に作り直しが必要になる（仕様書 21 節）",
    "CC-BY-NC-SA-4.0": "非商用限定のため、商用化時に作り直しが必要になる（仕様書 21 節）",
}

#: Section 12 accepts LaTeX source or structured XML. Anything else — a PDF, or extracted
#: plain text — has already lost the equation markup the pipeline needs, so accepting it
#: would mean guessing at the maths.
SUPPORTED_FORMATS: frozenset[str] = frozenset({"latex", "jats_xml"})


@dataclass(frozen=True)
class LicenceDecision:
    """Whether the body may be used, and the reason either way.

    The reason is kept even when the answer is yes, because it is what gets written to the
    audit log: "permitted under CC-BY-4.0" is checkable later, "permitted" is not.
    """

    permitted: bool
    #: Machine-readable, for the audit log and for metrics.
    code: str
    #: Japanese, for a maintainer reading the log.
    reason: str
    license_id: str | None = None


def licence_decision(record: FullTextRecord | None) -> LicenceDecision:
    """Decide whether ``record``'s body may be parsed into maths cards."""
    if record is None:
        return LicenceDecision(False, "no_source", "本文を取得できなかった")

    if record.body_format not in SUPPORTED_FORMATS:
        return LicenceDecision(
            False,
            "unsupported_format",
            f"{record.body_format} は構造化本文ではないため、数式の抽出が推測になる",
            record.license_id,
        )

    if not record.body.strip():
        return LicenceDecision(False, "empty_body", "本文が空", record.license_id)

    if not record.source_url.strip():
        # Section 21 requires 原文リンクを明示 for anything shown to a reader. A record we
        # cannot link back to cannot satisfy that, whatever its licence says.
        return LicenceDecision(
            False, "no_source_url", "原文リンクが無いため出典を明示できない", record.license_id
        )

    licence = (record.license_id or "").strip()
    if not licence:
        return LicenceDecision(
            False, "unknown_licence", "ライセンス不明（仕様書 21 節により対象外）", None
        )

    if licence in REFUSED_LICENSES:
        return LicenceDecision(False, "refused_licence", REFUSED_LICENSES[licence], licence)

    if licence not in PERMITTED_LICENSES:
        # Not on either list. Unrecognised is refused, not investigated at runtime: the
        # decision of whether a licence permits this belongs to a person reading it once,
        # not to a string comparison guessing.
        return LicenceDecision(
            False, "unrecognised_licence", f"未検討のライセンス（{licence}）", licence
        )

    return LicenceDecision(True, "permitted", f"{licence} により許諾", licence)


def may_build_math_cards(record: FullTextRecord | None) -> bool:
    """Shorthand for callers that do not need the reason."""
    return licence_decision(record).permitted


# ------------------------------------------------------------------ storage
#
# Everything above decides *whether* a body may be used. What follows keeps the ones that
# may, so section 17's mention extraction has a text to read.


def store_full_text(
    session: Session, paper: Paper, record: FullTextRecord | None
) -> PaperFullText | None:
    """Keep this body, if the licence permits it. Returns None when it does not.

    **Refusing is silent to the caller but not to the log.** `licence_decision` produces a
    reason either way, and the caller writes it to the audit trail — "we have no body for
    this paper" and "we were not allowed to keep one" are different facts and the second is
    the one somebody will need to explain later.

    A refused paper also has any *existing* row removed. A licence can change from permissive
    to unknown between fetches (a paper is republished, a manifest is corrected), and leaving
    the old body behind would mean the gate had been passed once and never again.
    """
    decision = licence_decision(record)
    existing = session.get(PaperFullText, paper.id)

    if not decision.permitted or record is None or decision.license_id is None:
        if existing is not None:
            session.delete(existing)
            session.flush()
        return None

    if existing is None:
        existing = PaperFullText(paper_id=paper.id)
        session.add(existing)

    existing.body_format = record.body_format
    existing.body = record.body
    existing.license_id = decision.license_id
    existing.license_url = record.license_url
    existing.source_url = record.source_url
    existing.version = record.version
    existing.retrieved_at = record.retrieved_at
    session.flush()
    return existing


def stored_body(session: Session, paper_id: uuid.UUID) -> str | None:
    """The stored body, or None. None means "no body", never "no permission" — that
    distinction lives in the audit log, because a caller that could tell them apart here
    would leak the licence state of papers it is not otherwise entitled to know about."""
    row = session.get(PaperFullText, paper_id)
    return None if row is None else row.body


@dataclass
class FullTextReport:
    """What one pass over the corpus did, in the terms an operator asks about."""

    stored: int = 0
    #: The provider had nothing for this paper. Not a licence problem.
    unavailable: int = 0
    #: The provider had a body and the gate refused it, counted by `LicenceDecision.code`.
    refused: dict[str, int] = field(default_factory=dict)


def load_full_texts(
    session: Session, provider: FullTextProvider, *, limit: int | None = None
) -> FullTextReport:
    """Fetch and store every body the licence permits, for the papers already ingested.

    **Every refusal is written to the audit log with its reason.** Section 21 requires the
    licence decision to be answerable later, and a body that is simply missing from the table
    cannot say whether it was never offered or was offered and declined. The permitted case
    is logged too, for the same reason: "permitted under CC-BY-4.0" is checkable, a row with
    no explanation is not.

    Idempotent — `store_full_text` replaces the row for a paper rather than adding one — so
    this can be re-run after the fixtures change.
    """
    report = FullTextReport()
    statement = select(Paper).order_by(Paper.acquired_at.asc())
    if limit is not None:
        statement = statement.limit(limit)

    for paper in session.execute(statement).scalars():
        record = provider.fetch_source(paper.canonical_id)
        decision = licence_decision(record)
        stored = store_full_text(session, paper, record)

        if stored is not None:
            report.stored += 1
        elif record is None:
            report.unavailable += 1
        else:
            report.refused[decision.code] = report.refused.get(decision.code, 0) + 1

        if record is not None:
            session.add(
                AuditLog(
                    kind="fulltext.licence_decision",
                    actor="system",
                    entity_type="paper",
                    entity_id=str(paper.id),
                    detail={
                        "canonicalId": paper.canonical_id,
                        "permitted": decision.permitted,
                        "code": decision.code,
                        "reason": decision.reason,
                        "licenseId": decision.license_id,
                        "provider": getattr(provider, "name", "unknown"),
                    },
                )
            )

    session.flush()
    return report
