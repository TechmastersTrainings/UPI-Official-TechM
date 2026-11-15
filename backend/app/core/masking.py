import re
from typing import Any

SENSITIVE_KEYS = {
    "password",
    "new_password",
    "current_password",
    "password_hash",
    "secret",
    "api_secret",
    "secret_hash",
    "token",
    "access_token",
    "refresh_token",
    "authorization",
    "cookie",
    "credentials",
    "credentials_enc",
    "signing_secret",
    "signing_secret_enc",
    "account_number",
    "account_number_enc",
    "upi_pin",
    "otp",
    "pin",
    "cvv",
    "card_number",
}


def mask_tail(value: str | None, visible: int = 4) -> str | None:
    if value is None:
        return None
    value = str(value)
    if len(value) <= visible:
        return "*" * len(value)
    return "X" * (len(value) - visible) + value[-visible:]


def mask_email(value: str | None) -> str | None:
    if not value or "@" not in value:
        return value
    local, domain = value.split("@", 1)
    return (local[:2] + "***" if len(local) > 2 else "***") + "@" + domain


def mask_mobile(value: str | None) -> str | None:
    if not value:
        return value
    digits = re.sub(r"\D", "", value)
    return "******" + digits[-4:] if len(digits) >= 4 else "****"


def redact(data: Any) -> Any:
    """Recursively replace values of sensitive keys. Used for logs and audit snapshots."""
    if isinstance(data, dict):
        return {
            k: ("[REDACTED]" if str(k).lower() in SENSITIVE_KEYS else redact(v)) for k, v in data.items()
        }
    if isinstance(data, list):
        return [redact(v) for v in data]
    return data
