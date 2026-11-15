"""TechMasters sandbox provider — a simulator for the TEST environment. It never moves money.

* Refuses to be constructed for LIVE.
* Its QR / intent content uses the `tmsandbox://` scheme rather than `upi://`, so no UPI app can
  act on it, even if someone scans a test QR with a real phone.
* Status: the session waits for the customer until it expires. Simulated outcomes (success,
  failure) are added with the sandbox tools in Phase 6 and go through the same verification path
  as live payments.
"""

import secrets
from datetime import datetime
from urllib.parse import urlencode

from app.db.types import utcnow
from app.models.enums import Environment
from app.providers.base import ProviderContext, ProviderState, ProviderStatus, PaymentSnapshot, SessionResult

SANDBOX_SCHEME = "tmsandbox"


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
