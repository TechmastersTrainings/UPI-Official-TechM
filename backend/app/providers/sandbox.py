"""TechMasters sandbox provider — a simulator for the TEST environment. It never moves money.

* Refuses to be constructed for LIVE.
* Its QR / intent content uses the `tmsandbox://` scheme rather than `upi://`, so no UPI app can
  act on it, even if someone scans a test QR with a real phone.
* Callbacks are JSON signed with HMAC-SHA256 under a server-only key (`X-Sandbox-Signature`), and
  go through exactly the same verification pipeline as a real provider's callbacks.
* Status: a session waits for the customer until it expires. Simulated outcomes are produced by
  the sandbox tools (Phase 6) as signed callbacks.
"""

import hashlib
import hmac
import json
import secrets
from datetime import datetime
from urllib.parse import urlencode

from app.core.crypto import keyed_hash
from app.db.types import utcnow
from app.models.enums import Environment
from app.providers.base import (
    CallbackEvent,
    CallbackRef,
    InvalidSignature,
    PaymentSnapshot,
    ProviderContext,
    ProviderState,
    ProviderStatus,
    SessionResult,
)

SANDBOX_SCHEME = "tmsandbox"
SIGNATURE_HEADER = "x-sandbox-signature"
MAX_CALLBACK_BYTES = 16_384


def _signing_key() -> bytes:
    # Derived from the server pepper, so it never leaves the server and differs per deployment.
    return keyed_hash("sandbox-callback-signing-v1").encode()


def sign_callback(body: bytes) -> str:
    return hmac.new(_signing_key(), body, hashlib.sha256).hexdigest()


def _parse(body: bytes) -> dict:
    if len(body) > MAX_CALLBACK_BYTES:
        raise InvalidSignature("callback body too large")
    try:
        data = json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise InvalidSignature("callback body is not JSON") from exc
    if not isinstance(data, dict) or not isinstance(data.get("event_id"), str) or not isinstance(data.get("session_ref"), str):
        raise InvalidSignature("callback is missing event_id / session_ref")
    return data


class SandboxProvider:
    code = "sandbox"
    live_capable = False

    def __init__(self, environment: str):
        if environment != Environment.TEST:
            raise RuntimeError("The sandbox provider can only be used in the TEST environment")
        self.environment = environment

    def create_session(self, ctx: ProviderContext, payment: PaymentSnapshot) -> SessionResult:
        ref = "sbx_" + secrets.token_hex(12)
        query = urlencode({
            "sid": ref,
            "am": f"{payment.amount / 100:.2f}",
            "cu": payment.currency,
            "pn": payment.payee_name[:50],
            "tr": payment.merchant_reference,
            "mode": "TEST-NO-REAL-MONEY",
        })
        uri = f"{SANDBOX_SCHEME}://pay?{query}"
        return SessionResult(
            provider_session_ref=ref, expires_at=payment.expires_at, qr_payload=uri, intent_uri=uri,
            raw={"simulated": True, "session": ref},
        )

    def fetch_status(self, ctx: ProviderContext, payment: PaymentSnapshot, session_ref: str,
                     session_expires_at: datetime) -> ProviderStatus:
        if utcnow() >= session_expires_at:
            return ProviderStatus(ProviderState.EXPIRED, raw={"simulated": True, "session": session_ref})
        return ProviderStatus(ProviderState.AWAITING_CUSTOMER, raw={"simulated": True, "session": session_ref})

    @classmethod
    def identify_callback(cls, headers: dict[str, str], body: bytes) -> CallbackRef:
        data = _parse(body)
        return CallbackRef(event_id=data["event_id"][:128], session_ref=data["session_ref"][:100])

    def verify_callback(self, ctx: ProviderContext, headers: dict[str, str], body: bytes) -> CallbackEvent:
        given = headers.get(SIGNATURE_HEADER, "")
        if not given or not hmac.compare_digest(given, sign_callback(body)):
            raise InvalidSignature("signature mismatch")
        data = _parse(body)
        try:
            state = ProviderState(data["state"])
        except (KeyError, ValueError) as exc:
            raise InvalidSignature("unknown state") from exc
        amount = data.get("amount")
        status = ProviderStatus(
            state=state,
            amount=amount if isinstance(amount, int) else None,
            currency=data.get("currency"),
            provider_transaction_id=data.get("provider_transaction_id"),
            bank_reference=data.get("bank_reference"),
            failure_reason=data.get("failure_reason"),
            payer_vpa=data.get("payer_vpa"),
            raw={k: v for k, v in data.items() if k != "payer_vpa"} | {"simulated": True},
        )
        return CallbackEvent(event_id=data["event_id"], session_ref=data["session_ref"], status=status)
