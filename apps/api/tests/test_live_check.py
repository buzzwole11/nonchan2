"""The live-data check (spec sections 1-A, 29).

The pass itself needs the network; what is testable without it is the part that decides
what the operator is told. That matters more than it sounds: this command exists to be run
once, in an environment nobody has debugged yet, and its whole value is that a failure
names the step that failed rather than ending in an empty feed with four possible causes.

Driven here with the mock provider, which is exactly why `run_live_check` takes its
providers as an argument.
"""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from papermatch_api.models import Paper, User
from papermatch_api.providers.base import PaperQuery, ProviderHealth, ProviderUnavailable
from papermatch_api.providers.mock_paper import MockPaperProvider
from papermatch_api.services.ingestion import load_fields
from papermatch_api.services.live_check import TARGET_PAPERS, run_live_check
from tests.conftest import FIXTURES_DIR, requires_db

pytestmark = [pytest.mark.integration, requires_db]


class _Unreachable:
    """A provider that cannot be reached — the state this whole command exists to name."""

    name = "unreachable"

    # Signatures match `providers.base.PaperProvider` exactly. A double that invents an
    # extra parameter passes its own tests and proves nothing about the real call — which
    # is what happened here: the first version took a `cursor` the Protocol does not have,
    # and the resulting TypeError was reported as "unreachable".
    def search(self, query: PaperQuery) -> tuple[list, str | None]:  # type: ignore[type-arg]
        raise ProviderUnavailable("gateway answered 403 to CONNECT")

    def fetch(self, canonical_id: str):  # type: ignore[no-untyped-def]
        raise ProviderUnavailable("gateway answered 403 to CONNECT")

    def health(self) -> ProviderHealth:
        return ProviderHealth(name=self.name, healthy=False, detail="blocked")


class _Malformed(MockPaperProvider):
    """Reachable, but returning records with no abstract at all.

    The interesting failure: the network is fine and the *shape* has moved. A check that
    only pinged the host would call this a success and leave the corpus empty. Every
    record is stripped, not some — a few unusable records are normal and must not fail the
    check (see `_parses`).
    """

    name = "malformed"

    def search(self, query: PaperQuery) -> tuple[list, str | None]:  # type: ignore[type-arg]
        records, next_cursor = super().search(query)
        return [replace(record, abstract="") for record in records], next_cursor


def test_it_stops_before_ingesting_when_the_taxonomy_is_missing(db_session: Session) -> None:
    # Ingestion assigns papers to fields; running it first would produce a corpus with no
    # field weights and a feed with nothing to allocate between (spec section 16).
    report = run_live_check(db_session, {"mock": MockPaperProvider(Path(FIXTURES_DIR))})

    assert report.ok is False
    assert [step.name for step in report.steps] == ["分野タクソノミー"]
    assert "seed" in report.steps[0].detail


def test_an_unreachable_provider_is_named_as_unreachable(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)

    report = run_live_check(db_session, {"unreachable": _Unreachable()})

    assert report.ok is False
    failed = [step for step in report.steps if not step.ok]
    assert failed[0].name == "unreachable: 疎通"
    # The one thing an operator needs to be told here, because the setting is per-session.
    assert "セッション" in failed[0].detail
    # And nothing was ingested: the check stopped where it should have.
    assert db_session.execute(select(func.count()).select_from(Paper)).scalar_one() == 0


def test_a_reachable_provider_returning_unusable_records_fails_the_shape_step(
    db_session: Session,
) -> None:
    load_fields(db_session, FIXTURES_DIR)

    report = run_live_check(db_session, {"malformed": _Malformed(Path(FIXTURES_DIR))})

    assert report.ok is False
    names = [step.name for step in report.steps if not step.ok]
    # Reached, then refused — which is the distinction the two steps exist to draw.
    assert names == ["malformed: 形状"]
    assert "応答形状が変わった" in report.steps[-1].detail


def test_a_working_provider_ingests_and_builds_a_feed(db_session: Session) -> None:
    load_fields(db_session, FIXTURES_DIR)

    report = run_live_check(db_session, {"mock": MockPaperProvider(Path(FIXTURES_DIR))})

    names = [step.name for step in report.steps]
    assert names[:3] == ["分野タクソノミー", "mock: 疎通", "mock: 形状"]
    assert "取り込み" in names
    assert "フィード構成" in names


def test_the_hundred_paper_bar_is_reported_rather_than_assumed(db_session: Session) -> None:
    """Section 29 says 実データ100件以上. The corpus fixture has fewer, so this must say so.

    That is the point of the assertion: the check has to fail loudly on a corpus that is
    too small, rather than building a feed from 40 papers and calling the phase complete.
    """
    load_fields(db_session, FIXTURES_DIR)

    report = run_live_check(db_session, {"mock": MockPaperProvider(Path(FIXTURES_DIR))})

    feed_step = next(step for step in report.steps if step.name == "フィード構成")
    corpus = db_session.execute(select(func.count()).select_from(Paper)).scalar_one()
    if corpus < TARGET_PAPERS:
        assert feed_step.ok is False
        assert "100 件" in feed_step.detail
    else:
        assert feed_step.ok is True


def test_the_probe_reader_does_not_survive_the_check(db_session: Session) -> None:
    # A diagnostic must not leave accounts behind, and a feed built for a real reader
    # would record impressions against a library they did not ask us to touch.
    load_fields(db_session, FIXTURES_DIR)
    before = db_session.execute(select(func.count()).select_from(User)).scalar_one()

    run_live_check(db_session, {"mock": MockPaperProvider(Path(FIXTURES_DIR))})

    assert db_session.execute(select(func.count()).select_from(User)).scalar_one() == before
