"""Runtime configuration.

Secrets never have a usable default outside development: ``JWT_SECRET`` must be set
explicitly whenever ``ENVIRONMENT`` is not ``development`` or ``test`` (spec section 25).
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[3]

DEV_ONLY_JWT_SECRET = "dev-only-insecure-secret-change-me"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PAPERMATCH_",
        env_file=".env",
        extra="ignore",
    )

    environment: str = "development"
    api_version: str = "0.1.0"

    database_url: str = "postgresql+psycopg://papermatch:papermatch@localhost:5432/papermatch"

    jwt_secret: str = DEV_ONLY_JWT_SECRET
    jwt_algorithm: str = "HS256"
    guest_token_ttl_seconds: int = 60 * 60 * 24 * 30

    # Provider selection (spec section 22: everything external is swappable).
    paper_provider: str = "mock"
    translation_provider: str = "mock"
    #: Section 12 restricts the maths pipeline to licensed sources; see services/fulltext.py.
    fulltext_provider: str = "mock"
    #: Section 8's explanations. `derived` answers only what can be grounded in the paper
    #: and names what it cannot; `anthropic` answers the rest and needs a key. The default
    #: is the one that cannot invent anything.
    explanation_provider: str = "derived"
    explanation_model: str = "claude-haiku-4-5-20251001"
    #: **Server-side only.** Spec section 25: API キーをクライアントに置かない. The mobile app
    #: calls this API; this API calls the model. Never serialised into a response, a health
    #: payload or the audit log.
    anthropic_api_key: str = ""

    #: Sent on every outbound request. Spec section 21 asks that provider terms and
    #: acknowledgements be respected, and arXiv asks callers to identify themselves.
    provider_user_agent: str = (
        "PaperMatch/0.1 (+https://github.com/buzzwole11/nonchan2; research reading app)"
    )
    #: OpenAlex offers a faster "polite pool" to callers who supply a contact address.
    openalex_mailto: str | None = None

    fixtures_dir: Path = Field(default=REPO_ROOT / "fixtures")

    cors_allow_origins: list[str] = Field(default_factory=lambda: ["http://localhost:8081"])

    # Spec section 25: input length and rate limits.
    max_selection_chars: int = 1500
    max_abstract_chars: int = 20000

    @property
    def is_production_like(self) -> bool:
        return self.environment not in {"development", "test"}

    @model_validator(mode="after")
    def _reject_default_secret_outside_dev(self) -> Settings:
        if self.is_production_like and self.jwt_secret == DEV_ONLY_JWT_SECRET:
            raise ValueError(
                "PAPERMATCH_JWT_SECRET must be set to a real secret when "
                f"PAPERMATCH_ENVIRONMENT={self.environment!r}."
            )
        return self


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
