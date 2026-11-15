"""Test setup. Runs against SQLite by default; set TEST_DATABASE_URL to run against MySQL 8.
The schema is built with the real Alembic migrations, so migrations are exercised by every run."""

import os
import tempfile

_tmp = tempfile.mkdtemp(prefix="tmpg-tests-")
os.environ.update(
    APP_ENV="test",
    DATABASE_URL=os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_tmp}/test.db"),
    REDIS_URL="",  # in-process rate limiter; deterministic tests
    JWT_SECRET="test-jwt-secret-" + "x" * 40,
    ENCRYPTION_KEYS="0Fh7hx1y4cPOV0fF1mQh6h6vR4yS2TQ0bUu0f9fZcGQ=",
    HASH_PEPPER="test-pepper",
    LOG_LEVEL="WARNING",
)

import pytest  # noqa: E402
from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.core import rate_limit  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import get_engine, get_sessionmaker  # noqa: E402
from app.models import Role  # noqa: E402

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STRONG_PASSWORD = "Correct-Horse-42!"


def alembic_config() -> Config:
    cfg = Config(os.path.join(BACKEND_DIR, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(BACKEND_DIR, "alembic"))
    cfg.attributes["database_url"] = os.environ["DATABASE_URL"]
    return cfg


@pytest.fixture(scope="session", autouse=True)
def _schema():
    cfg = alembic_config()
    command.downgrade(cfg, "base")
    command.upgrade(cfg, "head")
    yield
    get_engine().dispose()


@pytest.fixture(autouse=True)
def _clean_db():
    yield
    rate_limit.reset_local()
    with get_engine().begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            if table.name != Role.__tablename__:
                conn.execute(delete(table))


@pytest.fixture
def db():
    with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app, headers={"X-TM-Client": "dashboard"}) as c:
        yield c


def make_user(db, email="admin@example.com", role="SUPER_ADMIN", password=STRONG_PASSWORD, **kw):
    from app.services.users import create_user

    user = create_user(db, email=email, full_name=kw.pop("full_name", "Test User"), password=password, role=role, **kw)
    db.commit()
    return user


def login(client, email="admin@example.com", password=STRONG_PASSWORD) -> str:
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}
