from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import select

from app.db.base import Base
from app.db.session import get_engine
from app.models import Role
from app.models.enums import RoleName

MYSQL_IDENTIFIER_LIMIT = 64


def test_migrations_match_models():
    with get_engine().connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == [], diff


def test_all_identifiers_fit_mysql_limit():
    too_long = []
    for table in Base.metadata.tables.values():
        names = [table.name]
        names += [c.name for c in table.constraints if c.name]
        names += [i.name for i in table.indexes if i.name]
        too_long += [n for n in names if len(str(n)) > MYSQL_IDENTIFIER_LIMIT]
    assert too_long == []


def test_every_table_has_primary_key():
    # Aiven MySQL enforces sql_require_primary_key.
    assert all(t.primary_key.columns for t in Base.metadata.tables.values())


def test_roles_seeded(db):
    names = set(db.scalars(select(Role.name)))
    assert names == {r.value for r in RoleName}
