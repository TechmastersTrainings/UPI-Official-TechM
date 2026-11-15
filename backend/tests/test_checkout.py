"""Phase 4: provider adapters, provider sessions (UPI QR / intent) and hosted checkout."""

from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.types import utcnow
from app.models import Merchant, Payment, PaymentAttempt, ProviderConfiguration
from app.providers import registry
from app.providers.base import ProviderError, ProviderState, ProviderStatus
from app.providers.sandbox import SandboxProvider
from app.workers import run_once
from tests.conftest import auth
from tests.test_payments import create, merchant  # noqa: F401  (fixture)


def _token(p: dict) -> str:
    return p["checkout_url"].rsplit("/", 1)[1]


@pytest.fixture
def payment(client, merchant):  # noqa: F811
    r = create(client, merchant, return_url="https://shop.example.com/thanks",
               customer={"name": "Asha Verma", "mobile": "9876543210", "email": "asha@example.com"})
    assert r.status_code == 201, r.text
    return r.json()


def test_checkout_url_is_returned(payment):
    assert payment["checkout_url"].startswith("http://localhost:5177/checkout/")
    assert len(_token(payment)) >= 40


def test_checkout_view_has_no_pii_or_secrets(client, payment):
    r = client.get(f"/api/v1/checkout/{_token(payment)}")
    assert r.status_code == 200
    v = r.json()
    assert v["status"] == "CREATED" and v["amount"] == 49_900 and v["merchant_name"] == "Sharma Electronics"
    assert v["environment"] == "TEST" and v["session"] is None
    assert v["return_url"] is None  # only offered once the payment is final
    text = r.text
    for leaked in ("Asha", "9876543210", "asha@example.com", "idempotency", "request_hash", "provider_configuration"):
        assert leaked not in text


def test_unknown_token(client):
    assert client.get("/api/v1/checkout/nope").json()["error"]["code"] == "CHECKOUT_NOT_FOUND"
    assert client.get("/api/v1/checkout/" + "x" * 80).status_code == 404


def test_checkout_initiate_opens_sandbox_session(client, merchant, payment, db):  # noqa: F811
    tok = _token(payment)
    r = client.post(f"/api/v1/checkout/{tok}/initiate")
    assert r.status_code == 200, r.text
    v = r.json()
    assert v["status"] == "INITIATED"
    s = v["session"]
    # Sandbox payloads can never be paid by a real UPI app.
    assert s["qr_payload"].startswith("tmsandbox://pay?") and "upi://" not in s["qr_payload"]
    assert "am=499.00" in s["qr_payload"] and "TEST-NO-REAL-MONEY" in s["qr_payload"]
    assert s["provider_code"] == "sandbox"

    again = client.post(f"/api/v1/checkout/{tok}/initiate").json()
    assert again["session"]["attempt_id"] == s["attempt_id"]
    viaapi = client.post(f"/api/v1/payments/{payment['id']}/initiate", headers=merchant["headers"]).json()
    assert viaapi["session"]["attempt_id"] == s["attempt_id"] and viaapi["payment"]["status"] == "INITIATED"
    assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 1

    detail = client.get(f"/api/merchant/payments/{payment['id']}", headers=auth(merchant["token"])).json()
    assert [(e["to_status"], e["source"]) for e in detail["events"]] == [("CREATED", "MERCHANT_API"), ("INITIATED", "CHECKOUT")]
    assert detail["attempts"][0]["status"] == "AWAITING_CUSTOMER"

    # The polling view keeps returning the open session.
    assert client.get(f"/api/v1/checkout/{tok}").json()["session"]["attempt_id"] == s["attempt_id"]


def test_api_initiate_records_merchant_source(client, merchant, payment):  # noqa: F811
    r = client.post(f"/api/v1/payments/{payment['id']}/initiate", headers=merchant["headers"])
    assert r.status_code == 200 and r.json()["session"]["intent_uri"].startswith("tmsandbox://")
    d = client.get(f"/api/merchant/payments/{payment['id']}", headers=auth(merchant["token"])).json()
    assert d["events"][-1]["source"] == "MERCHANT_API"
    # Another merchant's key can't initiate it.
    assert client.post(f"/api/v1/payments/{payment['id']}/initiate").status_code == 401


def test_concurrent_pay_clicks_open_one_session(client, payment, db):
    tok = _token(payment)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda _: client.post(f"/api/v1/checkout/{tok}/initiate"), range(6)))
    ok = [r for r in results if r.status_code == 200]
    assert ok and all(r.status_code in (200, 409) for r in results), [r.text for r in results]
    assert len({r.json()["session"]["attempt_id"] for r in ok}) == 1
    assert db.scalar(select(func.count()).select_from(PaymentAttempt)) == 1


def test_cannot_pay_a_cancelled_payment(client, merchant, payment):  # noqa: F811
    client.post(f"/api/v1/payments/{payment['id']}/cancel", headers=merchant["headers"])
    tok = _token(payment)
    r = client.post(f"/api/v1/checkout/{tok}/initiate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PAYMENT_NOT_PAYABLE"
    v = client.get(f"/api/v1/checkout/{tok}").json()
    assert v["status"] == "CANCELLED" and v["session"] is None and v["return_url"] == "https://shop.example.com/thanks"


def test_suspended_merchant_cannot_collect(client, merchant, payment, db):  # noqa: F811
    m = db.get(Merchant, merchant["id"])
    m.status = "SUSPENDED"
    db.commit()
    r = client.post(f"/api/v1/checkout/{_token(payment)}/initiate")
    assert r.status_code == 403 and r.json()["error"]["code"] == "MERCHANT_NOT_ACTIVE"
    assert db.get(Payment, payment["id"]).status == "CREATED"


def test_disabled_provider_config_blocks_session(client, merchant, payment, db):  # noqa: F811
    cfg = db.get(ProviderConfiguration, db.get(Payment, payment["id"]).provider_configuration_id)
    cfg.status = "DISABLED"
    db.commit()
    r = client.post(f"/api/v1/checkout/{_token(payment)}/initiate")
    assert r.status_code == 409 and r.json()["error"]["code"] == "PROVIDER_UNAVAILABLE"


def test_provider_error_keeps_payment_payable(client, payment, db, monkeypatch):
    def boom(self, ctx, snap):
        raise ProviderError("upstream timeout")

    monkeypatch.setattr(SandboxProvider, "create_session", boom)
    r = client.post(f"/api/v1/checkout/{_token(payment)}/initiate")
    assert r.status_code == 502 and r.json()["error"]["code"] == "PROVIDER_ERROR"
    db.expire_all()
    assert db.get(Payment, payment["id"]).status == "CREATED"
    failed = db.scalars(select(PaymentAttempt)).all()
    assert [(a.status, a.error_message) for a in failed] == [("FAILED", "upstream timeout")]
    monkeypatch.undo()
    assert client.post(f"/api/v1/checkout/{_token(payment)}/initiate").json()["status"] == "INITIATED"


# ---------- Provider isolation ----------
def test_sandbox_refuses_live():
    with pytest.raises(RuntimeError):
        SandboxProvider("LIVE")
    with pytest.raises(registry.ProviderUnavailable):
        registry.get_adapter("sandbox", "LIVE", db_live_capable=True)  # even if the DB row were wrong
    with pytest.raises(registry.ProviderUnavailable):
        registry.get_adapter("made-up-bank", "TEST", db_live_capable=True)
    assert isinstance(registry.get_adapter("sandbox", "TEST", db_live_capable=False), SandboxProvider)


# ---------- Expiry with an open session ----------
def _overdue(db, payment_id):
    p = db.get(Payment, payment_id)
    p.expires_at = utcnow() - timedelta(seconds=1)
    for a in db.scalars(select(PaymentAttempt).where(PaymentAttempt.payment_id == payment_id)):
        a.expires_at = p.expires_at
    db.commit()


def test_open_session_expires_when_provider_confirms(client, merchant, payment, db):  # noqa: F811
    tok = _token(payment)
    client.post(f"/api/v1/checkout/{tok}/initiate")
    _overdue(db, payment["id"])
    v = client.get(f"/api/v1/checkout/{tok}").json()
    assert v["status"] == "EXPIRED" and v["session"] is None
    d = client.get(f"/api/merchant/payments/{payment['id']}", headers=auth(merchant["token"])).json()
    assert d["attempts"][0]["status"] == "EXPIRED"
    assert d["events"][-1]["payload"]["provider_state"] == "EXPIRED" and d["events"][-1]["source"] == "SYSTEM"


def test_worker_expires_open_sessions(client, payment, db):
    client.post(f"/api/v1/checkout/{_token(payment)}/initiate")
    _overdue(db, payment["id"])
    assert run_once() == {"payments_expired": 0, "sessions_expired": 1}
    db.expire_all()
    assert db.get(Payment, payment["id"]).status == "EXPIRED"
    assert run_once() == {"payments_expired": 0, "sessions_expired": 0}


@pytest.mark.parametrize("state", [ProviderState.SUCCESS, ProviderState.AWAITING_CUSTOMER, ProviderState.PROCESSING])
def test_expiry_never_overrides_other_provider_answers(client, payment, db, monkeypatch, state):
    """Past the deadline, a provider answer other than 'expired, nothing collected' leaves the payment
    alone. In particular a reported success is NOT applied here: it must go through verification."""
    client.post(f"/api/v1/checkout/{_token(payment)}/initiate")
    _overdue(db, payment["id"])
    monkeypatch.setattr(SandboxProvider, "fetch_status", lambda *a, **k: ProviderStatus(state, amount=49_900))
    assert client.get(f"/api/v1/checkout/{_token(payment)}").json()["status"] == "INITIATED"
    run_once()
    db.expire_all()
    assert db.get(Payment, payment["id"]).status == "INITIATED"


def test_provider_status_error_leaves_payment(client, payment, db, monkeypatch):
    client.post(f"/api/v1/checkout/{_token(payment)}/initiate")
    _overdue(db, payment["id"])

    def down(*a, **k):
        raise ProviderError("status API down")

    monkeypatch.setattr(SandboxProvider, "fetch_status", down)
    assert client.get(f"/api/v1/checkout/{_token(payment)}").json()["status"] == "INITIATED"


def test_checkout_is_rate_limited(client, payment, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "CHECKOUT_RATE_LIMIT_PER_MINUTE", 5)
    codes = [client.get(f"/api/v1/checkout/{_token(payment)}").status_code for _ in range(7)]
    assert codes[:5] == [200] * 5 and codes[-1] == 429
