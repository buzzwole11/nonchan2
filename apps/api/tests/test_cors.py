"""Which browser origins the API answers.

The rule these cover: during development a phone on the same Wi-Fi may open the Expo web
build and call this API, and its origin (`http://192.168.x.x:8081`) cannot be listed in
advance. Outside development that allowance disappears — a deployed API answers exactly the
configured origins. None of this affects the native app, where CORS does not apply.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from papermatch_api.config import get_settings
from papermatch_api.main import create_app


@pytest.fixture
def _fresh_settings() -> Iterator[None]:
    """`get_settings` is cached for the process; environment edits need it cleared."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _allowed_origin(origin: str) -> str | None:
    """The `access-control-allow-origin` a preflight comes back with, if any."""
    with TestClient(create_app()) as client:
        response = client.options(
            "/fields",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )
    return response.headers.get("access-control-allow-origin")


@pytest.mark.usefixtures("_fresh_settings")
@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:8081",
        "http://127.0.0.1:8081",
        "http://192.168.1.23:8081",
        "http://10.0.0.5:8081",
        "http://172.16.4.9:19006",
        "http://macbook.local:8081",
    ],
)
def test_development_answers_the_dev_server_and_the_local_network(origin: str) -> None:
    assert _allowed_origin(origin) == origin


@pytest.mark.usefixtures("_fresh_settings")
@pytest.mark.parametrize(
    "origin",
    [
        # A page on the public internet, opened in the same browser as the dev server.
        "https://example.com",
        # Close enough to look private, but routable: 172.32 is outside the RFC 1918 block,
        # and a hostname can end in the name of a private range without being one.
        "http://172.32.0.1:8081",
        "http://192.168.1.23.example.com",
    ],
)
def test_development_still_refuses_public_origins(origin: str) -> None:
    assert _allowed_origin(origin) is None


@pytest.mark.usefixtures("_fresh_settings")
def test_production_drops_the_local_network_allowance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PAPERMATCH_ENVIRONMENT", "production")
    monkeypatch.setenv("PAPERMATCH_JWT_SECRET", "not-the-development-default")
    get_settings.cache_clear()

    assert _allowed_origin("http://192.168.1.23:8081") is None
    # The configured list is still honoured; only the regex is gone.
    assert _allowed_origin("http://localhost:8081") == "http://localhost:8081"
