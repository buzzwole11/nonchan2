"""Searching the saved library (spec sections 2, 14, 24).

The library is small, so "does it find the row" is the easy half. The tests that matter are
the ones about what a search must never do: reach into another reader's library, treat a
reader's punctuation as a wildcard, or return a hit with no visible reason for it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.orm import Session

from papermatch_api.models import Paper, SavedPaper, User
from papermatch_api.services.search import search_library
from tests.conftest import requires_db

pytestmark = [pytest.mark.integration, requires_db]


def _paper(
    session: Session,
    *,
    slug: str,
    title: str = "A Paper",
    abstract: str = "Nothing in particular.",
    authors: list[dict[str, Any]] | None = None,
    venue: str | None = None,
) -> Paper:
    row = Paper(
        canonical_id=f"test:{slug}",
        title=title,
        normalized_title=title.lower(),
        abstract=abstract,
        authors=authors if authors is not None else [{"name": "A. Nonymous"}],
        year=2024,
        venue=venue,
        source_provider="mock",
        source_url=f"https://example.invalid/{slug}",
        acquired_at=datetime.now(tz=UTC),
    )
    session.add(row)
    session.flush()
    return row


def _user(session: Session) -> User:
    row = User(is_guest=True)
    session.add(row)
    session.flush()
    return row


def _save(session: Session, user: User, paper: Paper, *, notes: str | None = None, age: int = 0):  # type: ignore[no-untyped-def]
    row = SavedPaper(
        user_id=user.id,
        paper_id=paper.id,
        reasons=["interesting"],
        status="unread",
        notes=notes,
        saved_at=datetime.now(tz=UTC) - timedelta(minutes=age),
    )
    session.add(row)
    session.flush()
    return row


def _auth(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


@pytest.fixture
def reader(db_session: Session) -> User:
    return _user(db_session)


# ------------------------------------------------------------------ what it finds


def test_it_matches_a_title_word(db_session: Session, reader: User) -> None:
    paper = _paper(db_session, slug="a", title="Thresholds for Sparse Subgraphs")
    _save(db_session, reader, paper)

    hits = search_library(db_session, reader, "sparse")

    assert [hit.paper.id for hit in hits] == [paper.id]
    assert hits[0].matched == "title"


def test_it_matches_an_author_inside_the_json_array(db_session: Session, reader: User) -> None:
    paper = _paper(
        db_session,
        slug="b",
        authors=[{"name": "R. Okamoto"}, {"name": "M. Zubkov"}],
    )
    _save(db_session, reader, paper)

    hits = search_library(db_session, reader, "zubkov")

    assert [hit.paper.id for hit in hits] == [paper.id]
    assert hits[0].matched == "author"


def test_it_matches_a_japanese_note(db_session: Session, reader: User) -> None:
    """The reason this is `ILIKE` and not `to_tsvector` — see `services/search.py`.

    A Japanese note is one unsegmented run of characters, so a full-text index would store
    it as a single token and 「測度」 would not match 「集中不等式の測度論的な背景」.
    """
    paper = _paper(db_session, slug="c")
    _save(db_session, reader, paper, notes="集中不等式の測度論的な背景をあとで読む")

    hits = search_library(db_session, reader, "測度")

    assert [hit.paper.id for hit in hits] == [paper.id]
    assert hits[0].matched == "note"


def test_it_matches_regardless_of_case(db_session: Session, reader: User) -> None:
    paper = _paper(db_session, slug="d", title="Celestial Amplitudes")
    _save(db_session, reader, paper)

    assert len(search_library(db_session, reader, "CELESTIAL")) == 1


def test_an_empty_query_returns_nothing_rather_than_everything(
    db_session: Session, reader: User
) -> None:
    """Blank is "not asked yet", not "match all" — the endpoint says so separately."""
    _save(db_session, reader, _paper(db_session, slug="e"))

    assert search_library(db_session, reader, "") == []
    assert search_library(db_session, reader, "   ") == []


# ------------------------------------------------------------------ what it must not do


def test_it_never_returns_another_readers_library(db_session: Session, reader: User) -> None:
    other = _user(db_session)
    paper = _paper(db_session, slug="f", title="Private Reading")
    _save(db_session, other, paper)

    assert search_library(db_session, reader, "private") == []


def test_it_never_returns_an_unsaved_paper(db_session: Session, reader: User) -> None:
    """Search covers the library, not the corpus. A paper nobody saved is not a result."""
    _paper(db_session, slug="g", title="Unsaved But Matching")

    assert search_library(db_session, reader, "unsaved") == []


def test_an_underscore_is_a_character_and_not_a_wildcard(db_session: Session, reader: User) -> None:
    """Unescaped, `_` matches any single character and every row comes back."""
    subscripted = _paper(db_session, slug="h", title="Bounds on n_max")
    _save(db_session, reader, subscripted)
    _save(db_session, reader, _paper(db_session, slug="i", title="Bounds on the Diameter"))

    hits = search_library(db_session, reader, "n_max")

    assert [hit.paper.id for hit in hits] == [subscripted.id]


def test_a_percent_is_a_character_and_not_a_wildcard(db_session: Session, reader: User) -> None:
    literal = _paper(db_session, slug="j", title="A 40% Improvement")
    _save(db_session, reader, literal)
    _save(db_session, reader, _paper(db_session, slug="k", title="No Numbers Here"))

    hits = search_library(db_session, reader, "40%")

    assert [hit.paper.id for hit in hits] == [literal.id]


def test_a_bare_percent_does_not_match_everything(db_session: Session, reader: User) -> None:
    _save(db_session, reader, _paper(db_session, slug="l", title="Plain"))

    assert search_library(db_session, reader, "%") == []


def test_a_backslash_does_not_break_the_pattern(db_session: Session, reader: User) -> None:
    r"""A reader pasting `\alpha` out of a formula must not get a database error."""
    paper = _paper(db_session, slug="m", abstract=r"We bound \alpha from below.")
    _save(db_session, reader, paper)

    assert [hit.paper.id for hit in search_library(db_session, reader, r"\alpha")] == [paper.id]


# ------------------------------------------------------------------ how it ranks


def test_a_title_hit_outranks_an_abstract_hit(db_session: Session, reader: User) -> None:
    """Section 6's rule that a card says why it is there applies to a search result too."""
    in_abstract = _paper(db_session, slug="n", abstract="A study of percolation thresholds.")
    in_title = _paper(db_session, slug="o", title="Percolation on Trees")
    _save(db_session, reader, in_abstract)
    _save(db_session, reader, in_title)

    hits = search_library(db_session, reader, "percolation")

    assert [hit.matched for hit in hits] == ["title", "abstract"]
    assert hits[0].paper.id == in_title.id


def test_equal_matches_put_the_newest_save_first(db_session: Session, reader: User) -> None:
    older = _paper(db_session, slug="p", title="Entropy Bounds I")
    newer = _paper(db_session, slug="q", title="Entropy Bounds II")
    _save(db_session, reader, older, age=60)
    _save(db_session, reader, newer, age=1)

    hits = search_library(db_session, reader, "entropy bounds")

    assert [hit.paper.id for hit in hits] == [newer.id, older.id]


def test_the_limit_is_applied_after_ranking(db_session: Session, reader: User) -> None:
    """Truncating before the sort would drop the title hit and keep the abstract ones."""
    for index in range(5):
        paper = _paper(db_session, slug=f"r{index}", abstract="Discussion of martingales.")
        _save(db_session, reader, paper, age=index + 10)
    titled = _paper(db_session, slug="s", title="Martingales in Practice")
    _save(db_session, reader, titled, age=100)

    hits = search_library(db_session, reader, "martingales", limit=1)

    assert [hit.paper.id for hit in hits] == [titled.id]


# ------------------------------------------------------------------ through the endpoint


def test_the_endpoint_reports_an_empty_query_as_such(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/search", params={"q": "  "}, headers=_auth(client))

    assert response.status_code == 200
    body = response.json()
    assert body["emptyQuery"] is True
    assert body["hits"] == []


def test_the_endpoint_returns_the_matched_field(client, db_session: Session) -> None:  # type: ignore[no-untyped-def]
    headers = _auth(client)
    paper = _paper(db_session, slug="t", title="Kagome Lattices")
    client.post(f"/saved/{paper.id}", json={"reasons": ["interesting"]}, headers=headers)

    body = client.get("/search", params={"q": "kagome"}, headers=headers).json()

    assert body["emptyQuery"] is False
    assert [hit["matchedField"] for hit in body["hits"]] == ["title"]
    assert body["hits"][0]["paper"]["title"] == "Kagome Lattices"


def test_the_endpoint_rejects_an_absurdly_long_query(client) -> None:  # type: ignore[no-untyped-def]
    response = client.get("/search", params={"q": "x" * 5000}, headers=_auth(client))

    assert response.status_code == 422
