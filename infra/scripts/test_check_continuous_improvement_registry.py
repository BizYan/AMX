import copy
import json
import tempfile
import unittest
from pathlib import Path

from infra.scripts.check_continuous_improvement_registry import build_report, validate_registry


class ContinuousImprovementRegistryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.repo_root = Path(self.temp_dir.name)
        (self.repo_root / "evidence.md").write_text("evidence", encoding="utf-8")
        self.entry = {
            "id": "IMP-001",
            "title": "Example improvement",
            "category": "quality",
            "priority": "P1",
            "status": "adopted",
            "recurrence": 2,
            "summary": "A repeated issue.",
            "evidence": [{"kind": "runbook", "reference": "evidence.md"}],
            "proposed_change": "Add a deterministic check.",
            "destinations": ["evidence.md"],
            "validation": {
                "result": "passed",
                "reference": "evidence.md",
                "summary": "The check prevented the issue.",
            },
            "next_review": "2026-07-15",
        }
        self.registry = {
            "version": 1,
            "updated_at": "2026-06-15",
            "entries": [self.entry],
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_accepts_valid_registry(self) -> None:
        self.assertEqual(validate_registry(self.registry, self.repo_root), [])

    def test_rejects_duplicate_ids(self) -> None:
        duplicate = copy.deepcopy(self.entry)
        self.registry["entries"].append(duplicate)
        errors = validate_registry(self.registry, self.repo_root)
        self.assertIn("Duplicate entry id: IMP-001.", errors)

    def test_rejects_high_priority_entry_without_evidence(self) -> None:
        self.entry["evidence"] = []
        errors = validate_registry(self.registry, self.repo_root)
        self.assertIn("IMP-001 requires evidence because it is P1.", errors)

    def test_rejects_adoption_without_passing_validation(self) -> None:
        self.entry["validation"]["result"] = "pending"
        errors = validate_registry(self.registry, self.repo_root)
        self.assertIn("IMP-001 requires validation.result=passed.", errors)

    def test_report_highlights_open_candidates(self) -> None:
        self.entry["status"] = "candidate"
        self.entry["validation"] = None
        report = build_report(self.registry)
        self.assertIn("## Open Improvement Work", report)
        self.assertIn("IMP-001: Example improvement", report)

    def test_fixture_is_json_serializable(self) -> None:
        json.dumps(self.registry)


if __name__ == "__main__":
    unittest.main()

