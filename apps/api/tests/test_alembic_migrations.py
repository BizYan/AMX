"""Alembic migration safety checks."""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import UniqueConstraint

from app.domains.change.models import DocumentConflict


API_ROOT = Path(__file__).resolve().parents[1]
VERSIONS_DIR = API_ROOT / "alembic" / "versions"


def test_alembic_revision_ids_fit_production_version_column():
    """Production alembic_version.version_num is varchar(32)."""
    revision_pattern = re.compile(r'^revision\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)

    violations = []
    for migration in VERSIONS_DIR.glob("*.py"):
        match = revision_pattern.search(migration.read_text(encoding="utf-8"))
        if match and len(match.group(1)) > 32:
            violations.append(f"{migration.name}: {match.group(1)}")

    assert violations == []


def test_alembic_migrations_have_single_head():
    """Production deploy runs `alembic upgrade head`, so main must be linearized."""
    config = Config(str(API_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(API_ROOT / "alembic"))
    heads = ScriptDirectory.from_config(config).get_heads()

    assert len(heads) == 1


def test_document_conflicts_migration_defines_idempotent_project_fingerprint():
    migration = (VERSIONS_DIR / "0022_document_conflicts.py").read_text(encoding="utf-8")

    assert 'revision = "0022_document_conflicts"' in migration
    assert 'down_revision = "0021_invitation_delivery"' in migration
    assert 'op.create_table(' in migration
    assert '"document_conflicts"' in migration
    assert '"uq_document_conflicts_tenant_project_fingerprint"' in migration
    assert 'op.drop_table("document_conflicts")' in migration


def test_document_conflict_model_matches_migration_constraint_and_indexes():
    constraint_names = {
        constraint.name
        for constraint in DocumentConflict.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }
    index_names = {index.name for index in DocumentConflict.__table__.indexes}
    all_index_names = [index.name for index in DocumentConflict.__table__.indexes]

    assert DocumentConflict.__table__.c.tenant_id.nullable is False
    assert len(all_index_names) == len(set(all_index_names))
    assert "uq_document_conflicts_tenant_project_fingerprint" in constraint_names
    assert {
        "ix_document_conflicts_tenant_id",
        "ix_document_conflicts_project_id",
        "ix_document_conflicts_status",
        "ix_document_conflicts_severity",
        "ix_document_conflicts_last_scan_id",
        "ix_document_conflicts_primary_document_id",
        "ix_document_conflicts_related_document_id",
    } <= index_names
