"""Symmetric encryption for secrets stored in the database (API keys, OAuth tokens, SMTP password).

The key is derived from SECRET_KEY with HKDF, so one secret configures the whole deployment.
"""
import base64
import hashlib
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .config import get_config


@lru_cache
def _fernet() -> Fernet:
    # The label keeps the project's old name on purpose: changing it would make every stored secret unreadable.
    key = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"smartlists/secrets/v1").derive(
        get_config().secret_key.encode()
    )
    return Fernet(base64.urlsafe_b64encode(key))


def encrypt(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt(token: str | None) -> str | None:
    if not token:
        return None
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None   # SECRET_KEY changed: treat the secret as missing


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def mask(value: str | None) -> str:
    """For showing that a secret is set without revealing it: 'sk-…3f9a'."""
    if not value:
        return ""
    return f"{value[:3]}…{value[-4:]}" if len(value) > 10 else "…" + value[-2:]
