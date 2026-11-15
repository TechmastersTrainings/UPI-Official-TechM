"""Authentication for the public gateway API (/api/v1).

Merchant servers authenticate with HTTP Basic `key_id:secret`. The key decides the environment
(TEST or LIVE), so callers never pass an environment parameter and cannot cross between them.
"""

import base64
import binascii
import re
from dataclasses import dataclass

from fastapi import Depends, Header, Request
from sqlalchemy.orm import Session

from app.core import rate_limit
from app.core.config import get_settings
from app.core.errors import AppError, Unauthorized
from app.db.session import get_db
from app.models import ApiCredential, Merchant
from app.services import credentials

IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_\-:.]{1,100}$")


@dataclass
class ApiClient:
    credential: ApiCredential
    merchant: Merchant

    @property
    def environment(self) -> str:
        return self.credential.environment


def _parse_basic(header: str | None) -> tuple[str, str] | None:
    if not header:
        return None
    scheme, _, value = header.partition(" ")
    if scheme.lower() != "basic" or not value:
        return None
    try:
        decoded = base64.b64decode(value.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    key_id, sep, secret = decoded.partition(":")
    return (key_id, secret) if sep else None


def get_api_client(request: Request, db: Session = Depends(get_db)) -> ApiClient:
    s = get_settings()
    ip = request.client.host if request.client else "unknown"
    pair = _parse_basic(request.headers.get("authorization"))
    try:
        if pair is None:
            raise Unauthorized("Authenticate with HTTP Basic using your API key id and secret", code="INVALID_API_KEY")
        cred, merchant = credentials.authenticate(db, *pair)
    except Unauthorized:
        rate_limit.hit(f"v1-authfail:{ip}", s.API_AUTH_FAILURES_PER_MINUTE)
        raise
    # Tag the request so the access log row is attributed to this merchant and key.
    request.state.api_client = {"merchant_id": merchant.id, "credential_id": cred.id, "environment": cred.environment}
    rate_limit.hit(f"v1-key:{cred.id}", s.API_RATE_LIMIT_PER_MINUTE)
    return ApiClient(cred, merchant)


def idempotency_key(idempotency_key: str | None = Header(None, alias="Idempotency-Key")) -> str:
    if not idempotency_key:
        raise AppError("The Idempotency-Key header is required", code="IDEMPOTENCY_KEY_REQUIRED")
    if not IDEMPOTENCY_KEY_RE.match(idempotency_key):
        raise AppError("Idempotency-Key must be 1–100 characters of A–Z, a–z, 0–9, '_', '-', ':' or '.'",
                       code="IDEMPOTENCY_KEY_INVALID")
    return idempotency_key
