"""Phase 3: gateway API payments — auth, validation, idempotency, isolation, state machine, expiry,
and concurrency."""

import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.db.session import get_sessionmaker
from app.db.types import utcnow
from app.models import ApiCredential, ApiRequestLog, Merchant, Payment, PaymentEvent
from app.models.enums import EventSource, PaymentStatus
from app.services import payment_state, payments
from tests.conftest import STRONG_PASSWORD, auth, login, make_user, register_merchant

OWNER = "ravi@sharma.example.com"


def owner_token(client):
    return login(client, OWNER, STRONG_PASSWORD)


def basic(key_id: str, secret: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{key_id}:{secret}".encode()).decode()}


@pytest.fixture
def merchant(client):
    m = register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "TEST"})
    assert r.status_code == 201, r.text
    key = r.json()
    return {"id": m["id"], "token": token, "headers": basic(key["key_id"], key["key_secret"]), "key_id": key["key_id"]}


def body(**over) -> dict:
    b = {"merchant_reference": "ORD-1001", "amount": 49_900, "customer": {"name": "Asha", "mobile": "9876543210"}}
    b.update(over)
    return b


def create(client, merchant, key="idem-1", **over):
    return client.post("/api/v1/payments/create", json=body(**over),
                       headers={**merchant["headers"], "Idempotency-Key": key})


# ---------- Authentication ----------
def test_v1_requires_valid_api_key(client, merchant):
    assert client.get("/api/v1/payments").json()["error"]["code"] == "INVALID_API_KEY"
    r = client.get("/api/v1/payments", headers=basic(merchant["key_id"], "tmsk_test_wrong"))
    assert r.status_code == 401 and r.json()["error"]["code"] == "INVALID_API_KEY"
    r = client.get("/api/v1/payments", headers={"Authorization": "Basic !!notbase64"})
    assert r.status_code == 401
    # A dashboard JWT is not an API key.
    assert client.get("/api/v1/payments", headers=auth(merchant["token"])).status_code == 401
    assert client.get("/api/v1/payments", headers=merchant["headers"]).status_code == 200


def test_revoked_key_and_disabled_api_access_are_refused(client, merchant, db):
    assert client.put("/api/merchant/api-access", headers=auth(merchant["token"]), json={"enabled": False}).status_code == 200
    r = client.get("/api/v1/payments", headers=merchant["headers"])
    assert r.status_code == 403 and r.json()["error"]["code"] == "API_ACCESS_DISABLED"
    client.put("/api/merchant/api-access", headers=auth(merchant["token"]), json={"enabled": True})

    cred = db.scalar(select(ApiCredential).where(ApiCredential.key_id == merchant["key_id"]))
    client.post(f"/api/merchant/api-credentials/{cred.id}/revoke", headers=auth(merchant["token"]))
    assert client.get("/api/v1/payments", headers=merchant["headers"]).status_code == 401


def test_repeated_auth_failures_are_rate_limited(client, merchant):
    bad = basic(merchant["key_id"], "tmsk_test_wrong")
    codes = [client.get("/api/v1/payments", headers=bad).status_code for _ in range(25)]
    assert codes[0] == 401 and codes[-1] == 429


# ---------- Create ----------
def test_create_payment(client, merchant, db):
    r = create(client, merchant, notes={"cart": "42"})
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["id"].startswith("pay_")
    assert p["status"] == "CREATED" and p["environment"] == "TEST"
    assert p["amount"] == 49_900 and p["currency"] == "INR" and p["payment_method"] == "HOSTED"
    assert p["customer"] == {"name": "Asha", "mobile": "9876543210", "email": None}
    assert p["confirmed_at"] is None and p["notes"] == {"cart": "42"}
    assert "checkout_token" not in p and "request_hash" not in p and "idempotency_key" not in p

    row = db.get(Payment, p["id"])
    assert row.provider_code == "sandbox" and row.version == 1
    events = db.scalars(select(PaymentEvent).where(PaymentEvent.payment_id == p["id"])).all()
    assert [e.event_type for e in events] == ["payment.created"]
    assert events[0].payload["key_id"] == merchant["key_id"]


def test_default_and_custom_expiry(client, merchant):
    before = utcnow()
    p = create(client, merchant).json()
    from datetime import datetime

    exp = datetime.fromisoformat(p["expires_at"])
    assert timedelta(seconds=890) < exp - before < timedelta(seconds=910)
    p2 = create(client, merchant, key="k2", merchant_reference="ORD-2", expires_in_seconds=120).json()
    assert datetime.fromisoformat(p2["expires_at"]) - before < timedelta(seconds=130)


@pytest.mark.parametrize("over, field", [
    ({"amount": 99}, "amount"),
    ({"amount": 10_000_001}, "amount"),
    ({"amount": 100.5}, "amount"),
    ({"currency": "USD"}, "currency"),
    ({"payment_method": "CARD"}, "payment_method"),
    ({"merchant_reference": "bad ref with spaces"}, "merchant_reference"),
    ({"expires_in_seconds": 30}, "expires_in_seconds"),
    ({"expires_in_seconds": 90_000}, "expires_in_seconds"),
    ({"customer": {"mobile": "12345"}}, "customer.mobile"),
    ({"notes": {f"k{i}": "v" for i in range(16)}}, "notes"),
    ({"status": "SUCCESS"}, "status"),  # clients can never set status
    ({"return_url": "javascript:alert(1)"}, "return_url"),
])
def test_create_validation(client, merchant, over, field):
    r = create(client, merchant, **over)
    assert r.status_code == 422, r.text
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"
    assert any(d["field"].startswith(field) for d in r.json()["error"]["details"])


def test_webhook_url_must_match_registered_endpoint(client, merchant):
    r = create(client, merchant, webhook_url="https://shop.example.com/hooks/pay")
    assert r.status_code == 422 and "register" in r.json()["error"]["details"][0]["message"]
    client.put("/api/merchant/webhooks/TEST", headers=auth(merchant["token"]),
               json={"url": "https://shop.example.com/hooks", "events": ["payment.success"]})
    r = create(client, merchant, webhook_url="https://evil.example.net/hooks")
    assert r.status_code == 422
    r = create(client, merchant, webhook_url="https://shop.example.com/hooks/order-77")
    assert r.status_code == 201 and r.json()["webhook_url"].endswith("order-77")


def test_idempotency_key_required_and_validated(client, merchant):
    r = client.post("/api/v1/payments/create", json=body(), headers=merchant["headers"])
    assert r.status_code == 400 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_REQUIRED"
    r = create(client, merchant, key="has spaces")
    assert r.status_code == 400 and r.json()["error"]["code"] == "IDEMPOTENCY_KEY_INVALID"


def test_auth_is_checked_before_idempotency_key(client):
    r = client.post("/api/v1/payments/create", json=body())
    assert r.status_code == 401


# ---------- Idempotency ----------
def test_idempotent_replay_returns_original(client, merchant, db):
    first = create(client, merchant)
    # Same semantic body with different key order / formatting.
    again = client.post(
        "/api/v1/payments/create",
        content='{"amount":49900,"customer":{"mobile":"+91 98765 43210","name":"Asha"},"merchant_reference":"ORD-1001"}',
        headers={**merchant["headers"], "Idempotency-Key": "idem-1", "Content-Type": "application/json"},
    )
    assert again.status_code == 200 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json()["id"] == first.json()["id"]
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_idempotency_conflict_on_different_body(client, merchant):
    create(client, merchant)
    r = create(client, merchant, amount=50_000)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_duplicate_merchant_reference_rejected(client, merchant):
    assert create(client, merchant).status_code == 201
    r = create(client, merchant, key="idem-other")
    assert r.status_code == 409 and r.json()["error"]["code"] == "DUPLICATE_MERCHANT_REFERENCE"


def test_idempotency_race_resolved_by_unique_constraint(client, merchant, monkeypatch):
    """Simulate a concurrent request that inserts between our lookup and our insert."""
    first = create(client, merchant).json()
    real = payments._by_idempotency_key
    calls = {"n": 0}

    def stale_lookup(*a, **kw):
        calls["n"] += 1
        return None if calls["n"] == 1 else real(*a, **kw)

    monkeypatch.setattr(payments, "_by_idempotency_key", stale_lookup)
    monkeypatch.setattr(payments, "_check_urls", lambda *a, **kw: None)
    # Skip the pre-insert reference check too, so the INSERT itself hits the unique constraint.
    monkeypatch.setattr(payments, "select", _select_without_reference_check(payments.select))
    r = create(client, merchant)
    assert r.status_code == 200 and r.json()["id"] == first["id"]
    r = create(client, merchant, amount=1_000)
    assert r.status_code == 409 and r.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def _select_without_reference_check(real_select):
    def patched(*cols, **kw):
        if len(cols) == 1 and getattr(cols[0], "key", None) == "id" and getattr(cols[0], "class_", None) is Payment:
            return real_select(Payment.id).where(Payment.id.is_(None))
        return real_select(*cols, **kw)

    return patched


def test_concurrent_creates_with_same_key_make_one_payment(client, merchant, db):
    def go(_):
        return create(client, merchant, key="race-key")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(go, range(8)))
    codes = sorted(r.status_code for r in results)
    assert codes.count(201) == 1 and codes.count(200) == 7, [r.text for r in results if r.status_code >= 300]
    assert len({r.json()["id"] for r in results}) == 1
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


def test_concurrent_creates_with_same_reference_make_one_payment(client, merchant, db):
    def go(i):
        return create(client, merchant, key=f"ref-race-{i}")

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(go, range(8)))
    codes = [r.status_code for r in results]
    assert codes.count(201) == 1 and codes.count(409) == 7
    assert {r.json()["error"]["code"] for r in results if r.status_code == 409} == {"DUPLICATE_MERCHANT_REFERENCE"}
    assert db.scalar(select(func.count()).select_from(Payment)) == 1


# ---------- Isolation ----------
def test_test_key_cannot_see_live_or_other_merchants_payments(client, merchant, db):
    own = create(client, merchant).json()
    # A LIVE payment row for the same merchant (inserted directly; LIVE creation needs a live provider).
    live = Payment(
        merchant_id=merchant["id"], environment="LIVE", merchant_reference="L-1", amount=100, currency="INR",
        payment_method="HOSTED", expires_at=utcnow() + timedelta(minutes=5), idempotency_key="l1",
        request_hash="x" * 64, checkout_token="live-token-1",
    )
    db.add(live)
    db.commit()
    assert client.get(f"/api/v1/payments/{live.id}", headers=merchant["headers"]).status_code == 404
    listing = client.get("/api/v1/payments", headers=merchant["headers"]).json()
    assert [p["id"] for p in listing["items"]] == [own["id"]]

    other = register_merchant(
        client,
        business={"business_email": "a@other.example.com", "business_name": "Other Shop"},
        owner={"email": "o@other.example.com"},
    )
    t2 = login(client, "o@other.example.com", STRONG_PASSWORD)
    k2 = client.post("/api/merchant/api-credentials", headers=auth(t2), json={"environment": "TEST"}).json()
    h2 = basic(k2["key_id"], k2["key_secret"])
    assert client.get(f"/api/v1/payments/{own['id']}", headers=h2).status_code == 404
    assert client.post(f"/api/v1/payments/{own['id']}/cancel", headers=h2).status_code == 404
    # Same merchant_reference is fine for a different merchant.
    r = client.post("/api/v1/payments/create", json=body(), headers={**h2, "Idempotency-Key": "idem-1"})
    assert r.status_code == 201
    assert other["id"] != merchant["id"]


def test_live_key_cannot_create_without_live_provider(client, merchant, db):
    m = db.get(Merchant, merchant["id"])
    m.status, m.live_enabled = "ACTIVE", True
    db.commit()
    token = owner_token(client)
    k = client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "LIVE"}).json()
    r = client.post("/api/v1/payments/create", json=body(),
                    headers={**basic(k["key_id"], k["key_secret"]), "Idempotency-Key": "live-1"})
    # The sandbox provider is TEST-only, so nothing can collect live money yet.
    assert r.status_code == 409 and r.json()["error"]["code"] == "NO_ACTIVE_PROVIDER"


# ---------- Read / cancel ----------
def test_get_status_and_list(client, merchant):
    p = create(client, merchant).json()
    create(client, merchant, key="k2", merchant_reference="ORD-2")
    s = client.get(f"/api/v1/payments/{p['id']}/status", headers=merchant["headers"]).json()
    assert (s["id"], s["status"], s["amount"], s["merchant_reference"]) == (p["id"], "CREATED", 49_900, "ORD-1001")
    lst = client.get("/api/v1/payments?page_size=1", headers=merchant["headers"]).json()
    assert lst["total"] == 2 and len(lst["items"]) == 1
    lst = client.get("/api/v1/payments?merchant_reference=ORD-1001", headers=merchant["headers"]).json()
    assert [i["id"] for i in lst["items"]] == [p["id"]]
    assert client.get("/api/v1/payments?status=BOGUS", headers=merchant["headers"]).status_code == 422


def test_cancel_payment_is_idempotent(client, merchant, db):
    p = create(client, merchant).json()
    r = client.post(f"/api/v1/payments/{p['id']}/cancel", headers=merchant["headers"], json={"reason": "customer left"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    r = client.post(f"/api/v1/payments/{p['id']}/cancel", headers=merchant["headers"])
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    events = payments.events(db, p["id"])
    assert [(e.from_status, e.to_status) for e in events] == [(None, "CREATED"), ("CREATED", "CANCELLED")]
    assert events[1].payload == {"reason": "customer left", "by": merchant["key_id"]}


def test_cannot_cancel_after_expiry(client, merchant, db):
    p = create(client, merchant).json()
    row = db.get(Payment, p["id"])
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    r = client.post(f"/api/v1/payments/{p['id']}/cancel", headers=merchant["headers"])
    assert r.status_code == 409 and r.json()["error"]["code"] == "PAYMENT_NOT_CANCELLABLE"


# ---------- Expiry ----------
def test_read_expires_overdue_created_payment(client, merchant, db):
    p = create(client, merchant).json()
    row = db.get(Payment, p["id"])
    row.expires_at = utcnow() - timedelta(seconds=1)
    db.commit()
    r = client.get(f"/api/v1/payments/{p['id']}/status", headers=merchant["headers"])
    assert r.json()["status"] == "EXPIRED"


def test_expiry_job(client, merchant, db):
    ids = [create(client, merchant, key=f"e{i}", merchant_reference=f"E-{i}").json()["id"] for i in range(3)]
    for pid in ids[:2]:
        db.get(Payment, pid).expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    with get_sessionmaker()() as s:
        assert payments.expire_due(s, batch_size=1) == 2
        assert payments.expire_due(s) == 0  # already done; second run is a no-op
    db.expire_all()
    assert [db.get(Payment, i).status for i in ids] == ["EXPIRED", "EXPIRED", "CREATED"]
    ev = payments.events(db, ids[0])[-1]
    assert ev.source == "SYSTEM" and ev.to_status == "EXPIRED"


def test_expiry_does_not_touch_payments_with_a_provider_session(client, merchant, db):
    """Once a provider session exists the customer may have paid; only the provider can settle it."""
    p = create(client, merchant).json()
    row = db.get(Payment, p["id"])
    payment_state.transition(db, row, PaymentStatus.INITIATED, source=EventSource.CHECKOUT)
    row.expires_at = utcnow() - timedelta(minutes=1)
    db.commit()
    with get_sessionmaker()() as s:
        assert payments.expire_due(s) == 0
    db.expire_all()
    assert db.get(Payment, p["id"]).status == "INITIATED"


# ---------- State machine ----------
def _payment(db, merchant_id, status="CREATED"):
    p = Payment(
        merchant_id=merchant_id, environment="TEST", merchant_reference=f"SM-{utcnow().timestamp()}", amount=100,
        currency="INR", payment_method="HOSTED", expires_at=utcnow() + timedelta(minutes=5),
        idempotency_key=f"sm-{utcnow().timestamp()}", request_hash="x" * 64,
        checkout_token=f"tok-{utcnow().timestamp()}", status=status,
    )
    db.add(p)
    db.commit()
    return p


@pytest.mark.parametrize("path", [
    ["INITIATED", "PENDING", "PROCESSING", "SUCCESS"],
    ["INITIATED", "SUCCESS"],
    ["INITIATED", "PENDING", "FAILED"],
    ["INITIATED", "PENDING", "EXPIRED"],
])
def test_valid_paths(merchant, db, path):
    p = _payment(db, merchant["id"])
    for target in path:
        source = {"INITIATED": EventSource.CHECKOUT, "EXPIRED": EventSource.SYSTEM}.get(target, EventSource.PROVIDER_POLL)
        payment_state.transition(db, p, target, source=source)
        db.commit()
    assert p.status == path[-1]
    if path[-1] == "SUCCESS":
        assert p.confirmed_at is not None and p.initiated_at is not None
    assert len(payments.events(db, p.id)) == len(path)


@pytest.mark.parametrize("start, target", [
    ("CREATED", "SUCCESS"),       # cannot skip the provider session
    ("CREATED", "PENDING"),
    ("SUCCESS", "FAILED"),        # final states are final
    ("FAILED", "SUCCESS"),
    ("EXPIRED", "SUCCESS"),       # a late success must go to reconciliation, not silently apply
    ("CANCELLED", "INITIATED"),
    ("PROCESSING", "EXPIRED"),    # money may be moving; only the provider can end it
    ("REFUNDED", "SUCCESS"),
])
def test_invalid_transitions_rejected(merchant, db, start, target):
    p = _payment(db, merchant["id"], status=start)
    with pytest.raises(payment_state.InvalidTransition):
        payment_state.transition(db, p, target, source=EventSource.PROVIDER_POLL)


@pytest.mark.parametrize("source", [EventSource.MERCHANT_API, EventSource.CHECKOUT, EventSource.ADMIN, EventSource.SYSTEM])
def test_only_provider_can_mark_success(merchant, db, source):
    p = _payment(db, merchant["id"], status="PENDING")
    with pytest.raises(payment_state.InvalidTransition) as exc:
        payment_state.transition(db, p, PaymentStatus.SUCCESS, source=source)
    assert exc.value.code == "TRANSITION_SOURCE_NOT_ALLOWED"


def test_transition_table_covers_every_status():
    assert set(payment_state.TRANSITIONS) == {s.value for s in PaymentStatus}
    for target in {t for nxt in payment_state.TRANSITIONS.values() for t in nxt}:
        assert target in payment_state.ALLOWED_SOURCES


# ---------- Concurrency (optimistic locking) ----------
def test_concurrent_transitions_only_one_wins(merchant, db):
    """A provider callback and a status poll race to finish the same payment."""
    p = _payment(db, merchant["id"], status="PENDING")
    maker = get_sessionmaker()
    with maker() as a, maker() as b:
        pa, pb = a.get(Payment, p.id), b.get(Payment, p.id)
        payment_state.transition(a, pa, PaymentStatus.SUCCESS, source=EventSource.PROVIDER_CALLBACK)
        payment_state.transition(b, pb, PaymentStatus.FAILED, source=EventSource.PROVIDER_POLL)
        payment_state.commit_guarded(a)
        with pytest.raises(Exception) as exc:
            payment_state.commit_guarded(b)
        assert getattr(exc.value, "code", None) == "PAYMENT_CONCURRENT_UPDATE"
    db.expire_all()
    final = db.get(Payment, p.id)
    assert final.status == "SUCCESS" and final.version == 2
    assert [e.to_status for e in payments.events(db, p.id)] == ["SUCCESS"]  # loser's event rolled back


def test_cancel_racing_expiry(client, merchant, db):
    p = create(client, merchant).json()
    maker = get_sessionmaker()
    with maker() as a, maker() as b:
        pa, pb = a.get(Payment, p["id"]), b.get(Payment, p["id"])
        pb.expires_at  # load
        payment_state.transition(a, pa, PaymentStatus.CANCELLED, source=EventSource.MERCHANT_API)
        payment_state.commit_guarded(a)
        pb.expires_at = utcnow() - timedelta(seconds=1)
        payments.expire_if_due(b, pb)  # loses the race quietly and reloads the winner's state
        assert pb.status == "CANCELLED"


# ---------- Request logs & consoles ----------
def test_api_requests_are_logged_for_the_merchant(client, merchant):
    create(client, merchant)
    create(client, merchant, amount=1)  # 422
    r = client.get("/api/merchant/api-request-logs", headers=auth(merchant["token"])).json()
    assert r["total"] == 2
    codes = {(i["status_code"], i["error_code"]) for i in r["items"]}
    assert codes == {(201, None), (422, "VALIDATION_ERROR")}
    assert all(i["idempotency_key"] == "idem-1" and i["environment"] == "TEST" for i in r["items"])


def test_unauthenticated_requests_are_not_stored(client, merchant, db):
    client.get("/api/v1/payments")
    assert db.scalar(select(func.count()).select_from(ApiRequestLog)) == 0


def test_merchant_console_payments(client, merchant):
    p = create(client, merchant).json()
    h = auth(merchant["token"])
    lst = client.get("/api/merchant/payments?environment=TEST", headers=h).json()
    assert lst["total"] == 1 and lst["items"][0]["id"] == p["id"]
    assert client.get("/api/merchant/payments?environment=LIVE", headers=h).json()["total"] == 0
    d = client.get(f"/api/merchant/payments/{p['id']}", headers=h).json()
    assert d["events"][0]["event_type"] == "payment.created" and d["provider_code"] == "sandbox"
    r = client.post(f"/api/merchant/payments/{p['id']}/cancel", headers=h, json={"reason": "duplicate order"})
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"


def test_merchant_viewer_cannot_cancel(client, merchant, db):
    make_user(db, email="viewer@sharma.example.com", role="MERCHANT_VIEWER", merchant_id=merchant["id"])
    p = create(client, merchant).json()
    t = login(client, "viewer@sharma.example.com")
    assert client.get(f"/api/merchant/payments/{p['id']}", headers=auth(t)).status_code == 200
    assert client.post(f"/api/merchant/payments/{p['id']}/cancel", headers=auth(t)).status_code == 403


def test_admin_payments(client, merchant, db):
    p = create(client, merchant).json()
    make_user(db)
    t = login(client)
    lst = client.get("/api/admin/payments?environment=TEST", headers=auth(t)).json()
    assert lst["total"] == 1 and lst["items"][0]["merchant_name"] == "Sharma Electronics"
    assert client.get("/api/admin/payments?environment=LIVE", headers=auth(t)).json()["total"] == 0
    d = client.get(f"/api/admin/payments/{p['id']}", headers=auth(t)).json()
    assert d["merchant_name"] == "Sharma Electronics" and len(d["events"]) == 1
    # Merchant users can't use admin endpoints.
    assert client.get("/api/admin/payments", headers=auth(merchant["token"])).status_code == 403
