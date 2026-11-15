from sqlalchemy import select

from app.models import AuditLog, MerchantBankAccount, ProviderConfiguration
from tests.conftest import REGISTRATION, STRONG_PASSWORD, auth, login, make_user, register_merchant

OWNER = REGISTRATION["owner"]["email"]


def owner_token(client):
    return login(client, email=OWNER)


def admin_token(client, db):
    make_user(db)
    return login(client)


# ---------- Registration ----------
def test_registration_creates_merchant_profile_owner_and_sandbox(client, db):
    m = register_merchant(client)
    assert m["status"] == "PENDING_REVIEW" and m["live_enabled"] is False
    assert m["mobile"] == "9876543210"
    assert m["profile"]["pan"] == "ABCDE1234F"

    token = owner_token(client)
    me = client.get("/api/auth/me", headers=auth(token)).json()
    assert me["role"] == "MERCHANT_ADMIN" and me["merchant_id"] == m["id"]

    cfgs = client.get("/api/merchant/provider-configs", headers=auth(token)).json()
    assert len(cfgs) == 1
    assert cfgs[0]["provider"]["code"] == "sandbox" and cfgs[0]["environment"] == "TEST"
    assert cfgs[0]["status"] == "ACTIVE" and cfgs[0]["provider"]["is_live_capable"] is False

    actions = set(db.scalars(select(AuditLog.action)))
    assert {"merchant.registered", "user.created"} <= actions


def test_registration_validation(client):
    import copy

    body = copy.deepcopy(REGISTRATION)
    body["business"]["mobile"] = "12345"
    body["address"]["postal_code"] = "0001"
    body["contact"]["pan"] = "BAD"
    r = client.post("/api/merchant/register", json=body)
    assert r.status_code == 422
    fields = {d["field"] for d in r.json()["error"]["details"]}
    assert {"business.mobile", "address.postal_code", "contact.pan"} <= fields


def test_registration_duplicates_and_weak_password(client):
    register_merchant(client)
    r = client.post("/api/merchant/register", json=REGISTRATION)
    assert r.status_code == 409 and r.json()["error"]["code"] == "BUSINESS_EMAIL_TAKEN"
    import copy

    body = copy.deepcopy(REGISTRATION)
    body["business"]["business_email"] = "other@sharma.example.com"
    r = client.post("/api/merchant/register", json=body)
    assert r.status_code == 409 and r.json()["error"]["code"] == "EMAIL_TAKEN"
    body["owner"] = {"full_name": "X Y", "email": "new@sharma.example.com", "password": "aaaaaaaaaaaa"}
    r = client.post("/api/merchant/register", json=body)
    assert r.status_code == 400 and r.json()["error"]["code"] == "WEAK_PASSWORD"


def test_merchant_cannot_use_admin_endpoints_and_vice_versa(client, db):
    register_merchant(client)
    token = owner_token(client)
    assert client.get("/api/admin/merchants", headers=auth(token)).status_code == 403
    admin = admin_token(client, db)
    r = client.get("/api/merchant/profile", headers=auth(admin))
    assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_A_MERCHANT_USER"


def test_profile_update(client):
    register_merchant(client)
    token = owner_token(client)
    r = client.patch("/api/merchant/profile", headers=auth(token), json={
        "business_name": "Sharma Digital", "address": {**REGISTRATION["address"], "city": "Mysuru"},
    })
    assert r.status_code == 200
    assert r.json()["business_name"] == "Sharma Digital" and r.json()["profile"]["city"] == "Mysuru"


# ---------- Bank accounts ----------
BANK = {"environment": "LIVE", "account_holder_name": "Sharma Electronics Pvt Ltd", "bank_name": "HDFC Bank",
        "account_number": "50100012345678", "ifsc": "hdfc0001234", "upi_vpa": "sharma@hdfcbank"}


def test_bank_account_lifecycle_encrypted_and_masked(client, db):
    register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/bank-accounts", headers=auth(token), json=BANK)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["account_number_masked"] == "XXXX5678" and a["ifsc"] == "HDFC0001234"
    assert a["is_default"] is True and a["verification_status"] == "PENDING"
    assert "50100012345678" not in r.text

    row = db.get(MerchantBankAccount, a["id"])
    assert "50100012345678" not in row.account_number_enc

    dup = client.post("/api/merchant/bank-accounts", headers=auth(token), json=BANK)
    assert dup.status_code == 409 and dup.json()["error"]["code"] == "DUPLICATE_BANK_ACCOUNT"

    b = client.post("/api/merchant/bank-accounts", headers=auth(token),
                    json={**BANK, "account_number": "50100099999999", "upi_vpa": None}).json()
    assert b["is_default"] is False
    assert client.post(f"/api/merchant/bank-accounts/{b['id']}/default", headers=auth(token)).json()["is_default"]
    listed = {x["id"]: x for x in client.get("/api/merchant/bank-accounts", headers=auth(token)).json()}
    assert listed[a["id"]]["is_default"] is False

    d = client.post(f"/api/merchant/bank-accounts/{b['id']}/deactivate", headers=auth(token)).json()
    assert d["is_active"] is False and d["is_default"] is False
    r = client.post(f"/api/merchant/bank-accounts/{b['id']}/default", headers=auth(token))
    assert r.json()["error"]["code"] == "ACCOUNT_INACTIVE"

    rev = client.post(f"/api/merchant/bank-accounts/{a['id']}/reveal", headers=auth(token)).json()
    assert rev["account_number"] == "50100012345678"
    assert "bank_account.revealed" in set(db.scalars(select(AuditLog.action)))


def test_bank_account_verification_and_reset_on_change(client, db):
    register_merchant(client)
    token = owner_token(client)
    a = client.post("/api/merchant/bank-accounts", headers=auth(token), json=BANK).json()
    admin = admin_token(client, db)

    r = client.post(f"/api/admin/bank-accounts/{a['id']}/verification", headers=auth(admin), json={"decision": "REJECTED"})
    assert r.json()["error"]["code"] == "REASON_REQUIRED"
    r = client.post(f"/api/admin/bank-accounts/{a['id']}/verification", headers=auth(admin), json={"decision": "VERIFIED"})
    assert r.json()["verification_status"] == "VERIFIED" and r.json()["verified_at"]

    # Cosmetic change keeps verification; changing the account number resets it.
    r = client.patch(f"/api/merchant/bank-accounts/{a['id']}", headers=auth(token), json={"bank_name": "HDFC Bank Ltd"})
    assert r.json()["verification_status"] == "VERIFIED"
    r = client.patch(f"/api/merchant/bank-accounts/{a['id']}", headers=auth(token), json={"account_number": "50100011112222"})
    assert r.json()["verification_status"] == "PENDING" and r.json()["account_number_masked"] == "XXXX2222"


def test_bank_accounts_isolated_between_merchants(client):
    register_merchant(client)
    a = client.post("/api/merchant/bank-accounts", headers=auth(owner_token(client)), json=BANK).json()
    register_merchant(
        client,
        business={"business_email": "hello@other.example.com"},
        owner={"email": "owner@other.example.com"},
    )
    other = login(client, email="owner@other.example.com")
    assert client.get("/api/merchant/bank-accounts", headers=auth(other)).json() == []
    r = client.post(f"/api/merchant/bank-accounts/{a['id']}/reveal", headers=auth(other))
    assert r.status_code == 404
    r = client.patch(f"/api/merchant/bank-accounts/{a['id']}", headers=auth(other), json={"bank_name": "Hijack"})
    assert r.status_code == 404


def test_bank_account_input_validation(client):
    register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/bank-accounts", headers=auth(token),
                    json={**BANK, "ifsc": "HDFC1234567", "account_number": "12ab", "upi_vpa": "not-a-vpa"})
    assert r.status_code == 422
    assert {d["field"] for d in r.json()["error"]["details"]} == {"ifsc", "account_number", "upi_vpa"}


# ---------- Provider configurations ----------
def test_live_provider_config_refused_without_live_capable_provider(client):
    register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/provider-configs", headers=auth(token), json={
        "provider_code": "sandbox", "environment": "LIVE", "provider_merchant_id": "x", "credentials": {"k": "v"},
    })
    assert r.status_code == 409 and r.json()["error"]["code"] == "SANDBOX_MANAGED"
    r = client.post("/api/merchant/provider-configs", headers=auth(token), json={
        "provider_code": "made-up-psp", "environment": "LIVE", "provider_merchant_id": "x", "credentials": {"k": "v"},
    })
    assert r.status_code == 404


def _add_live_capable_provider(db):
    from app.models import PaymentProvider

    p = PaymentProvider(code="acme_psp", name="Acme PSP (test fixture)", supports_upi_qr=True, is_live_capable=True)
    db.add(p)
    db.commit()
    return p


def test_provider_config_onboarding_flow(client, db):
    _add_live_capable_provider(db)
    register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/provider-configs", headers=auth(token), json={
        "provider_code": "acme_psp", "environment": "LIVE", "provider_merchant_id": "ACME-123",
        "credentials": {"key_id": "acme_live_key", "key_secret": "super-secret-value"},
    })
    assert r.status_code == 201, r.text
    cfg = r.json()
    assert cfg["status"] == "DRAFT" and cfg["credential_fields"] == ["key_id", "key_secret"]
    assert "super-secret-value" not in r.text
    assert "super-secret-value" not in db.get(ProviderConfiguration, cfg["id"]).credentials_enc

    admin = admin_token(client, db)
    r = client.post(f"/api/admin/provider-configs/{cfg['id']}/approve", headers=auth(admin))
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"

    assert client.post(f"/api/merchant/provider-configs/{cfg['id']}/submit", headers=auth(token)).json()["status"] == "SUBMITTED"
    r = client.patch(f"/api/merchant/provider-configs/{cfg['id']}", headers=auth(token), json={"provider_merchant_id": "X"})
    assert r.json()["error"]["code"] == "CONFIG_LOCKED"

    r = client.post(f"/api/admin/provider-configs/{cfg['id']}/reject", headers=auth(admin), json={"reason": "MID mismatch"})
    assert r.json()["status"] == "DRAFT" and r.json()["status_reason"] == "MID mismatch"
    client.post(f"/api/merchant/provider-configs/{cfg['id']}/submit", headers=auth(token))
    r = client.post(f"/api/admin/provider-configs/{cfg['id']}/approve", headers=auth(admin))
    assert r.json()["status"] == "APPROVED"
    # ACTIVE requires a passed integration test (Phase 7), so activation is refused for now.
    r = client.post(f"/api/admin/provider-configs/{cfg['id']}/activate", headers=auth(admin))
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"


# ---------- API credentials ----------
def test_api_credentials_shown_once_and_authenticate(client, db):
    from app.services.credentials import authenticate

    register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "TEST", "label": "server"})
    assert r.status_code == 201
    c = r.json()
    assert c["key_id"].startswith("tm_test_") and c["key_secret"].startswith("tmsk_test_")
    assert c["secret_prefix"] == c["key_secret"][:14]

    listed = client.get("/api/merchant/api-credentials", headers=auth(token))
    assert c["key_secret"] not in listed.text and "key_secret" not in listed.json()[0]

    cred, merchant = authenticate(db, c["key_id"], c["key_secret"])
    assert cred.id == c["id"] and cred.last_used_at is not None

    import pytest

    from app.core.errors import Forbidden, Unauthorized
    with pytest.raises(Unauthorized):
        authenticate(db, c["key_id"], c["key_secret"] + "x")
    with pytest.raises(Unauthorized):
        authenticate(db, "tm_test_nope", c["key_secret"])

    # Regenerate: old key stops working, new one works.
    new = client.post(f"/api/merchant/api-credentials/{c['id']}/regenerate", headers=auth(token)).json()
    db.expire_all()  # the API changed rows through its own session
    with pytest.raises(Unauthorized):
        authenticate(db, c["key_id"], c["key_secret"])
    db.expire_all()
    authenticate(db, new["key_id"], new["key_secret"])

    # Merchant-level API switch.
    client.put("/api/merchant/api-access", headers=auth(token), json={"enabled": False})
    db.expire_all()
    with pytest.raises(Forbidden):
        authenticate(db, new["key_id"], new["key_secret"])


def test_live_credentials_require_live_mode_and_limits(client):
    register_merchant(client)
    token = owner_token(client)
    r = client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "LIVE"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "LIVE_NOT_ENABLED"
    for _ in range(2):
        assert client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "TEST"}).status_code == 201
    r = client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "TEST"})
    assert r.json()["error"]["code"] == "LIMIT_REACHED"


# ---------- Webhooks ----------
def test_webhook_config_secret_once_and_url_rules(client, db):
    register_merchant(client)
    token = owner_token(client)
    r = client.put("/api/merchant/webhooks/LIVE", headers=auth(token),
                   json={"url": "http://shop.example.com/hook", "events": ["payment.success"]})
    assert r.json()["error"]["code"] == "INVALID_WEBHOOK_URL"
    r = client.put("/api/merchant/webhooks/LIVE", headers=auth(token),
                   json={"url": "https://10.0.0.5/hook", "events": ["payment.success"]})
    assert r.json()["error"]["code"] == "INVALID_WEBHOOK_URL"
    # Local http endpoints are allowed only for TEST in development/test environments.
    r = client.put("/api/merchant/webhooks/TEST", headers=auth(token),
                   json={"url": "http://localhost:9000/hook", "events": ["payment.success"]})
    assert r.status_code == 200 and r.json()["signing_secret"].startswith("whsec_")

    r = client.put("/api/merchant/webhooks/LIVE", headers=auth(token),
                   json={"url": "https://shop.example.com/hook", "events": ["payment.success", "payment.failed"]})
    first = r.json()
    assert first["signing_secret"].startswith("whsec_") and first["validated_at"] is None
    r = client.put("/api/merchant/webhooks/LIVE", headers=auth(token),
                   json={"url": "https://shop.example.com/hook2", "events": ["payment.success"]})
    assert "signing_secret" not in r.json()
    rotated = client.post("/api/merchant/webhooks/LIVE/rotate-secret", headers=auth(token)).json()
    assert rotated["signing_secret"] != first["signing_secret"]
    listed = client.get("/api/merchant/webhooks", headers=auth(token))
    assert len(listed.json()) == 2
    assert first["signing_secret"] not in listed.text and rotated["signing_secret"] not in listed.text
    assert "signing_secret" not in listed.text

    r = client.put("/api/merchant/webhooks/LIVE", headers=auth(token), json={"url": "https://a.example.com", "events": ["nope"]})
    assert r.status_code == 422


# ---------- Admin merchant management & live gating ----------
def test_admin_review_suspend_and_live_gating(client, db):
    m = register_merchant(client)
    token = owner_token(client)
    admin = admin_token(client, db)

    page = client.get("/api/admin/merchants?status=PENDING_REVIEW", headers=auth(admin)).json()
    assert page["total"] == 1 and page["items"][0]["id"] == m["id"]
    assert client.get("/api/admin/merchants?q=Sharma", headers=auth(admin)).json()["total"] == 1
    assert client.get("/api/admin/merchants?q=nomatch", headers=auth(admin)).json()["total"] == 0

    r = client.post(f"/api/admin/merchants/{m['id']}/suspend", headers=auth(admin), json={"reason": "x"})
    assert r.status_code == 422  # reason too short
    r = client.post(f"/api/admin/merchants/{m['id']}/suspend", headers=auth(admin), json={"reason": "fraud check"})
    assert r.json()["error"]["code"] == "INVALID_STATUS_TRANSITION"
    assert client.post(f"/api/admin/merchants/{m['id']}/approve", headers=auth(admin), json={}).json()["status"] == "ACTIVE"

    r = client.post(f"/api/admin/merchants/{m['id']}/live/enable", headers=auth(admin))
    assert r.status_code == 409 and r.json()["error"]["code"] == "LIVE_PREREQUISITES_UNMET"
    unmet = {i["key"] for i in r.json()["error"]["details"]}
    assert unmet == {"provider_approved", "provider_tested", "provider_active", "bank_verified", "webhook_validated"}

    detail = client.get(f"/api/admin/merchants/{m['id']}", headers=auth(admin)).json()
    assert detail["live_readiness"]["ready"] is False and len(detail["users"]) == 1

    r = client.post(f"/api/admin/merchants/{m['id']}/suspend", headers=auth(admin), json={"reason": "chargeback review"})
    assert r.json()["status"] == "SUSPENDED"
    # Suspended merchants can sign in and read, but not change configuration.
    assert client.get("/api/merchant/profile", headers=auth(token)).status_code == 200
    r = client.post("/api/merchant/bank-accounts", headers=auth(token), json=BANK)
    assert r.status_code == 403 and r.json()["error"]["code"] == "MERCHANT_NOT_ACTIVE"


def test_live_enable_succeeds_once_all_prerequisites_met(client, db):
    """Simulates the state a merchant reaches after Phase 7 provider onboarding + testing."""
    from datetime import datetime, timezone

    from app.models import Merchant, WebhookConfiguration

    _add_live_capable_provider(db)
    m = register_merchant(client)
    token = owner_token(client)
    admin = admin_token(client, db)
    client.post(f"/api/admin/merchants/{m['id']}/approve", headers=auth(admin), json={})
    acct = client.post("/api/merchant/bank-accounts", headers=auth(token), json=BANK).json()
    client.post(f"/api/admin/bank-accounts/{acct['id']}/verification", headers=auth(admin), json={"decision": "VERIFIED"})
    client.put("/api/merchant/webhooks/LIVE", headers=auth(token),
               json={"url": "https://shop.example.com/hook", "events": ["payment.success"]})
    cfg = client.post("/api/merchant/provider-configs", headers=auth(token), json={
        "provider_code": "acme_psp", "environment": "LIVE", "provider_merchant_id": "ACME-1", "credentials": {"k": "v"},
    }).json()
    client.post(f"/api/merchant/provider-configs/{cfg['id']}/submit", headers=auth(token))
    client.post(f"/api/admin/provider-configs/{cfg['id']}/approve", headers=auth(admin))

    now = datetime.now(timezone.utc)
    row = db.get(ProviderConfiguration, cfg["id"])
    row.status, row.integration_tested_at = "TESTED", now  # set by the Phase 7 integration test
    db.query(WebhookConfiguration).update({"validated_at": now})  # set by a successful test delivery
    db.commit()
    assert client.post(f"/api/admin/provider-configs/{cfg['id']}/activate", headers=auth(admin)).json()["status"] == "ACTIVE"

    ready = client.get("/api/merchant/live-readiness", headers=auth(token)).json()
    assert ready["ready"] is True, ready
    r = client.post(f"/api/admin/merchants/{m['id']}/live/enable", headers=auth(admin))
    assert r.status_code == 200 and r.json()["live_enabled"] is True
    live = client.post("/api/merchant/api-credentials", headers=auth(token), json={"environment": "LIVE"}).json()
    assert live["key_id"].startswith("tm_live_")

    # Suspension switches live off.
    client.post(f"/api/admin/merchants/{m['id']}/suspend", headers=auth(admin), json={"reason": "compliance hold"})
    db.expire_all()
    assert db.get(Merchant, m["id"]).live_enabled is False


def test_platform_roles_for_merchant_admin(client, db):
    m = register_merchant(client)
    make_user(db, email="support@example.com", role="PLATFORM_SUPPORT")
    support = login(client, email="support@example.com")
    assert client.get(f"/api/admin/merchants/{m['id']}", headers=auth(support)).status_code == 200
    r = client.post(f"/api/admin/merchants/{m['id']}/approve", headers=auth(support), json={})
    assert r.status_code == 403

    make_user(db, email="ops@example.com", role="PLATFORM_ADMIN")
    ops = login(client, email="ops@example.com")
    assert client.post(f"/api/admin/merchants/{m['id']}/approve", headers=auth(ops), json={}).status_code == 200
    assert client.post(f"/api/admin/merchants/{m['id']}/live/enable", headers=auth(ops)).status_code == 403


def test_merchant_viewer_permissions(client, db):
    m = register_merchant(client)
    from app.services.users import create_user

    create_user(db, email="viewer@sharma.example.com", full_name="Viewer", password=STRONG_PASSWORD,
                role="MERCHANT_VIEWER", merchant_id=m["id"])
    db.commit()
    viewer = login(client, email="viewer@sharma.example.com")
    assert client.get("/api/merchant/bank-accounts", headers=auth(viewer)).status_code == 200
    assert client.post("/api/merchant/bank-accounts", headers=auth(viewer), json=BANK).status_code == 403
    assert client.get("/api/merchant/api-credentials", headers=auth(viewer)).status_code == 403
