"""TechMasters sandbox provider — a simulator for the TEST environment. It never moves money.

* Refuses to be constructed for LIVE.
* QR / intent content uses the `tmsandbox://` scheme rather than `upi://`, so no UPI app can act
  on it, even if someone scans a test QR with a real phone.
* It keeps its own "provider-side" state in `sandbox_simulations`. The gateway learns outcomes
  only through this adapter's status API and its signed callbacks, the same way as with a real
  provider. The first decided outcome is final, so polls and callbacks always agree.
* Callbacks are JSON signed with HMAC-SHA256 under a server-only key (`X-Sandbox-Signature`).

Test outcomes by the paise of the amount (decided SANDBOX_AUTO_OUTCOME_SECONDS after the
customer opens the payment, discovered by status polling):

    ₹x.00 → SUCCESS     ₹x.01 → FAILED     ₹x.02 → PROCESSING (stays there)
    ₹x.03 → nothing happens; the session expires at the payment's deadline
    other → nothing automatic; use the Simulate panel on the test checkout

Refunds succeed after the same delay, except refund amounts ending in .01, which fail.
"""

import hashlib
import hmac
import json
import secrets
from datetime import datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy.exc import IntegrityError

from app.core.config import get_settings
from app.core.crypto import keyed_hash
from app.db.types import utcnow
from app.models.enums import Environment
from app.providers.base import (
    CallbackEvent,
    CallbackRef,
    InvalidSignature,
    PaymentSnapshot,
    ProviderContext,
    ProviderError,
    ProviderState,
    ProviderStatus,
    RefundResult,
    RefundSnapshot,
    RefundState,
    SessionResult,
)

SANDBOX_SCHEME = "tmsandbox"
SIGNATURE_HEADER = "x-sandbox-signature"
MAX_CALLBACK_BYTES = 16_384
SANDBOX_PAYER_VPA = "sandbox.customer@tmsandbox"

PAYMENT_AUTO_OUTCOMES = {0: "SUCCESS", 1: "FAILED", 2: "PROCESSING"}
SIMULATABLE = ("SUCCESS", "FAILED", "PROCESSING")
FINAL = ("SUCCESS", "FAILED", "EXPIRED")


class AlreadyDecided(Exception):
    def __init__(self, outcome: str):
        super().__init__(outcome)
        self.outcome = outcome


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


# ---------------------------------------------------------------- simulator store
def _session():
    from app.db.session import get_sessionmaker

    return get_sessionmaker()()


def _delay() -> timedelta:
    return timedelta(seconds=get_settings().SANDBOX_AUTO_OUTCOME_SECONDS)


def _decide_on(sim, outcome: str) -> None:
    sim.outcome = outcome
    sim.decided_at = utcnow()
    if outcome == "SUCCESS" and sim.provider_transaction_id is None:
        prefix = "sbxtxn_" if sim.kind == "PAYMENT" else "sbxrfd_"
        sim.provider_transaction_id = prefix + secrets.token_hex(10)


def _resolve(ref: str):
    """Load a simulation and apply any outcome that is now due (auto outcome or expiry)."""
    from app.models import SandboxSimulation

    with _session() as s:
        sim = s.get(SandboxSimulation, ref)
        if sim is None:
            return None
        now = utcnow()
        if sim.outcome not in FINAL:
            if sim.auto_outcome and sim.outcome != sim.auto_outcome and now >= sim.created_at + _delay():
                _decide_on(sim, sim.auto_outcome)
            elif sim.outcome is None and sim.expires_at is not None and now >= sim.expires_at:
                _decide_on(sim, "EXPIRED")
            s.commit()
        s.expunge(sim)
        return sim


def simulate(session_ref: str, outcome: str):
    """Decide a payment session's outcome from the Simulate panel. Final outcomes can't be changed."""
    from app.models import SandboxSimulation

    if outcome not in SIMULATABLE:
        raise ValueError(f"outcome must be one of {SIMULATABLE}")
    current = _resolve(session_ref)
    if current is None:
        raise ProviderError("unknown sandbox session", retryable=False, provider_code="sandbox")
    with _session() as s:
        sim = s.get(SandboxSimulation, session_ref)
        if sim.outcome in FINAL or sim.outcome == outcome:
            raise AlreadyDecided(sim.outcome)
        _decide_on(sim, outcome)
        sim.auto_outcome = None  # a manual decision replaces any scheduled one
        s.commit()
        s.expunge(sim)
        return sim


def callback_for(sim) -> tuple[bytes, dict[str, str]]:
    """Signed callback the simulated provider sends for a decided session."""
    body = {"event_id": "sbxevt_" + secrets.token_hex(10), "session_ref": sim.ref, "state": sim.outcome}
    if sim.outcome == "SUCCESS":
        body |= {"amount": sim.amount, "currency": sim.currency, "provider_transaction_id": sim.provider_transaction_id,
                 "bank_reference": "SBX" + sim.ref[-9:].upper(), "payer_vpa": SANDBOX_PAYER_VPA}
    elif sim.outcome == "FAILED":
        body["failure_reason"] = "Declined by the customer's bank (simulated)"
    raw = json.dumps(body).encode()
    return raw, {"content-type": "application/json", SIGNATURE_HEADER: sign_callback(raw)}


def _status_from(sim) -> ProviderStatus:
    raw = {"simulated": True, "session": sim.ref, "outcome": sim.outcome}
    if sim.outcome == "SUCCESS":
        return ProviderStatus(ProviderState.SUCCESS, amount=sim.amount, currency=sim.currency,
                              provider_transaction_id=sim.provider_transaction_id,
                              bank_reference="SBX" + sim.ref[-9:].upper(), payer_vpa=SANDBOX_PAYER_VPA, raw=raw)
    if sim.outcome == "FAILED":
        return ProviderStatus(ProviderState.FAILED, failure_reason="Declined by the customer's bank (simulated)", raw=raw)
    if sim.outcome == "PROCESSING":
        return ProviderStatus(ProviderState.PROCESSING, raw=raw)
    if sim.outcome == "EXPIRED":
        return ProviderStatus(ProviderState.EXPIRED, raw=raw)
    return ProviderStatus(ProviderState.AWAITING_CUSTOMER, raw=raw)


# ---------------------------------------------------------------- adapter
class SandboxProvider:
    code = "sandbox"
    live_capable = False

    def __init__(self, environment: str):
        if environment != Environment.TEST:
            raise RuntimeError("The sandbox provider can only be used in the TEST environment")
        self.environment = environment

    def create_session(self, ctx: ProviderContext, payment: PaymentSnapshot) -> SessionResult:
        from app.models import SandboxSimulation

        ref = "sbx_" + secrets.token_hex(12)
        with _session() as s:
            s.add(SandboxSimulation(
                ref=ref, kind="PAYMENT", amount=payment.amount, currency=payment.currency,
                auto_outcome=PAYMENT_AUTO_OUTCOMES.get(payment.amount % 100), expires_at=payment.expires_at,
            ))
            s.commit()
        query = urlencode({
            "sid": ref,
            "am": f"{payment.amount / 100:.2f}",
            "cu": payment.currency,
            "pn": payment.payee_name[:50],
            "tr": payment.merchant_reference,
            "mode": "TEST-NO-REAL-MONEY",
        })
        uri = f"{SANDBOX_SCHEME}://pay?{query}"
        return SessionResult(provider_session_ref=ref, expires_at=payment.expires_at, qr_payload=uri, intent_uri=uri,
                             raw={"simulated": True, "session": ref})

    def fetch_status(self, ctx: ProviderContext, payment: PaymentSnapshot, session_ref: str,
                     session_expires_at: datetime) -> ProviderStatus:
        sim = _resolve(session_ref)
        if sim is None:
            raise ProviderError("unknown sandbox session", retryable=False, provider_code=self.code)
        return _status_from(sim)

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

    def create_refund(self, ctx: ProviderContext, refund: RefundSnapshot) -> RefundResult:
        from app.models import SandboxSimulation

        ref = "sbxr_" + secrets.token_hex(12)
        with _session() as s:
            s.add(SandboxSimulation(
                ref=ref, kind="REFUND", session_ref=refund.session_ref, amount=refund.amount, currency=refund.currency,
                auto_outcome="FAILED" if refund.amount % 100 == 1 else "SUCCESS",
            ))
            try:
                s.commit()
            except IntegrityError as exc:  # pragma: no cover - random ref collision
                raise ProviderError("sandbox refund reference collision") from exc
        return RefundResult(RefundState.PENDING, provider_refund_ref=ref, amount=refund.amount, raw={"simulated": True})

    def fetch_refund_status(self, ctx: ProviderContext, refund: RefundSnapshot) -> RefundResult:
        sim = _resolve(refund.provider_refund_ref or "")
        if sim is None:
            raise ProviderError("unknown sandbox refund", retryable=False, provider_code=self.code)
        if sim.outcome == "SUCCESS":
            return RefundResult(RefundState.SUCCESS, provider_refund_ref=sim.ref, amount=sim.amount,
                                provider_transaction_id=sim.provider_transaction_id,
                                raw={"simulated": True, "refund": sim.ref})
        if sim.outcome == "FAILED":
            return RefundResult(RefundState.FAILED, provider_refund_ref=sim.ref,
                                failure_reason="Refund rejected by the bank (simulated)", raw={"simulated": True})
        return RefundResult(RefundState.PENDING, provider_refund_ref=sim.ref, raw={"simulated": True})
