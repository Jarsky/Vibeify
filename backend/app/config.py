"""Deployment configuration from environment variables.

Only things that must exist before the database is reachable, or that a deployer should control
outside the admin panel, live here. Everything else (site name, sign-in methods, LLM providers,
SMTP, quotas) is stored in the database and edited in the admin panel.
"""
from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Config(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Public URL of the site, no trailing slash. OAuth redirect URIs are built from it.
    public_url: str = Field("http://localhost:8000", alias="PUBLIC_URL")
    # Signs session cookies and derives the key that encrypts stored secrets. Changing it logs
    # everyone out and makes stored API keys/tokens unreadable.
    secret_key: str = Field(..., alias="SECRET_KEY", min_length=32)
    database_url: str = Field("sqlite+aiosqlite:///./data/vibeify.db", alias="DATABASE_URL")

    # Comma-separated emails or Spotify user ids that are made admins when they sign in.
    bootstrap_admins: str = Field("", alias="BOOTSTRAP_ADMINS")

    # Optional first-start seeds; afterwards these are managed in the admin panel.
    seed_spotify_client_id: str = Field("", alias="SPOTIFY_CLIENT_ID")
    seed_spotify_client_secret: str = Field("", alias="SPOTIFY_CLIENT_SECRET")
    seed_openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    seed_anthropic_api_key: str = Field("", alias="ANTHROPIC_API_KEY")
    seed_gemini_api_key: str = Field("", alias="GEMINI_API_KEY")

    # Set when running behind a reverse proxy that terminates TLS (cookies get the Secure flag
    # when PUBLIC_URL is https regardless).
    trust_proxy_headers: bool = Field(True, alias="TRUST_PROXY_HEADERS")
    static_dir: str = Field("static", alias="STATIC_DIR")

    @property
    def secure_cookies(self) -> bool:
        return self.public_url.startswith("https://")

    @property
    def admin_bootstrap_set(self) -> set[str]:
        return {x.strip().lower() for x in self.bootstrap_admins.split(",") if x.strip()}


@lru_cache
def get_config() -> Config:
    return Config()
