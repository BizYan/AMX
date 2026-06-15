"""Alembic migration safety checks."""

import re
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import UniqueConstraint

from app.domains.change.models import DocumentConflict, DocumentConflictDecision


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


def test_conflict_assignment_governance_migration_is_additive():
    migration = (VERSIONS_DIR / "0023_conflict_assignment_governance.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0023_conflict_assignment"' in migration
    assert 'down_revision = "0022_document_conflicts"' in migration
    assert 'op.add_column(' in migration
    assert '"document_conflicts"' in migration
    assert '"assignee_user_id"' in migration
    assert '"assignment_source"' in migration
    assert '"assigned_at"' in migration
    assert '"due_at"' in migration
    assert 'op.create_table(' in migration
    assert '"document_conflict_decisions"' in migration
    assert 'op.drop_table("document_conflict_decisions")' in migration


def test_conflict_assignment_governance_model_matches_migration_contract():
    conflict_columns = DocumentConflict.__table__.c
    decision_columns = DocumentConflictDecision.__table__.c
    decision_indexes = {index.name for index in DocumentConflictDecision.__table__.indexes}

    assert "assignee_user_id" in conflict_columns
    assert "assignment_source" in conflict_columns
    assert "assigned_at" in conflict_columns
    assert "due_at" in conflict_columns
    assert decision_columns.tenant_id.nullable is False
    assert decision_columns.project_id.nullable is False
    assert decision_columns.conflict_id.nullable is False
    assert decision_columns.action.nullable is False
    assert decision_columns.actor_id.nullable is False
    assert decision_columns.resulting_status.nullable is False
    assert decision_columns.evidence_json.nullable is False
    assert {
        "ix_document_conflict_decisions_tenant_id",
        "ix_document_conflict_decisions_project_id",
        "ix_document_conflict_decisions_conflict_id",
        "ix_document_conflict_decisions_actor_id",
        "ix_document_conflict_decisions_action",
    } <= decision_indexes


def test_conflict_change_request_linkage_migration_is_additive():
    migration = (VERSIONS_DIR / "0024_conflict_change_linkage.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0024_conflict_change_linkage"' in migration
    assert 'down_revision = "0023_conflict_assignment"' in migration
    assert '"linked_change_request_id"' in migration
    assert '"accepted_revision_json"' in migration
    assert '"revision_accepted_at"' in migration
    assert '"ix_document_conflicts_linked_change_request_id"' in migration


def test_conflict_change_request_linkage_model_matches_migration_contract():
    conflict_columns = DocumentConflict.__table__.c
    index_names = {index.name for index in DocumentConflict.__table__.indexes}

    assert "linked_change_request_id" in conflict_columns
    assert "accepted_revision_json" in conflict_columns
    assert "revision_accepted_at" in conflict_columns
    assert "ix_document_conflicts_linked_change_request_id" in index_names


def test_conflict_closure_rescan_migration_is_additive():
    migration = (VERSIONS_DIR / "0025_conflict_closure_rescan.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0025_conflict_closure"' in migration
    assert 'down_revision = "0024_conflict_change_linkage"' in migration
    assert '"closure_scan_id"' in migration
    assert '"closure_verified_at"' in migration
    assert '"closure_evidence_json"' in migration
    assert '"ix_document_conflicts_closure_scan_id"' in migration


def test_conflict_closure_rescan_model_matches_migration_contract():
    conflict_columns = DocumentConflict.__table__.c
    index_names = {index.name for index in DocumentConflict.__table__.indexes}

    assert "closure_scan_id" in conflict_columns
    assert "closure_verified_at" in conflict_columns
    assert "closure_evidence_json" in conflict_columns
    assert "ix_document_conflicts_closure_scan_id" in index_names


def test_conflict_risk_acceptance_migration_is_additive():
    migration = (VERSIONS_DIR / "0026_conflict_risk_acceptance.py").read_text(
        encoding="utf-8"
    )

    assert 'revision = "0026_conflict_risk"' in migration
    assert 'down_revision = "0025_conflict_closure"' in migration
    assert '"risk_accepted_by"' in migration
    assert '"risk_accepted_at"' in migration
    assert '"risk_acceptance_expires_at"' in migration
    assert '"risk_acceptance_json"' in migration
    assert '"ix_document_conflicts_risk_accepted_by"' in migration
    assert '"ix_document_conflicts_risk_acceptance_expires_at"' in migration


def test_conflict_risk_acceptance_model_matches_migration_contract():
    conflict_columns = DocumentConflict.__table__.c
    index_names = {index.name for index in DocumentConflict.__table__.indexes}

    assert "risk_accepted_by" in conflict_columns
    assert "risk_accepted_at" in conflict_columns
    assert "risk_acceptance_expires_at" in conflict_columns
    assert "risk_acceptance_json" in conflict_columns
    assert "ix_document_conflicts_risk_accepted_by" in index_names
    assert "ix_document_conflicts_risk_acceptance_expires_at" in index_names
