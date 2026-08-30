"""Searching what the reader has already saved (spec sections 2, 14, 24).

**This searches the reader's library, not the corpus.** Every mention of search in the spec
points the same way: section 2's fifth job is 保存した論文を後から検索し、学習素材として再利用
したい, section 14 describes the Library View as 検索・管理に適した整然UI, and section 1 pairs
it with Canvas over 保存データ. Nothing anywhere asks for a box that queries every paper.

That is a product decision and not an omission. Section 16 makes discovery a *feed* —
70/20/10, diversity control, reasons on every card — and a search-the-world box is the
thing people reach for instead. Adding one would quietly replace the mechanism the app is
built around with the one every other tool already has. If corpus search is ever wanted it
should be a deliberate second feature, not a side effect of this one.

**Substring matching, not full-text.** PostgreSQL's `to_tsvector` is the better tool for
English prose at scale, and the wrong tool here for two reasons. A personal library is
hundreds of rows, not millions. And the text is mixed: the abstract is English but the notes
a reader writes are Japanese, which `to_tsvector` cannot segment — 「量子」 inside a longer
Japanese note would simply not match. `ILIKE` finds it.

**The embeddings are not used either.** They are hashed bag-of-words (D-016): a two-word
query produces a nearly empty vector, so semantic search over it would rank worse than
substring matching while looking cleverer.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Text, case, cast, func, or_, select
from sqlalchemy.orm import Session

from papermatch_api.models import Paper, SavedPaper, User

__all__ = ["MAX_QUERY_LENGTH", "SearchHit", "search_library"]

#: Long enough for a title, short enough that nobody pastes an abstract in and asks the
#: database to scan for it.
MAX_QUERY_LENGTH = 200

#: Which field matched, strongest first. The reader is told *why* a row came back for the
#: same reason a feed card carries its reason (section 6): a hit with no visible cause looks
#: like the search is guessing.
FIELD_RANK = ("title", "author", "venue", "note", "abstract")


@dataclass(frozen=True)
class SearchHit:
    saved: SavedPaper
    paper: Paper
    #: The field that matched most strongly, from `FIELD_RANK`.
    matched: str


def _escape(term: str) -> str:
    """Make a user's text safe to put inside a LIKE pattern.

    `%` and `_` are wildcards. A reader searching for `O(n_max)` means those characters
    literally, and without escaping the `_` silently matches any character — the search
    quietly returns more than was asked for, which is worse than returning nothing.
    """
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search_library(session: Session, user: User, query: str, *, limit: int = 30) -> list[SearchHit]:
    """Rows from this reader's library that mention the query.

    Scoped to `user` in the query itself rather than filtered afterwards: a search that
    fetched everything and then removed other people's rows is one refactor away from
    forgetting to.
    """
    term = query.strip()
    if not term:
        return []
    pattern = f"%{_escape(term.lower())}%"

    # `authors` is JSON; cast to text so a name is searchable without unpacking the array.
    # It means a query can technically match a JSON key, but the keys are `name`/`orcid`
    # and a reader searching for "name" gets their own papers back, which is harmless.
    columns = {
        "title": func.lower(Paper.title),
        "author": func.lower(cast(Paper.authors, Text)),
        "venue": func.lower(func.coalesce(Paper.venue, "")),
        "note": func.lower(func.coalesce(SavedPaper.notes, "")),
        "abstract": func.lower(Paper.abstract),
    }
    matches = {name: column.like(pattern, escape="\\") for name, column in columns.items()}

    # The rank is computed in SQL, not in Python, because `LIMIT` happens in SQL. Ranking
    # afterwards lets the database choose which rows to keep in whatever order it likes: a
    # title hit gets dropped in favour of an abstract hit, and the survivors are then
    # "sorted" so the abstract hit sits first. The order looks correct and the best row is
    # simply absent — which is why this is ordered before it is truncated.
    rank = case(
        *((matches[name], index) for index, name in enumerate(FIELD_RANK[:-1])),
        else_=len(FIELD_RANK) - 1,
    )

    rows = session.execute(
        select(SavedPaper, Paper, rank.label("rank"))
        .join(Paper, Paper.id == SavedPaper.paper_id)
        .where(SavedPaper.user_id == user.id, or_(*matches.values()))
        .order_by(rank.asc(), SavedPaper.saved_at.desc())
        .limit(limit)
    ).all()

    return [
        SearchHit(saved=saved, paper=paper, matched=FIELD_RANK[matched_rank])
        for saved, paper, matched_rank in rows
    ]
