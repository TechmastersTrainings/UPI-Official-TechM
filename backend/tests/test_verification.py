"""Phase 5: verification engine, provider callbacks, status polling, ledger and outbound webhooks."""

import hashlib
import hmac
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from app.db.session import get_sessionmaker
from app.db.types import utcnow
from app.models import (
    Payment,
    PaymentAttempt,
    PaymentEvent,
    ProviderCallback,
    ReconciliationRecord,
    Transaction,
    WebhookConfiguration,
    WebhookDelivery,
)
from app.providers.base import ProviderError, ProviderState, ProviderStatus
from app.providers.sandbox import SandboxProvider, sign_callback
from app.services import verification, webhooks
from tests.conftest import auth
from tests.test_checkout import _token, payment  # noqa: F401  (fixture)
from tests.test_payments import create, merchant  # noqa: F401  (fixture)

AMOUNT = 49_900


# ---------------------------------------------------------------- helpers
@pytest.fixture
def session(client, payment):  # noqa: F811
    v = client.post(f"/api/v1/checkout/{_token(payment)}/initiate").json()
    assert v["status"] == "INITIATED"
    ref = v["session"]["qr_payload"].split("sid=")[1].split("&")[0]
    return {"payment": payment, "ref": ref, "token": _token(payment)}


_seq = {"n": 0}


def callback(client, ref, state="SUCCESS", *, event_id=None, sign=True, **fields):
    _seq["n"] += 1
    body = {"event_id": event_id or f"evt_test_{_seq['n']}", "session_ref": ref, "state": state}
    if state == "SUCCESS":
        body |= {"amount": AMOUNT, "currency": "INR", "provider_transaction_id": "sbx_txn_001",
                 "bank_reference": "RRN123456", "payer_vpa": "asha.verma@okaxis"}
    body |= fields
    raw = json.dumps(body).encode()
    headers = {"Content-Type": "application/json"}
    if sign:
        headers["X-Sandbox-Signature"] = sign_callback(raw)
    return client.post("/api/v1/providers/sandbox/callback", content=raw, headers=headers)


def status_of(db, pid):
    db.expire_all()
    return db.get(Payment, pid).status


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


# ---------------------------------------------------------------- callbacks
def test_signed_success_callback_confirms_payment(client, merchant, session, db):  # noqa: F811
    r = callback(client, session["ref"])
    assert r.status_code == 200 and r.json() == {"status": "processed"}
    pid = session["payment"]["id"]
    assert status_of(db, pid) == "SUCCESS"

    txn = db.scalar(select(Transaction).where(Transaction.payment_id == pid))
    assert (txn.amount, txn.currency, txn.provider_transaction_id, txn.bank_reference) == (AMOUNT, "INR", "sbx_txn_001", "RRN123456")
    assert txn.verification_method == "PROVIDER_WEBHOOK" and txn.type == "PAYMENT"
    assert txn.payer_vpa_masked == "as********@okaxis"  # never stored in full
    rec = db.scalar(select(ReconciliationRecord).where(ReconciliationRecord.payment_id == pid))
    assert rec.status == "NOT_RECONCILED" and rec.expected_amount == AMOUNT  # confirmed ≠ bank-credited

    cb = db.scalar(select(ProviderCallback))
    assert cb.signature_valid and cb.processed_at is not None and "asha.verma@okaxis" in cb.body
    p = db.get(Payment, pid)
    assert p.confirmed_at is not None and p.provider_transaction_id == "sbx_txn_001"
    assert db.scalar(select(PaymentAttempt).where(PaymentAttempt.payment_id == pid)).status == "SUCCESS"

    view = client.get(f"/api/v1/checkout/{session['token']}").json()
    assert view["status"] == "SUCCESS" and view["session"] is None and view["return_url"]
    d = client.get(f"/api/merchant/payments/{pid}", headers=auth(merchant["token"])).json()
    assert d["events"][-1]["source"] == "PROVIDER_CALLBACK" and d["transactions"][0]["provider_transaction_id"] == "sbx_txn_001"


def test_duplicate_callback_is_a_no_op(client, session, db):
    assert callback(client, session["ref"], event_id="evt_dup").json()["status"] == "processed"
    assert callback(client, session["ref"], event_id="evt_dup").json()["status"] == "duplicate"
    # Same transaction reported again under a new event id (e.g. provider resend): still one ledger row.
    assert callback(client, session["ref"], event_id="evt_dup_2").json()["status"] == "processed"
    pid = session["payment"]["id"]
    assert count(db, Transaction) == 1
    assert count(db, PaymentEvent, PaymentEvent.payment_id == pid, PaymentEvent.to_status == "SUCCESS",
                 PaymentEvent.from_status.is_not(None)) == 1


@pytest.mark.parametrize("headers", [{}, {"X-Sandbox-Signature": "0" * 64}])
def test_bad_signature_is_stored_and_ignored(client, session, db, headers):
    raw = json.dumps({"event_id": "evt_forged", "session_ref": session["ref"], "state": "SUCCESS", "amount": AMOUNT,
                      "currency": "INR", "provider_transaction_id": "forged"}).encode()
    r = client.post("/api/v1/providers/sandbox/callback", content=raw, headers=headers)
    assert r.status_code == 401
    assert status_of(db, session["payment"]["id"]) == "INITIATED"
    cb = db.scalar(select(ProviderCallback))
    assert cb.signature_valid is False and cb.processed_at is None and "Rejected" in cb.processing_error
    assert count(db, Transaction) == 0


def test_signature_from_another_body_is_rejected(client, session, db):
    good = json.dumps({"event_id": "e1", "session_ref": session["ref"], "state": "FAILED"}).encode()
    evil = json.dumps({"event_id": "e1", "session_ref": session["ref"], "state": "SUCCESS", "amount": AMOUNT,
                       "currency": "INR", "provider_transaction_id": "x"}).encode()
    r = client.post("/api/v1/providers/sandbox/callback", content=evil, headers={"X-Sandbox-Signature": sign_callback(good)})
    assert r.status_code == 401 and status_of(db, session["payment"]["id"]) == "INITIATED"


@pytest.mark.parametrize("fields, field", [
    ({"amount": 100}, "amount"),
    ({"currency": "USD"}, "currency"),
    ({"provider_transaction_id": None}, "provider_transaction_id"),
])
def test_success_with_mismatched_details_is_not_applied(client, merchant, session, db, fields, field):  # noqa: F811
    assert callback(client, session["ref"], **fields).status_code == 200
    callback(client, session["ref"], **fields)  # identical repeat
    pid = session["payment"]["id"]
    assert status_of(db, pid) == "INITIATED" and count(db, Transaction) == 0
    evs = db.scalars(select(PaymentEvent).where(PaymentEvent.payment_id == pid,
                                                PaymentEvent.event_type == "payment.verification_failed")).all()
    assert len(evs) == 1 and evs[0].payload["mismatches"][0]["field"] == field


def test_unknown_session_and_provider(client, db):
    r = callback(client, "sbx_does_not_exist")
    assert r.status_code == 202 and r.json()["status"] == "unknown_session"
    assert db.scalar(select(ProviderCallback)).processing_error
    assert client.post("/api/v1/providers/acme-bank/callback", content=b"{}").status_code == 404
    assert client.post("/api/v1/providers/sandbox/callback", content=b"not json").status_code == 400
    big = b'{"event_id":"a","session_ref":"b","x":"' + b"x" * 70_000 + b'"}'
    assert client.post("/api/v1/providers/sandbox/callback", content=big).status_code == 413


def test_failed_then_late_success_needs_investigation(client, session, db):
    pid = session["payment"]["id"]
    assert callback(client, session["ref"], "FAILED", failure_reason="Customer declined").status_code == 200
    p = db.get(Payment, pid)
    assert p.status == "FAILED" and p.failure_reason == "Customer declined"
    # Money reported after failure is real money: recorded, but the payment is not silently flipped.
    callback(client, session["ref"])
    assert status_of(db, pid) == "FAILED"
    assert count(db, Transaction) == 1
    rec = db.scalar(select(ReconciliationRecord))
    assert rec.status == "INVESTIGATION_REQUIRED" and "after it was FAILED" in rec.mismatch_reason
    assert db.scalar(select(PaymentEvent).where(PaymentEvent.event_type == "payment.investigation_required"))


def test_second_transaction_for_paid_payment_needs_investigation(client, session, db):
    callback(client, session["ref"])
    callback(client, session["ref"], provider_transaction_id="sbx_txn_002")
    assert status_of(db, session["payment"]["id"]) == "SUCCESS"
    statuses = sorted(r.status for r in db.scalars(select(ReconciliationRecord)))
    assert statuses == ["INVESTIGATION_REQUIRED", "NOT_RECONCILED"]


def test_processing_then_success(client, session, db):
    callback(client, session["ref"], "PROCESSING")
    assert status_of(db, session["payment"]["id"]) == "PROCESSING"
    callback(client, session["ref"], "AWAITING_CUSTOMER")  # stale/backwards answer: ignored
    assert status_of(db, session["payment"]["id"]) == "PROCESSING"
    callback(client, session["ref"])
    assert status_of(db, session["payment"]["id"]) == "SUCCESS"


def test_concurrent_confirmations_record_one_transaction(client, session, db):
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda i: callback(client, session["ref"], event_id=f"race_{i}"), range(6)))
    assert all(r.status_code == 200 for r in results), [r.text for r in results]
    assert status_of(db, session["payment"]["id"]) == "SUCCESS"
    assert count(db, Transaction) == 1 and count(db, ReconciliationRecord) == 1


# ---------------------------------------------------------------- polling / verify
def _provider_says(monkeypatch, state, **kw):
    monkeypatch.setattr(SandboxProvider, "fetch_status",
                        lambda *a, **k: ProviderStatus(state, **kw))


def _due(db, pid):
    a = db.scalar(select(PaymentAttempt).where(PaymentAttempt.payment_id == pid))
    a.next_poll_at = utcnow() - timedelta(seconds=1)
    db.commit()
    return a


def test_poll_confirms_success(client, session, db, monkeypatch):
    _provider_says(monkeypatch, ProviderState.SUCCESS, amount=AMOUNT, currency="INR", provider_transaction_id="sbx_poll_1")
    _due(db, session["payment"]["id"])
    with get_sessionmaker()() as s:
        assert verification.poll_due(s) == 1
    assert status_of(db, session["payment"]["id"]) == "SUCCESS"
    assert db.scalar(select(Transaction)).verification_method == "PROVIDER_API"
    a = db.scalar(select(PaymentAttempt))
    assert a.status == "SUCCESS" and a.next_poll_at is None and a.poll_count == 1


def test_poll_backs_off_while_waiting(client, session, db, monkeypatch):
    a = _due(db, session["payment"]["id"])
    with get_sessionmaker()() as s:
        verification.poll_due(s)
        verification.poll_due(s)  # not due again yet
    db.expire_all()
    a = db.get(PaymentAttempt, a.id)
    assert a.poll_count == 1 and a.status == "AWAITING_CUSTOMER"
    assert timedelta(seconds=8) < a.next_poll_at - a.last_polled_at <= timedelta(seconds=10)


def test_poll_survives_provider_outage(client, session, db, monkeypatch):
    def down(*a, **k):
        raise ProviderError("timeout")

    monkeypatch.setattr(SandboxProvider, "fetch_status", down)
    a = _due(db, session["payment"]["id"])
    with get_sessionmaker()() as s:
        verification.poll_due(s)
    db.expire_all()
    a = db.get(PaymentAttempt, a.id)
    assert a.poll_count == 1 and a.next_poll_at > utcnow() and status_of(db, a.payment_id) == "INITIATED"


def test_verify_endpoint(client, merchant, session, db, monkeypatch):  # noqa: F811
    pid = session["payment"]["id"]
    r = client.post(f"/api/v1/payments/{pid}/verify", headers=merchant["headers"])
    assert r.status_code == 200 and r.json()["status"] == "INITIATED"
    _provider_says(monkeypatch, ProviderState.SUCCESS, amount=AMOUNT, currency="INR", provider_transaction_id="sbx_v_1")
    assert client.post(f"/api/v1/payments/{pid}/verify", headers=merchant["headers"]).json()["status"] == "SUCCESS"
    # Ledger API
    lst = client.get("/api/v1/transactions", headers=merchant["headers"]).json()
    assert lst["total"] == 1 and lst["items"][0]["payment_id"] == pid


def test_verify_on_unstarted_payment_is_harmless(client, merchant, payment):  # noqa: F811
    r = client.post(f"/api/v1/payments/{payment['id']}/verify", headers=merchant["headers"])
    assert r.status_code == 200 and r.json()["status"] == "CREATED"


# ---------------------------------------------------------------- outbound webhooks
class Receiver:
    def __init__(self, status=200):
        self.status = status
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        return httpx.Response(self.status, text="ok" if self.status < 300 else "nope")


@pytest.fixture
def receiver(monkeypatch):
    r = Receiver()
    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(r))
    monkeypatch.setattr(webhooks, "_resolve", lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", port))])
    return r


@pytest.fixture
def hook(client, merchant):  # noqa: F811
    r = client.put("/api/merchant/webhooks/TEST", headers=auth(merchant["token"]), json={
        "url": "https://shop.example.com/hooks",
        "events": ["payment.created", "payment.initiated", "payment.success", "payment.failed", "payment.expired"],
    })
    assert r.status_code == 200
    return r.json()["signing_secret"]


def run_deliveries():
    with get_sessionmaker()() as s:
        return webhooks.deliver_due(s)


def test_events_are_signed_and_delivered(client, merchant, hook, receiver, db):  # noqa: F811
    p = create(client, merchant).json()
    v = client.post(f"/api/v1/checkout/{_token(p)}/initiate").json()
    ref = v["session"]["qr_payload"].split("sid=")[1].split("&")[0]
    callback(client, ref)
    assert run_deliveries() == 3
    types = [json.loads(r.content)["type"] for r in receiver.requests]
    assert sorted(types) == ["payment.created", "payment.initiated", "payment.success"]

    req = next(r for r in receiver.requests if json.loads(r.content)["type"] == "payment.success")
    ts, sig = req.headers["X-TM-Timestamp"], req.headers["X-TM-Signature"]
    expected = hmac.new(hook.encode(), f"{ts}.".encode() + req.content, hashlib.sha256).hexdigest()
    assert sig == f"v1={expected}"
    body = json.loads(req.content)
    assert body["id"] == req.headers["X-TM-Event-Id"] and body["data"]["payment"]["status"] == "SUCCESS"
    assert body["environment"] == "TEST"
    assert all(d.status == "DELIVERED" for d in db.scalars(select(WebhookDelivery)))
    assert run_deliveries() == 0


def test_unsubscribed_events_are_not_queued(client, merchant, hook, receiver, db):  # noqa: F811
    p = create(client, merchant).json()
    client.post(f"/api/v1/payments/{p['id']}/cancel", headers=merchant["headers"])  # payment.cancelled not subscribed
    assert [d.event_type for d in db.scalars(select(WebhookDelivery))] == ["payment.created"]


def test_no_webhook_without_configuration(client, merchant, receiver, db):  # noqa: F811
    create(client, merchant)
    assert count(db, WebhookDelivery) == 0


def test_failed_delivery_retries_with_backoff_then_fails(client, merchant, hook, receiver, db):  # noqa: F811
    receiver.status = 500
    create(client, merchant)
    d = db.scalar(select(WebhookDelivery))
    for attempt in range(1, webhooks.MAX_ATTEMPTS + 1):
        d.next_attempt_at = utcnow() - timedelta(seconds=1)
        db.commit()
        run_deliveries()
        db.expire_all()
        d = db.get(WebhookDelivery, d.id)
        assert d.attempt_count == attempt and d.last_response_code == 500
        if attempt < webhooks.MAX_ATTEMPTS:
            assert d.status == "RETRYING"
            delay = (d.next_attempt_at - d.last_attempt_at).total_seconds()
            assert abs(delay - webhooks.RETRY_DELAYS[attempt - 1]) < 2
    assert d.status == "FAILED" and d.next_attempt_at is None
    assert len(receiver.requests) == webhooks.MAX_ATTEMPTS

    # Manual redelivery from the console after the endpoint is fixed.
    receiver.status = 200
    r = client.post(f"/api/merchant/webhook-deliveries/{d.id}/redeliver", headers=auth(merchant["token"]))
    assert r.status_code == 200 and r.json()["status"] == "DELIVERED"
    assert len({json.loads(x.content)["id"] for x in receiver.requests}) == 1  # same event id on every try


def test_redirects_are_not_followed(client, merchant, hook, monkeypatch, db):  # noqa: F811
    monkeypatch.setattr(webhooks, "_transport", httpx.MockTransport(
        lambda req: httpx.Response(302, headers={"Location": "http://169.254.169.254/"})))
    monkeypatch.setattr(webhooks, "_resolve", lambda host, port, **kw: [(2, 1, 6, "", ("93.184.216.34", port))])
    create(client, merchant)
    run_deliveries()
    d = db.scalar(select(WebhookDelivery))
    assert d.status == "RETRYING" and d.last_response_code == 302


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.2.3", "169.254.169.254", "::1"])
def test_live_destinations_must_be_public(monkeypatch, ip):
    monkeypatch.setattr(webhooks, "_resolve", lambda host, port, **kw: [(2, 1, 6, "", (ip, port))])
    with pytest.raises(webhooks.DestinationRefused):
        webhooks.check_destination("https://hooks.example.com/x", "LIVE")
    with pytest.raises(webhooks.DestinationRefused):
        webhooks.check_destination("http://hooks.example.com/x", "LIVE")


def test_webhook_test_event_validates_endpoint(client, merchant, hook, receiver, db):  # noqa: F811
    r = client.post("/api/v1/webhooks/test", headers=merchant["headers"])
    assert r.status_code == 200 and r.json()["status"] == "DELIVERED" and r.json()["event_type"] == "webhook.test"
    assert db.scalar(select(WebhookConfiguration)).validated_at is not None

    # Changing the URL clears validation; a failing test does not validate and does not retry.
    client.put("/api/merchant/webhooks/TEST", headers=auth(merchant["token"]),
               json={"url": "https://shop.example.com/hooks/v2", "events": ["payment.success"]})
    receiver.status = 503
    r = client.post("/api/merchant/webhook-deliveries/test/TEST", headers=auth(merchant["token"]))
    assert r.json()["status"] == "FAILED" and r.json()["last_response_code"] == 503
    db.expire_all()
    assert db.scalar(select(WebhookConfiguration)).validated_at is None


def test_webhook_test_without_endpoint(client, merchant):  # noqa: F811
    r = client.post("/api/v1/webhooks/test", headers=merchant["headers"])
    assert r.status_code == 404 and r.json()["error"]["code"] == "WEBHOOK_NOT_CONFIGURED"


def test_console_deliveries_are_scoped(client, merchant, hook, receiver, db):  # noqa: F811
    p = create(client, merchant).json()
    h = auth(merchant["token"])
    lst = client.get("/api/merchant/webhook-deliveries?environment=TEST", headers=h).json()
    assert lst["total"] == 1 and lst["items"][0]["payment_id"] == p["id"]
    did = lst["items"][0]["id"]
    assert client.get(f"/api/merchant/webhook-deliveries/{did}", headers=h).json()["payload"]["type"] == "payment.created"
    d = client.get(f"/api/merchant/payments/{p['id']}", headers=h).json()
    assert d["webhook_deliveries"][0]["event_type"] == "payment.created"


def test_rolled_back_transition_sends_no_webhook(client, merchant, hook, session, db):  # noqa: F811
    """Outbox: a notification only exists if its status change committed."""
    from app.models.enums import EventSource
    from app.services import payment_state

    before = count(db, WebhookDelivery)
    maker = get_sessionmaker()
    with maker() as a, maker() as b:
        pa, pb = a.get(Payment, session["payment"]["id"]), b.get(Payment, session["payment"]["id"])
        payment_state.transition(a, pa, "FAILED", source=EventSource.PROVIDER_POLL)
        payment_state.transition(b, pb, "SUCCESS", source=EventSource.PROVIDER_POLL)
        a.commit()
        with pytest.raises(Exception):
            payment_state.commit_guarded(b)
    db.expire_all()
    new = [d.event_type for d in db.scalars(select(WebhookDelivery))][before:]
    assert new == ["payment.failed"]
