"""Signing in (spec section 24), and the notification schedule (section 26).

The login tests are almost all about what the endpoint refuses to tell you. A login form
that answers "no such account" differently from "wrong password" is a way of finding out who
reads what, which is a fact about someone that they did not publish.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from papermatch_api.passwords import hash_password, verify_password
from tests.conftest import requires_db

PASSWORD = "correct horse battery"


def _guest(client: TestClient) -> dict[str, str]:
    response = client.post("/auth/guest", json={"locale": "ja-JP", "timezone": "Asia/Tokyo"})
    return {"Authorization": f"Bearer {response.json()['accessToken']}"}


# ------------------------------------------------------------------ hashing


def test_a_password_never_appears_in_its_own_hash() -> None:
    stored = hash_password(PASSWORD)

    assert PASSWORD not in stored
    assert stored.startswith("scrypt$")


def test_two_hashes_of_the_same_password_differ() -> None:
    # A fresh salt each time, so a leak cannot be read as "these two people chose the same
    # password" — which is itself a fact worth not leaking.
    assert hash_password(PASSWORD) != hash_password(PASSWORD)


def test_a_hash_carries_the_parameters_it_was_made_with() -> None:
    # Cost parameters get raised over the years. A verifier using today's constants on
    # yesterday's hash would reject every old password at once — a self-inflicted lockout
    # that looks exactly like an attack.
    stored = hash_password(PASSWORD)
    algorithm, n, r, p, _salt, _hash = stored.split("$")

    assert algorithm == "scrypt"
    assert int(n) > 1 and int(r) >= 1 and int(p) >= 1


def test_verification_answers_false_for_every_kind_of_failure() -> None:
    stored = hash_password(PASSWORD)

    assert verify_password(PASSWORD, stored) is True
    assert verify_password("wrong", stored) is False
    assert verify_password(PASSWORD, None) is False
    assert verify_password(PASSWORD, "") is False
    assert verify_password(PASSWORD, "not-a-record") is False
    assert verify_password(PASSWORD, "bcrypt$1$1$1$aa$bb") is False


# ------------------------------------------------------------------ over HTTP


@pytest.mark.integration
@requires_db
def test_registering_upgrades_the_guest_rather_than_making_a_second_account(
    client: TestClient, seeded_db: Session
) -> None:
    # By the time someone registers they have a library. A new account here would strand it
    # while looking like success.
    headers = _guest(client)
    before = client.get("/me", headers=headers).json()["id"]

    body = client.post(
        "/auth/register",
        json={"email": "Reader@Example.invalid", "password": PASSWORD},
        headers=headers,
    ).json()

    assert body["user"]["id"] == before
    assert body["user"]["isGuest"] is False


@pytest.mark.integration
@requires_db
def test_a_registered_reader_can_sign_in_again(client: TestClient, seeded_db: Session) -> None:
    headers = _guest(client)
    client.post(
        "/auth/register",
        json={"email": "again@example.invalid", "password": PASSWORD},
        headers=headers,
    )

    response = client.post(
        "/auth/login", json={"email": "again@example.invalid", "password": PASSWORD}
    )

    assert response.status_code == 200
    assert response.json()["user"]["isGuest"] is False


@pytest.mark.integration
@requires_db
def test_the_email_is_matched_without_regard_to_case(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _guest(client)
    client.post(
        "/auth/register",
        json={"email": "Mixed@Example.invalid", "password": PASSWORD},
        headers=headers,
    )

    assert (
        client.post(
            "/auth/login", json={"email": "mixed@example.INVALID", "password": PASSWORD}
        ).status_code
        == 200
    )


@pytest.mark.integration
@requires_db
def test_a_wrong_password_and_an_unknown_email_are_indistinguishable(
    client: TestClient, seeded_db: Session
) -> None:
    # The whole point. A different message here turns the form into a way of asking whether
    # a particular person has an account.
    headers = _guest(client)
    client.post(
        "/auth/register",
        json={"email": "known@example.invalid", "password": PASSWORD},
        headers=headers,
    )

    wrong = client.post(
        "/auth/login", json={"email": "known@example.invalid", "password": "not it"}
    )
    unknown = client.post(
        "/auth/login", json={"email": "nobody@example.invalid", "password": PASSWORD}
    )

    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json()


@pytest.mark.integration
@requires_db
def test_a_guest_account_cannot_be_signed_into(client: TestClient, seeded_db: Session) -> None:
    # A guest has no password, and "no password set" must not mean "any password works".
    _guest(client)

    assert client.post("/auth/login", json={"email": "", "password": ""}).status_code in (401, 422)


@pytest.mark.integration
@requires_db
def test_an_email_already_in_use_does_not_say_so_any_differently(
    client: TestClient, seeded_db: Session
) -> None:
    first = _guest(client)
    client.post(
        "/auth/register",
        json={"email": "taken@example.invalid", "password": PASSWORD},
        headers=first,
    )

    second = _guest(client)
    response = client.post(
        "/auth/register",
        json={"email": "taken@example.invalid", "password": PASSWORD},
        headers=second,
    )

    assert response.status_code == 409
    assert "taken@example.invalid" not in response.text


@pytest.mark.integration
@requires_db
def test_registering_twice_on_one_account_is_refused(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _guest(client)
    client.post(
        "/auth/register",
        json={"email": "once@example.invalid", "password": PASSWORD},
        headers=headers,
    )

    again = client.post(
        "/auth/register",
        json={"email": "twice@example.invalid", "password": PASSWORD},
        headers=headers,
    )

    assert again.status_code == 409


@pytest.mark.integration
@requires_db
def test_a_short_password_is_refused_before_it_is_stored(
    client: TestClient, seeded_db: Session
) -> None:
    headers = _guest(client)

    response = client.post(
        "/auth/register",
        json={"email": "short@example.invalid", "password": "abc"},
        headers=headers,
    )

    assert response.status_code == 422
