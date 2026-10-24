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
