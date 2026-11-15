"""Phase 6: sandbox simulator (amount-based outcomes, Simulate panel), refunds, and the full sandbox
lifecycle end to end."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config import get_settings
from app.db.session import get_sessionmaker
from app.db.types import utcnow
from app.models import (
    Payment,
    PaymentAttempt,
    ProviderCallback,
    ReconciliationRecord,
    Refund,
    SandboxSimulation,
    Transaction,
    WebhookDelivery,
)
from app.providers.base import ProviderError
from app.providers.sandbox import SandboxProvider
from app.services import refunds, verification, webhooks
from app.workers import run_once
from tests.conftest import auth, login, make_user
from tests.test_checkout import _token
from tests.test_payments import create, merchant  # noqa: F401  (fixture)


# ---------------------------------------------------------------- helpers
def opened(client, merchant, amount=49_900, ref="ORD-1"):  # noqa: F811
    p = create(client, merchant, key=f"k-{ref}", merchant_reference=ref, amount=amount).json()
    v = client.post(f"/api/v1/checkout/{_token(p)}/initiate").json()
    assert v["status"] == "INITIATED", v
    return p


def simulate(client, p, outcome):
    return client.post(f"/api/v1/checkout/{_token(p)}/simulate", json={"outcome": outcome})


def status_of(db, pid):
    db.expire_all()
    return db.get(Payment, pid).status


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


@pytest.fixture
def instant(monkeypatch):
    """Amount-based outcomes decided immediately and polls due at once."""
    monkeypatch.setattr(get_settings(), "SANDBOX_AUTO_OUTCOME_SECONDS", 0)


def poll_all(db):
    for model in (PaymentAttempt, Refund):
        for row in db.scalars(select(model).where(model.next_poll_at.is_not(None))):
            row.next_poll_at = utcnow() - timedelta(seconds=1)
    db.commit()
    with get_sessionmaker()() as s:
        verification.poll_due(s)
        refunds.poll_due(s)


@pytest.fixture
def paid(client, merchant):  # noqa: F811
    p = opened(client, merchant)
    assert simulate(client, p, "SUCCESS").json()["status"] == "SUCCESS"
    return p


def refund(client, merchant, pid, key="r1", **body):  # noqa: F811
    return client.post("/api/v1/refunds", json={"payment_id": pid, **body},
                       headers={**merchant["headers"], "Idempotency-Key": key})


# ---------------------------------------------------------------- simulate panel
def test_simulate_success_runs_the_real_pipeline(client, merchant, db):  # noqa: F811
    p = opened(client, merchant)
    r = simulate(client, p, "SUCCESS")
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS" and r.json()["return_url"] is None
    cb = db.scalar(select(ProviderCallback))
    assert cb.signature_valid and cb.processed_at  # went through the signed-callback path
    txn = db.scalar(select(Transaction))
    assert txn.verification_method == "PROVIDER_WEBHOOK" and txn.amount == 49_900
    assert txn.payer_vpa_masked == "sa**************@tmsandbox"
    # The simulator's later status answers agree with the callback: no duplicate, no investigation.
    poll_all(db)
    assert count(db, Transaction) == 1 and count(db, ReconciliationRecord, ReconciliationRecord.status == "INVESTIGATION_REQUIRED") == 0


def test_simulate_failure_and_processing(client, merchant, db):  # noqa: F811
    a = opened(client, merchant, ref="A")
    assert simulate(client, a, "FAILED").json()["status"] == "FAILED"
    assert db.get(Payment, a["id"]).failure_reason.endswith("(simulated)")
    b = opened(client, merchant, ref="B")
    assert simulate(client, b, "PROCESSING").json()["status"] == "PROCESSING"
    assert simulate(client, b, "SUCCESS").json()["status"] == "SUCCESS"


def test_final_outcomes_cannot_be_changed(client, merchant, db):  # noqa: F811
    p = opened(client, merchant)
    simulate(client, p, "FAILED")
    r = simulate(client, p, "SUCCESS")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_ACTIVE_SESSION"
    assert status_of(db, p["id"]) == "FAILED" and count(db, Transaction) == 0


def test_simulate_requires_open_session(client, merchant):  # noqa: F811
    p = create(client, merchant).json()
    r = simulate(client, p, "SUCCESS")
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_ACTIVE_SESSION"
    assert simulate(client, p, "REFUNDED").status_code == 422


def test_simulate_refused_for_live(client, merchant, db):  # noqa: F811
    live = Payment(
        merchant_id=merchant["id"], environment="LIVE", merchant_reference="L-1", amount=100, currency="INR",
        payment_method="HOSTED", expires_at=utcnow() + timedelta(minutes=5), idempotency_key="l1",
        request_hash="x" * 64, checkout_token="live-token-sim", status="INITIATED", provider_code="acme",
    )
    db.add(live)
    db.commit()
    r = client.post("/api/v1/checkout/live-token-sim/simulate", json={"outcome": "SUCCESS"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SANDBOX_ONLY"
    assert status_of(db, live.id) == "INITIATED"


def test_simulate_via_api(client, merchant):  # noqa: F811
    p = opened(client, merchant)
    r = client.post(f"/api/v1/payments/{p['id']}/simulate", json={"outcome": "SUCCESS"}, headers=merchant["headers"])
    assert r.status_code == 200 and r.json()["status"] == "SUCCESS"


def test_expired_session_cannot_be_paid(client, merchant, db):  # noqa: F811
    p = opened(client, merchant, amount=49_937)
    past = utcnow() - timedelta(seconds=1)
    db.get(Payment, p["id"]).expires_at = past
    for sim in db.scalars(select(SandboxSimulation)):
        sim.expires_at = past
    db.commit()
    r = simulate(client, p, "SUCCESS")
    assert r.status_code == 409 and status_of(db, p["id"]) == "EXPIRED"


# ---------------------------------------------------------------- amount-based outcomes
@pytest.mark.parametrize("amount, expected", [
    (10_000, "SUCCESS"),      # ₹100.00
    (10_001, "FAILED"),       # ₹100.01
    (10_002, "PROCESSING"),   # ₹100.02
    (10_003, "INITIATED"),    # ₹100.03: nothing until the deadline
    (10_037, "INITIATED"),    # no automatic outcome
])
def test_amount_based_outcomes(client, merchant, db, instant, amount, expected):  # noqa: F811
    p = opened(client, merchant, amount=amount)
    poll_all(db)
    assert status_of(db, p["id"]) == expected
    if expected == "SUCCESS":
        assert db.scalar(select(Transaction)).verification_method == "PROVIDER_API"


def test_amount_03_expires_at_deadline(client, merchant, db, instant):  # noqa: F811
    p = opened(client, merchant, amount=10_003)
    past = utcnow() - timedelta(seconds=1)
    db.get(Payment, p["id"]).expires_at = past
    for sim in db.scalars(select(SandboxSimulation)):
        sim.expires_at = past
    db.commit()
    run_once()
    assert status_of(db, p["id"]) == "EXPIRED"


def test_scheduled_outcome_wins_once_due(client, merchant, db, instant):  # noqa: F811
    """Polls and the Simulate panel see the same provider state: the first decision is final."""
    p = opened(client, merchant, amount=10_000)
    r = simulate(client, p, "FAILED")  # the x.00 success is already due
    assert r.status_code in (200, 409)
    poll_all(db)
    assert status_of(db, p["id"]) == "SUCCESS"
    assert count(db, ReconciliationRecord, ReconciliationRecord.status == "INVESTIGATION_REQUIRED") == 0


# ---------------------------------------------------------------- refunds
def test_full_refund(client, merchant, paid, db, instant):  # noqa: F811
    r = refund(client, merchant, paid["id"], reason="Customer returned item")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "PROCESSING" and body["amount"] == 49_900 and body["provider_refund_ref"].startswith("sbxr_")
    assert status_of(db, paid["id"]) == "REFUND_PENDING"
    poll_all(db)
    db.expire_all()
    assert db.get(Refund, body["id"]).status == "SUCCESS"
    p = db.get(Payment, paid["id"])
    assert p.status == "REFUNDED" and p.amount_refunded == 49_900
    txns = sorted((t.type, t.amount) for t in db.scalars(select(Transaction)))
    assert txns == [("PAYMENT", 49_900), ("REFUND", 49_900)]
    assert client.get(f"/api/v1/refunds/{body['id']}", headers=merchant["headers"]).json()["status"] == "SUCCESS"
    assert refund(client, merchant, paid["id"], key="r2").json()["error"]["code"] == "PAYMENT_NOT_REFUNDABLE"


def test_partial_refunds(client, merchant, paid, db, instant):  # noqa: F811
    assert refund(client, merchant, paid["id"], key="a", amount=20_000).status_code == 201
    r = refund(client, merchant, paid["id"], key="b", amount=100)
    assert r.status_code == 409 and r.json()["error"]["code"] == "REFUND_IN_PROGRESS"
    poll_all(db)
    assert status_of(db, paid["id"]) == "PARTIALLY_REFUNDED"
    r = refund(client, merchant, paid["id"], key="c", amount=30_000)
    assert r.status_code == 422 and r.json()["error"]["details"]["refundable"] == 29_900
    assert refund(client, merchant, paid["id"], key="d").json()["amount"] == 29_900  # the rest
    poll_all(db)
    assert status_of(db, paid["id"]) == "REFUNDED"
    lst = client.get(f"/api/v1/payments/{paid['id']}/refunds", headers=merchant["headers"]).json()
    assert [(x["amount"], x["status"]) for x in lst] == [(20_000, "SUCCESS"), (29_900, "SUCCESS")]


def test_failed_refund_restores_payment(client, merchant, paid, db, instant):  # noqa: F811
    r = refund(client, merchant, paid["id"], amount=1_001)  # sandbox: refund amounts ending .01 fail
    poll_all(db)
    db.expire_all()
    rf = db.get(Refund, r.json()["id"])
    assert rf.status == "FAILED" and "simulated" in rf.failure_reason
    p = db.get(Payment, paid["id"])
    assert p.status == "SUCCESS" and p.amount_refunded == 0
    assert count(db, Transaction, Transaction.type == "REFUND") == 0


def test_refund_provider_error(client, merchant, paid, db, monkeypatch):  # noqa: F811
    def down(*a, **k):
        raise ProviderError("refund API down")

    monkeypatch.setattr(SandboxProvider, "create_refund", down)
    r = refund(client, merchant, paid["id"])
    assert r.status_code == 201 and r.json()["status"] == "FAILED" and "refund API down" in r.json()["failure_reason"]
    assert status_of(db, paid["id"]) == "SUCCESS"


def test_refund_idempotency(client, merchant, paid, db):  # noqa: F811
    a = refund(client, merchant, paid["id"], amount=100)
    b = refund(client, merchant, paid["id"], amount=100)
    assert b.status_code == 200 and b.headers["Idempotent-Replayed"] == "true" and a.json()["id"] == b.json()["id"]
    c = refund(client, merchant, paid["id"], amount=200)
    assert c.status_code == 409 and c.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert count(db, Refund) == 1


def test_refund_rules(client, merchant, db):  # noqa: F811
    p = create(client, merchant).json()
    assert refund(client, merchant, p["id"]).json()["error"]["code"] == "PAYMENT_NOT_REFUNDABLE"
    assert refund(client, merchant, "pay_nope").status_code == 404
    assert client.post("/api/v1/refunds", json={"payment_id": p["id"]}, headers=merchant["headers"]).status_code == 400
    assert refund(client, merchant, p["id"], amount=0).status_code == 422


def test_concurrent_refunds_only_one_proceeds(client, merchant, paid, db):  # noqa: F811
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: refund(client, merchant, paid["id"], key=f"cr{i}", amount=10_000), range(6)))
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and all(c == 409 for c in codes if c != 201), [r.text for r in results]
    assert count(db, Refund) == 1


def test_console_refund(client, merchant, paid, db, instant):  # noqa: F811
    h = auth(merchant["token"])
    r = client.post(f"/api/merchant/payments/{paid['id']}/refunds", json={"amount": 10_000, "reason": "goodwill"},
                    headers={**h, "Idempotency-Key": "console-1"})
    assert r.status_code == 201 and r.json()["refunds"][0]["amount"] == 10_000
    assert client.post(f"/api/merchant/payments/{paid['id']}/refunds", json={}, headers=h).status_code == 400
    make_user(db, email="viewer@sharma.example.com", role="MERCHANT_VIEWER", merchant_id=merchant["id"])
    t = login(client, "viewer@sharma.example.com")
    r = client.post(f"/api/merchant/payments/{paid['id']}/refunds", json={}, headers={**auth(t), "Idempotency-Key": "v"})
    assert r.status_code == 403


# ---------------------------------------------------------------- full lifecycle
def test_full_sandbox_lifecycle(client, merchant, db, monkeypatch, instant):  # noqa: F811
    """create → checkout → pay (simulated) → verified → webhook delivered → partial refund → full refund."""
    received = []

    def endpoint(request: httpx.Request) -> httpx.Response:
        received.append(json.loads(request.content))
        return httpx.Response(200)

    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(endpoint))
    monkeypatch.setattr(webhooks, "_resolve", lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", port))])
    client.put("/api/merchant/webhooks/TEST", headers=auth(merchant["token"]), json={
        "url": "https://shop.example.com/hooks",
        "events": ["payment.created", "payment.initiated", "payment.success", "payment.refund_initiated", "payment.refunded"],
    })

    p = opened(client, merchant, amount=120_037)  # no automatic outcome: the customer "pays" via Simulate
    assert simulate(client, p, "SUCCESS").json()["status"] == "SUCCESS"
    assert client.post(f"/api/v1/payments/{p['id']}/verify", headers=merchant["headers"]).json()["status"] == "SUCCESS"
    run_once()

    refund(client, merchant, p["id"], key="life-1", amount=20_037)
    poll_all(db)
    refund(client, merchant, p["id"], key="life-2")
    poll_all(db)
    run_once()

    final = db.get(Payment, p["id"])
    db.refresh(final)
    assert final.status == "REFUNDED" and final.amount_refunded == 120_037
    ledger = sorted((t.type, t.amount) for t in db.scalars(select(Transaction)))
    assert ledger == [("PAYMENT", 120_037), ("REFUND", 20_037), ("REFUND", 100_000)]
    assert db.scalar(select(ReconciliationRecord)).status == "NOT_RECONCILED"  # bank credit is a separate step

    types = [e["type"] for e in received]
    assert types == ["payment.created", "payment.initiated", "payment.success", "payment.refund_initiated",
                     "payment.refunded", "payment.refund_initiated", "payment.refunded"]
    last = received[-1]["data"]
    assert last["payment"]["status"] == "REFUNDED" and last["refund"]["amount"] == 100_000
    assert all(d.status == "DELIVERED" for d in db.scalars(select(WebhookDelivery)))
