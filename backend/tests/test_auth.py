from sqlalchemy import select

from app.models import AuditLog, User
from app.services import auth as auth_service
from tests.conftest import STRONG_PASSWORD, auth, login, make_user


def test_login_me_and_refresh_cookie(client, db):
    make_user(db)
    r = client.post("/api/auth/login", json={"email": "ADMIN@example.com", "password": STRONG_PASSWORD})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "SUPER_ADMIN"
    assert "dashboard:view" in body["user"]["permissions"]
    set_cookie = r.headers["set-cookie"]
    assert "tm_refresh=" in set_cookie and "HttpOnly" in set_cookie and "Path=/api/auth" in set_cookie
    assert "samesite=lax" in set_cookie.lower()

    me = client.get("/api/auth/me", headers=auth(body["access_token"]))
    assert me.status_code == 200 and me.json()["email"] == "admin@example.com"
    assert "password_hash" not in me.text


def test_wrong_password_is_generic_and_audited(client, db):
    make_user(db)
    r1 = client.post("/api/auth/login", json={"email": "admin@example.com", "password": "nope-nope-nope"})
    r2 = client.post("/api/auth/login", json={"email": "ghost@example.com", "password": "nope-nope-nope"})
    assert r1.status_code == r2.status_code == 401
    assert r1.json()["error"]["code"] == r2.json()["error"]["code"] == "INVALID_CREDENTIALS"
    actions = list(db.scalars(select(AuditLog.action)))
    assert actions.count("auth.login_failed") == 2


def test_lockout_after_repeated_failures(client, db):
    make_user(db)
    for _ in range(5):
        client.post("/api/auth/login", json={"email": "admin@example.com", "password": "bad-password-x"})
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": STRONG_PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "ACCOUNT_LOCKED"


def test_login_rate_limited(client, db):
    for i in range(10):
        client.post("/api/auth/login", json={"email": f"u{i}@example.org", "password": "whatever-123"})
    r = client.post("/api/auth/login", json={"email": "u99@example.org", "password": "whatever-123"})
    assert r.status_code == 429 and r.json()["error"]["code"] == "RATE_LIMITED"


def test_cookie_endpoints_require_client_header(client, db):
    make_user(db)
    r = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": STRONG_PASSWORD},
        headers={"X-TM-Client": ""},
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "CSRF_CHECK_FAILED"


def test_refresh_rotates_and_detects_reuse(client, db, monkeypatch):
    make_user(db)
    login(client)
    old_refresh = client.cookies.get("tm_refresh")

    r = client.post("/api/auth/refresh")
    assert r.status_code == 200
    new_refresh = client.cookies.get("tm_refresh")
    assert new_refresh and new_refresh != old_refresh
    new_access = r.json()["access_token"]
    assert client.get("/api/auth/me", headers=auth(new_access)).status_code == 200

    # Within the grace window a concurrent replay is answered with 409 and nothing is revoked.
    client.cookies.clear()
    client.cookies.set("tm_refresh", old_refresh)
    r = client.post("/api/auth/refresh")
    assert r.status_code == 409 and r.json()["error"]["code"] == "SESSION_ROTATED"
    assert client.get("/api/auth/me", headers=auth(new_access)).status_code == 200

    # After the grace window, replaying the rotated-out token revokes every session and access token.
    monkeypatch.setattr(auth_service, "ROTATION_GRACE_SECONDS", 0)
    client.cookies.clear()
    client.cookies.set("tm_refresh", old_refresh)
    r = client.post("/api/auth/refresh")
    assert r.status_code == 401 and r.json()["error"]["code"] == "SESSION_INVALID"
    assert client.get("/api/auth/me", headers=auth(new_access)).status_code == 401
    client.cookies.clear()
    client.cookies.set("tm_refresh", new_refresh)
    assert client.post("/api/auth/refresh").status_code == 401
    assert "auth.refresh_token_reuse" in set(db.scalars(select(AuditLog.action)))


def test_logout_revokes_session(client, db):
    make_user(db)
    token = login(client)
    assert client.post("/api/auth/logout").status_code == 204
    r = client.get("/api/auth/me", headers=auth(token))
    assert r.status_code == 401 and r.json()["error"]["code"] == "TOKEN_REVOKED"
    assert client.post("/api/auth/refresh").status_code == 401


def test_change_password_invalidates_old_tokens(client, db):
    make_user(db)
    old = login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": STRONG_PASSWORD, "new_password": "Another-Strong-77"},
        headers=auth(old),
    )
    assert r.status_code == 200, r.text
    assert client.get("/api/auth/me", headers=auth(old)).status_code == 401
    assert client.get("/api/auth/me", headers=auth(r.json()["access_token"])).status_code == 200
    login(client, password="Another-Strong-77")


def test_change_password_rejects_weak(client, db):
    make_user(db)
    token = login(client)
    r = client.post(
        "/api/auth/change-password",
        json={"current_password": STRONG_PASSWORD, "new_password": "aaaaaaaaaaaa"},
        headers=auth(token),
    )
    assert r.status_code == 400 and r.json()["error"]["code"] == "WEAK_PASSWORD"


def test_invalid_and_missing_tokens(client):
    assert client.get("/api/auth/me").json()["error"]["code"] == "AUTH_REQUIRED"
    assert client.get("/api/auth/me", headers=auth("garbage")).json()["error"]["code"] == "TOKEN_INVALID"


def test_deactivated_user_cannot_login(client, db):
    user = make_user(db)
    db.get(User, user.id).is_active = False
    db.commit()
    r = client.post("/api/auth/login", json={"email": "admin@example.com", "password": STRONG_PASSWORD})
    assert r.status_code == 401 and r.json()["error"]["code"] == "ACCOUNT_DISABLED"
