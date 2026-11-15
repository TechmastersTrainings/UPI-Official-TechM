"""Field-level encryption for sensitive values (bank account numbers, provider credentials,
webhook signing secrets) and keyed hashing for high-entropy secrets (API secrets, refresh tokens)."""

import hashlib
import hmac
import json
import secrets
from functools import lru_cache

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

from app.core.config import get_settings


class EncryptionNotConfigured(RuntimeError):
    pass


@lru_cache
def _fernet() -> MultiFernet:
    raw = get_settings().ENCRYPTION_KEYS
    keys = [k.strip() for k in raw.split(",") if k.strip()]
    if not keys:
        raise EncryptionNotConfigured("ENCRYPTION_KEYS is not set")
    return MultiFernet([Fernet(k.encode()) for k in keys])


def encrypt_str(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_str(token: str) -> str:
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken as exc:  # wrong key or tampered ciphertext
        raise ValueError("Unable to decrypt value") from exc


def encrypt_json(value: dict) -> str:
    return encrypt_str(json.dumps(value, separators=(",", ":"), sort_keys=True))


def decrypt_json(token: str) -> dict:
    return json.loads(decrypt_str(token))


def rotate(token: str) -> str:
    """Re-encrypt with the newest key (used by key-rotation jobs)."""
    return _fernet().rotate(token.encode()).decode()


def keyed_hash(value: str) -> str:
    """HMAC-SHA256 with a server-side pepper. Suitable only for high-entropy random secrets."""
    pepper = get_settings().HASH_PEPPER
    if not pepper:
        raise EncryptionNotConfigured("HASH_PEPPER is not set")
    return hmac.new(pepper.encode(), value.encode(), hashlib.sha256).hexdigest()


def constant_time_equals(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def random_token(nbytes: int = 32) -> str:
    return secrets.token_urlsafe(nbytes)


def generate_fernet_key() -> str:
    return Fernet.generate_key().decode()
