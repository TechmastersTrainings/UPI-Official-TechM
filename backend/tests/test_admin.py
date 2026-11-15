from datetime import timedelta

from app.db.types import utcnow
from app.models import Merchant, Payment, Refund, Transaction
from tests.conftest import STRONG_PASSWORD, auth, login, make_user


def _merchant(db, email="shop@example.com", status="ACTIVE"):
    m = Merchant(
        business_name="Shop", legal_business_name="Shop Pvt Ltd", business_email=email,
        mobile="9876543210", business_type="RETAIL", status=status,
    )
    db.add(m)
    db.flush()
    return m


def _payment(db, m, *, env="LIVE", status="SUCCESS", amount=10000, ref, confirmed=True, created=None, refunded=0):
    now = utcnow()
    p = Payment(
        merchant_id=m.id, environment=env, merchant_reference=ref, amount=amount, amount_refunded=refunded,
        currency="INR", status=status, payment_method="UPI_QR", expires_at=now + timedelta(minutes=15),
        idempotency_key=f"idem-{ref}", request_hash="h" * 64, checkout_token=f"tok-{ref}",
        confirmed_at=now if confirmed else None, created_at=created or now,
    )
    db.add(p)
    db.flush()
    return p


def test_dashboard_requires_auth_and_permission(client, db):
    assert client.get("/api/admin/dashboard/summary").status_code == 401
    make_user(db, email="support@example.com", role="PLATFORM_SUPPORT")
    token = login(client, email="support@example.com")
    assert client.get("/api/admin/dashboard/summary", headers=auth(token)).status_code == 200
    r = client.get("/api/admin/audit-logs", headers=auth(token))
    assert r.status_code == 403 and r.json()["error"]["code"] == "PERMISSION_DENIED"
    assert client.post("/api/admin/users", headers=auth(token), json={}).status_code in (403, 422)


def test_dashboard_empty_state_is_zero(client, db):
    make_user(db)
    s = client.get("/api/admin/dashboard/summary", headers=auth(login(client))).json()
    assert s["merchants"] == {"total": 0, "active": 0, "live_enabled": 0}
    assert s["payments"]["total"] == 0 and s["collection"]["total_amount"] == 0


def test_dashboard_aggregates_are_environment_isolated(client, db):
    make_user(db)
    m = _merchant(db)
    _merchant(db, email="pending@example.com", status="PENDING_REVIEW")
    _payment(db, m, ref="l1", amount=50000)
    _payment(db, m, ref="l2", amount=25000, status="PARTIALLY_REFUNDED", refunded=5000)
    _payment(db, m, ref="l3", status="FAILED", confirmed=False)
    _payment(db, m, ref="l4", status="PENDING", confirmed=False)
    old = _payment(db, m, ref="l5", amount=7000, created=utcnow() - timedelta(days=40))
    old.confirmed_at = utcnow() - timedelta(days=40)
    _payment(db, m, ref="t1", env="TEST", amount=99900)
    p1 = db.query(Payment).filter_by(merchant_reference="l1").one()
    db.add(Transaction(
        payment_id=p1.id, merchant_id=m.id, environment="LIVE", type="PAYMENT", amount=50000, currency="INR",
        provider_code="sandbox", provider_transaction_id="ptx1", verification_method="PROVIDER_API", verified_at=utcnow(),
    ))
    db.add(Refund(
        payment_id=p1.id, merchant_id=m.id, environment="LIVE", amount=5000, currency="INR", status="SUCCESS",
        idempotency_key="r1", request_hash="h" * 64,
    ))
    db.commit()

    token = login(client)
    live = client.get("/api/admin/dashboard/summary?environment=LIVE", headers=auth(token)).json()
    assert live["merchants"] == {"total": 2, "active": 1, "live_enabled": 0}
    assert live["payments"]["total"] == 5
    assert live["payments"]["successful"] == 3
    assert live["payments"]["failed"] == 1 and live["payments"]["pending"] == 1
    assert live["collection"]["total_amount"] == 82000
    assert live["collection"]["refunded_amount"] == 5000
    assert live["collection"]["net_amount"] == 77000
    assert live["collection"]["today_amount"] == 75000
    assert live["upi_transactions"] == 1
    assert live["refunds"]["total"] == 1 and live["refunds"]["succeeded_amount"] == 5000
    assert live["environment_counts"] == {"TEST": 1, "LIVE": 5}

    test = client.get("/api/admin/dashboard/summary?environment=TEST", headers=auth(token)).json()
    assert test["payments"]["total"] == 1 and test["collection"]["total_amount"] == 99900
    assert test["upi_transactions"] == 0

    assert client.get("/api/admin/dashboard/summary?environment=PROD", headers=auth(token)).status_code == 422


def test_timeseries_buckets(client, db):
    make_user(db)
    m = _merchant(db)
    _payment(db, m, ref="a", amount=1000)
    _payment(db, m, ref="b", status="FAILED", confirmed=False)
    _payment(db, m, ref="c", amount=2000, created=utcnow() - timedelta(days=2))
    db.commit()
    data = client.get("/api/admin/dashboard/timeseries?days=7", headers=auth(login(client))).json()
    pts = data["points"]
    assert len(pts) == 7
    assert pts[-1]["created"] == 2 and pts[-1]["successful"] == 1 and pts[-1]["failed"] == 1
    assert pts[-1]["collected_amount"] == 1000
    assert sum(p["collected_amount"] for p in pts) == 3000


def test_activity_feed(client, db):
    make_user(db)
    m = _merchant(db)
    _payment(db, m, ref="x1")
    db.commit()
    data = client.get("/api/admin/dashboard/activity", headers=auth(login(client))).json()
    assert data["recent_payments"][0]["merchant_name"] == "Shop"
    assert any(a["action"] == "auth.login" for a in data["recent_audit"])


def test_audit_log_listing_and_filters(client, db):
    make_user(db)
    token = login(client)
    r = client.get("/api/admin/audit-logs?action=auth.", headers=auth(token)).json()
    assert r["total"] >= 1 and all(i["action"].startswith("auth.") for i in r["items"])
    r = client.get("/api/admin/audit-logs?action=user.created", headers=auth(token)).json()
    assert r["total"] == 1 and r["items"][0]["actor_label"] == "cli"


def test_platform_user_management(client, db):
    admin = make_user(db)
    token = login(client)
    r = client.post(
        "/api/admin/users", headers=auth(token),
        json={"email": "ops@example.com", "full_name": "Ops", "password": STRONG_PASSWORD, "role": "PLATFORM_ADMIN"},
    )
    assert r.status_code == 201, r.text
    ops_id = r.json()["id"]
    dup = client.post(
        "/api/admin/users", headers=auth(token),
        json={"email": "ops@example.com", "full_name": "Ops", "password": STRONG_PASSWORD, "role": "PLATFORM_ADMIN"},
    )
    assert dup.status_code == 409
    bad_role = client.post(
        "/api/admin/users", headers=auth(token),
        json={"email": "m@example.com", "full_name": "M", "password": STRONG_PASSWORD, "role": "MERCHANT_ADMIN"},
    )
    assert bad_role.status_code == 422

    ops_token = login(client, email="ops@example.com")
    assert client.get("/api/admin/users", headers=auth(ops_token)).status_code == 200
    assert client.patch(f"/api/admin/users/{admin.id}", headers=auth(ops_token), json={"is_active": False}).status_code == 403

    r = client.patch(f"/api/admin/users/{ops_id}", headers=auth(token), json={"is_active": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert client.get("/api/auth/me", headers=auth(ops_token)).status_code == 401

    # The only Super Admin can't lock themselves out.
    r = client.patch(f"/api/admin/users/{admin.id}", headers=auth(token), json={"is_active": False})
    assert r.status_code == 403 and r.json()["error"]["code"] == "SELF_MODIFICATION"


def test_last_super_admin_protected(client, db):
    make_user(db)
    other = make_user(db, email="second@example.com")
    token = login(client)
    r = client.patch(f"/api/admin/users/{other.id}", headers=auth(token), json={"role": "PLATFORM_ADMIN"})
    assert r.status_code == 200  # first admin still remains
    r = client.patch(f"/api/admin/users/{other.id}", headers=auth(token), json={"role": "SUPER_ADMIN"})
    assert r.status_code == 200


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}
    r = client.get("/health/ready")
    assert r.status_code == 200 and r.json()["checks"]["database"] is True
    assert client.get("/health").headers["x-request-id"]
