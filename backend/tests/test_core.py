from datetime import datetime, timezone

import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError

from app.core import crypto
from app.core.config import Settings
from app.core.masking import mask_email, mask_mobile, mask_tail, redact
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    validate_password_strength,
    verify_password,
)
from app.db.types import UTCDateTime


def test_encrypt_roundtrip_and_key_rotation(monkeypatch):
    token = crypto.encrypt_str("123456789012")
    assert "123456789012" not in token
    assert crypto.decrypt_str(token) == "123456789012"

    # Add a new primary key: old ciphertext still decrypts, rotate() moves it to the new key.
    new_key = Fernet.generate_key().decode()
    old_keys = crypto.get_settings().ENCRYPTION_KEYS
    monkeypatch.setattr(crypto.get_settings(), "ENCRYPTION_KEYS", f"{new_key},{old_keys}")
    crypto._fernet.cache_clear()
    try:
        assert crypto.decrypt_str(token) == "123456789012"
        rotated = crypto.rotate(token)
        assert Fernet(new_key.encode()).decrypt(rotated.encode()) == b"123456789012"
    finally:
        monkeypatch.undo()
        crypto._fernet.cache_clear()


def test_decrypt_tampered_value_fails():
    token = crypto.encrypt_str("secret")
    with pytest.raises(ValueError):
        crypto.decrypt_str(token[:-4] + "AAAA")


def test_json_encryption():
    assert crypto.decrypt_json(crypto.encrypt_json({"key": "v", "n": 1})) == {"key": "v", "n": 1}


def test_keyed_hash_is_deterministic_and_peppered():
    assert crypto.keyed_hash("abc") == crypto.keyed_hash("abc")
    assert crypto.keyed_hash("abc") != crypto.keyed_hash("abd")
    assert len(crypto.keyed_hash("abc")) == 64


def test_password_hashing():
    h = hash_password("Correct-Horse-42!")
    assert h.startswith("$argon2id$")
    assert verify_password("Correct-Horse-42!", h)
    assert not verify_password("wrong", h)
    assert not verify_password("anything", None)
    assert not verify_password("anything", "not-a-hash")


@pytest.mark.parametrize(
    "pw,ok",
    [("short1A!", False), ("alllowercaseletters", False), ("Lowercase-and-digits1", True), ("NoSymbolsButLong12", True)],
)
def test_password_strength(pw, ok):
    assert (validate_password_strength(pw) == []) is ok


def test_access_token_roundtrip():
    token, ttl = create_access_token(user_id="usr_1", role="SUPER_ADMIN", session_id="ses_1", token_version=3)
    claims = decode_access_token(token)
    assert claims["sub"] == "usr_1" and claims["tv"] == 3 and claims["sid"] == "ses_1"
    assert ttl == 900


def test_masking():
    assert mask_tail("123456789012") == "XXXXXXXX9012"
    assert mask_email("rahul@example.com") == "ra***@example.com"
    assert mask_mobile("+91 98765 43210") == "******3210"
    assert redact({"password": "x", "nested": [{"account_number": "1"}], "ok": 1}) == {
        "password": "[REDACTED]",
        "nested": [{"account_number": "[REDACTED]"}],
        "ok": 1,
    }


def test_utc_datetime_rejects_naive():
    t = UTCDateTime()
    with pytest.raises(ValueError):
        t.process_bind_param(datetime(2026, 1, 1), None)
    aware = datetime(2026, 1, 1, 5, 30, tzinfo=timezone.utc)
    stored = t.process_bind_param(aware, None)
    assert stored.tzinfo is None
    assert t.process_result_value(stored, None) == aware


def test_production_requires_secrets():
    with pytest.raises(ValidationError):
        Settings(_env_file=None, APP_ENV="production", JWT_SECRET="", ENCRYPTION_KEYS="", HASH_PEPPER="")
    with pytest.raises(ValidationError):  # sqlite forbidden in production
        Settings(
            _env_file=None, APP_ENV="production", JWT_SECRET="x" * 40, ENCRYPTION_KEYS="k", HASH_PEPPER="p",
            DATABASE_URL="sqlite:///x.db", COOKIE_SECURE=True,
        )
    ok = Settings(
        _env_file=None, APP_ENV="production", JWT_SECRET="x" * 40, ENCRYPTION_KEYS="k", HASH_PEPPER="p",
        DATABASE_URL="mysql+pymysql://u:p@h/db", COOKIE_SECURE=True,
    )
    assert ok.APP_ENV == "production"
