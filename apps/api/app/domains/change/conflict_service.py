"""Persistent document conflict governance helpers."""

import hashlib
import json
from typing import Any
from uuid import UUID


MUTABLE_EVIDENCE_KEYS = {
    "description",
    "detected_at",
    "last_detected_at",
    "summary",
}


def build_conflict_fingerprint(
    *,
    tenant_id: UUID,
    project_id: UUID,
    rule_key: str,
    primary_document_id: UUID,
    related_document_id: UUID | None,
    evidence: dict[str, Any],
) -> str:
    """Build a stable fingerprint from rule identity and immutable evidence."""
    stable_evidence = {
        key: value
        for key, value in evidence.items()
        if key not in MUTABLE_EVIDENCE_KEYS
    }
    canonical = json.dumps(
        {
            "tenant_id": str(tenant_id),
            "project_id": str(project_id),
            "rule_key": rule_key,
            "primary_document_id": str(primary_document_id),
            "related_document_id": str(related_document_id) if related_document_id else None,
            "evidence": stable_evidence,
        },
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
