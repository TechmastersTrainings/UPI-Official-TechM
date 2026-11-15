"""Sandbox tools for merchants testing their integration (TEST environment only).

The Simulate action decides the outcome on the simulated provider's side and then has the
simulator send its signed callback through the normal callback endpoint logic, so the full live
pipeline runs: signature check → de-duplication → verification engine → state machine → ledger →
webhooks. Nothing here writes a payment status directly.
"""

from sqlalchemy.orm import Session

from app.core.errors import AppError, Conflict, Forbidden
from app.models import Payment
from app.models.enums import Environment
from app.providers import sandbox
from app.providers.base import ProviderError
from app.services import callbacks, checkout, verification


def simulate(db: Session, payment: Payment, outcome: str) -> Payment:
    if payment.environment != Environment.TEST or payment.provider_code != sandbox.SandboxProvider.code:
        raise Forbidden("Simulation is only available for sandbox (TEST) payments", code="SANDBOX_ONLY")
    payment = checkout.sync_expiry(db, payment)
    if payment.status not in checkout.AWAITING_STATUSES:
        raise Conflict(f"Open the payment first; simulation needs an active session (status {payment.status})",
                       code="NO_ACTIVE_SESSION")
    attempt = verification.latest_session(db, payment.id)
    if attempt is None:
        raise Conflict("Open the payment first", code="NO_ACTIVE_SESSION")
    try:
        sim = sandbox.simulate(attempt.provider_session_ref, outcome)
    except sandbox.AlreadyDecided as exc:
        raise Conflict(f"The simulated provider already decided this payment: {exc.outcome}",
                       code="SANDBOX_OUTCOME_ALREADY_DECIDED") from exc
    except ProviderError as exc:
        raise AppError(exc.message, code="PROVIDER_ERROR", status_code=502) from exc
    body, headers = sandbox.callback_for(sim)
    result = callbacks.receive(db, sandbox.SandboxProvider.code, headers, body)
    if result.http_status != 200:
        raise AppError("The simulated callback was not accepted", code="SIMULATION_FAILED", status_code=500,
                       details={"result": result.result})
    db.refresh(payment)
    return payment
