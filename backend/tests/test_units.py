from app import crypto
from app.services import matching, recommend


def test_crypto_roundtrip_and_mask():
    token = crypto.encrypt("secret-value-123456")
    assert crypto.decrypt(token) == "secret-value-123456"
    assert crypto.decrypt("garbage") is None
    assert "secret" not in crypto.mask("secret-value-123456")


def test_norm_strips_versions():
    assert matching.norm("Song (2011 Remaster)") == matching.norm("Song")
    assert matching.norm("Song - Live at Wembley") == "song"
    assert matching.norm("Beyoncé") == "beyonce"


def test_score_rejects_wrong_artist():
    cand = {"name": "Hello", "artists": [{"name": "Adele"}]}
    assert matching.score("Hello", "Adele", cand) > 90
    assert matching.score("Hello", "Lionel Richie", cand) == 0


def test_with_extra():
    assert recommend.with_extra(20) == 25
    assert recommend.with_extra(5) == 8


def test_database_url_accepts_plain_postgres_urls():
    from app.config import Config
    url = lambda v: Config(SECRET_KEY="k" * 32, DATABASE_URL=v).database_url  # noqa: E731
    assert url("postgresql://u:p@dpg-x-a/vibeify") == "postgresql+asyncpg://u:p@dpg-x-a/vibeify"
    assert url("postgres://u:p@h:5432/db?sslmode=require") == "postgresql+asyncpg://u:p@h:5432/db?ssl=require"
    assert url("postgresql+asyncpg://u:p@db/x") == "postgresql+asyncpg://u:p@db/x"
    assert url("sqlite+aiosqlite:///./data/x.db") == "sqlite+aiosqlite:///./data/x.db"
