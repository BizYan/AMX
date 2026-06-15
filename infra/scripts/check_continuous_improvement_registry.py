#!/usr/bin/env python3
"""Validate and summarize the evidence-driven continuous-improvement registry."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any


ALLOWED_STATUSES = {"observed", "candidate", "validated", "adopted", "rejected"}
ALLOWED_PRIORITIES = {"P0", "P1", "P2", "P3"}
REQUIRED_ENTRY_FIELDS = {
    "id",
    "title",
    "category",
    "priority",
    "status",
    "recurrence",
    "summary",
    "evidence",
    "proposed_change",
    "destinations",
    "validation",
    "next_review",
}


def _non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _reference_exists(reference: str, repo_root: Path) -> bool:
    if reference.startswith(("http://", "https://")):
        return True
    path_text = reference.split("#", 1)[0]
    return (repo_root / path_text).exists()


def validate_registry(data: Any, repo_root: Path) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["Registry root must be a JSON object."]

    if data.get("version") != 1:
        errors.append("Registry version must be 1.")
    try:
        date.fromisoformat(data.get("updated_at", ""))
    except (TypeError, ValueError):
        errors.append("updated_at must be an ISO date.")

    entries = data.get("entries")
    if not isinstance(entries, list) or not entries:
        errors.append("entries must be a non-empty array.")
        return errors

    seen_ids: set[str] = set()
    for index, entry in enumerate(entries):
        label = f"entries[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{label} must be an object.")
            continue

        missing = sorted(REQUIRED_ENTRY_FIELDS - entry.keys())
        if missing:
            errors.append(f"{label} missing fields: {', '.join(missing)}.")
            continue

        entry_id = entry["id"]
        if not _non_empty_string(entry_id):
            errors.append(f"{label}.id must be a non-empty string.")
        elif entry_id in seen_ids:
            errors.append(f"Duplicate entry id: {entry_id}.")
        else:
            seen_ids.add(entry_id)
        label = entry_id if _non_empty_string(entry_id) else label

        if not _non_empty_string(entry["title"]):
            errors.append(f"{label}.title must be a non-empty string.")
        if not _non_empty_string(entry["summary"]):
            errors.append(f"{label}.summary must be a non-empty string.")
        if entry["priority"] not in ALLOWED_PRIORITIES:
            errors.append(f"{label}.priority must be one of {sorted(ALLOWED_PRIORITIES)}.")
        if entry["status"] not in ALLOWED_STATUSES:
            errors.append(f"{label}.status must be one of {sorted(ALLOWED_STATUSES)}.")
        if not isinstance(entry["recurrence"], int) or entry["recurrence"] < 1:
            errors.append(f"{label}.recurrence must be an integer greater than zero.")

        evidence = entry["evidence"]
        if not isinstance(evidence, list):
            errors.append(f"{label}.evidence must be an array.")
            evidence = []
        if entry["priority"] in {"P0", "P1"} and not evidence:
            errors.append(f"{label} requires evidence because it is {entry['priority']}.")
        for evidence_index, item in enumerate(evidence):
            evidence_label = f"{label}.evidence[{evidence_index}]"
            if not isinstance(item, dict):
                errors.append(f"{evidence_label} must be an object.")
                continue
            if not _non_empty_string(item.get("kind")):
                errors.append(f"{evidence_label}.kind must be a non-empty string.")
            reference = item.get("reference")
            if not _non_empty_string(reference):
                errors.append(f"{evidence_label}.reference must be a non-empty string.")
            elif not _reference_exists(reference, repo_root):
                errors.append(f"{evidence_label}.reference does not exist: {reference}.")

        destinations = entry["destinations"]
        if not isinstance(destinations, list):
            errors.append(f"{label}.destinations must be an array.")
            destinations = []
        if entry["status"] in {"candidate", "validated", "adopted"}:
            if not _non_empty_string(entry["proposed_change"]):
                errors.append(f"{label} requires a concrete proposed_change.")
            if not destinations or not all(_non_empty_string(item) for item in destinations):
                errors.append(f"{label} requires at least one destination.")

        validation = entry["validation"]
        if entry["status"] in {"validated", "adopted"}:
            if not isinstance(validation, dict):
                errors.append(f"{label} requires a validation object.")
            elif validation.get("result") != "passed":
                errors.append(f"{label} requires validation.result=passed.")
            else:
                for field in ("reference", "summary"):
                    if not _non_empty_string(validation.get(field)):
                        errors.append(f"{label}.validation.{field} must be a non-empty string.")

        try:
            date.fromisoformat(entry["next_review"])
        except (TypeError, ValueError):
            errors.append(f"{label}.next_review must be an ISO date.")

    return errors


def build_report(data: dict[str, Any]) -> str:
    entries = data["entries"]
    lines = [
        "# Continuous Improvement Review",
        "",
        f"- Registry version: {data['version']}",
        f"- Updated: {data['updated_at']}",
        f"- Entries: {len(entries)}",
        "",
        "| ID | Priority | Status | Recurrence | Title | Next review |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for entry in entries:
        lines.append(
            f"| {entry['id']} | {entry['priority']} | {entry['status']} | "
            f"{entry['recurrence']} | {entry['title']} | {entry['next_review']} |"
        )

    candidates = [entry for entry in entries if entry["status"] in {"observed", "candidate"}]
    lines.extend(["", "## Open Improvement Work", ""])
    if not candidates:
        lines.append("No open improvement candidates.")
    else:
        for entry in candidates:
            lines.extend(
                [
                    f"### {entry['id']}: {entry['title']}",
                    "",
                    f"- Status: `{entry['status']}`",
                    f"- Proposed change: {entry['proposed_change'] or 'Not defined'}",
                    f"- Destination: {', '.join(entry['destinations']) or 'Not defined'}",
                    f"- Next review: {entry['next_review']}",
                    "",
                ]
            )
    return "\n".join(lines).rstrip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--registry",
        default="docs/continuous-improvement/registry.json",
        help="Registry path relative to the repository root.",
    )
    parser.add_argument("--report", help="Optional Markdown report path relative to the repository root.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[2]
    registry_path = repo_root / args.registry
    try:
        data = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Unable to read registry: {exc}", file=sys.stderr)
        return 1

    errors = validate_registry(data, repo_root)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    if args.report:
        report_path = repo_root / args.report
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(build_report(data), encoding="utf-8")
        print(f"Report written: {report_path}")

    print(f"Continuous improvement registry valid: {len(data['entries'])} entries.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

