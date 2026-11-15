from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def build_engine(url: str | None = None) -> Engine:
    s = get_settings()
    url = url or s.DATABASE_URL
    if url.startswith("sqlite"):
        engine = create_engine(url, connect_args={"check_same_thread": False})

        @event.listens_for(engine, "connect")
        def _sqlite_fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")

        return engine

    connect_args: dict = {}
    if url.startswith("mysql"):
        connect_args["init_command"] = "SET time_zone = '+00:00'"
        if s.DATABASE_SSL_CA:
            # Aiven requires TLS; verify the server certificate against the project CA.
            connect_args["ssl"] = {"ca": s.DATABASE_SSL_CA, "check_hostname": True}
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=s.DATABASE_POOL_SIZE,
        max_overflow=s.DATABASE_MAX_OVERFLOW,
        pool_recycle=s.DATABASE_POOL_RECYCLE,
        isolation_level="READ COMMITTED",
        connect_args=connect_args,
    )


@lru_cache
def get_engine() -> Engine:
    return build_engine()


@lru_cache
def get_sessionmaker() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = get_sessionmaker()()
    try:
        yield db
    finally:
        db.close()
