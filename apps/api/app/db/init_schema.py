"""Database schema initialization helpers."""

from app.db.base import Base
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.dialects.postgresql import JSONB, UUID

@compiles(JSONB, "sqlite")
def compile_jsonb_sqlite(element, compiler, **kw):
    return "JSON"

@compiles(UUID, "sqlite")
def compile_uuid_sqlite(element, compiler, **kw):
    return "VARCHAR(36)"




def import_domain_models() -> None:
    """Import domain models so SQLAlchemy registers all tables."""
    import app.domains.agent.models  # noqa: F401
    import app.domains.change.models  # noqa: F401
    import app.domains.collaboration.models  # noqa: F401
    import app.domains.config.models  # noqa: F401
    import app.domains.documents.models  # noqa: F401
    import app.domains.export.models  # noqa: F401
    import app.domains.identity.models  # noqa: F401
    import app.domains.integrations.models  # noqa: F401
    import app.domains.knowledge.models  # noqa: F401
    import app.domains.notifications.models  # noqa: F401
    import app.domains.ops.models  # noqa: F401
    import app.domains.projects.models  # noqa: F401
    import app.domains.providers.models  # noqa: F401
    import app.domains.providers.raw_artifact  # noqa: F401
    import app.domains.templates.models  # noqa: F401
    import app.models.identity  # noqa: F401
    import app.models.projects  # noqa: F401


def deduplicate_indexes() -> None:
    """Remove duplicate index objects with the same generated name per table."""
    for table in Base.metadata.tables.values():
        seen: set[str] = set()
        duplicates = []
        for index in table.indexes:
            if index.name and index.name in seen:
                duplicates.append(index)
            elif index.name:
                seen.add(index.name)

        for index in duplicates:
            table.indexes.discard(index)


async def create_missing_tables() -> None:
    """Create model tables that are not yet covered by Alembic migrations."""
    from app.db.session import async_engine

    import_domain_models()
    deduplicate_indexes()
    async with async_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
