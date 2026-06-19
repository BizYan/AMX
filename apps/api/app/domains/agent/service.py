"""Agent Runtime Domain Service

Business logic for workflow management, agent run execution, and skill execution.
"""

import asyncio
import ast
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import String, delete, or_, select, func, and_, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.domains.agent.models import (
    WorkflowDefinition,
    WorkflowVersion,
    AgentSkill,
    AgentSkillBinding,
    AgentProfile,
    AgentRun,
    AgentTask,
    AgentEvent,
    AgentRunStatus,
    AgentTaskStatus,
    WorkflowCategory,
    SkillStatus,
    AgentProfileStatus,
)
from app.domains.agent.schemas import (
    WorkflowDefinitionCreate,
    WorkflowDefinitionUpdate,
    WorkflowVersionCreate,
    SkillCatalogCreate,
    SkillCatalogUpdate,
    AgentProfileCreate,
    AgentProfileUpdate,
    AgentRunCreate,
    SkillContractSchema,
    ToolContractSchema,
    DAGSchema,
    DAGNodeSchema,
)

logger = logging.getLogger(__name__)


SUPPORTED_DAG_NODE_TYPES = {
    "skill",
    "tool",
    "condition",
    "parallel_group",
    "human_approval",
    "delay",
    "merge",
}


def _dag_issue(
    severity: str,
    code: str,
    message: str,
    node_id: str | None = None,
) -> dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "node_id": node_id,
        "message": message,
    }


def _node_config(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("config") if isinstance(node.get("config"), dict) else {}


def _node_data(node: dict[str, Any]) -> dict[str, Any]:
    return node.get("data") if isinstance(node.get("data"), dict) else {}


def _node_skill_name(node: dict[str, Any]) -> str | None:
    config = _node_config(node)
    data = _node_data(node)
    skill_name = (
        node.get("skill")
        or config.get("skill")
        or data.get("skill")
        or data.get("skill_name")
    )
    return str(skill_name).strip() if skill_name is not None and str(skill_name).strip() else None


def _node_tool_name(node: dict[str, Any]) -> str | None:
    config = _node_config(node)
    data = _node_data(node)
    tool_name = node.get("tool") or config.get("tool") or data.get("tool")
    return str(tool_name).strip() if tool_name is not None and str(tool_name).strip() else None


SENSITIVE_RUNTIME_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "credential",
    "credential_ref",
    "password",
    "secret",
    "token",
}


def _runtime_key_is_sensitive(key: Any) -> bool:
    normalized = str(key).strip().lower()
    return any(marker in normalized for marker in SENSITIVE_RUNTIME_KEYS)


def _sanitize_runtime_value(value: Any) -> Any:
    """Create a runtime evidence copy without raw credentials or tokens."""
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if _runtime_key_is_sensitive(key):
                continue
            sanitized[str(key)] = _sanitize_runtime_value(item)
        return sanitized
    if isinstance(value, list):
        return [_sanitize_runtime_value(item) for item in value]
    if isinstance(value, tuple):
        return [_sanitize_runtime_value(item) for item in value]
    return value


def _runtime_snapshot(value: dict[str, Any] | None) -> dict[str, Any]:
    """Deep-copy JSON-compatible runtime input into sanitized metadata."""
    return _sanitize_runtime_value(json.loads(json.dumps(value or {}, default=str)))


def _artifact_refs_from_tool_result(tool_name: str, tool_result: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract stable artifact references from tool output without embedding raw payloads."""
    refs: list[dict[str, Any]] = []
    data = tool_result.get("data") if isinstance(tool_result.get("data"), dict) else {}
    artifacts = data.get("artifacts") if isinstance(data.get("artifacts"), list) else []
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            continue
        artifact_id = artifact.get("artifact_id") or artifact.get("id")
        if not artifact_id:
            continue
        refs.append(
            {
                "kind": "export_artifact" if tool_name == "document_export" else "tool_artifact",
                "tool_name": tool_name,
                "artifact_id": str(artifact_id),
                "filename": artifact.get("filename"),
                "content_type": artifact.get("content_type"),
                "file_size": artifact.get("file_size"),
            }
        )
    job_id = data.get("job_id") or tool_result.get("job_id")
    if job_id:
        refs.append(
            {
                "kind": "export_job" if tool_name == "document_export" else "tool_job",
                "tool_name": tool_name,
                "job_id": str(job_id),
            }
        )
    return refs


def _condition_expression(node: dict[str, Any]) -> str | None:
    config = _node_config(node)
    data = _node_data(node)
    expression = (
        node.get("expression")
        or config.get("expression")
        or config.get("condition")
        or data.get("expression")
        or data.get("condition")
    )
    return str(expression).strip() if expression is not None and str(expression).strip() else None


def _approval_metadata(node: dict[str, Any]) -> dict[str, Any]:
    config = _node_config(node)
    data = _node_data(node)
    approver_role = (
        config.get("approver_role")
        or data.get("approver_role")
        or config.get("role")
        or data.get("role")
    )
    approvers = config.get("approvers") or data.get("approvers")
    approval_title = (
        config.get("approval_title")
        or data.get("approval_title")
        or config.get("title")
        or data.get("title")
    )
    return {
        "approval_title": str(approval_title).strip() if approval_title is not None else None,
        "approver_role": str(approver_role).strip() if approver_role is not None else None,
        "approvers": approvers if isinstance(approvers, list) else [],
    }


def _parallel_branches(node: dict[str, Any]) -> list[str]:
    config = _node_config(node)
    data = _node_data(node)
    raw_branches = config.get("branches") or data.get("branches") or node.get("branches") or []
    branches: list[str] = []
    if isinstance(raw_branches, list):
        for branch in raw_branches:
            if isinstance(branch, dict):
                branch_id = branch.get("target") or branch.get("node_id") or branch.get("id")
            else:
                branch_id = branch
            branch_id = str(branch_id or "").strip()
            if branch_id:
                branches.append(branch_id)
    return branches


def _condition_paths(node: dict[str, Any]) -> list[dict[str, Any]]:
    config = _node_config(node)
    data = _node_data(node)
    raw_paths = config.get("paths") or config.get("branches") or data.get("paths") or []
    if isinstance(raw_paths, dict):
        raw_paths = [{"label": label, "target": target} for label, target in raw_paths.items()]
    paths: list[dict[str, Any]] = []
    if isinstance(raw_paths, list):
        for index, path in enumerate(raw_paths):
            if isinstance(path, dict):
                label = path.get("label") or path.get("name") or path.get("condition") or f"path_{index + 1}"
                target = path.get("target") or path.get("node_id") or path.get("next")
                condition = path.get("expression") or path.get("condition") or path.get("when")
            else:
                label = str(path)
                target = None
                condition = None
            paths.append(
                {
                    "label": str(label),
                    "target": str(target) if target is not None else None,
                    "condition": str(condition).strip() if condition is not None and str(condition).strip() else None,
                }
            )
    return paths


def _lookup_path(source: Any, key: Any) -> Any:
    """Read dict/list/object values for restricted workflow expressions."""
    if isinstance(source, dict):
        return source.get(str(key))
    if isinstance(source, list) and isinstance(key, int) and 0 <= key < len(source):
        return source[key]
    return getattr(source, str(key), None)


def _safe_condition_value(
    node: ast.AST,
    workflow_input: dict[str, Any],
    previous_outputs: dict[str, Any] | None = None,
) -> Any:
    """Evaluate a small, non-executable expression subset for routing."""
    previous_outputs = previous_outputs or {}
    if isinstance(node, ast.Expression):
        return _safe_condition_value(node.body, workflow_input, previous_outputs)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id == "input":
            return workflow_input
        if node.id == "outputs":
            return previous_outputs
        if node.id in {"true", "True"}:
            return True
        if node.id in {"false", "False"}:
            return False
        if node.id in {"none", "None", "null"}:
            return None
        return workflow_input.get(node.id)
    if isinstance(node, ast.Attribute):
        return _lookup_path(
            _safe_condition_value(node.value, workflow_input, previous_outputs),
            node.attr,
        )
    if isinstance(node, ast.Subscript):
        slice_node = node.slice
        key = _safe_condition_value(slice_node, workflow_input, previous_outputs)
        return _lookup_path(
            _safe_condition_value(node.value, workflow_input, previous_outputs),
            key,
        )
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return not bool(_safe_condition_value(node.operand, workflow_input, previous_outputs))
    if isinstance(node, ast.BoolOp):
        values = [
            bool(_safe_condition_value(value, workflow_input, previous_outputs))
            for value in node.values
        ]
        if isinstance(node.op, ast.And):
            return all(values)
        if isinstance(node.op, ast.Or):
            return any(values)
    if isinstance(node, ast.Compare):
        left = _safe_condition_value(node.left, workflow_input, previous_outputs)
        for op, comparator in zip(node.ops, node.comparators, strict=False):
            right = _safe_condition_value(comparator, workflow_input, previous_outputs)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Gt):
                ok = left is not None and right is not None and left > right
            elif isinstance(op, ast.GtE):
                ok = left is not None and right is not None and left >= right
            elif isinstance(op, ast.Lt):
                ok = left is not None and right is not None and left < right
            elif isinstance(op, ast.LtE):
                ok = left is not None and right is not None and left <= right
            elif isinstance(op, ast.In):
                ok = right is not None and left in right
            elif isinstance(op, ast.NotIn):
                ok = right is None or left not in right
            else:
                raise ValueError("Unsupported condition operator")
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, ast.List):
        return [_safe_condition_value(item, workflow_input, previous_outputs) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_safe_condition_value(item, workflow_input, previous_outputs) for item in node.elts)
    raise ValueError(f"Unsupported condition expression element: {type(node).__name__}")


def _evaluate_condition_expression(
    expression: str | None,
    workflow_input: dict[str, Any],
    previous_outputs: dict[str, Any] | None = None,
) -> bool:
    """Return the boolean value of a restricted condition expression."""
    if not expression:
        return False
    parsed = ast.parse(expression, mode="eval")
    return bool(_safe_condition_value(parsed, workflow_input, previous_outputs))


def validate_workflow_dag(
    dag_json: dict[str, Any],
    valid_skill_names: set[str] | None = None,
) -> dict[str, Any]:
    """Validate DAG shape and return deterministic execution order."""
    issues: list[dict[str, Any]] = []
    execution_order: list[str] = []

    if not isinstance(dag_json, dict):
        return {
            "valid": False,
            "issues": [_dag_issue("error", "invalid_dag", "DAG must be a JSON object")],
            "execution_order": [],
        }

    nodes = dag_json.get("nodes", [])
    if not isinstance(nodes, list):
        return {
            "valid": False,
            "issues": [_dag_issue("error", "invalid_nodes", "DAG nodes must be a list")],
            "execution_order": [],
        }

    if not nodes:
        return {
            "valid": False,
            "issues": [_dag_issue("error", "empty_dag", "DAG must contain at least one node")],
            "execution_order": [],
        }

    node_map: dict[str, dict[str, Any]] = {}
    dependencies: dict[str, list[str]] = {}

    for index, node in enumerate(nodes):
        if not isinstance(node, dict):
            issues.append(_dag_issue("error", "invalid_node", f"Node at index {index} must be an object"))
            continue

        node_id = str(node.get("id") or "").strip()
        if not node_id:
            issues.append(_dag_issue("error", "missing_node_id", f"Node at index {index} is missing id"))
            continue

        if node_id in node_map:
            issues.append(_dag_issue("error", "duplicate_node_id", f"Duplicate node id '{node_id}'", node_id))
            continue

        node_map[node_id] = node

    for node_id, node in node_map.items():
        raw_dependencies = node.get("depends_on", [])
        if raw_dependencies is None:
            raw_dependencies = []
        if not isinstance(raw_dependencies, list):
            issues.append(_dag_issue("error", "invalid_dependencies", "depends_on must be a list", node_id))
            raw_dependencies = []

        normalized_dependencies: list[str] = []
        for dependency in raw_dependencies:
            dependency_id = str(dependency or "").strip()
            if not dependency_id:
                continue
            if dependency_id == node_id:
                issues.append(_dag_issue("error", "self_dependency", "Node cannot depend on itself", node_id))
            elif dependency_id not in node_map:
                issues.append(
                    _dag_issue(
                        "error",
                        "missing_dependency",
                        f"Node depends on undefined node '{dependency_id}'",
                        node_id,
                    )
                )
            else:
                normalized_dependencies.append(dependency_id)
        dependencies[node_id] = normalized_dependencies

        config = _node_config(node)
        skill_name = _node_skill_name(node)
        tool_name = _node_tool_name(node)
        node_type = str(node.get("type") or "").strip()

        if not node_type:
            issues.append(_dag_issue("error", "missing_node_type", "Node type is required", node_id))
        elif node_type not in SUPPORTED_DAG_NODE_TYPES:
            issues.append(_dag_issue("error", "unknown_node_type", f"Unknown node type '{node_type}'", node_id))

        if skill_name and valid_skill_names is not None and skill_name not in valid_skill_names:
            issues.append(
                _dag_issue(
                    "error",
                    "unavailable_skill",
                    f"Skill '{skill_name}' is not published or available",
                    node_id,
                )
            )
        elif node_type == "skill" and not skill_name:
            issues.append(_dag_issue("error", "skill_binding_missing", "Skill node has no skill binding", node_id))
        elif node_type == "tool" and not tool_name:
            issues.append(_dag_issue("warning", "tool_binding_missing", "Tool node has no tool binding", node_id))
        elif not skill_name and not tool_name and node_type not in {
            "condition",
            "merge",
            "parallel_group",
            "human_approval",
            "delay",
        }:
            issues.append(_dag_issue("warning", "node_binding_missing", "Node has no skill or tool binding", node_id))

        if node_type == "condition" and not _condition_expression(node):
            issues.append(
                _dag_issue(
                    "error",
                    "condition_missing_expression",
                    "Condition node must define a non-empty expression",
                    node_id,
                )
            )
        if node_type == "human_approval":
            approval = _approval_metadata(node)
            if not approval["approval_title"]:
                issues.append(
                    _dag_issue(
                        "error",
                        "human_approval_missing_title",
                        "Human approval node must define approval_title",
                        node_id,
                    )
                )
            if not approval["approver_role"] and not approval["approvers"]:
                issues.append(
                    _dag_issue(
                        "error",
                        "human_approval_missing_approver",
                        "Human approval node must define approver_role or approvers",
                        node_id,
                    )
                )
        if node_type == "parallel_group":
            branches = _parallel_branches(node)
            if not branches:
                issues.append(_dag_issue("warning", "parallel_group_empty", "Parallel group has no explicit branches", node_id))
            for branch_id in branches:
                if branch_id not in node_map:
                    issues.append(
                        _dag_issue(
                            "error",
                            "parallel_branch_missing",
                            f"Parallel group references undefined branch '{branch_id}'",
                            node_id,
                        )
                    )
        if node_type == "delay":
            duration = config.get("duration_seconds") or config.get("delay_seconds")
            if duration is None:
                issues.append(
                    _dag_issue(
                        "warning",
                        "delay_missing_duration",
                        "Delay node has no duration_seconds configured",
                        node_id,
                    )
                )

    adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
    in_degree: dict[str, int] = {node_id: 0 for node_id in node_map}
    for node_id, dependency_ids in dependencies.items():
        for dependency_id in dependency_ids:
            if dependency_id not in node_map:
                continue
            adjacency[dependency_id].append(node_id)
            in_degree[node_id] += 1

    queue = [node_id for node_id, degree in in_degree.items() if degree == 0]
    while queue:
        node_id = queue.pop(0)
        execution_order.append(node_id)
        for child_id in adjacency[node_id]:
            in_degree[child_id] -= 1
            if in_degree[child_id] == 0:
                queue.append(child_id)

    if len(execution_order) != len(node_map):
        issues.append(_dag_issue("error", "dependency_cycle", "DAG contains a dependency cycle"))

    has_errors = any(issue["severity"] == "error" for issue in issues)
    return {
        "valid": not has_errors,
        "issues": issues,
        "execution_order": execution_order if not has_errors else [],
    }


def build_workflow_execution_preview(
    dag_json: dict[str, Any],
    input_data: dict[str, Any] | None = None,
    valid_skill_names: set[str] | None = None,
) -> dict[str, Any]:
    """Build a frontend-friendly workflow execution preview."""
    validation = validate_workflow_dag(dag_json, valid_skill_names)
    nodes = dag_json.get("nodes", []) if isinstance(dag_json, dict) else []
    node_by_id = {
        str(node.get("id")): node
        for node in nodes
        if isinstance(node, dict) and str(node.get("id") or "").strip()
    }
    ordered_ids = validation["execution_order"] or list(node_by_id.keys())

    parallel_groups: list[dict[str, Any]] = []
    approval_gates: list[dict[str, Any]] = []
    condition_paths: list[dict[str, Any]] = []

    for node_id in ordered_ids:
        node = node_by_id.get(node_id)
        if not node:
            continue
        node_type = str(node.get("type") or "").strip()
        config = _node_config(node)
        if node_type == "parallel_group":
            parallel_groups.append(
                {
                    "node_id": node_id,
                    "branches": _parallel_branches(node),
                    "depends_on": node.get("depends_on", []),
                }
            )
        elif node_type == "human_approval":
            approval = _approval_metadata(node)
            approval_gates.append(
                {
                    "node_id": node_id,
                    "approval_title": approval["approval_title"],
                    "approver_role": approval["approver_role"],
                    "approvers": approval["approvers"],
                    "depends_on": node.get("depends_on", []),
                }
            )
        elif node_type == "condition":
            condition_paths.append(
                {
                    "node_id": node_id,
                    "expression": _condition_expression(node),
                    "paths": _condition_paths(node),
                    "depends_on": node.get("depends_on", []),
                    "input_keys": list((input_data or {}).keys()),
                }
            )
        elif node_type == "delay":
            parallel_groups.append(
                {
                    "node_id": node_id,
                    "type": "delay",
                    "duration_seconds": config.get("duration_seconds") or config.get("delay_seconds"),
                    "depends_on": node.get("depends_on", []),
                }
            )

    blocking_issues = [
        issue for issue in validation["issues"] if issue.get("severity") == "error"
    ]
    return {
        "valid": validation["valid"],
        "issues": validation["issues"],
        "execution_order": validation["execution_order"],
        "parallel_groups": parallel_groups,
        "approval_gates": approval_gates,
        "condition_paths": condition_paths,
        "estimated_steps": len(node_by_id),
        "blocking_issues": blocking_issues,
    }


class SkillCatalogService:
    """Service for marketplace-style skill catalog management."""

    BUILTIN_SKILL_METADATA = {
        "MECEAnalyzer": {
            "display_name": "MECE 分析器",
            "skill_type": "analysis",
            "category": "consulting",
            "supported_doc_types": ["brd", "prd", "strategy"],
            "governance_scope": "system",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
        },
        "IssueTreeAnalyzer": {
            "display_name": "问题树分析器",
            "skill_type": "analysis",
            "category": "consulting",
            "supported_doc_types": ["brd", "strategy"],
            "governance_scope": "system",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
        },
        "DocumentReviewer": {
            "display_name": "文档评审器",
            "skill_type": "quality",
            "category": "review",
            "supported_doc_types": ["urs", "brd", "prd", "test_case"],
            "governance_scope": "system",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
        },
        "RequirementClarifier": {
            "display_name": "需求澄清器",
            "skill_type": "clarification",
            "category": "requirements",
            "supported_doc_types": ["urs", "brd", "prd"],
            "governance_scope": "system",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
        },
        "ExportOrchestrator": {
            "display_name": "导出编排器",
            "skill_type": "export",
            "category": "delivery",
            "supported_doc_types": ["urs", "brd", "prd", "test_case"],
            "governance_scope": "system",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
        },
        "BRDDeepThinkingEngine": {
            "display_name": "BRD 深度澄清引擎",
            "skill_type": "clarification",
            "category": "brd",
            "supported_doc_types": ["brd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:brd-deep-thinking-engine",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "deep-thinking-engine"},
        },
        "BRDWritePipeline": {
            "display_name": "BRD 写入管线",
            "skill_type": "generation",
            "category": "brd",
            "supported_doc_types": ["brd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:brd-write-pipeline",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "brd-write-pipeline"},
        },
        "BRDResearchAssistant": {
            "display_name": "BRD 行业调研辅助",
            "skill_type": "research",
            "category": "brd",
            "supported_doc_types": ["brd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:brd-research",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "brd-research"},
        },
        "BRDPatternLibrary": {
            "display_name": "BRD 模式库",
            "skill_type": "analysis",
            "category": "brd",
            "supported_doc_types": ["brd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:brd-pattern",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "brd-pattern"},
        },
        "BRDOffTopicHandler": {
            "display_name": "对话边界处理",
            "skill_type": "guardrail",
            "category": "conversation",
            "supported_doc_types": ["brd", "prd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:off-topic-handler",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "off-topic-handler"},
        },
        "PRDTraceabilityMapper": {
            "display_name": "PRD 血缘映射器",
            "skill_type": "generation",
            "category": "prd",
            "supported_doc_types": ["prd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:prd-traceability-mapper",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "prd-brd-traceability"},
        },
        "PRDSkeletonPlanner": {
            "display_name": "PRD 骨架规划器",
            "skill_type": "generation",
            "category": "prd",
            "supported_doc_types": ["prd"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:prd-skeleton-planner",
            "metadata": {"source": "prototype_adapted", "prototype_adaptation": "prd-skeleton-first"},
        },
        "DocumentTemplateSectionPlanner": {
            "display_name": "文档模板章节规划器",
            "skill_type": "generation",
            "category": "template",
            "supported_doc_types": ["brd", "prd", "test_case"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:template-section-planner",
            "metadata": {"source": "project_builtin", "use_case": "template_section_design"},
        },
        "ChangeImpactAnalyzer": {
            "display_name": "变更影响分析器",
            "skill_type": "analysis",
            "category": "change",
            "supported_doc_types": ["brd", "prd", "test_case"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:change-impact-analysis",
            "metadata": {"source": "project_builtin", "use_case": "traceability_impact"},
        },
        "KnowledgeGraphExtractor": {
            "display_name": "知识图谱抽取器",
            "skill_type": "extraction",
            "category": "knowledge",
            "supported_doc_types": ["urs", "brd", "prd", "test_case"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:knowledge-graph-extraction",
            "metadata": {"source": "project_builtin", "use_case": "knowledge_graph"},
        },
        "TestCaseDesigner": {
            "display_name": "测试用例设计器",
            "skill_type": "generation",
            "category": "testing",
            "supported_doc_types": ["prd", "test_case"],
            "governance_scope": "platform",
            "visibility": "platform",
            "managed_by": "platform",
            "is_locked": 1,
            "implementation_ref": "methodology:test-case-design",
            "metadata": {"source": "project_builtin", "use_case": "test_case_generation"},
        },
    }

    BUILTIN_SKILL_TEST_FIXTURES = {
        "MECEAnalyzer": {
            "test_scenario": "检查 PRD 功能模块拆分是否互斥且覆盖完整。",
            "sample_input": {
                "content": "业务流程优化包含申请提交、资料校验、任务分派、质量复核和异常处理模块。",
                "categories": ["申请提交", "资料校验", "任务分派", "异常处理"],
            },
            "sample_context": {"document_type": "prd", "project_name": "业务流程优化"},
        },
        "IssueTreeAnalyzer": {
            "test_scenario": "把处理超时的问题拆解为可分析的问题树。",
            "sample_input": {"issue": "审批处理超时率高", "depth": 3, "branch_type": "cause"},
            "sample_context": {"industry": "general_business", "document_type": "brd"},
        },
        "DocumentReviewer": {
            "test_scenario": "评审一段 PRD 草稿是否结构清晰、是否仍有占位内容。",
            "sample_input": {
                "content": "## 质量复核\n- 系统必须支持逐项校验并记录处理人、时间和结果。\n- 异常任务进入人工复核队列，处理结论写入审计记录。",
                "review_type": "detailed",
                "check_list": ["结构完整性", "占位内容", "验收标准"],
            },
            "sample_context": {"document_type": "prd", "stage": "draft_review"},
        },
        "RequirementClarifier": {
            "test_scenario": "识别含糊需求并给出澄清问题。",
            "sample_input": {
                "requirements": [
                    "系统应该尽快完成任务分派。",
                    "异常任务可能需要人工处理。",
                    "质量复核必须记录处理人和时间。",
                ],
                "context": "当前项目为业务流程优化 BRD。",
            },
            "sample_context": {"document_type": "brd", "project_name": "业务流程优化"},
        },
        "ExportOrchestrator": {
            "test_scenario": "模拟把文档导出为 Word。",
            "sample_input": {"document_id": "prd-quality-review-001", "format": "word", "options": {"include_toc": True}},
            "sample_context": {"document_type": "prd"},
        },
        "BRDDeepThinkingEngine": {
            "test_scenario": "根据用户回答判断 BRD 当前章节是否足够，并生成下一问。",
            "sample_input": {
                "user_message": "目前处理超时主要发生在资料补全后，复核环节只抽检，缺少逐项校验。",
                "current_section": "brd.business_flows",
                "known_facts": ["系统覆盖申请提交、资料校验、任务分派、复核和归档"],
            },
            "sample_context": {"document_type": "brd", "project_name": "业务流程优化"},
        },
        "BRDWritePipeline": {
            "test_scenario": "把已确认事实写成 BRD 业务流程章节草稿。",
            "sample_input": {
                "section_key": "brd.business_flows",
                "confirmed_facts": [
                    "现有复核只抽检，无法覆盖全部任务。",
                    "目标是建立逐项校验和异常拦截。",
                ],
                "quality_rules": [{"rule": "必须包含现状、目标流程、异常处理"}],
            },
            "sample_context": {"document_type": "brd"},
        },
        "BRDResearchAssistant": {
            "test_scenario": "判断 BRD 是否需要补充行业调研主题。",
            "sample_input": {"industry": "general_business", "unknown_terms": ["任务分派", "质量复核", "异常拦截"]},
            "sample_context": {"document_type": "brd"},
        },
        "BRDPatternLibrary": {
            "test_scenario": "为业务流程优化项目推荐 BRD 章节写作模式。",
            "sample_input": {
                "domain": "business_process_optimization",
                "section_key": "brd.requirement_modules",
                "keywords": ["任务分派", "复核", "异常拦截"],
            },
            "sample_context": {"document_type": "brd"},
        },
        "BRDOffTopicHandler": {
            "test_scenario": "识别用户输入是否偏离当前文档生成任务。",
            "sample_input": {"user_message": "顺便帮我生成一张宣传海报。", "active_task": "BRD 业务流程澄清"},
            "sample_context": {"document_type": "brd"},
        },
        "PRDTraceabilityMapper": {
            "test_scenario": "把 BRD 痛点映射为 PRD 功能追踪行。",
            "sample_input": {
                "brd_content": "痛点：复核只抽检导致处理遗漏。目标：逐项校验并记录异常。",
                "product_scope": "质量复核模块",
            },
            "sample_context": {"document_type": "prd", "source_document_type": "brd"},
        },
        "PRDSkeletonPlanner": {
            "test_scenario": "根据追踪行生成 PRD 模块骨架。",
            "sample_input": {
                "traceability_rows": [
                    {"brd_item": "逐项校验", "prd_module": "质量复核", "priority": "P0"}
                ],
                "module_candidates": ["质量复核", "异常拦截", "操作审计"],
            },
            "sample_context": {"document_type": "prd"},
        },
        "DocumentTemplateSectionPlanner": {
            "test_scenario": "为 PRD 模板规划可复用章节结构。",
            "sample_input": {
                "doc_type": "prd",
                "business_domain": "business_process_optimization",
                "required_sections": ["功能范围", "业务规则", "验收标准"],
            },
            "sample_context": {"template_name": "PRD 标准模板"},
        },
        "ChangeImpactAnalyzer": {
            "test_scenario": "分析 BRD 变更对 PRD、测试用例和模板章节的影响。",
            "sample_input": {
                "change_summary": "BRD 增加逐项校验要求。",
                "source_document": "业务流程优化 BRD",
                "linked_artifacts": ["流程优化 PRD", "质量复核测试用例", "PRD 标准模板"],
            },
            "sample_context": {"document_type": "brd", "change_type": "requirement_added"},
        },
        "KnowledgeGraphExtractor": {
            "test_scenario": "从文档片段抽取业务实体、流程和依赖关系。",
            "sample_input": {
                "content": "任务提交后，复核员逐项校验资料完整性和处理结果，异常任务进入人工处理。",
                "project_context": "业务流程优化",
            },
            "sample_context": {"document_type": "brd"},
        },
        "TestCaseDesigner": {
            "test_scenario": "根据 PRD 功能点生成验收测试用例草案。",
            "sample_input": {
                "feature_name": "逐项质量复核",
                "acceptance_criteria": [
                    "复核项必须匹配当前任务。",
                    "资料或处理结果不一致时阻止归档并记录异常。",
                ],
            },
            "sample_context": {"document_type": "test_case", "source_document_type": "prd"},
        },
    }

    def __init__(self, db: AsyncSession):
        self.db = db

    async def _get_or_dedupe_builtin_skill(
        self,
        tenant_id: UUID,
        skill_name: str,
    ) -> AgentSkill | None:
        """Return one active built-in skill and retire historical duplicates."""
        result = await self.db.execute(
            select(AgentSkill)
            .where(
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.name == skill_name,
                AgentSkill.is_builtin == 1,
                AgentSkill.deleted_at.is_(None),
            )
            .order_by(AgentSkill.created_at.asc(), AgentSkill.id.asc())
        )
        active_skills = list(result.scalars().all())
        if not active_skills:
            return None

        keeper = active_skills[0]
        duplicates = active_skills[1:]
        if not duplicates:
            return keeper

        duplicate_ids = [skill.id for skill in duplicates]
        await self.db.execute(
            update(AgentSkillBinding)
            .where(AgentSkillBinding.skill_id.in_(duplicate_ids))
            .values(skill_id=keeper.id)
        )

        deleted_at = datetime.now(timezone.utc)
        for duplicate in duplicates:
            duplicate.deleted_at = deleted_at

        return keeper

    async def ensure_builtin_skills(self, tenant_id: UUID, created_by: UUID) -> None:
        """Seed built-in skills into the tenant catalog if missing."""
        for skill in SkillService.BUILTIN_SKILLS.values():
            existing_skill = await self._get_or_dedupe_builtin_skill(
                tenant_id,
                skill["name"],
            )
            metadata = self.BUILTIN_SKILL_METADATA.get(skill["name"], {})
            metadata_json = {"source": "builtin"}
            metadata_json.update(metadata.get("metadata", {}))
            metadata_json.update(self.BUILTIN_SKILL_TEST_FIXTURES.get(skill["name"], {}))
            if existing_skill:
                existing_skill.display_name = metadata.get("display_name", existing_skill.display_name)
                existing_skill.description = skill.get("description", existing_skill.description)
                existing_skill.skill_type = metadata.get("skill_type", existing_skill.skill_type)
                existing_skill.category = metadata.get("category", existing_skill.category)
                existing_skill.input_schema_json = skill.get("input_schema", existing_skill.input_schema_json)
                existing_skill.output_schema_json = skill.get("output_schema", existing_skill.output_schema_json)
                existing_skill.supported_doc_types = metadata.get(
                    "supported_doc_types", existing_skill.supported_doc_types
                )
                existing_skill.governance_scope = metadata.get(
                    "governance_scope", existing_skill.governance_scope or "system"
                )
                existing_skill.visibility = metadata.get("visibility", existing_skill.visibility or "platform")
                existing_skill.managed_by = metadata.get("managed_by", existing_skill.managed_by or "platform")
                existing_skill.is_locked = metadata.get("is_locked", existing_skill.is_locked or 1)
                existing_skill.implementation_ref = metadata.get(
                    "implementation_ref", existing_skill.implementation_ref or f"builtin:{skill['name']}"
                )
                existing_skill.metadata_json = {**(existing_skill.metadata_json or {}), **metadata_json}
                continue

            self.db.add(
                AgentSkill(
                    tenant_id=tenant_id,
                    name=skill["name"],
                    display_name=metadata.get("display_name", skill["name"]),
                    description=skill.get("description"),
                    skill_type=metadata.get("skill_type", "builtin"),
                    category=metadata.get("category", "builtin"),
                    input_schema_json=skill.get("input_schema", {}),
                    output_schema_json=skill.get("output_schema", {}),
                    supported_doc_types=metadata.get("supported_doc_types", []),
                    supported_industries=[],
                    version="1.0.0",
                    status=SkillStatus.PUBLISHED.value,
                    is_builtin=1,
                    governance_scope=metadata.get("governance_scope", "system"),
                    visibility=metadata.get("visibility", "platform"),
                    managed_by=metadata.get("managed_by", "platform"),
                    is_locked=metadata.get("is_locked", 1),
                    implementation_ref=metadata.get("implementation_ref", f"builtin:{skill['name']}"),
                    metadata_json=metadata_json,
                    created_by=created_by,
                )
            )
        await self.db.flush()

    async def list_skills(
        self,
        tenant_id: UUID,
        created_by: UUID,
        skill_type: str | None = None,
        status: str | None = None,
        doc_type: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[AgentSkill], int]:
        """List skills with catalog filters."""
        await self.ensure_builtin_skills(tenant_id, created_by)

        query = select(AgentSkill).where(
            AgentSkill.tenant_id == tenant_id,
            AgentSkill.deleted_at.is_(None),
        )

        if skill_type:
            query = query.where(AgentSkill.skill_type == skill_type)
        if status:
            query = query.where(AgentSkill.status == status)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    AgentSkill.name.ilike(pattern),
                    AgentSkill.display_name.ilike(pattern),
                    AgentSkill.description.ilike(pattern),
                    AgentSkill.category.ilike(pattern),
                )
            )

        result = await self.db.execute(
            query.order_by(
                AgentSkill.is_builtin.desc(),
                AgentSkill.skill_type,
                AgentSkill.name,
            )
        )
        skills = list(result.scalars().all())

        if doc_type:
            skills = [
                skill
                for skill in skills
                if doc_type in (skill.supported_doc_types or [])
            ]

        total = len(skills)
        return skills[skip : skip + limit], total

    async def create_skill(
        self,
        tenant_id: UUID,
        created_by: UUID,
        data: SkillCatalogCreate,
    ) -> AgentSkill:
        """Create a custom skill."""
        if data.governance_scope in {"system", "platform"}:
            raise ValueError("Tenant users cannot create system or platform scoped skills")

        skill = AgentSkill(
            tenant_id=tenant_id,
            name=data.name,
            display_name=data.display_name or data.name,
            description=data.description,
            skill_type=data.skill_type,
            category=data.category,
            input_schema_json=data.input_schema_json,
            output_schema_json=data.output_schema_json,
            supported_doc_types=data.supported_doc_types,
            supported_industries=data.supported_industries,
            version=data.version,
            status=data.status,
            is_builtin=0,
            governance_scope=data.governance_scope or "tenant",
            visibility=data.visibility or "tenant",
            managed_by="tenant",
            is_locked=0,
            implementation_ref=data.implementation_ref,
            metadata_json=data.metadata_json,
            created_by=created_by,
        )
        self.db.add(skill)
        await self.db.flush()
        await self.db.refresh(skill)
        return skill

    async def get_skill(
        self,
        skill_id: UUID,
        tenant_id: UUID | None = None,
    ) -> AgentSkill | None:
        """Get a catalog skill by ID."""
        query = select(AgentSkill).where(
            AgentSkill.id == skill_id,
            AgentSkill.deleted_at.is_(None),
        )
        if tenant_id is not None:
            query = query.where(AgentSkill.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_skill(
        self,
        skill_id: UUID,
        tenant_id: UUID | None,
        data: SkillCatalogUpdate,
    ) -> AgentSkill | None:
        """Update a custom skill or catalog metadata for a built-in skill."""
        skill = await self.get_skill(skill_id, tenant_id)
        if not skill:
            return None
        if not skill.can_edit:
            raise ValueError(f"Skill is locked: {skill.locked_reason}")

        updates = data.model_dump(exclude_unset=True)
        if updates.get("governance_scope") in {"system", "platform"}:
            raise ValueError("Tenant users cannot promote skills to system or platform scope")
        for field, value in updates.items():
            setattr(skill, field, value)

        await self.db.flush()
        await self.db.refresh(skill)
        return skill

    async def set_skill_status(
        self,
        skill_id: UUID,
        tenant_id: UUID | None,
        status: str,
    ) -> AgentSkill | None:
        """Publish or disable a skill."""
        skill = await self.get_skill(skill_id, tenant_id)
        if not skill:
            return None
        if not skill.can_disable and status == SkillStatus.DISABLED.value:
            raise ValueError(f"Skill is locked: {skill.locked_reason}")
        if not skill.can_publish and status == SkillStatus.PUBLISHED.value:
            raise ValueError(f"Skill is locked: {skill.locked_reason}")

        skill.status = status
        await self.db.flush()
        await self.db.refresh(skill)
        return skill

    async def test_skill(
        self,
        skill_id: UUID,
        tenant_id: UUID | None,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Validate and execute a catalog skill in test mode."""
        import time

        skill = await self.get_skill(skill_id, tenant_id)
        if not skill:
            return None
        if skill.status == SkillStatus.DISABLED.value:
            raise ValueError("Skill is disabled")

        start_time = time.time()
        schema_errors = self._validate_input_contract(
            skill.input_schema_json or {},
            input_data,
        )
        if schema_errors:
            execution_time_ms = round((time.time() - start_time) * 1000, 2)
            return {
                "skill": skill,
                "success": False,
                "output_data": None,
                "error_message": "; ".join(schema_errors),
                "execution_time_ms": execution_time_ms,
                "mode": "contract",
            }

        implementation_ref = skill.implementation_ref or ""
        builtin_skill_name = None
        if implementation_ref.startswith("builtin:"):
            builtin_skill_name = implementation_ref.split(":", 1)[1]
        elif skill.name in SkillService.BUILTIN_SKILLS:
            builtin_skill_name = skill.name

        try:
            run_id = None
            task_id = None
            context_data = dict(context or {})
            project_id = self._coerce_uuid(context_data.get("project_id"))
            created_by = self._coerce_uuid(context_data.get("created_by"))

            run = await AgentRunService(self.db).create_run(
                tenant_id=tenant_id,
                project_id=project_id,
                run_type="direct_skill",
                input_data=input_data,
                created_by=created_by,
                metadata_json={
                    "execution_kind": "direct_skill",
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "mode": "builtin" if builtin_skill_name else "contract",
                },
            )
            run_id = run.id
            await AgentRunService(self.db).update_run_status(
                run_id=run.id,
                tenant_id=tenant_id,
                status=AgentRunStatus.RUNNING.value,
            )
            await AgentRunService(self.db).log_event(
                run_id=run.id,
                tenant_id=tenant_id,
                event_type="direct_skill_started",
                event_data={
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "mode": "builtin" if builtin_skill_name else "contract",
                },
            )

            if builtin_skill_name:
                task, output_data, duration_ms = await AgentRunService(
                    self.db
                ).execute_tracked_skill_task(
                    run_id=run.id,
                    tenant_id=tenant_id,
                    node_id=f"direct:{skill.name}",
                    skill_name=builtin_skill_name,
                    input_data=input_data,
                    context={
                        **context_data,
                        "run_id": str(run.id),
                        "run_type": "direct_skill",
                        "skill_id": str(skill.id),
                    },
                )
                task_id = task.id
                mode = "builtin"
            else:
                output_data = {
                    "message": "Custom skill contract validation passed",
                    "input_data": input_data,
                }
                output_data = SkillService(self.db).normalize_skill_output(
                    skill.name,
                    output_data,
                    {"run_id": str(run.id), "run_type": "direct_skill"},
                )
                task = await AgentRunService(self.db).submit_task(
                    run_id=run.id,
                    tenant_id=tenant_id,
                    node_id=f"direct:{skill.name}",
                    skill_name=skill.name,
                    input_data=input_data,
                )
                task_id = task.id
                duration_ms = round((time.time() - start_time) * 1000, 2)
                await AgentRunService(self.db).update_task_status(
                    task.id,
                    AgentTaskStatus.COMPLETED.value,
                    output_data={
                        "result": output_data,
                        "execution": {
                            "duration_ms": duration_ms,
                            "skill_name": skill.name,
                            "mode": "contract",
                        },
                    },
                )
                mode = "contract"

            execution_time_ms = round((time.time() - start_time) * 1000, 2)
            await AgentRunService(self.db).merge_run_metadata(
                run.id,
                tenant_id,
                {
                    "task_id": str(task_id),
                    "duration_ms": execution_time_ms,
                    "status": AgentRunStatus.COMPLETED.value,
                },
            )
            await AgentRunService(self.db).update_run_status(
                run_id=run.id,
                tenant_id=tenant_id,
                status=AgentRunStatus.COMPLETED.value,
            )
            await AgentRunService(self.db).log_event(
                run_id=run.id,
                tenant_id=tenant_id,
                event_type="direct_skill_completed",
                event_data={
                    "skill_id": str(skill.id),
                    "skill_name": skill.name,
                    "task_id": str(task_id),
                    "duration_ms": execution_time_ms,
                },
            )

            return {
                "skill": skill,
                "success": True,
                "output_data": output_data,
                "error_message": None,
                "execution_time_ms": execution_time_ms,
                "mode": mode,
                "run_id": str(run_id),
                "task_id": str(task_id),
            }
        except Exception as exc:
            if "run_id" in locals() and run_id is not None:
                await AgentRunService(self.db).update_run_status(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    status=AgentRunStatus.FAILED.value,
                    error_message=str(exc),
                )
                await AgentRunService(self.db).log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="direct_skill_failed",
                    event_data={"skill_id": str(skill.id), "skill_name": skill.name, "error": str(exc)},
                )
            return {
                "skill": skill,
                "success": False,
                "output_data": None,
                "error_message": str(exc),
                "execution_time_ms": round((time.time() - start_time) * 1000, 2),
                "mode": "builtin" if builtin_skill_name else "contract",
            }

    @staticmethod
    def _coerce_uuid(value: Any) -> UUID | None:
        """Best-effort UUID coercion for optional execution context IDs."""
        if value is None or isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _validate_input_contract(
        input_schema: dict[str, Any],
        input_data: dict[str, Any],
    ) -> list[str]:
        """Perform lightweight JSON-schema-style required field validation."""
        if not input_schema:
            return []
        if input_schema.get("type") == "object" and not isinstance(input_data, dict):
            return ["Input data must be an object"]

        errors = []
        required = input_schema.get("required", [])
        if isinstance(required, list):
            for field in required:
                if isinstance(field, str) and field not in input_data:
                    errors.append(f"Missing required input field: {field}")
        return errors


class AgentProfileService:
    """Service for configurable agent profiles and skill bindings."""

    DEFAULT_AGENT_PROFILES = [
        {
            "name": "BRD 业务分析顾问",
            "description": "面向 BRD 的业务访谈、流程梳理、行业补充和章节草稿生成 Agent。",
            "agent_type": "brd",
            "applicable_doc_types": ["brd"],
            "tool_names": ["knowledge_graph", "web_search"],
            "workflow_template_id": "brd-document-generation",
            "skill_names": [
                "RequirementClarifier",
                "BRDDeepThinkingEngine",
                "BRDResearchAssistant",
                "BRDPatternLibrary",
                "BRDWritePipeline",
                "DocumentReviewer",
            ],
            "system_prompt": "你是资深业务分析顾问，负责把访谈输入沉淀为可追溯、可验收的 BRD。",
        },
        {
            "name": "PRD 产品方案顾问",
            "description": "把 BRD 目标、痛点和流程映射为 PRD 模块、功能、规则和验收标准。",
            "agent_type": "prd",
            "applicable_doc_types": ["prd"],
            "tool_names": ["knowledge_graph", "document_export"],
            "workflow_template_id": "conditional-requirement-governance",
            "skill_names": [
                "PRDTraceabilityMapper",
                "PRDSkeletonPlanner",
                "MECEAnalyzer",
                "DocumentReviewer",
            ],
            "system_prompt": "你是产品方案顾问，必须保持 PRD 与 BRD 的需求血缘一致。",
        },
        {
            "name": "文档质量评审顾问",
            "description": "评审 URS、BRD、PRD 和测试用例的结构完整性、逻辑闭环和占位内容。",
            "agent_type": "quality",
            "applicable_doc_types": ["urs", "brd", "prd", "test_case"],
            "tool_names": ["knowledge_graph"],
            "workflow_template_id": "document-quality-assessment",
            "skill_names": ["DocumentReviewer", "MECEAnalyzer", "IssueTreeAnalyzer"],
            "system_prompt": "你是文档质量评审顾问，优先指出缺口、矛盾、不可验收表达和追溯断点。",
        },
        {
            "name": "变更影响分析顾问",
            "description": "分析需求和文档变更对 PRD、测试用例、模板章节和知识图谱的影响。",
            "agent_type": "change",
            "applicable_doc_types": ["brd", "prd", "test_case"],
            "tool_names": ["knowledge_graph"],
            "workflow_template_id": "change-impact-governance",
            "skill_names": ["ChangeImpactAnalyzer", "PRDTraceabilityMapper", "TestCaseDesigner"],
            "system_prompt": "你是变更影响分析顾问，负责给出影响范围、更新建议和回归验证建议。",
        },
        {
            "name": "模板与知识图谱顾问",
            "description": "规划文档模板章节，并从项目文档中抽取实体、流程和关系。",
            "agent_type": "knowledge",
            "applicable_doc_types": ["urs", "brd", "prd"],
            "tool_names": ["knowledge_graph"],
            "workflow_template_id": "parallel-quality-review",
            "skill_names": ["DocumentTemplateSectionPlanner", "KnowledgeGraphExtractor", "BRDPatternLibrary"],
            "system_prompt": "你是模板与知识图谱顾问，负责让模板结构和知识图谱可复用、可追溯。",
        },
        {
            "name": "交付导出顾问",
            "description": "负责发布前文档评审、导出格式选择和交付包生成检查。",
            "agent_type": "delivery",
            "applicable_doc_types": ["urs", "brd", "prd", "test_case"],
            "tool_names": ["document_export"],
            "workflow_template_id": "delivery-export-orchestration",
            "skill_names": ["ExportOrchestrator", "DocumentReviewer"],
            "system_prompt": "你是交付导出顾问，负责把已确认文档稳定导出为交付格式。",
        },
    ]

    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_default_agent_profiles(self, tenant_id: UUID, created_by: UUID) -> None:
        """Seed project-specific agent profiles for first-run testing."""
        await SkillCatalogService(self.db).ensure_builtin_skills(tenant_id, created_by)
        await WorkflowService(self.db).ensure_default_workflows(tenant_id, created_by)

        skill_names = {
            skill_name
            for profile in self.DEFAULT_AGENT_PROFILES
            for skill_name in profile["skill_names"]
        }
        skill_result = await self.db.execute(
            select(AgentSkill).where(
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.name.in_(skill_names),
                AgentSkill.deleted_at.is_(None),
            )
        )
        skill_by_name = {skill.name: skill for skill in skill_result.scalars().all()}

        workflow_template_names = {
            workflow["template_id"]: workflow["name"]
            for workflow in WorkflowService.list_workflow_templates()
        }
        workflow_result = await self.db.execute(
            select(WorkflowDefinition).where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.name.in_(workflow_template_names.values()),
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        workflow_by_name = {workflow.name: workflow for workflow in workflow_result.scalars().all()}

        for profile_data in self.DEFAULT_AGENT_PROFILES:
            workflow_name = workflow_template_names.get(
                str(profile_data.get("workflow_template_id") or "")
            )
            workflow = workflow_by_name.get(workflow_name) if workflow_name else None
            result = await self.db.execute(
                select(AgentProfile).where(
                    AgentProfile.tenant_id == tenant_id,
                    AgentProfile.name == profile_data["name"],
                    AgentProfile.deleted_at.is_(None),
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                if workflow and not existing.workflow_definition_id:
                    existing.workflow_definition_id = workflow.id
                continue

            profile = AgentProfile(
                tenant_id=tenant_id,
                name=profile_data["name"],
                description=profile_data["description"],
                agent_type=profile_data["agent_type"],
                applicable_doc_types=profile_data["applicable_doc_types"],
                tool_names=profile_data["tool_names"],
                workflow_definition_id=workflow.id if workflow else None,
                human_review_required=1,
                status=AgentProfileStatus.ACTIVE.value,
                system_prompt=profile_data["system_prompt"],
                created_by=created_by,
            )
            self.db.add(profile)
            await self.db.flush()

            for order_index, skill_name in enumerate(profile_data["skill_names"]):
                skill = skill_by_name.get(skill_name)
                if not skill:
                    continue
                self.db.add(
                    AgentSkillBinding(
                        tenant_id=tenant_id,
                        agent_profile_id=profile.id,
                        skill_id=skill.id,
                        order_index=order_index,
                        is_required=1,
                    )
                )

        await self.db.flush()

    async def list_agent_profiles(
        self,
        tenant_id: UUID,
        created_by: UUID | None = None,
        agent_type: str | None = None,
        status: str | None = None,
        doc_type: str | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[AgentProfile], int]:
        """List agent profiles with filters."""
        if created_by is not None:
            await self.ensure_default_agent_profiles(tenant_id, created_by)

        query = (
            select(AgentProfile)
            .options(
                selectinload(AgentProfile.skill_bindings).selectinload(
                    AgentSkillBinding.skill
                )
            )
            .where(
                AgentProfile.tenant_id == tenant_id,
                AgentProfile.deleted_at.is_(None),
            )
        )

        if agent_type:
            query = query.where(AgentProfile.agent_type == agent_type)
        if status:
            query = query.where(AgentProfile.status == status)
        if search:
            pattern = f"%{search}%"
            query = query.where(
                or_(
                    AgentProfile.name.ilike(pattern),
                    AgentProfile.description.ilike(pattern),
                )
            )

        result = await self.db.execute(
            query.order_by(AgentProfile.status, AgentProfile.agent_type, AgentProfile.name)
        )
        profiles = list(result.scalars().unique().all())

        if doc_type:
            profiles = [
                profile
                for profile in profiles
                if doc_type in (profile.applicable_doc_types or [])
            ]

        total = len(profiles)
        return profiles[skip : skip + limit], total

    async def get_agent_profile(
        self,
        agent_profile_id: UUID,
        tenant_id: UUID | None = None,
    ) -> AgentProfile | None:
        """Get an agent profile with skill bindings."""
        query = (
            select(AgentProfile)
            .options(
                selectinload(AgentProfile.skill_bindings).selectinload(
                    AgentSkillBinding.skill
                )
            )
            .where(
                AgentProfile.id == agent_profile_id,
                AgentProfile.deleted_at.is_(None),
            )
        )
        if tenant_id is not None:
            query = query.where(AgentProfile.tenant_id == tenant_id)

        result = await self.db.execute(query.execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    async def create_agent_profile(
        self,
        tenant_id: UUID,
        created_by: UUID,
        data: AgentProfileCreate,
    ) -> AgentProfile:
        """Create an agent profile and bind selected skills."""
        await self._validate_skill_ids(tenant_id, data.skill_ids)

        profile = AgentProfile(
            tenant_id=tenant_id,
            name=data.name,
            description=data.description,
            agent_type=data.agent_type,
            applicable_doc_types=data.applicable_doc_types,
            default_template_id=data.default_template_id,
            tool_names=data.tool_names,
            workflow_definition_id=data.workflow_definition_id,
            human_review_required=1 if data.human_review_required else 0,
            status=data.status,
            system_prompt=data.system_prompt,
            created_by=created_by,
        )
        self.db.add(profile)
        await self.db.flush()

        await self.replace_skill_bindings(profile.id, tenant_id, data.skill_ids)
        profile_with_bindings = await self.get_agent_profile(profile.id, tenant_id)
        return profile_with_bindings or profile

    async def update_agent_profile(
        self,
        agent_profile_id: UUID,
        tenant_id: UUID | None,
        data: AgentProfileUpdate,
    ) -> AgentProfile | None:
        """Update an agent profile and optionally replace skills."""
        profile = await self.get_agent_profile(agent_profile_id, tenant_id)
        if not profile:
            return None

        updates = data.model_dump(exclude_unset=True)
        skill_ids = updates.pop("skill_ids", None)
        if skill_ids is not None:
            await self.replace_skill_bindings(profile.id, tenant_id, skill_ids)

        for field, value in updates.items():
            if field == "human_review_required" and value is not None:
                value = 1 if value else 0
            setattr(profile, field, value)

        await self.db.flush()
        await self.db.refresh(profile)
        return await self.get_agent_profile(profile.id, tenant_id)

    async def replace_skill_bindings(
        self,
        agent_profile_id: UUID,
        tenant_id: UUID | None,
        skill_ids: list[UUID],
    ) -> list[AgentSkillBinding]:
        """Replace an agent profile's ordered skill bindings."""
        if tenant_id is not None:
            await self._validate_skill_ids(tenant_id, skill_ids)

        await self.db.execute(
            delete(AgentSkillBinding).where(
                AgentSkillBinding.agent_profile_id == agent_profile_id
            )
        )

        bindings = []
        for order_index, skill_id in enumerate(skill_ids):
            binding = AgentSkillBinding(
                tenant_id=tenant_id,
                agent_profile_id=agent_profile_id,
                skill_id=skill_id,
                order_index=order_index,
                is_required=1,
            )
            self.db.add(binding)
            bindings.append(binding)

        await self.db.flush()
        return bindings

    async def set_agent_status(
        self,
        agent_profile_id: UUID,
        tenant_id: UUID | None,
        status: str,
    ) -> AgentProfile | None:
        """Enable, disable, or draft an agent profile."""
        profile = await self.get_agent_profile(agent_profile_id, tenant_id)
        if not profile:
            return None

        profile.status = status
        await self.db.flush()
        await self.db.refresh(profile)
        return await self.get_agent_profile(profile.id, tenant_id)

    async def _validate_skill_ids(self, tenant_id: UUID, skill_ids: list[UUID]) -> None:
        """Ensure all requested skill IDs are visible to the tenant."""
        if not skill_ids:
            return

        result = await self.db.execute(
            select(AgentSkill.id).where(
                AgentSkill.tenant_id == tenant_id,
                AgentSkill.id.in_(skill_ids),
                AgentSkill.deleted_at.is_(None),
            )
        )
        found = set(result.scalars().all())
        missing = [str(skill_id) for skill_id in skill_ids if skill_id not in found]
        if missing:
            raise ValueError(f"Skill not found or unavailable: {', '.join(missing)}")


class WorkflowService:
    """Service for workflow definition and version management.

    Handles CRUD operations for workflows and their versions,
    including DAG management and version activation.
    """

    def __init__(self, db: AsyncSession):
        """Initialize workflow service.

        Args:
            db: Async database session
        """
        self.db = db

    DEFAULT_WORKFLOWS = [
        {
            "template_id": "brd-document-generation",
            "name": "BRD Document Generation",
            "display_name": "BRD 文档生成流水线",
            "description": "Default first-run workflow for BRD clarification, drafting, and review.",
            "category": WorkflowCategory.DOCUMENT_GENERATION.value,
            "recommended_doc_types": ["brd"],
            "readiness_checks": ["已发布需求澄清 Skill", "已发布 BRD 写入 Skill", "已配置人工评审关口"],
            "dag_json": {
                "nodes": [
                    {"id": "clarify", "type": "skill", "skill": "RequirementClarifier"},
                    {
                        "id": "draft",
                        "type": "skill",
                        "skill": "BRDWritePipeline",
                        "depends_on": ["clarify"],
                    },
                    {
                        "id": "review",
                        "type": "skill",
                        "skill": "DocumentReviewer",
                        "depends_on": ["draft"],
                    },
                ]
            },
        },
        {
            "template_id": "document-quality-assessment",
            "name": "Document Quality Assessment",
            "display_name": "文档质量评审流水线",
            "description": "Default workflow for document quality and structure review.",
            "category": WorkflowCategory.QUALITY_ASSESSMENT.value,
            "recommended_doc_types": ["urs", "brd", "prd", "test_case"],
            "readiness_checks": ["已发布文档评审 Skill", "已发布 MECE 分析 Skill", "失败运行可重试"],
            "dag_json": {
                "nodes": [
                    {"id": "review", "type": "skill", "skill": "DocumentReviewer"},
                    {
                        "id": "mece",
                        "type": "skill",
                        "skill": "MECEAnalyzer",
                        "depends_on": ["review"],
                    },
                ]
            },
        },
        {
            "template_id": "delivery-export-orchestration",
            "name": "Delivery Export Orchestration",
            "display_name": "交付导出编排流水线",
            "description": "Default workflow for pre-delivery review and export orchestration.",
            "category": WorkflowCategory.EXPORT_ORCHESTRATION.value,
            "recommended_doc_types": ["urs", "brd", "prd", "test_case"],
            "readiness_checks": ["交付前质量评审", "导出任务编排", "运行事件可追踪"],
            "dag_json": {
                "nodes": [
                    {"id": "review", "type": "skill", "skill": "DocumentReviewer"},
                    {
                        "id": "export",
                        "type": "skill",
                        "skill": "ExportOrchestrator",
                        "depends_on": ["review"],
                    },
                ]
            },
        },
        {
            "template_id": "change-impact-governance",
            "name": "Change Impact Governance",
            "display_name": "变更影响治理流水线",
            "description": "Trace requirement changes into downstream PRD, test, template, and knowledge impacts.",
            "category": WorkflowCategory.REQUIREMENT_ANALYSIS.value,
            "recommended_doc_types": ["brd", "prd", "test_case"],
            "readiness_checks": ["变更影响分析", "PRD 追溯映射", "测试用例联动"],
            "dag_json": {
                "nodes": [
                    {"id": "impact", "type": "skill", "skill": "ChangeImpactAnalyzer"},
                    {
                        "id": "traceability",
                        "type": "skill",
                        "skill": "PRDTraceabilityMapper",
                        "depends_on": ["impact"],
                    },
                    {
                        "id": "tests",
                        "type": "skill",
                        "skill": "TestCaseDesigner",
                        "depends_on": ["traceability"],
                    },
                ]
            },
        },
        {
            "template_id": "human-approval-delivery-pipeline",
            "name": "Human Approval Delivery Pipeline",
            "display_name": "\u4eba\u5de5\u5ba1\u6279\u4ea4\u4ed8\u6d41\u6c34\u7ebf",
            "description": "Delivery workflow with explicit human approval, wait metadata, and export traceability.",
            "category": WorkflowCategory.EXPORT_ORCHESTRATION.value,
            "recommended_doc_types": ["urs", "brd", "prd", "test_case"],
            "readiness_checks": ["quality_review", "delivery_owner_approval", "export_trace"],
            "dag_json": {
                "nodes": [
                    {"id": "review", "type": "skill", "skill": "DocumentReviewer"},
                    {
                        "id": "approval",
                        "type": "human_approval",
                        "depends_on": ["review"],
                        "config": {
                            "approval_title": "Approve delivery package",
                            "approver_role": "delivery_owner",
                        },
                    },
                    {
                        "id": "stabilize",
                        "type": "delay",
                        "depends_on": ["approval"],
                        "config": {"duration_seconds": 300},
                    },
                    {
                        "id": "export",
                        "type": "skill",
                        "skill": "ExportOrchestrator",
                        "depends_on": ["stabilize"],
                    },
                ]
            },
        },
        {
            "template_id": "conditional-requirement-governance",
            "name": "Conditional Requirement Governance",
            "display_name": "\u6761\u4ef6\u5206\u652f\u9700\u6c42\u6cbb\u7406\u6d41\u6c34\u7ebf",
            "description": "Requirement governance workflow with risk-based conditional routing.",
            "category": WorkflowCategory.REQUIREMENT_ANALYSIS.value,
            "recommended_doc_types": ["brd", "prd"],
            "readiness_checks": ["impact_analysis", "conditional_branch", "traceability"],
            "dag_json": {
                "nodes": [
                    {"id": "impact", "type": "skill", "skill": "ChangeImpactAnalyzer"},
                    {
                        "id": "risk_branch",
                        "type": "condition",
                        "depends_on": ["impact"],
                        "config": {
                            "expression": "input.risk_level == 'high'",
                            "paths": [
                                {"label": "high_risk", "target": "approval"},
                                {"label": "standard", "target": "traceability"},
                            ],
                        },
                    },
                    {
                        "id": "approval",
                        "type": "human_approval",
                        "depends_on": ["risk_branch"],
                        "config": {
                            "approval_title": "Approve high-risk requirement change",
                            "approver_role": "product_owner",
                        },
                    },
                    {
                        "id": "traceability",
                        "type": "skill",
                        "skill": "PRDTraceabilityMapper",
                        "depends_on": ["risk_branch"],
                    },
                ]
            },
        },
        {
            "template_id": "parallel-quality-review",
            "name": "Parallel Quality Review",
            "display_name": "\u5e76\u884c\u8d28\u91cf\u8bc4\u5ba1\u6d41\u6c34\u7ebf",
            "description": "Parallel quality checks for document review, MECE structure, and test case impact.",
            "category": WorkflowCategory.QUALITY_ASSESSMENT.value,
            "recommended_doc_types": ["brd", "prd", "test_case"],
            "readiness_checks": ["parallel_review", "quality_gate", "merge_evidence"],
            "dag_json": {
                "nodes": [
                    {"id": "prepare", "type": "skill", "skill": "RequirementClarifier"},
                    {
                        "id": "parallel_reviews",
                        "type": "parallel_group",
                        "depends_on": ["prepare"],
                        "config": {"branches": ["document_review", "mece_review", "test_review"]},
                    },
                    {
                        "id": "document_review",
                        "type": "skill",
                        "skill": "DocumentReviewer",
                        "depends_on": ["parallel_reviews"],
                    },
                    {
                        "id": "mece_review",
                        "type": "skill",
                        "skill": "MECEAnalyzer",
                        "depends_on": ["parallel_reviews"],
                    },
                    {
                        "id": "test_review",
                        "type": "skill",
                        "skill": "TestCaseDesigner",
                        "depends_on": ["parallel_reviews"],
                    },
                ]
            },
        },
    ]

    @classmethod
    def _template_skill_names(cls, dag_json: dict[str, Any]) -> list[str]:
        """Extract unique skill names from a workflow template DAG."""
        names: list[str] = []
        for node in (dag_json or {}).get("nodes", []):
            if not isinstance(node, dict):
                continue
            config = node.get("config") if isinstance(node.get("config"), dict) else {}
            data = node.get("data") if isinstance(node.get("data"), dict) else {}
            skill_name = (
                node.get("skill")
                or config.get("skill")
                or data.get("skill")
                or data.get("skill_name")
            )
            if skill_name and skill_name not in names:
                names.append(str(skill_name))
        return names

    @classmethod
    def list_workflow_templates(cls) -> list[dict[str, Any]]:
        """Return platform workflow templates in response-ready shape."""
        templates: list[dict[str, Any]] = []
        for template in cls.DEFAULT_WORKFLOWS:
            dag_json = template["dag_json"]
            templates.append(
                {
                    "template_id": template["template_id"],
                    "name": template["name"],
                    "display_name": template.get("display_name") or template["name"],
                    "description": template["description"],
                    "category": template["category"],
                    "dag_json": dag_json,
                    "node_count": len(dag_json.get("nodes", [])),
                    "skill_names": cls._template_skill_names(dag_json),
                    "recommended_doc_types": template.get("recommended_doc_types", []),
                    "readiness_checks": template.get("readiness_checks", []),
                }
            )
        return templates

    @classmethod
    def get_workflow_template(cls, template_id: str) -> dict[str, Any] | None:
        """Find a platform workflow template by stable template id."""
        for template in cls.list_workflow_templates():
            if template["template_id"] == template_id:
                return template
        return None

    async def ensure_default_workflows(self, tenant_id: UUID, created_by: UUID) -> None:
        """Seed active workflow definitions and versions for an empty tenant."""
        await SkillCatalogService(self.db).ensure_builtin_skills(tenant_id, created_by)

        for workflow_data in self.DEFAULT_WORKFLOWS:
            result = await self.db.execute(
                select(WorkflowDefinition).where(
                    WorkflowDefinition.tenant_id == tenant_id,
                    WorkflowDefinition.name == workflow_data["name"],
                    WorkflowDefinition.deleted_at.is_(None),
                )
            )
            existing = result.scalar_one_or_none()
            if existing:
                if existing.version_count < 1:
                    existing.version_count = 1
                continue

            workflow = WorkflowDefinition(
                tenant_id=tenant_id,
                name=workflow_data["name"],
                description=workflow_data["description"],
                category=workflow_data["category"],
                version_count=1,
                is_active=1,
                created_by=created_by,
            )
            self.db.add(workflow)
            await self.db.flush()
            self.db.add(
                WorkflowVersion(
                    workflow_definition_id=workflow.id,
                    version=1,
                    dag_json=workflow_data["dag_json"],
                    skill_contracts_json=[],
                    tool_contracts_json=[],
                    is_active=1,
                    created_by=created_by,
                )
            )

        await self.db.flush()

    async def create_workflow_from_template(
        self,
        tenant_id: UUID,
        created_by: UUID,
        template_id: str,
        name: str | None = None,
        description: str | None = None,
        publish: bool = True,
    ) -> WorkflowDefinition:
        """Create a tenant workflow and first version from a platform template."""
        template = self.get_workflow_template(template_id)
        if template is None:
            raise LookupError("Workflow template not found")

        await SkillCatalogService(self.db).ensure_builtin_skills(tenant_id, created_by)
        validation = await self.validate_dag(tenant_id, template["dag_json"])
        if not validation["valid"]:
            messages = [
                issue["message"]
                for issue in validation["issues"]
                if issue["severity"] == "error"
            ]
            raise ValueError("; ".join(messages) or "Workflow template is not executable")

        base_name = name or template["display_name"]
        existing_names = await self.db.execute(
            select(WorkflowDefinition.name).where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.name.like(f"{base_name}%"),
                WorkflowDefinition.deleted_at.is_(None),
            )
        )
        existing_name_set = set(existing_names.scalars().all())
        final_name = base_name
        suffix = 2
        while final_name in existing_name_set:
            final_name = f"{base_name} ({suffix})"
            suffix += 1

        workflow = await self.create_workflow(
            tenant_id=tenant_id,
            name=final_name,
            description=description or template["description"],
            category=template["category"],
            created_by=created_by,
        )
        version = await self.create_version(
            workflow_id=workflow.id,
            tenant_id=tenant_id,
            dag_json=template["dag_json"],
            skill_contracts=[],
            tool_contracts=[],
            created_by=created_by,
        )
        if version and publish:
            await self.activate_version(version.id, tenant_id)
        await self.db.refresh(workflow)
        return workflow

    async def create_workflow(
        self,
        tenant_id: UUID,
        name: str,
        description: str | None,
        category: str,
        created_by: UUID,
    ) -> WorkflowDefinition:
        """Create a new workflow definition.

        Args:
            tenant_id: Tenant UUID
            name: Workflow name
            description: Workflow description
            category: Workflow category
            created_by: User ID of creator

        Returns:
            Created WorkflowDefinition
        """
        workflow = WorkflowDefinition(
            tenant_id=tenant_id,
            name=name,
            description=description,
            category=category,
            version_count=0,
            is_active=1,
            created_by=created_by,
        )
        self.db.add(workflow)
        await self.db.flush()
        await self.db.refresh(workflow)
        return workflow

    async def get_workflow(
        self,
        workflow_id: UUID,
        tenant_id: UUID | None = None,
    ) -> WorkflowDefinition | None:
        """Get workflow by ID with versions loaded.

        Args:
            workflow_id: Workflow UUID
            tenant_id: Optional tenant filter

        Returns:
            WorkflowDefinition if found, None otherwise
        """
        query = (
            select(WorkflowDefinition)
            .options(selectinload(WorkflowDefinition.versions))
            .where(WorkflowDefinition.id == workflow_id)
            .where(WorkflowDefinition.deleted_at.is_(None))
        )
        if tenant_id is not None:
            query = query.where(WorkflowDefinition.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def list_workflows(
        self,
        tenant_id: UUID,
        created_by: UUID | None = None,
        category: str | None = None,
        is_active: bool | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[WorkflowDefinition], int]:
        """List workflows for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID
            category: Optional category filter
            is_active: Optional active filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of WorkflowDefinitions, total count)
        """
        if created_by is not None:
            await self.ensure_default_workflows(tenant_id, created_by)

        filters = [
            WorkflowDefinition.tenant_id == tenant_id,
            WorkflowDefinition.deleted_at.is_(None),
        ]

        if category is not None:
            filters.append(WorkflowDefinition.category == category)
        if is_active is not None:
            filters.append(WorkflowDefinition.is_active == (1 if is_active else 0))

        count_query = select(func.count()).select_from(WorkflowDefinition).where(*filters)
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        result = await self.db.execute(
            select(WorkflowDefinition)
            .where(*filters)
            .order_by(WorkflowDefinition.created_at.desc())
            .offset(skip)
            .limit(limit)
        )
        workflows = list(result.scalars().all())

        return workflows, total

    async def update_workflow(
        self,
        workflow_id: UUID,
        tenant_id: UUID | None,
        updates: WorkflowDefinitionUpdate,
    ) -> WorkflowDefinition | None:
        """Update a workflow definition.

        Args:
            workflow_id: Workflow UUID
            tenant_id: Optional tenant filter
            updates: Update data

        Returns:
            Updated WorkflowDefinition if found, None otherwise
        """
        workflow = await self.get_workflow(workflow_id, tenant_id)
        if not workflow:
            return None

        if updates.name is not None:
            workflow.name = updates.name
        if updates.description is not None:
            workflow.description = updates.description
        if updates.category is not None:
            workflow.category = updates.category
        if updates.is_active is not None:
            workflow.is_active = 1 if updates.is_active else 0

        await self.db.flush()
        await self.db.refresh(workflow)
        return workflow

    async def delete_workflow(
        self,
        workflow_id: UUID,
        tenant_id: UUID | None = None,
    ) -> bool:
        """Soft delete a workflow definition.

        Args:
            workflow_id: Workflow UUID
            tenant_id: Optional tenant filter

        Returns:
            True if deleted, False if not found
        """
        workflow = await self.get_workflow(workflow_id, tenant_id)
        if not workflow:
            return False

        workflow.deleted_at = datetime.now(timezone.utc)
        await self.db.flush()
        return True

    async def create_version(
        self,
        workflow_id: UUID,
        tenant_id: UUID | None,
        dag_json: dict[str, Any],
        skill_contracts: list[dict[str, Any]],
        tool_contracts: list[dict[str, Any]],
        created_by: UUID,
    ) -> WorkflowVersion | None:
        """Create a new workflow version.

        Args:
            workflow_id: Workflow UUID
            tenant_id: Optional tenant filter
            dag_json: DAG definition as JSON
            skill_contracts: List of skill contract dicts
            tool_contracts: List of tool contract dicts
            created_by: User ID

        Returns:
            Created WorkflowVersion if workflow found, None otherwise
        """
        workflow = await self.get_workflow(workflow_id, tenant_id)
        if not workflow:
            return None

        validation = await self.validate_dag(tenant_id, dag_json)
        if not validation["valid"]:
            messages = [
                issue["message"]
                for issue in validation["issues"]
                if issue["severity"] == "error"
            ]
            raise ValueError("; ".join(messages) or "Invalid workflow DAG")

        # Calculate next version number
        next_version = workflow.version_count + 1

        version = WorkflowVersion(
            workflow_definition_id=workflow_id,
            version=next_version,
            dag_json=dag_json,
            skill_contracts_json=skill_contracts,
            tool_contracts_json=tool_contracts,
            is_active=0,  # New versions are not active by default
            created_by=created_by,
        )
        self.db.add(version)

        # Update workflow version count
        workflow.version_count = next_version

        await self.db.flush()
        await self.db.refresh(version)
        return version

    async def get_active_version(
        self,
        workflow_id: UUID,
        tenant_id: UUID | None = None,
    ) -> WorkflowVersion | None:
        """Get the active version of a workflow.

        Args:
            workflow_id: Workflow UUID
            tenant_id: Optional tenant filter

        Returns:
            WorkflowVersion if found, None otherwise
        """
        query = select(WorkflowVersion).where(
            WorkflowVersion.workflow_definition_id == workflow_id,
            WorkflowVersion.is_active == 1,
        )

        # Optionally verify workflow belongs to tenant
        if tenant_id is not None:
            query = query.join(WorkflowDefinition).where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.deleted_at.is_(None),
            )

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def validate_dag(
        self,
        tenant_id: UUID | None,
        dag_json: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate workflow DAG against available catalog skills."""
        valid_skill_names = set(SkillService.BUILTIN_SKILLS.keys())
        if tenant_id is not None:
            result = await self.db.execute(
                select(AgentSkill.name).where(
                    AgentSkill.tenant_id == tenant_id,
                    AgentSkill.status == SkillStatus.PUBLISHED.value,
                    AgentSkill.deleted_at.is_(None),
                )
            )
            valid_skill_names.update(result.scalars().all())

        return validate_workflow_dag(dag_json, valid_skill_names)

    async def preview_dag(
        self,
        tenant_id: UUID | None,
        dag_json: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return runtime execution preview for a DAG and optional input."""
        valid_skill_names = set(SkillService.BUILTIN_SKILLS.keys())
        if tenant_id is not None:
            result = await self.db.execute(
                select(AgentSkill.name).where(
                    AgentSkill.tenant_id == tenant_id,
                    AgentSkill.status == SkillStatus.PUBLISHED.value,
                    AgentSkill.deleted_at.is_(None),
                )
            )
            valid_skill_names.update(result.scalars().all())

        return build_workflow_execution_preview(
            dag_json,
            input_data or {},
            valid_skill_names,
        )

    async def get_workflow_production_preflight(
        self,
        workflow_id: UUID,
        tenant_id: UUID | None,
        project_id: UUID | None = None,
        input_data: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Build a production run preflight for one workflow."""
        workflow = await self.get_workflow(workflow_id, tenant_id)
        if not workflow:
            return None

        active_version = await self.get_active_version(workflow_id, tenant_id)
        dag_json = active_version.dag_json if active_version else {"nodes": []}
        preview = await self.preview_dag(tenant_id, dag_json, input_data or {})

        recent_query = (
            select(AgentRun)
            .join(WorkflowVersion, AgentRun.workflow_version_id == WorkflowVersion.id)
            .where(
                WorkflowVersion.workflow_definition_id == workflow_id,
            )
            .order_by(AgentRun.created_at.desc())
            .limit(5)
        )
        if tenant_id is not None:
            recent_query = recent_query.where(AgentRun.tenant_id == tenant_id)
        recent_runs = list((await self.db.scalars(recent_query)).all())

        has_successful_run = any(
            run.status == AgentRunStatus.COMPLETED.value for run in recent_runs
        )
        has_failed_run = any(run.status == AgentRunStatus.FAILED.value for run in recent_runs)

        checks: list[dict[str, Any]] = []

        def add_check(
            code: str,
            severity: str,
            title: str,
            detail: str,
            status: str,
            action_label: str | None = None,
            action_href: str | None = None,
        ) -> None:
            checks.append(
                {
                    "code": code,
                    "severity": severity,
                    "title": title,
                    "detail": detail,
                    "status": status,
                    "action_label": action_label,
                    "action_href": action_href,
                }
            )

        if not bool(workflow.is_active):
            add_check(
                "workflow_disabled",
                "critical",
                "工作流已停用",
                "停用状态的工作流不能进入项目执行队列。",
                "failed",
                "启用工作流",
                f"/workflows/{workflow_id}/editor",
            )
        else:
            add_check(
                "workflow_enabled",
                "info",
                "工作流已启用",
                "工作流定义处于启用状态，可以进入版本和 DAG 检查。",
                "passed",
            )

        if not active_version:
            add_check(
                "missing_active_version",
                "critical",
                "缺少活动版本",
                "必须发布一个活动版本后才能执行工作流。",
                "failed",
                "发布版本",
                f"/workflows/{workflow_id}/editor",
            )
        else:
            add_check(
                "active_version",
                "info",
                "活动版本可用",
                f"当前将执行 v{active_version.version}。",
                "passed",
            )

        if preview["blocking_issues"]:
            add_check(
                "dag_blocked",
                "critical",
                "DAG 存在阻断项",
                "请先修复节点、依赖或 Skill 绑定问题。",
                "failed",
                "打开编辑器",
                f"/workflows/{workflow_id}/editor",
            )
        else:
            add_check(
                "dag_valid",
                "info",
                "DAG 校验通过",
                f"预计执行 {preview['estimated_steps']} 个节点。",
                "passed",
            )

        if project_id is None:
            add_check(
                "missing_project_context",
                "high",
                "缺少项目上下文",
                "生产执行需要绑定项目，便于写入文档、知识、审计和运行记录。",
                "failed",
                "选择项目",
                "/workflows",
            )
        else:
            add_check(
                "project_context",
                "info",
                "项目上下文已绑定",
                "运行将带入当前项目上下文。",
                "passed",
            )

        if preview["approval_gates"]:
            add_check(
                "human_approval_gates",
                "medium",
                "包含人工审批节点",
                f"检测到 {len(preview['approval_gates'])} 个审批门禁，运行中可能需要人工处理。",
                "warning",
                "查看运行中心",
                "/agent-ops",
            )

        if not recent_runs:
            add_check(
                "no_run_evidence",
                "medium",
                "缺少历史运行证据",
                "该工作流还没有运行记录，首次生产执行后应关注运行中心结果。",
                "warning",
                "执行一次",
                "/workflows",
            )
        elif has_failed_run and not has_successful_run:
            add_check(
                "recent_failures",
                "high",
                "最近运行存在失败",
                "该工作流已有失败记录且未看到成功运行，建议先处理失败原因。",
                "warning",
                "查看运行中心",
                f"/agent-ops?workflowDefinitionId={workflow_id}",
            )
        elif has_successful_run:
            add_check(
                "successful_run_evidence",
                "info",
                "已有成功运行证据",
                "最近运行记录包含成功完成结果。",
                "passed",
            )

        blockers = [check["title"] for check in checks if check["status"] == "failed"]
        warnings = [check["title"] for check in checks if check["status"] == "warning"]
        if blockers:
            gate_status = "blocked"
            gate_label = "不可执行"
            gate_summary = f"{len(blockers)} 个阻断项需要先处理。"
        elif warnings:
            gate_status = "attention"
            gate_label = "可执行但需关注"
            gate_summary = f"无阻断项，仍有 {len(warnings)} 个风险提示。"
        else:
            gate_status = "passed"
            gate_label = "可以执行"
            gate_summary = "工作流已具备生产执行前置条件。"

        next_actions = [
            check for check in checks if check["status"] in {"failed", "warning"}
        ][:4]

        return {
            "workflow_id": workflow.id,
            "workflow_name": workflow.name,
            "project_id": project_id,
            "active_version_id": active_version.id if active_version else None,
            "release_gate": {
                "status": gate_status,
                "label": gate_label,
                "summary": gate_summary,
                "blockers": blockers,
                "warnings": warnings,
            },
            "preview": preview,
            "checks": checks,
            "recent_runs": recent_runs,
            "next_actions": next_actions,
        }

    async def activate_version(
        self,
        version_id: UUID,
        tenant_id: UUID | None = None,
    ) -> WorkflowVersion | None:
        """Activate a workflow version (deactivates others).

        Args:
            version_id: WorkflowVersion UUID
            tenant_id: Optional tenant filter

        Returns:
            Updated WorkflowVersion if found, None otherwise
        """
        # Get the version to activate
        query = select(WorkflowVersion).where(WorkflowVersion.id == version_id)
        if tenant_id is not None:
            query = query.join(WorkflowDefinition).where(
                WorkflowDefinition.tenant_id == tenant_id
            )

        result = await self.db.execute(query)
        version = result.scalar_one_or_none()
        if not version:
            return None

        # Deactivate all other versions of the same workflow.
        deactivate_stmt = (
            update(WorkflowVersion)
            .where(
                WorkflowVersion.workflow_definition_id == version.workflow_definition_id,
                WorkflowVersion.id != version_id,
            )
            .values(is_active=0)
        )
        if tenant_id is not None:
            tenant_workflows = select(WorkflowDefinition.id).where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.deleted_at.is_(None),
            )
            deactivate_stmt = deactivate_stmt.where(
                WorkflowVersion.workflow_definition_id.in_(tenant_workflows)
            )

        await self.db.execute(deactivate_stmt)

        # Activate this version
        version.is_active = 1
        await self.db.flush()
        await self.db.refresh(version)
        return version

    async def get_version(
        self,
        version_id: UUID,
        tenant_id: UUID | None = None,
    ) -> WorkflowVersion | None:
        """Get a workflow version by ID.

        Args:
            version_id: WorkflowVersion UUID
            tenant_id: Optional tenant filter

        Returns:
            WorkflowVersion if found, None otherwise
        """
        query = select(WorkflowVersion).where(WorkflowVersion.id == version_id)
        if tenant_id is not None:
            query = query.join(WorkflowDefinition).where(
                WorkflowDefinition.tenant_id == tenant_id
            )

        result = await self.db.execute(query)
        return result.scalar_one_or_none()


class AgentRunService:
    """Service for agent run and task management.

    Handles agent run lifecycle, task submission, and status tracking.
    """

    def __init__(self, db: AsyncSession):
        """Initialize agent run service.

        Args:
            db: Async database session
        """
        self.db = db

    async def create_run(
        self,
        tenant_id: UUID,
        project_id: UUID | None,
        workflow_version_id: UUID | None = None,
        agent_profile_id: UUID | None = None,
        run_type: str = "workflow",
        created_by: UUID | None = None,
        input_data: dict[str, Any] | None = None,
        metadata_json: dict[str, Any] | None = None,
    ) -> AgentRun:
        """Create a new agent run.

        Args:
            tenant_id: Tenant UUID
            project_id: Project UUID
            workflow_version_id: Optional workflow version ID
            created_by: User ID (from JWT in production)

        Returns:
            Created AgentRun
        """
        merged_metadata = {**(metadata_json or {"execution_kind": run_type})}
        input_snapshot = _runtime_snapshot(input_data or {})
        merged_metadata.setdefault("input_snapshot", input_snapshot)
        merged_metadata.setdefault("input_snapshot_keys", sorted(input_snapshot.keys()))
        if workflow_version_id is not None:
            version = await self._get_workflow_version_snapshot(workflow_version_id, tenant_id)
            merged_metadata["workflow_version_id"] = str(workflow_version_id)
            if version is not None:
                merged_metadata["workflow_definition_id"] = str(version.workflow_definition_id)
                merged_metadata["workflow_version"] = version.version
        if created_by is not None:
            merged_metadata["created_by"] = str(created_by)
        run = AgentRun(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_profile_id=agent_profile_id,
            workflow_version_id=workflow_version_id,
            run_type=run_type,
            input_data=input_data or {},
            metadata_json=merged_metadata,
            status=AgentRunStatus.PENDING.value,
        )
        self.db.add(run)
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def _get_workflow_version_snapshot(
        self,
        workflow_version_id: UUID,
        tenant_id: UUID | None,
    ) -> WorkflowVersion | None:
        """Load workflow version identity for immutable run metadata."""
        query = select(WorkflowVersion).where(WorkflowVersion.id == workflow_version_id)
        if tenant_id is not None:
            query = query.join(WorkflowDefinition).where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.deleted_at.is_(None),
            )
        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def merge_run_metadata(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        metadata: dict[str, Any],
    ) -> AgentRun | None:
        """Merge execution metadata onto an existing run."""
        run = await self.get_run(run_id, tenant_id)
        if not run:
            return None
        run.metadata_json = {**(run.metadata_json or {}), **metadata}
        await self.db.flush()
        await self.db.refresh(run)
        return run

    async def get_run(
        self,
        run_id: UUID,
        tenant_id: UUID | None = None,
    ) -> AgentRun | None:
        """Get agent run by ID with tasks loaded.

        Args:
            run_id: AgentRun UUID
            tenant_id: Optional tenant filter

        Returns:
            AgentRun if found, None otherwise
        """
        query = (
            select(AgentRun)
            .options(
                selectinload(AgentRun.tasks),
                selectinload(AgentRun.events),
                selectinload(AgentRun.agent_profile),
                selectinload(AgentRun.workflow_version).selectinload(
                    WorkflowVersion.workflow_definition
                ),
            )
            .where(AgentRun.id == run_id)
        )
        if tenant_id is not None:
            query = query.where(AgentRun.tenant_id == tenant_id)

        result = await self.db.execute(query.execution_options(populate_existing=True))
        return result.scalar_one_or_none()

    async def list_runs(
        self,
        tenant_id: UUID,
        project_id: UUID | None = None,
        status: str | None = None,
        run_type: str | None = None,
        workflow_definition_id: UUID | None = None,
        workflow_version_id: UUID | None = None,
        agent_profile_id: UUID | None = None,
        search: str | None = None,
        skip: int = 0,
        limit: int = 20,
    ) -> tuple[list[AgentRun], int]:
        """List agent runs for a tenant with optional filters.

        Args:
            tenant_id: Tenant UUID
            project_id: Optional project filter
            status: Optional status filter
            skip: Number of records to skip
            limit: Maximum number of records to return

        Returns:
            Tuple of (list of AgentRuns, total count)
        """
        filters = [AgentRun.tenant_id == tenant_id]

        if project_id is not None:
            filters.append(AgentRun.project_id == project_id)
        if status is not None:
            filters.append(AgentRun.status == status)
        if run_type is not None:
            filters.append(AgentRun.run_type == run_type)
        if workflow_version_id is not None:
            filters.append(AgentRun.workflow_version_id == workflow_version_id)
        if agent_profile_id is not None:
            filters.append(AgentRun.agent_profile_id == agent_profile_id)
        if search:
            search_pattern = f"%{search.strip()}%"
            filters.append(
                or_(
                    AgentRun.id.cast(String).ilike(search_pattern),
                    AgentRun.error_message.ilike(search_pattern),
                    AgentRun.input_data.cast(String).ilike(search_pattern),
                    AgentRun.metadata_json.cast(String).ilike(search_pattern),
                )
            )

        query_from = AgentRun
        if workflow_definition_id is not None:
            filters.append(WorkflowVersion.workflow_definition_id == workflow_definition_id)
            query_from = AgentRun.__table__.join(
                WorkflowVersion.__table__,
                AgentRun.workflow_version_id == WorkflowVersion.id,
            )

        count_query = select(func.count()).select_from(query_from).where(*filters)
        count_result = await self.db.execute(count_query)
        total = count_result.scalar()

        runs_query = (
            select(AgentRun)
            .options(
                selectinload(AgentRun.tasks),
                selectinload(AgentRun.events),
                selectinload(AgentRun.agent_profile),
                selectinload(AgentRun.workflow_version).selectinload(
                    WorkflowVersion.workflow_definition
                ),
            )
            .where(*filters)
            .order_by(AgentRun.created_at.desc())
            .offset(skip)
            .limit(limit)
            .execution_options(populate_existing=True)
        )
        if workflow_definition_id is not None:
            runs_query = runs_query.join(
                WorkflowVersion,
                AgentRun.workflow_version_id == WorkflowVersion.id,
            )
        result = await self.db.execute(runs_query)
        runs = list(result.scalars().all())

        return runs, total

    async def bootstrap_orchestration(
        self,
        tenant_id: UUID,
        created_by: UUID,
    ) -> dict[str, Any]:
        """Explicitly initialize callable orchestration defaults for a tenant."""
        await SkillCatalogService(self.db).ensure_builtin_skills(tenant_id, created_by)
        await WorkflowService(self.db).ensure_default_workflows(tenant_id, created_by)
        await AgentProfileService(self.db).ensure_default_agent_profiles(tenant_id, created_by)

        async def count_where(model, *filters) -> int:
            result = await self.db.execute(select(func.count()).select_from(model).where(*filters))
            return int(result.scalar() or 0)

        published_skills = await count_where(
            AgentSkill,
            AgentSkill.tenant_id == tenant_id,
            AgentSkill.status == SkillStatus.PUBLISHED.value,
            AgentSkill.deleted_at.is_(None),
        )
        active_agents = await count_where(
            AgentProfile,
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.status == AgentProfileStatus.ACTIVE.value,
            AgentProfile.deleted_at.is_(None),
        )
        executable_agents = await count_where(
            AgentProfile,
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.status == AgentProfileStatus.ACTIVE.value,
            AgentProfile.workflow_definition_id.is_not(None),
            AgentProfile.deleted_at.is_(None),
        )
        active_workflows = await count_where(
            WorkflowDefinition,
            WorkflowDefinition.tenant_id == tenant_id,
            WorkflowDefinition.is_active == 1,
            WorkflowDefinition.deleted_at.is_(None),
        )
        executable_workflows_result = await self.db.execute(
            select(func.count(func.distinct(WorkflowDefinition.id)))
            .select_from(WorkflowDefinition)
            .join(WorkflowVersion, WorkflowVersion.workflow_definition_id == WorkflowDefinition.id)
            .where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.is_active == 1,
                WorkflowDefinition.deleted_at.is_(None),
                WorkflowVersion.is_active == 1,
            )
        )
        executable_workflows = int(executable_workflows_result.scalar() or 0)
        dashboard = await self.get_orchestration_dashboard(
            tenant_id=tenant_id,
            created_by=created_by,
        )
        return {
            "message": "Intelligent orchestration defaults initialized",
            "initialized": {
                "published_skills": published_skills,
                "active_agents": active_agents,
                "executable_agents": executable_agents,
                "active_workflows": active_workflows,
                "executable_workflows": executable_workflows,
            },
            "dashboard": dashboard,
        }

    async def get_orchestration_dashboard(
        self,
        tenant_id: UUID,
        created_by: UUID,
        recent_limit: int = 8,
    ) -> dict[str, Any]:
        """Build a production cockpit snapshot for intelligent orchestration."""
        await SkillCatalogService(self.db).ensure_builtin_skills(tenant_id, created_by)
        await AgentProfileService(self.db).ensure_default_agent_profiles(tenant_id, created_by)
        await WorkflowService(self.db).ensure_default_workflows(tenant_id, created_by)

        async def count_where(model, *filters) -> int:
            result = await self.db.execute(select(func.count()).select_from(model).where(*filters))
            return int(result.scalar() or 0)

        active_agents = await count_where(
            AgentProfile,
            AgentProfile.tenant_id == tenant_id,
            AgentProfile.status == AgentProfileStatus.ACTIVE.value,
            AgentProfile.deleted_at.is_(None),
        )
        published_skills = await count_where(
            AgentSkill,
            AgentSkill.tenant_id == tenant_id,
            AgentSkill.status == SkillStatus.PUBLISHED.value,
            AgentSkill.deleted_at.is_(None),
        )
        active_workflows = await count_where(
            WorkflowDefinition,
            WorkflowDefinition.tenant_id == tenant_id,
            WorkflowDefinition.is_active == 1,
            WorkflowDefinition.deleted_at.is_(None),
        )
        executable_result = await self.db.execute(
            select(func.count(func.distinct(WorkflowDefinition.id)))
            .select_from(WorkflowDefinition)
            .join(WorkflowVersion, WorkflowVersion.workflow_definition_id == WorkflowDefinition.id)
            .where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.is_active == 1,
                WorkflowDefinition.deleted_at.is_(None),
                WorkflowVersion.is_active == 1,
            )
        )
        executable_workflows = int(executable_result.scalar() or 0)

        status_rows = await self.db.execute(
            select(AgentRun.status, func.count())
            .where(AgentRun.tenant_id == tenant_id)
            .group_by(AgentRun.status)
        )
        run_status_counts = {str(status): int(count) for status, count in status_rows.all()}
        total_runs = sum(run_status_counts.values())
        running_runs = run_status_counts.get(AgentRunStatus.RUNNING.value, 0) + run_status_counts.get(
            AgentRunStatus.PENDING.value,
            0,
        )
        failed_runs = run_status_counts.get(AgentRunStatus.FAILED.value, 0)
        recoverable_runs = failed_runs + run_status_counts.get(AgentRunStatus.CANCELLED.value, 0)

        category_rows = await self.db.execute(
            select(WorkflowDefinition.category, func.count())
            .where(
                WorkflowDefinition.tenant_id == tenant_id,
                WorkflowDefinition.deleted_at.is_(None),
            )
            .group_by(WorkflowDefinition.category)
        )
        workflow_category_counts = {
            str(category): int(count) for category, count in category_rows.all()
        }
        recent_runs, _ = await self.list_runs(
            tenant_id=tenant_id,
            skip=0,
            limit=recent_limit,
        )

        recommendations: list[dict[str, Any]] = []
        if published_skills == 0:
            recommendations.append(
                {
                    "severity": "critical",
                    "code": "no_published_skills",
                    "title": "缺少已发布 Skill",
                    "detail": "没有可执行 Skill 时，Agent 和工作流只能保存配置，不能形成运行闭环。",
                    "action_label": "查看 Skill 市场",
                    "action_href": "/agents",
                }
            )
        if active_agents == 0:
            recommendations.append(
                {
                    "severity": "high",
                    "code": "no_active_agents",
                    "title": "缺少启用 Agent",
                    "detail": "至少需要一个启用 Agent 绑定 Skill 和工作流，才能从配置中心直接运行。",
                    "action_label": "配置 Agent",
                    "action_href": "/agents",
                }
            )
        if executable_workflows == 0:
            recommendations.append(
                {
                    "severity": "high",
                    "code": "no_executable_workflows",
                    "title": "缺少可执行工作流",
                    "detail": "工作流需要活动版本和通过校验的 DAG，才能在项目上下文中触发。",
                    "action_label": "从模板创建",
                    "action_href": "/workflows",
                }
            )
        if recoverable_runs > 0:
            recommendations.append(
                {
                    "severity": "medium",
                    "code": "recoverable_runs",
                    "title": "存在可恢复运行",
                    "detail": f"{recoverable_runs} 条失败或取消运行可以在运行中心重试。",
                    "action_label": "打开运行中心",
                    "action_href": "/agent-ops",
                }
            )
        if not recommendations:
            recommendations.append(
                {
                    "severity": "info",
                    "code": "ready",
                    "title": "智能编排基础闭环可用",
                    "detail": "Skill、Agent、工作流和运行观测均已具备可用配置。",
                    "action_label": "运行工作流",
                    "action_href": "/workflows",
                }
            )

        readiness_score = 0
        readiness_score += 25 if published_skills > 0 else 0
        readiness_score += 25 if active_agents > 0 else 0
        readiness_score += 30 if executable_workflows > 0 else 0
        readiness_score += 10 if total_runs > 0 else 0
        readiness_score += 10 if failed_runs == 0 else max(0, 10 - min(10, failed_runs * 2))

        return {
            "generated_at": datetime.now(timezone.utc),
            "readiness_score": min(100, readiness_score),
            "kpis": {
                "active_agents": active_agents,
                "published_skills": published_skills,
                "active_workflows": active_workflows,
                "executable_workflows": executable_workflows,
                "total_runs": total_runs,
                "running_runs": running_runs,
                "failed_runs": failed_runs,
                "recoverable_runs": recoverable_runs,
            },
            "run_status_counts": run_status_counts,
            "workflow_category_counts": workflow_category_counts,
            "recent_runs": recent_runs,
            "recommendations": recommendations,
            "template_count": len(WorkflowService.list_workflow_templates()),
        }

    async def update_run_status(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        status: str,
        error_message: str | None = None,
    ) -> AgentRun | None:
        """Update agent run status.

        Args:
            run_id: AgentRun UUID
            tenant_id: Optional tenant filter
            status: New status
            error_message: Optional error message

        Returns:
            Updated AgentRun if found, None otherwise
        """
        run = await self.get_run(run_id, tenant_id)
        if not run:
            return None

        previous_status = run.status
        run.status = status

        if status == AgentRunStatus.RUNNING.value and run.started_at is None:
            run.started_at = datetime.now(timezone.utc)
        elif status in [
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        ]:
            run.completed_at = datetime.now(timezone.utc)

        if error_message:
            run.error_message = error_message

        await self.db.flush()
        await self.db.refresh(run)
        if status != previous_status and status in {
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        }:
            from app.domains.notifications.service import UserNotificationService

            metadata = dict(run.metadata_json or {})
            created_by = metadata.get("created_by")
            try:
                user_id = created_by if isinstance(created_by, UUID) else UUID(str(created_by))
            except (TypeError, ValueError):
                user_id = None
            try:
                async with self.db.begin_nested():
                    await UserNotificationService(self.db).notify_agent_run_terminal(
                        tenant_id=run.tenant_id,
                        run_id=run.id,
                        user_id=user_id,
                        status=status,
                        project_id=run.project_id,
                        run_name=metadata.get("workflow_name") or metadata.get("agent_profile_name"),
                        error_message=run.error_message,
                    )
            except Exception:
                logger.exception("Failed to create terminal notification for Agent run %s", run.id)
        return await self.get_run(run.id, tenant_id) or run

    async def submit_task(
        self,
        run_id: UUID,
        node_id: str,
        tenant_id: UUID | None = None,
        skill_name: str | None = None,
        tool_name: str | None = None,
        input_data: dict[str, Any] | None = None,
        max_retries: int = 3,
    ) -> AgentTask:
        """Submit a task to the agent run queue.

        Args:
            run_id: AgentRun UUID
            node_id: DAG node ID
            skill_name: Optional skill name
            tool_name: Optional tool name
            input_data: Task input data
            max_retries: Maximum retry attempts

        Returns:
            Created AgentTask
        """
        task = AgentTask(
            agent_run_id=run_id,
            tenant_id=tenant_id,
            node_id=node_id,
            skill_name=skill_name,
            tool_name=tool_name,
            input_data=input_data or {},
            status=AgentTaskStatus.PENDING.value,
            retries=0,
            max_retries=max_retries,
        )
        self.db.add(task)
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def create_tasks_for_dag(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        dag_json: dict[str, Any],
        input_data: dict[str, Any] | None = None,
    ) -> list[AgentTask]:
        """Create one pending task per executable workflow node."""
        dag = dag_json if isinstance(dag_json, dict) else {}
        nodes = dag.get("nodes", [])
        validation = validate_workflow_dag(dag)
        if not validation["valid"]:
            raise ValueError(
                {
                    "code": "invalid_workflow_dag",
                    "message": "Workflow DAG validation failed",
                    "issues": validation["issues"],
                }
            )

        node_by_id = {
            str(node.get("id")): node
            for node in nodes
            if isinstance(node, dict) and str(node.get("id") or "").strip()
        }
        ordered_nodes = [
            node_by_id[node_id]
            for node_id in validation["execution_order"]
            if node_id in node_by_id
        ]
        tasks: list[AgentTask] = []
        preview = build_workflow_execution_preview(dag, input_data or {})
        await self.merge_run_metadata(
            run_id,
            tenant_id,
            {
                "execution_order": preview["execution_order"],
                "parallel_groups": preview["parallel_groups"],
                "approval_gates": preview["approval_gates"],
                "condition_paths": preview["condition_paths"],
                "estimated_steps": preview["estimated_steps"],
                "requires_human_action": bool(preview["approval_gates"]),
                "status_hint": "requires_human_approval" if preview["approval_gates"] else None,
                "can_resume": False,
            },
        )

        for node in ordered_nodes:
            node_id = str(node.get("id") or "").strip()
            if not node_id:
                continue

            node_config = _node_config(node)
            skill_name = _node_skill_name(node)
            tool_name = _node_tool_name(node)
            node_type = str(node.get("type") or "").strip()
            control_metadata: dict[str, Any] = {}
            if node_type == "human_approval":
                control_metadata = _approval_metadata(node)
            elif node_type == "condition":
                control_metadata = {
                    "expression": _condition_expression(node),
                    "paths": _condition_paths(node),
                }
            elif node_type == "parallel_group":
                control_metadata = {"branches": _parallel_branches(node)}
            elif node_type == "delay":
                control_metadata = {
                    "duration_seconds": node_config.get("duration_seconds")
                    or node_config.get("delay_seconds"),
                }

            task = await self.submit_task(
                run_id=run_id,
                tenant_id=tenant_id,
                node_id=node_id,
                skill_name=skill_name,
                tool_name=tool_name,
                input_data={
                    "workflow_input": input_data or {},
                    "node_config": node_config,
                    "depends_on": node.get("depends_on", []),
                    "node_type": node_type,
                    "control_metadata": control_metadata,
                },
            )
            tasks.append(task)

        return tasks

    async def get_task(
        self,
        task_id: UUID,
        tenant_id: UUID | None = None,
    ) -> AgentTask | None:
        """Get agent task by ID.

        Args:
            task_id: AgentTask UUID
            tenant_id: Optional tenant filter

        Returns:
            AgentTask if found, None otherwise
        """
        query = select(AgentTask).where(AgentTask.id == task_id)
        if tenant_id is not None:
            query = query.where(AgentTask.tenant_id == tenant_id)

        result = await self.db.execute(query)
        return result.scalar_one_or_none()

    async def update_task_status(
        self,
        task_id: UUID,
        status: str,
        output_data: dict[str, Any] | None = None,
        error_message: str | None = None,
    ) -> AgentTask | None:
        """Update agent task status.

        Args:
            task_id: AgentTask UUID
            status: New status
            output_data: Task output data
            error_message: Optional error message

        Returns:
            Updated AgentTask if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        task.status = status

        if status == AgentTaskStatus.RUNNING.value and task.started_at is None:
            task.started_at = datetime.now(timezone.utc)
        elif status in [
            AgentTaskStatus.COMPLETED.value,
            AgentTaskStatus.FAILED.value,
        ]:
            task.completed_at = datetime.now(timezone.utc)

        if output_data is not None:
            task.output_data = output_data
        if error_message:
            task.error_message = error_message

        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def execute_tracked_skill_task(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        node_id: str,
        skill_name: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> tuple[AgentTask, dict[str, Any], float]:
        """Execute a skill and persist task/event timing and result evidence."""
        import time

        task = await self.submit_task(
            run_id=run_id,
            tenant_id=tenant_id,
            node_id=node_id,
            skill_name=skill_name,
            input_data=input_data,
        )
        await self.update_task_status(task.id, AgentTaskStatus.RUNNING.value)
        await self.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="skill_task_started",
            event_data={"task_id": str(task.id), "node_id": node_id, "skill_name": skill_name},
        )

        started = time.perf_counter()
        try:
            output_data = await SkillService(self.db).execute_skill(
                skill_name=skill_name,
                input_data=input_data,
                context=context or {},
            )
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            await self.update_task_status(
                task.id,
                AgentTaskStatus.COMPLETED.value,
                output_data={
                    "result": output_data,
                    "execution": {
                        "duration_ms": duration_ms,
                        "skill_name": skill_name,
                    },
                },
            )
            await self.log_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type="skill_task_completed",
                event_data={
                    "task_id": str(task.id),
                    "node_id": node_id,
                    "skill_name": skill_name,
                    "duration_ms": duration_ms,
                    "summary": output_data.get("summary"),
                },
            )
            refreshed = await self.get_task(task.id, tenant_id)
            return refreshed or task, output_data, duration_ms
        except Exception as exc:
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            await self.update_task_status(
                task.id,
                AgentTaskStatus.FAILED.value,
                error_message=str(exc),
            )
            await self.log_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type="skill_task_failed",
                event_data={
                    "task_id": str(task.id),
                    "node_id": node_id,
                    "skill_name": skill_name,
                    "duration_ms": duration_ms,
                    "error": str(exc),
                },
            )
            raise

    async def execute_agent_profile_run(
        self,
        tenant_id: UUID,
        project_id: UUID | None,
        agent_profile_id: UUID,
        input_data: dict[str, Any] | None = None,
        created_by: UUID | None = None,
    ) -> AgentRun:
        """Execute the first published skill bound to an active agent profile."""
        profile = await AgentProfileService(self.db).get_agent_profile(agent_profile_id, tenant_id)
        if not profile:
            raise LookupError("Agent profile not found")
        if profile.status != AgentProfileStatus.ACTIVE.value:
            raise ValueError(f"Agent profile is not active: {profile.status}")
        bindings = list(profile.skill_bindings or [])
        if not bindings:
            raise ValueError("Agent profile has no bound skills")

        executable_binding = None
        for binding in bindings:
            if binding.skill and binding.skill.status == SkillStatus.PUBLISHED.value:
                executable_binding = binding
                break
        if executable_binding is None:
            raise ValueError("Agent profile has no published bound skills")

        skill = executable_binding.skill
        run = await self.create_run(
            tenant_id=tenant_id,
            project_id=project_id,
            agent_profile_id=profile.id,
            run_type="agent_profile",
            created_by=created_by,
            input_data=input_data or {},
            metadata_json={
                "execution_kind": "agent_profile",
                "agent_profile_id": str(profile.id),
                "agent_profile_name": profile.name,
                "skill_id": str(skill.id),
                "skill_name": skill.name,
            },
        )
        await self.update_run_status(run.id, tenant_id, AgentRunStatus.RUNNING.value)
        await self.log_event(
            run_id=run.id,
            tenant_id=tenant_id,
            event_type="agent_run_started",
            event_data={
                "agent_profile_id": str(profile.id),
                "agent_profile_name": profile.name,
                "skill_id": str(skill.id),
                "skill_name": skill.name,
            },
        )

        try:
            task, output_data, duration_ms = await self.execute_tracked_skill_task(
                run_id=run.id,
                tenant_id=tenant_id,
                node_id=f"agent:{skill.name}",
                skill_name=skill.name,
                input_data=input_data or {},
                context={
                    "tenant_id": str(tenant_id),
                    "project_id": str(project_id) if project_id else None,
                    "run_id": str(run.id),
                    "run_type": "agent",
                    "agent_profile_id": str(profile.id),
                    "system_prompt": profile.system_prompt,
                },
            )
            await self.merge_run_metadata(
                run.id,
                tenant_id,
                {
                    "task_id": str(task.id),
                    "duration_ms": duration_ms,
                    "summary": output_data.get("summary"),
                    "status": AgentRunStatus.COMPLETED.value,
                },
            )
            await self.update_run_status(run.id, tenant_id, AgentRunStatus.COMPLETED.value)
            await self.log_event(
                run_id=run.id,
                tenant_id=tenant_id,
                event_type="agent_run_completed",
                event_data={
                    "agent_profile_id": str(profile.id),
                    "task_id": str(task.id),
                    "skill_name": skill.name,
                    "duration_ms": duration_ms,
                },
            )
        except Exception as exc:
            await self.merge_run_metadata(
                run.id,
                tenant_id,
                {"status": AgentRunStatus.FAILED.value, "error": str(exc)},
            )
            await self.update_run_status(
                run.id,
                tenant_id,
                AgentRunStatus.FAILED.value,
                error_message=str(exc),
            )
            await self.log_event(
                run_id=run.id,
                tenant_id=tenant_id,
                event_type="agent_run_failed",
                event_data={"agent_profile_id": str(profile.id), "skill_name": skill.name, "error": str(exc)},
            )

        refreshed = await self.get_run(run.id, tenant_id)
        return refreshed or run

    async def get_task_for_run_node(
        self,
        run_id: UUID,
        node_id: str,
    ) -> AgentTask | None:
        """Find a task for a workflow run node."""
        result = await self.db.execute(
            select(AgentTask).where(
                AgentTask.agent_run_id == run_id,
                AgentTask.node_id == node_id,
            )
        )
        return result.scalar_one_or_none()

    async def increment_task_retries(self, task_id: UUID) -> AgentTask | None:
        """Increment task retry count.

        Args:
            task_id: AgentTask UUID

        Returns:
            Updated AgentTask if found, None otherwise
        """
        task = await self.get_task(task_id)
        if not task:
            return None

        task.retries += 1
        await self.db.flush()
        await self.db.refresh(task)
        return task

    async def log_event(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        event_type: str,
        event_data: dict[str, Any] | None = None,
    ) -> AgentEvent:
        """Log an agent run event.

        Args:
            run_id: AgentRun UUID
            tenant_id: Tenant UUID
            event_type: Type of event
            event_data: Event payload

        Returns:
            Created AgentEvent
        """
        event = AgentEvent(
            agent_run_id=run_id,
            tenant_id=tenant_id,
            event_type=event_type,
            event_data=event_data or {},
        )
        self.db.add(event)
        await self.db.flush()
        await self.db.refresh(event)
        return event

    async def get_run_tasks(
        self,
        run_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[AgentTask]:
        """Get all tasks for an agent run.

        Args:
            run_id: AgentRun UUID
            tenant_id: Optional tenant filter

        Returns:
            List of AgentTasks
        """
        query = select(AgentTask).where(AgentTask.agent_run_id == run_id)
        if tenant_id is not None:
            query = query.where(AgentTask.tenant_id == tenant_id)

        result = await self.db.execute(query.order_by(AgentTask.created_at))
        return list(result.scalars().all())

    async def get_run_events(
        self,
        run_id: UUID,
        tenant_id: UUID | None = None,
    ) -> list[AgentEvent]:
        """Get ordered events for an agent run."""
        query = select(AgentEvent).where(AgentEvent.agent_run_id == run_id)
        if tenant_id is not None:
            query = query.where(AgentEvent.tenant_id == tenant_id)

        result = await self.db.execute(query.order_by(AgentEvent.created_at))
        return list(result.scalars().all())

    async def cancel_run(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        reason: str = "Cancelled by user",
    ) -> AgentRun | None:
        """Cancel a pending or running workflow run."""
        run = await self.get_run(run_id, tenant_id)
        if not run:
            return None
        if run.status in [
            AgentRunStatus.COMPLETED.value,
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        ]:
            raise ValueError(f"Run cannot be cancelled from status '{run.status}'")

        run.status = AgentRunStatus.CANCELLED.value
        run.completed_at = datetime.now(timezone.utc)
        run.error_message = reason

        cancelled_task_ids: list[str] = []
        for task in run.tasks:
            if task.status in [
                AgentTaskStatus.PENDING.value,
                AgentTaskStatus.RUNNING.value,
            ]:
                task.status = AgentTaskStatus.CANCELLED.value
                task.completed_at = datetime.now(timezone.utc)
                task.error_message = reason
                cancelled_task_ids.append(str(task.id))

        run.metadata_json = {
            **(run.metadata_json or {}),
            "status": AgentRunStatus.CANCELLED.value,
            "cancelled_task_ids": cancelled_task_ids,
            "status_hint": "cancelled",
            "can_resume": True,
        }

        await self.log_event(
            run_id=run.id,
            tenant_id=tenant_id,
            event_type="run_cancelled",
            event_data={"reason": reason, "cancelled_task_ids": cancelled_task_ids},
        )
        await self.db.flush()
        await self.db.refresh(run)
        return await self.get_run(run.id, tenant_id) or run

    async def apply_control_action(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        action: str,
        actor_id: UUID | None = None,
        node_id: str | None = None,
        comment: str | None = None,
        output_data: dict[str, Any] | None = None,
    ) -> AgentRun | None:
        """Resolve a workflow control node and update run recovery metadata."""
        normalized_action = action.strip().lower()
        if normalized_action not in {"approve", "reject", "resume", "skip"}:
            raise ValueError("Unsupported control action")

        run = await self.get_run(run_id, tenant_id)
        if not run:
            return None

        tasks = await self.get_run_tasks(run.id, tenant_id)
        control_tasks = [
            task
            for task in tasks
            if (task.input_data or {}).get("node_type")
            in {"human_approval", "condition", "parallel_group", "delay", "merge"}
        ]
        if node_id:
            control_tasks = [task for task in control_tasks if task.node_id == node_id]
        if not control_tasks:
            raise ValueError("No matching control task found for this run")

        target_task = next(
            (
                task
                for task in control_tasks
                if task.status in {AgentTaskStatus.PENDING.value, AgentTaskStatus.RUNNING.value}
            ),
            control_tasks[-1],
        )
        if target_task.status == AgentTaskStatus.COMPLETED.value and normalized_action in {"approve", "skip"}:
            raise ValueError("Control task is already resolved")

        now = datetime.now(timezone.utc)
        action_output = {
            "control_action": normalized_action,
            "node_id": target_task.node_id,
            "comment": comment,
            "actor_id": str(actor_id) if actor_id else None,
            "resolved_at": now.isoformat(),
            "payload": output_data or {},
            "previous_output": target_task.output_data or {},
        }

        if normalized_action == "reject":
            await self.update_task_status(
                target_task.id,
                AgentTaskStatus.FAILED.value,
                output_data=action_output,
                error_message=comment or "Rejected by human operator",
            )
            run_status = AgentRunStatus.FAILED.value
            run_error = comment or "Workflow control gate rejected"
            metadata_patch = {
                "requires_human_action": False,
                "can_resume": False,
                "status_hint": "control_rejected",
                "last_control_action": action_output,
            }
        else:
            await self.update_task_status(
                target_task.id,
                AgentTaskStatus.COMPLETED.value,
                output_data=action_output,
            )
            run_status = AgentRunStatus.PENDING.value
            run_error = None
            metadata_patch = {
                "requires_human_action": False,
                "can_resume": True,
                "status_hint": "control_resolved",
                "last_control_action": action_output,
            }

        await self.merge_run_metadata(run.id, tenant_id, metadata_patch)
        updated_run = await self.update_run_status(
            run.id,
            tenant_id,
            run_status,
            error_message=run_error,
        )
        await self.log_event(
            run_id=run.id,
            tenant_id=tenant_id,
            event_type=f"control_{normalized_action}",
            event_data={
                "node_id": target_task.node_id,
                "task_id": str(target_task.id),
                "actor_id": str(actor_id) if actor_id else None,
                "comment": comment,
                "status": run_status,
            },
        )
        await self.db.flush()
        return await self.get_run(run.id, tenant_id) or updated_run

    async def prepare_run_retry(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
    ) -> AgentRun | None:
        """Reset a failed or cancelled run so it can be enqueued again."""
        run = await self.get_run(run_id, tenant_id)
        if not run:
            return None
        if run.status not in [
            AgentRunStatus.FAILED.value,
            AgentRunStatus.CANCELLED.value,
        ]:
            raise ValueError(f"Run cannot be retried from status '{run.status}'")

        previous_status = run.status
        previous_error = run.error_message
        retry_attempt = int((run.metadata_json or {}).get("retry_attempt") or 0) + 1
        await self.db.execute(delete(AgentTask).where(AgentTask.agent_run_id == run.id))

        run.status = AgentRunStatus.PENDING.value
        run.started_at = None
        run.completed_at = None
        run.error_message = None
        run.metadata_json = {
            **(run.metadata_json or {}),
            "status": AgentRunStatus.PENDING.value,
            "retry_attempt": retry_attempt,
            "previous_status": previous_status,
            "previous_error": previous_error,
            "status_hint": "retry_queued",
            "can_resume": False,
        }

        dag_json = {}
        if run.workflow_version is not None:
            dag_json = run.workflow_version.dag_json or {}
        await self.create_tasks_for_dag(
            run_id=run.id,
            tenant_id=tenant_id,
            dag_json=dag_json,
            input_data=run.input_data or {},
        )
        await self.log_event(
            run_id=run.id,
            tenant_id=tenant_id,
            event_type="run_retry_queued",
            event_data={
                "attempt": retry_attempt,
                "previous_status": previous_status,
                "previous_error": previous_error,
                "input_snapshot": _runtime_snapshot(run.input_data or {}),
            },
        )
        await self.db.flush()
        await self.db.refresh(run)
        return run


class SkillService:
    """Service for skill execution and management.

    Provides built-in skills and executes them with proper contract
    validation.
    """

    # Built-in skills registry
    BUILTIN_SKILLS = {
        "MECEAnalyzer": {
            "name": "MECEAnalyzer",
            "description": "Analyze content for MECE (Mutually Exclusive, Collectively Exhaustive) principle compliance",
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string", "description": "Content to analyze"},
                    "categories": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Categories to check for overlap",
                    },
                },
                "required": ["content"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "score": {"type": "number", "description": "MECE compliance score (0-1)"},
                    "overlapping_categories": {
                        "type": "array",
                        "description": "List of overlapping category pairs",
                    },
                    "missing_categories": {
                        "type": "array",
                        "description": "List of missing categories for exhaustive coverage",
                    },
                    "recommendations": {
                        "type": "array",
                        "description": "List of recommendations for improvement",
                    },
                },
            },
            "is_builtin": True,
        },
        "IssueTreeAnalyzer": {
            "name": "IssueTreeAnalyzer",
            "description": "Break down issues using issue tree methodology (also known as logic tree or factor tree)",
            "input_schema": {
                "type": "object",
                "properties": {
                    "issue": {"type": "string", "description": "Main issue to break down"},
                    "depth": {"type": "integer", "description": "Maximum tree depth", "default": 3},
                    "branch_type": {
                        "type": "string",
                        "enum": ["problem", "cause", "solution"],
                        "description": "Type of issue tree",
                    },
                },
                "required": ["issue"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "tree": {
                        "type": "object",
                        "description": "Hierarchical issue tree structure",
                    },
                    "leaf_nodes": {"type": "integer", "description": "Number of leaf nodes"},
                    "depth": {"type": "integer", "description": "Actual tree depth"},
                },
            },
            "is_builtin": True,
        },
        "DocumentReviewer": {
            "name": "DocumentReviewer",
            "description": "Review documents for quality, consistency, and completeness",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID"},
                    "content": {"type": "string", "description": "Document content"},
                    "review_type": {
                        "type": "string",
                        "enum": ["full", "quick", "detailed"],
                        "description": "Type of review to perform",
                    },
                    "check_list": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific checks to perform",
                    },
                },
                "required": ["content"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "score": {"type": "number", "description": "Overall quality score (0-1)"},
                    "issues": {
                        "type": "array",
                        "description": "List of issues found",
                    },
                    "suggestions": {
                        "type": "array",
                        "description": "List of improvement suggestions",
                    },
                    "passed_checks": {
                        "type": "array",
                        "description": "List of checks that passed",
                    },
                },
            },
            "is_builtin": True,
        },
        "RequirementClarifier": {
            "name": "RequirementClarifier",
            "description": "Clarify ambiguous or unclear requirements",
            "input_schema": {
                "type": "object",
                "properties": {
                    "requirements": {
                        "type": "array",
                        "description": "List of requirements to clarify",
                    },
                    "context": {
                        "type": "string",
                        "description": "Additional context for clarification",
                    },
                },
                "required": ["requirements"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "clarified_requirements": {
                        "type": "array",
                        "description": "List of clarified requirements with explanations",
                    },
                    "ambiguous_count": {"type": "integer", "description": "Number of ambiguous items"},
                    "gaps_identified": {
                        "type": "array",
                        "description": "List of gaps or missing information",
                    },
                },
            },
            "is_builtin": True,
        },
        "ExportOrchestrator": {
            "name": "ExportOrchestrator",
            "description": "Orchestrate real document export jobs to Word, Markdown, PPTX, or project delivery packages.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string", "description": "Document ID to export"},
                    "project_id": {"type": "string", "description": "Project ID for project package exports"},
                    "format": {
                        "type": "string",
                        "enum": ["word", "docx", "markdown", "pptx", "project_package"],
                        "description": "Export format",
                    },
                    "options": {
                        "type": "object",
                        "description": "Format-specific export options",
                    },
                },
                "required": ["document_id", "format"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "Whether export succeeded"},
                    "job_id": {"type": "string", "description": "Export job ID"},
                    "file_path": {"type": "string", "description": "Path to exported file"},
                    "file_size": {"type": "integer", "description": "File size in bytes"},
                    "warnings": {
                        "type": "array",
                        "description": "List of warnings during export",
                    },
                },
            },
            "is_builtin": True,
        },
        "BRDDeepThinkingEngine": {
            "name": "BRDDeepThinkingEngine",
            "description": "Guide BRD conversations by filtering facts, detecting ambiguity, and selecting the next focused question.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "user_message": {"type": "string"},
                    "current_section": {"type": "string"},
                    "known_facts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["user_message"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "sufficiency_level": {"type": "string", "enum": ["L1", "L2", "L3", "L4"]},
                    "next_question": {"type": "string"},
                    "stashed_facts": {"type": "array", "items": {"type": "string"}},
                },
            },
            "is_builtin": True,
        },
        "BRDWritePipeline": {
            "name": "BRDWritePipeline",
            "description": "Convert confirmed BRD conversation facts into section-level draft patches with quality and verification metadata.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "section_key": {"type": "string"},
                    "confirmed_facts": {"type": "array", "items": {"type": "string"}},
                    "quality_rules": {"type": "array"},
                },
                "required": ["section_key", "confirmed_facts"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "draft_markdown": {"type": "string"},
                    "quality_score": {"type": "number"},
                    "pending_questions": {"type": "array", "items": {"type": "string"}},
                },
            },
            "is_builtin": True,
        },
        "BRDResearchAssistant": {
            "name": "BRDResearchAssistant",
            "description": "Identify industry reference needs for BRD drafting without writing unverifiable reference content into the document.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "industry": {"type": "string"},
                    "unknown_terms": {"type": "array", "items": {"type": "string"}},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "research_needed": {"type": "boolean"},
                    "safe_reference_topics": {"type": "array", "items": {"type": "string"}},
                },
            },
            "is_builtin": True,
        },
        "BRDPatternLibrary": {
            "name": "BRDPatternLibrary",
            "description": "Suggest reusable BRD structure patterns based on domain, document type, and section context.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "domain": {"type": "string"},
                    "section_key": {"type": "string"},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "pattern_hints": {"type": "array", "items": {"type": "string"}},
                    "confidence": {"type": "number"},
                },
            },
            "is_builtin": True,
        },
        "BRDOffTopicHandler": {
            "name": "BRDOffTopicHandler",
            "description": "Keep generation conversations within the active document task while preserving useful user-provided context.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "user_message": {"type": "string"},
                    "active_task": {"type": "string"},
                },
                "required": ["user_message"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "is_off_topic": {"type": "boolean"},
                    "reply": {"type": "string"},
                },
            },
            "is_builtin": True,
        },
        "PRDTraceabilityMapper": {
            "name": "PRDTraceabilityMapper",
            "description": "Map BRD pain points and requirement modules into PRD module, page, and feature traceability rows.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "brd_content": {"type": "string"},
                    "product_scope": {"type": "string"},
                },
                "required": ["brd_content"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "traceability_rows": {"type": "array"},
                    "uncovered_brd_items": {"type": "array", "items": {"type": "string"}},
                },
            },
            "is_builtin": True,
        },
        "PRDSkeletonPlanner": {
            "name": "PRDSkeletonPlanner",
            "description": "Create a PRD skeleton from confirmed BRD scope before expanding feature details.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "traceability_rows": {"type": "array"},
                    "module_candidates": {"type": "array", "items": {"type": "string"}},
                },
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "module_list": {"type": "array"},
                    "global_rules": {"type": "array"},
                    "tracking_events": {"type": "array"},
                },
            },
            "is_builtin": True,
        },
        "DocumentTemplateSectionPlanner": {
            "name": "DocumentTemplateSectionPlanner",
            "description": "Plan reusable document template sections, required inputs, and quality rules for BRD, PRD, and test-case templates.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "doc_type": {"type": "string"},
                    "business_domain": {"type": "string"},
                    "required_sections": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["doc_type"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "sections": {"type": "array"},
                    "quality_rules": {"type": "array"},
                },
            },
            "is_builtin": True,
        },
        "ChangeImpactAnalyzer": {
            "name": "ChangeImpactAnalyzer",
            "description": "Analyze requirement or document changes and propose downstream PRD, test, template, and knowledge graph updates.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "change_summary": {"type": "string"},
                    "source_document": {"type": "string"},
                    "linked_artifacts": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["change_summary"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "impact_level": {"type": "string"},
                    "affected_artifacts": {"type": "array"},
                    "recommended_actions": {"type": "array"},
                },
            },
            "is_builtin": True,
        },
        "KnowledgeGraphExtractor": {
            "name": "KnowledgeGraphExtractor",
            "description": "Extract business entities, flows, constraints, and traceability edges from project documents.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "content": {"type": "string"},
                    "project_context": {"type": "string"},
                },
                "required": ["content"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "entities": {"type": "array"},
                    "relationships": {"type": "array"},
                },
            },
            "is_builtin": True,
        },
        "TestCaseDesigner": {
            "name": "TestCaseDesigner",
            "description": "Generate acceptance test case drafts from PRD features, rules, and acceptance criteria.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "feature_name": {"type": "string"},
                    "acceptance_criteria": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["feature_name"],
            },
            "output_schema": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "test_cases": {"type": "array"},
                    "coverage_gaps": {"type": "array"},
                },
            },
            "is_builtin": True,
        },
    }

    def __init__(self, db: AsyncSession | None = None):
        """Initialize skill service.

        Args:
            db: Optional async database session
        """
        self.db = db

    def list_skills(self) -> list[dict[str, Any]]:
        """List all available skills.

        Returns:
            List of skill info dicts
        """
        return list(self.BUILTIN_SKILLS.values())

    def get_skill(self, skill_name: str) -> dict[str, Any] | None:
        """Get skill info by name.

        Args:
            skill_name: Name of the skill

        Returns:
            Skill info dict if found, None otherwise
        """
        return self.BUILTIN_SKILLS.get(skill_name)

    async def execute_skill(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a skill with the given input.

        Args:
            skill_name: Name of the skill to execute
            input_data: Input data for the skill
            context: Optional execution context

        Returns:
            Skill execution result dict

        Raises:
            ValueError: If skill not found or execution fails
        """
        skill = self.get_skill(skill_name)
        if not skill:
            raise ValueError(f"Skill not found: {skill_name}")

        schema_errors = SkillCatalogService._validate_input_contract(
            skill.get("input_schema") or {},
            input_data,
        )
        if schema_errors:
            raise ValueError("; ".join(schema_errors))

        context = context or {}

        # Execute the appropriate skill
        if skill_name == "MECEAnalyzer":
            raw_output = await self._execute_mece_analyzer(input_data, context)
        elif skill_name == "IssueTreeAnalyzer":
            raw_output = await self._execute_issue_tree_analyzer(input_data, context)
        elif skill_name == "DocumentReviewer":
            raw_output = await self._execute_document_reviewer(input_data, context)
        elif skill_name == "RequirementClarifier":
            raw_output = await self._execute_requirement_clarifier(input_data, context)
        elif skill_name == "ExportOrchestrator":
            raw_output = await self._execute_export_orchestrator(input_data, context)
        elif skill_name in self.BUILTIN_SKILLS:
            raw_output = await self._execute_project_methodology_skill(skill_name, input_data, context)
        else:
            raise ValueError(f"Unknown skill: {skill_name}")

        return self.normalize_skill_output(skill_name, raw_output, context)

    def normalize_skill_output(
        self,
        skill_name: str,
        raw_output: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Wrap built-in skill output in a stable frontend display envelope."""
        output = raw_output if isinstance(raw_output, dict) else {"value": raw_output}
        summary = output.get("summary") or self._build_skill_summary(skill_name, output)
        next_actions = output.get("next_actions") or self._extract_next_actions(output)
        evidence = output.get("evidence") or [
            {
                "source": "builtin_skill",
                "skill_name": skill_name,
                "run_id": (context or {}).get("run_id"),
                "status": "completed",
            }
        ]

        normalized = dict(output)
        normalized["summary"] = summary
        normalized["output"] = output
        normalized["evidence"] = evidence
        normalized["next_actions"] = next_actions
        return normalized

    @staticmethod
    def _build_skill_summary(skill_name: str, output: dict[str, Any]) -> str:
        """Create a deterministic summary when a built-in skill returns raw fields."""
        if skill_name == "DocumentReviewer":
            score = output.get("score")
            issue_count = len(output.get("issues") or [])
            return f"Document review completed with score {score}; {issue_count} issue(s) found."
        if skill_name == "RequirementClarifier":
            return f"Requirement clarification completed; {output.get('ambiguous_count', 0)} ambiguous item(s) found."
        if skill_name == "MECEAnalyzer":
            return f"MECE analysis completed with score {output.get('score')}."
        if skill_name == "IssueTreeAnalyzer":
            return f"Issue tree generated with {output.get('leaf_nodes', 0)} leaf node(s)."
        if skill_name == "ExportOrchestrator":
            return "Export orchestration completed." if output.get("success") else "Export orchestration failed validation."
        return f"{skill_name} completed."

    @staticmethod
    def _extract_next_actions(output: dict[str, Any]) -> list[Any]:
        """Map common raw output fields to displayable next actions."""
        for key in [
            "next_actions",
            "recommended_actions",
            "suggestions",
            "pending_questions",
            "warnings",
            "gaps_identified",
        ]:
            value = output.get(key)
            if isinstance(value, list):
                return value
            if value:
                return [value]
        return []

    @staticmethod
    def _coerce_uuid(value: Any) -> UUID | None:
        """Best-effort UUID coercion for optional execution context IDs."""
        if value is None or isinstance(value, UUID):
            return value
        try:
            return UUID(str(value))
        except (TypeError, ValueError):
            return None

    async def execute_tool(
        self,
        tool_name: str,
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a registered tool adapter with a stable runtime envelope."""
        from app.domains.agent.tools import TOOL_ADAPTERS, ToolExecutionError

        adapter_cls = TOOL_ADAPTERS.get(tool_name)
        if adapter_cls is None:
            raise ValueError(f"Tool not found: {tool_name}")

        context = context or {}
        tool_input = dict(input_data or {})
        for key in ["tenant_id", "created_by", "run_id", "project_id"]:
            if context.get(key) is not None and tool_input.get(key) is None:
                tool_input[key] = str(context[key])

        try:
            adapter = adapter_cls(self.db)  # type: ignore[call-arg]
        except TypeError:
            adapter = adapter_cls()

        try:
            output = await adapter.execute(tool_input)
        except ToolExecutionError:
            raise

        data = output.get("data") if isinstance(output.get("data"), dict) else {}
        summary = (
            output.get("summary")
            or data.get("summary")
            or (
                f"{tool_name} completed."
                if output.get("success")
                else f"{tool_name} failed validation."
            )
        )
        normalized = dict(output)
        normalized["summary"] = summary
        normalized["output"] = output
        normalized["evidence"] = output.get("evidence") or [
            {
                "source": "tool_adapter",
                "tool_name": tool_name,
                "run_id": context.get("run_id"),
                "status": "completed" if output.get("success") else "failed",
            }
        ]
        normalized["next_actions"] = output.get("next_actions") or []
        return normalized

    async def _execute_mece_analyzer(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute MECE Analyzer skill.

        Args:
            input_data: Input containing content and categories
            context: Execution context

        Returns:
            Analysis result
        """
        content = input_data.get("content", "")
        categories = input_data.get("categories", [])

        # Simple heuristic analysis for MECE compliance
        issues = []
        overlapping = []
        missing = []

        # Check content length
        if len(content) < 100:
            issues.append("Content is too short for meaningful analysis")

        # Check for overlapping categories (simple string matching)
        if len(categories) > 1:
            for i, cat1 in enumerate(categories):
                for cat2 in categories[i + 1 :]:
                    # Simple check: if one is substring of another, consider overlapping
                    if cat1.lower() in cat2.lower() or cat2.lower() in cat1.lower():
                        if cat1 != cat2:
                            overlapping.append((cat1, cat2))

        # Calculate MECE score
        base_score = 0.8  # Base score assuming reasonable content
        if overlapping:
            base_score -= 0.1 * len(overlapping)
        if len(categories) < 2:
            base_score -= 0.2  # Need multiple categories for MECE analysis
            missing.append("At least 2 categories required for MECE analysis")

        score = max(0.0, min(1.0, base_score))

        return {
            "score": round(score, 2),
            "overlapping_categories": overlapping,
            "missing_categories": missing,
            "recommendations": (
                ["Separate overlapping categories into distinct groups"]
                if overlapping
                else ["Content appears well-structured for MECE analysis"]
            ),
        }

    async def _execute_issue_tree_analyzer(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute Issue Tree Analyzer skill.

        Args:
            input_data: Input containing issue, depth, and branch_type
            context: Execution context

        Returns:
            Issue tree analysis result
        """
        issue = input_data.get("issue", "")
        depth = input_data.get("depth", 3)
        branch_type = input_data.get("branch_type", "problem")

        if not issue:
            return {"tree": {}, "leaf_nodes": 0, "depth": 0}

        source_terms = self._extract_methodology_terms(
            self._collect_methodology_texts(input_data, context),
            limit=max(4, min(12, depth * 3)),
        )
        branch_terms = [term for term in source_terms if term.lower() not in issue.lower()]
        if not branch_terms:
            branch_terms = ["目标", "流程", "角色", "约束"] if branch_type == "solution" else ["流程", "角色", "规则", "数据"]
        selected_terms = branch_terms[: max(2, min(4, depth + 1))]

        branch_labels = {
            "problem": "问题域",
            "cause": "可能原因",
            "solution": "解决路径",
        }
        leaf_labels = {
            "problem": ["影响范围", "可验收缺口"],
            "cause": ["触发条件", "验证证据"],
            "solution": ["实施动作", "验收标准"],
        }

        tree = {
            "id": "root",
            "label": issue,
            "type": branch_type,
            "children": [
                {
                    "id": f"branch_{index + 1}",
                    "label": f"{branch_labels.get(branch_type, '分析维度')}: {term}",
                    "type": branch_type,
                    "children": [
                        {
                            "id": f"leaf_{index + 1}_{leaf_index + 1}",
                            "label": f"{leaf_label}: {term}",
                            "type": branch_type,
                        }
                        for leaf_index, leaf_label in enumerate(leaf_labels.get(branch_type, ["分析项", "验证项"]))
                    ],
                }
                for index, term in enumerate(selected_terms)
            ],
        }

        leaf_count = sum(len(branch["children"]) for branch in tree["children"])
        actual_depth = 3 if leaf_count else 1

        return {"tree": tree, "leaf_nodes": leaf_count, "depth": actual_depth}

    async def _execute_document_reviewer(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute Document Reviewer skill.

        Args:
            input_data: Input containing document content and review_type
            context: Execution context

        Returns:
            Document review result
        """
        content = input_data.get("content", "")
        review_type = input_data.get("review_type", "quick")
        check_list = input_data.get("check_list", [])

        issues = []
        suggestions = []
        passed_checks = []

        # Basic checks
        if len(content) < 50:
            issues.append("Document is very short")
            suggestions.append("Consider adding more detailed content")

        # Check for structure (headings, lists)
        has_headings = "#" in content or "##" in content
        has_lists = "-" in content or "*" in content or "1." in content

        if review_type in ["full", "detailed"]:
            # More thorough checks
            if not has_headings:
                issues.append("Document lacks clear structure (headings)")
                suggestions.append("Add headings to organize content into sections")

            if not has_lists:
                issues.append("Document lacks visual organization (lists)")
                suggestions.append("Consider using bullet points or numbered lists")

        # Check for common quality issues
        placeholder_count = content.count("[TODO]") + content.count("[PLACEHOLDER]")
        if placeholder_count > 0:
            issues.append(f"Found {placeholder_count} placeholder(s)")
            suggestions.append("Replace all placeholders with actual content")

        # Calculate score
        base_score = 0.9
        if len(content) < 100:
            base_score -= 0.2
        if issues:
            base_score -= 0.05 * len(issues)

        if has_headings:
            passed_checks.append("Document has clear structure")
        if has_lists:
            passed_checks.append("Content uses lists for organization")

        return {
            "score": round(max(0.0, min(1.0, base_score)), 2),
            "issues": issues,
            "suggestions": suggestions,
            "passed_checks": passed_checks,
        }

    async def _execute_requirement_clarifier(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute Requirement Clarifier skill.

        Args:
            input_data: Input containing requirements and context
            context: Execution context

        Returns:
            Requirement clarification result
        """
        requirements = input_data.get("requirements", [])
        additional_context = input_data.get("context", "")

        clarified = []
        ambiguous_count = 0
        gaps = []

        for i, req in enumerate(requirements):
            if not isinstance(req, str):
                req = str(req)

            # Check for ambiguity indicators
            ambiguous_indicators = [
                "and/or",
                "etc",
                "maybe",
                "might",
                "should",
                "could",
                "probably",
                "possibly",
                "TBD",
                "TBC",
            ]

            is_ambiguous = any(ind in req.lower() for ind in ambiguous_indicators)

            if is_ambiguous:
                ambiguous_count += 1
                clarified.append(
                    {
                        "original": req,
                        "clarified": f"{req} [Needs clarification: specific criteria required]",
                        "issue": "Contains ambiguous language",
                    }
                )
            else:
                clarified.append({"original": req, "clarified": req, "issue": None})

        # Check for common gaps
        if len(requirements) < 3:
            gaps.append("Consider adding more detailed requirements")

        return {
            "clarified_requirements": clarified,
            "ambiguous_count": ambiguous_count,
            "gaps_identified": gaps,
        }

    async def _execute_export_orchestrator(
        self,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute Export Orchestrator skill.

        Args:
            input_data: Input containing document_id and format
            context: Execution context

        Returns:
            Export result
        """
        from app.domains.export.models import ExportType
        from app.domains.export.service import ExportService

        document_id = input_data.get("document_id", "")
        project_id = input_data.get("project_id") or context.get("project_id")
        export_format = str(input_data.get("format", "markdown")).lower()
        options = input_data.get("options", {})
        variables = input_data.get("variables") or options.get("variables") or {}
        title = input_data.get("title") or options.get("title")
        template_id = self._coerce_uuid(input_data.get("template_id") or options.get("template_id"))
        tenant_id = self._coerce_uuid(input_data.get("tenant_id") or context.get("tenant_id"))
        created_by = self._coerce_uuid(
            input_data.get("created_by")
            or context.get("created_by")
            or context.get("user_id")
        )

        if export_format == "docx":
            export_format = ExportType.WORD.value

        if export_format == "pdf":
            return {
                "success": False,
                "file_path": None,
                "file_size": 0,
                "warnings": ["PDF export is not enabled; use word, markdown, pptx, or project_package."],
                "next_actions": ["选择 Word、Markdown、PPTX 或项目交付包导出。"],
            }

        if not tenant_id or not self.db:
            return {
                "success": False,
                "file_path": None,
                "file_size": 0,
                "warnings": ["tenant_id and database session are required for real export orchestration."],
                "next_actions": ["从项目工作流或 Skill 测试页携带租户上下文重新执行。"],
            }

        if export_format == ExportType.PROJECT_PACKAGE.value:
            project_uuid = self._coerce_uuid(project_id)
            if not project_uuid:
                return {
                    "success": False,
                    "file_path": None,
                    "file_size": 0,
                    "warnings": ["project_id is required for project package export"],
                    "next_actions": ["选择一个项目后重新生成交付包。"],
                }
            document_ids = [
                item for item in (
                    self._coerce_uuid(value)
                    for value in (input_data.get("document_ids") or options.get("document_ids") or [])
                )
                if item is not None
            ]
            try:
                job = await ExportService(self.db).export_project_package(
                    project_id=project_uuid,
                    tenant_id=tenant_id,
                    document_ids=document_ids or None,
                    title=title,
                    include_drafts=bool(input_data.get("include_drafts") or options.get("include_drafts") or False),
                    include_manifest=bool(input_data.get("include_manifest", options.get("include_manifest", True))),
                    variables=variables,
                    created_by=created_by,
                )
            except ValueError as exc:
                return {
                    "success": False,
                    "job_id": None,
                    "file_path": None,
                    "file_size": 0,
                    "warnings": [str(exc)],
                    "next_actions": ["修复交付包阻塞项后重新导出。"],
                }
            return self._export_orchestrator_output(job)

        document_uuid = self._coerce_uuid(document_id)
        if not document_uuid:
            return {
                "success": False,
                "file_path": None,
                "file_size": 0,
                "warnings": ["Document ID is required"],
                "next_actions": ["选择一份可导出的文档后重新执行。"],
            }

        service = ExportService(self.db)
        try:
            if export_format == ExportType.WORD.value:
                job = await service.export_word(
                    document_id=document_uuid,
                    template_id=template_id,
                    tenant_id=tenant_id,
                    variables=variables,
                    title=title,
                    created_by=created_by,
                )
            elif export_format == ExportType.MARKDOWN.value:
                job = await service.export_markdown(
                    document_id=document_uuid,
                    tenant_id=tenant_id,
                    variables=variables,
                    title=title,
                    created_by=created_by,
                )
            elif export_format == ExportType.PPTX.value:
                job = await service.export_pptx(
                    document_id=document_uuid,
                    template_id=template_id,
                    tenant_id=tenant_id,
                    variables=variables,
                    title=title,
                    created_by=created_by,
                )
            else:
                return {
                    "success": False,
                    "file_path": None,
                    "file_size": 0,
                    "warnings": [f"Unsupported export format: {export_format}"],
                    "next_actions": ["选择 Word、Markdown、PPTX 或项目交付包导出。"],
                }
        except ValueError as exc:
            return {
                "success": False,
                "job_id": None,
                "file_path": None,
                "file_size": 0,
                "warnings": [str(exc)],
                "next_actions": ["修复文档状态或占位内容后重新导出。"],
            }
        return self._export_orchestrator_output(job)

    @staticmethod
    def _export_orchestrator_output(job: Any) -> dict[str, Any]:
        artifacts = [
            {
                "artifact_id": str(artifact.id),
                "filename": artifact.filename,
                "content_type": artifact.content_type,
                "file_size": artifact.file_size,
                "storage_path": artifact.storage_path,
                "download_url": f"/api/v1/exports/artifacts/{artifact.id}/download",
            }
            for artifact in (getattr(job, "artifacts", None) or [])
        ]
        first_artifact = artifacts[0] if artifacts else {}
        return {
            "success": str(getattr(job, "status", "")) == "completed",
            "job_id": str(job.id),
            "status": job.status,
            "export_type": job.export_type,
            "file_path": getattr(job, "output_path", None),
            "file_size": first_artifact.get("file_size", 0),
            "artifact_count": len(artifacts),
            "artifacts": artifacts,
            "warnings": [],
            "next_actions": [
                f"下载 {first_artifact.get('filename')}"
            ] if first_artifact else ["查看导出中心确认任务状态。"],
        }

    @staticmethod
    def _collect_methodology_texts(*sources: Any) -> list[str]:
        """Collect meaningful text from nested skill inputs without inventing facts."""
        texts: list[str] = []

        def visit(value: Any) -> None:
            if value is None:
                return
            if isinstance(value, str):
                stripped = value.strip()
                if stripped:
                    texts.append(stripped)
            elif isinstance(value, (int, float, bool)):
                texts.append(str(value))
            elif isinstance(value, dict):
                for item in value.values():
                    visit(item)
            elif isinstance(value, (list, tuple, set)):
                for item in value:
                    visit(item)

        for source in sources:
            visit(source)
        return texts

    @staticmethod
    def _text_items(value: Any) -> list[str]:
        """Normalize strings, arrays, and simple objects into readable items."""
        if value is None:
            return []
        if isinstance(value, str):
            return [item.strip() for item in re.split(r"[\r\n；;。]+", value) if item.strip()]
        if isinstance(value, dict):
            return [
                f"{key}: {item}".strip()
                for key, item in value.items()
                if item is not None and str(item).strip()
            ]
        if isinstance(value, (list, tuple, set)):
            items: list[str] = []
            for item in value:
                items.extend(SkillService._text_items(item))
            return items
        return [str(value).strip()] if str(value).strip() else []

    @staticmethod
    def _extract_methodology_terms(texts: list[str], limit: int = 8) -> list[str]:
        """Extract stable input terms for deterministic methodology outputs."""
        stop_words = {
            "the", "and", "for", "with", "input", "context", "document", "project",
            "当前", "系统", "需要", "必须", "支持", "文档", "项目", "业务",
        }
        counts: dict[str, int] = {}
        for text in texts:
            for term in re.findall(r"[A-Za-z0-9_\-\u4e00-\u9fff]{2,}", text):
                normalized = term.strip()
                if not normalized or normalized.lower() in stop_words:
                    continue
                counts[normalized] = counts.get(normalized, 0) + 1
        return [
            term
            for term, _count in sorted(
                counts.items(),
                key=lambda item: (-item[1], texts[0].find(item[0]) if texts else 0, item[0]),
            )
        ][:limit]

    @staticmethod
    def _methodology_gaps(texts: list[str]) -> list[str]:
        combined = "\n".join(texts)
        checks = [
            ("角色或责任人不明确", ["角色", "负责人", "用户", "顾问", "管理员", "操作员"]),
            ("量化指标或验收标准不足", ["指标", "标准", "验收", "%", "率", "时长", "数量"]),
            ("异常流程或边界条件不足", ["异常", "失败", "边界", "错误", "回滚", "降级"]),
            ("输入来源或证据链不足", ["来源", "证据", "引用", "访谈", "文档", "记录"]),
        ]
        return [label for label, markers in checks if not any(marker in combined for marker in markers)]

    @staticmethod
    def _methodology_evidence(skill_name: str, texts: list[str]) -> list[dict[str, Any]]:
        return [
            {
                "source": "input",
                "skill_name": skill_name,
                "excerpt": text[:180],
            }
            for text in texts[:5]
        ]

    async def _execute_project_methodology_skill(
        self,
        skill_name: str,
        input_data: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute project methodology skills using provided inputs and context."""
        document_type = context.get("document_type") or input_data.get("doc_type") or "project_document"
        texts = self._collect_methodology_texts(input_data, context)
        terms = self._extract_methodology_terms(texts)
        gaps = self._methodology_gaps(texts)
        evidence = self._methodology_evidence(skill_name, texts)
        next_actions = [
            f"补齐：{gap}" for gap in gaps[:3]
        ] or ["将本次 Skill 输出写入对应章节、追溯矩阵或评审记录。"]

        if skill_name == "BRDDeepThinkingEngine":
            current_section = input_data.get("current_section", "brd.background_goals")
            known_facts = self._text_items(input_data.get("known_facts"))
            user_message = str(input_data.get("user_message") or "")
            sufficiency_level = "L4" if len(known_facts) >= 5 and not gaps else "L3" if len(known_facts) >= 3 else "L2" if user_message else "L1"
            question_focus = gaps[0] if gaps else "下一步交付验收口径"
            return {
                "summary": f"已基于输入事实评估 {current_section} 的信息充分度：{sufficiency_level}。",
                "sufficiency_level": sufficiency_level,
                "next_question": f"请围绕“{question_focus}”补充可验证事实、责任角色和验收口径。",
                "stashed_facts": (known_facts + self._text_items(user_message))[:6],
                "quality_gaps": gaps,
                "evidence": evidence,
                "next_actions": next_actions,
            }

        if skill_name == "BRDWritePipeline":
            section_key = input_data.get("section_key", "brd.section")
            facts = self._text_items(input_data.get("confirmed_facts"))
            rules = self._text_items(input_data.get("quality_rules"))
            bullet_lines = "\n".join(f"- {fact}" for fact in facts[:8]) or "- 当前缺少已确认事实，不能形成可交付正文。"
            rule_lines = "\n".join(f"- {rule}" for rule in rules[:5]) or "- 按项目质量规则补齐验收、边界和证据来源。"
            quality_score = round(max(0.2, min(0.95, 0.35 + len(facts) * 0.12 - len(gaps) * 0.06)), 2)
            return {
                "summary": f"已根据 {len(facts)} 条确认事实生成 {section_key} 草稿。",
                "draft_markdown": f"## {section_key}\n\n### 已确认事实\n{bullet_lines}\n\n### 质量规则\n{rule_lines}\n\n### 待确认\n" + "\n".join(f"- {gap}" for gap in (gaps or ["无明显待确认缺口"])),
                "quality_score": quality_score,
                "pending_questions": [f"请补充{gap}。" for gap in gaps],
                "quality_gaps": gaps,
                "evidence": evidence,
                "next_actions": next_actions,
            }

        if skill_name == "BRDResearchAssistant":
            unknown_terms = self._text_items(input_data.get("unknown_terms")) or terms
            industry = input_data.get("industry") or context.get("industry") or "当前行业"
            return {
                "summary": f"已识别 {len(unknown_terms)} 个需要在 {industry} 背景下校验的主题。",
                "research_needed": bool(unknown_terms),
                "safe_reference_topics": [
                    f"{industry} 中“{term}”的业务定义、适用边界和常见指标" for term in unknown_terms[:6]
                ],
                "evidence": evidence,
                "next_actions": ["将调研结论作为参考材料，确认来源后再写入正式文档。"],
            }

        if skill_name == "BRDPatternLibrary":
            section_key = input_data.get("section_key", "brd.section")
            domain = input_data.get("domain") or context.get("business_domain") or document_type
            keywords = self._text_items(input_data.get("keywords")) or terms
            return {
                "summary": f"已为 {domain}/{section_key} 推荐输入驱动的章节模式。",
                "pattern_hints": [
                    f"围绕“{keyword}”分别描述现状、目标、边界和验收证据。"
                    for keyword in (keywords[:5] or [section_key])
                ],
                "confidence": round(0.55 + min(len(keywords), 5) * 0.07, 2),
                "quality_gaps": gaps,
                "evidence": evidence,
                "next_actions": next_actions,
            }

        if skill_name == "BRDOffTopicHandler":
            message = input_data.get("user_message", "")
            active_task = str(input_data.get("active_task") or context.get("active_task") or document_type)
            task_terms = set(self._extract_methodology_terms([active_task], limit=6))
            message_terms = set(self._extract_methodology_terms([str(message)], limit=10))
            off_topic_markers = ["海报", "宣传", "无关", "换个话题", "闲聊"]
            is_off_topic = bool(message) and (any(marker in str(message) for marker in off_topic_markers) or (task_terms and message_terms and not task_terms.intersection(message_terms)))
            return {
                "summary": f"已判断用户输入与“{active_task}”的相关性。",
                "is_off_topic": is_off_topic,
                "reply": (
                    "这条内容偏离当前文档任务，我会先保留为上下文备注，继续推进当前章节。"
                    if is_off_topic
                    else "这条内容与当前文档任务相关，可以进入当前章节处理。"
                ),
                "evidence": evidence,
                "next_actions": ["偏离内容进入上下文暂存，不直接写入正式章节。"] if is_off_topic else ["继续用于当前章节澄清或写入。"],
            }

        if skill_name == "PRDTraceabilityMapper":
            scope = input_data.get("product_scope", "产品范围")
            brd_items = self._text_items(input_data.get("brd_content"))
            rows = []
            for index, item in enumerate(brd_items[:8] or terms[:5]):
                rows.append(
                    {
                        "brd_item": item,
                        "prd_module": terms[index % len(terms)] if terms else str(scope),
                        "feature": f"{item[:40]} 的产品化功能",
                        "priority": "P0" if index == 0 else "P1",
                    }
                )
            return {
                "summary": f"已把 {len(rows)} 条 BRD 输入映射为 {scope} 的 PRD 追踪行。",
                "traceability_rows": rows,
                "uncovered_brd_items": gaps,
                "evidence": evidence,
                "next_actions": ["把追踪行关联到 PRD 模块、页面、接口和验收用例。"],
            }

        if skill_name == "PRDSkeletonPlanner":
            candidates = self._text_items(input_data.get("module_candidates")) or [
                str(row.get("prd_module"))
                for row in input_data.get("traceability_rows", [])
                if isinstance(row, dict) and row.get("prd_module")
            ] or terms
            return {
                "summary": f"已根据 {len(candidates)} 个候选模块生成 PRD 骨架。",
                "module_list": candidates or ["功能范围", "业务规则", "异常处理", "验收标准"],
                "global_rules": [
                    "所有 P0/P1 功能必须可追溯到 BRD 条目。",
                    "每个模块必须定义正常路径、异常路径、权限边界和验收标准。",
                ],
                "tracking_events": [f"{term}_confirmed" for term in (terms[:5] or ["requirement"])],
                "quality_gaps": gaps,
                "evidence": evidence,
                "next_actions": ["进入 PRD 编写页补齐每个模块的页面、接口、规则和验收。"],
            }

        if skill_name == "DocumentTemplateSectionPlanner":
            doc_type = input_data.get("doc_type", document_type)
            sections = self._text_items(input_data.get("required_sections")) or ["背景", "需求", "验收"]
            domain = input_data.get("business_domain") or context.get("business_domain") or doc_type
            return {
                "summary": f"已为 {domain}/{doc_type} 模板规划 {len(sections)} 个标准章节。",
                "sections": [
                    {
                        "section_key": f"{doc_type}.{index + 1}",
                        "title": title,
                        "required_inputs": ["输入来源", "关键事实", "责任角色", "验收或确认标准"],
                        "quality_prompt": f"请说明“{title}”的业务事实、边界、异常和可验收证据。",
                    }
                    for index, title in enumerate(sections)
                ],
                "quality_rules": ["章节必须有输入来源。", "章节必须包含验收或确认标准。", "不得写入未确认事实。"],
                "quality_gaps": gaps,
                "evidence": evidence,
                "next_actions": ["保存为模板章节后绑定到对应文档类型和 Skill。"],
            }

        if skill_name == "ChangeImpactAnalyzer":
            artifacts = self._text_items(input_data.get("linked_artifacts"))
            change_summary = str(input_data.get("change_summary") or "")
            impact_level = "high" if any(marker in change_summary for marker in ["核心", "P0", "权限", "发布", "合规"]) else "medium" if artifacts else "low"
            return {
                "summary": f"已识别 {len(artifacts)} 个下游对象可能受变更影响。",
                "impact_level": impact_level,
                "affected_artifacts": [
                    {
                        "name": artifact,
                        "impact": "需要复核相关章节、追溯链接、验收用例和导出交付物",
                        "suggested_check": f"确认“{artifact}”是否覆盖变更：{change_summary[:80]}",
                    }
                    for artifact in artifacts
                ],
                "recommended_actions": [
                    "更新 PRD 功能追踪矩阵。",
                    "补充或调整验收测试用例。",
                    "复核模板章节是否需要新增约束。",
                ],
                "evidence": evidence,
                "next_actions": ["创建或更新变更追溯记录，并安排受影响文档复核。"],
            }

        if skill_name == "KnowledgeGraphExtractor":
            content = input_data.get("content", "")
            entities = [
                {"name": term, "type": "entity" if index % 2 == 0 else "concept"}
                for index, term in enumerate((terms or self._extract_methodology_terms([str(content)], limit=8))[:8])
            ]
            relationships = [
                {
                    "source": entities[index]["name"],
                    "relation": "关联",
                    "target": entities[index + 1]["name"],
                }
                for index in range(max(0, len(entities) - 1))
            ]
            return {
                "summary": f"已从输入内容抽取 {len(entities)} 个实体/概念和 {len(relationships)} 条候选关系。",
                "entities": entities,
                "relationships": relationships,
                "source_excerpt": str(content)[:180],
                "quality_gaps": gaps,
                "evidence": evidence,
                "next_actions": ["将实体和关系写入知识图谱前，由顾问确认命名、类型和方向。"],
            }

        if skill_name == "TestCaseDesigner":
            feature_name = input_data.get("feature_name", "核心功能")
            criteria = self._text_items(input_data.get("acceptance_criteria"))
            return {
                "summary": f"已为 {feature_name} 生成 {max(1, len(criteria))} 条测试用例草案。",
                "test_cases": [
                    {
                        "title": f"{feature_name} - 验收点 {index + 1}",
                        "precondition": "用户具备对应业务操作权限。",
                        "steps": [
                            f"准备覆盖“{criterion[:40]}”的数据",
                            "执行对应业务操作",
                            "检查系统反馈、审计记录和下游状态",
                        ],
                        "expected_result": criterion,
                    }
                    for index, criterion in enumerate(criteria or ["系统按规则给出明确反馈"])
                ],
                "coverage_gaps": gaps or ["边界值、权限和异常恢复场景仍需按项目细化。"],
                "evidence": evidence,
                "next_actions": ["把测试用例关联到 PRD 功能和变更追溯矩阵。"],
            }

        return {
            "summary": f"{skill_name} 已基于输入完成方法论处理。",
            "derived_terms": terms,
            "quality_gaps": gaps,
            "evidence": evidence,
            "next_actions": next_actions,
        }

    def validate_skill_contract(
        self,
        skill_name: str,
        contract: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        """Validate a skill contract.

        Args:
            skill_name: Name of the skill
            contract: Contract dict to validate

        Returns:
            Tuple of (is_valid, list of errors)
        """
        skill = self.get_skill(skill_name)
        if not skill:
            return False, [f"Unknown skill: {skill_name}"]

        errors = []

        # Check required fields
        required_fields = ["name", "description", "input_schema", "output_schema"]
        for field in required_fields:
            if field not in contract:
                errors.append(f"Missing required field: {field}")

        # Validate schema structure
        if "input_schema" in contract:
            if not isinstance(contract["input_schema"], dict):
                errors.append("input_schema must be a dict")
            elif "type" not in contract["input_schema"]:
                errors.append("input_schema must have 'type' field")

        if "output_schema" in contract:
            if not isinstance(contract["output_schema"], dict):
                errors.append("output_schema must be a dict")
            elif "type" not in contract["output_schema"]:
                errors.append("output_schema must have 'type' field")

        return len(errors) == 0, errors


class DAGExecutor:
    """Service for executing workflow DAGs.

    Handles topological sorting of nodes, dependency resolution,
    and task scheduling.
    """

    def __init__(self, db: AsyncSession):
        """Initialize DAG executor.

        Args:
            db: Async database session
        """
        self.db = db
        self.agent_run_service = AgentRunService(db)
        self.skill_service = SkillService(db)

    def _dependency_graph(
        self,
        node_map: dict[str, dict[str, Any]],
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        """Return dependency and adjacency maps for runtime routing."""
        dependencies: dict[str, list[str]] = {}
        adjacency: dict[str, list[str]] = {node_id: [] for node_id in node_map}
        for node_id, node in node_map.items():
            dependency_ids = [
                str(dependency)
                for dependency in (node.get("depends_on") or [])
                if str(dependency or "").strip()
            ]
            dependencies[node_id] = dependency_ids
            for dependency_id in dependency_ids:
                adjacency.setdefault(dependency_id, []).append(node_id)
        return dependencies, adjacency

    def _expand_condition_skips(
        self,
        initial_skips: set[str],
        selected_nodes: set[str],
        dependencies: dict[str, list[str]],
        adjacency: dict[str, list[str]],
    ) -> set[str]:
        """Skip unselected branch descendants until a live dependency rejoins."""
        skipped = set(initial_skips) - selected_nodes
        queue = list(skipped)
        while queue:
            node_id = queue.pop(0)
            for child_id in adjacency.get(node_id, []):
                if child_id in skipped or child_id in selected_nodes:
                    continue
                child_dependencies = dependencies.get(child_id, [])
                if child_dependencies and all(dependency in skipped for dependency in child_dependencies):
                    skipped.add(child_id)
                    queue.append(child_id)
        return skipped

    async def _skip_node(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        node_id: str,
        reason: str,
        source_node: str | None = None,
    ) -> dict[str, Any]:
        """Mark a routed-out node as completed with explicit skip evidence."""
        output = {
            "status": "skipped",
            "node_id": node_id,
            "skip_reason": reason,
            "source_node": source_node,
        }
        task = await self.agent_run_service.get_task_for_run_node(run_id, node_id)
        if task and task.status != AgentTaskStatus.COMPLETED.value:
            await self.agent_run_service.update_task_status(
                task.id,
                AgentTaskStatus.COMPLETED.value,
                output_data=output,
            )
        await self.agent_run_service.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="node_skipped",
            event_data=output,
        )
        return output

    def _build_node_input(
        self,
        node: dict[str, Any],
        previous_outputs: dict[str, Any],
        workflow_input: dict[str, Any],
    ) -> dict[str, Any]:
        """Build the input payload for a node from workflow and dependency outputs."""
        depends_on = node.get("depends_on", [])
        node_input = dict(workflow_input or {})
        for dep_id in depends_on:
            if dep_id in previous_outputs and isinstance(previous_outputs[dep_id], dict):
                node_input[f"from_{dep_id}"] = previous_outputs[dep_id]
        node_input["workflow_input"] = workflow_input
        node_input.update(_node_config(node))
        return node_input

    async def _execute_parallel_skill_branches(
        self,
        run_id: UUID,
        tenant_id: UUID | None,
        branch_ids: list[str],
        node_map: dict[str, dict[str, Any]],
        node_outputs: dict[str, Any],
        workflow_input: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        """Run configured skill branches concurrently while keeping DB writes serialized."""
        runnable: list[tuple[str, dict[str, Any], AgentTask | None, str, str]] = []
        fallback: list[str] = []

        for branch_id in branch_ids:
            node = node_map.get(branch_id)
            if not node:
                continue
            task = await self.agent_run_service.get_task_for_run_node(run_id, branch_id)
            if task and task.status == AgentTaskStatus.COMPLETED.value:
                node_outputs[branch_id] = task.output_data or {
                    "status": "completed",
                    "node_id": branch_id,
                    "resumed_from_task": True,
                }
                continue
            skill_name = _node_skill_name(node)
            tool_name = _node_tool_name(node)
            node_type = str(node.get("type") or "").strip()
            if skill_name and node_type == "skill":
                runnable.append((branch_id, node, task, "skill", skill_name))
            elif tool_name and node_type == "tool":
                runnable.append((branch_id, node, task, "tool", tool_name))
            else:
                fallback.append(branch_id)

        for branch_id, _node, task, execution_type, execution_name in runnable:
            if task:
                await self.agent_run_service.update_task_status(
                    task.id,
                    AgentTaskStatus.RUNNING.value,
                )
            await self.agent_run_service.log_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type="node_started",
                event_data={"node_id": branch_id, execution_type: execution_name, "parallel": True},
            )

        async def run_adapter(
            branch_id: str,
            node: dict[str, Any],
            execution_type: str,
            execution_name: str,
        ) -> tuple[str, dict[str, Any]]:
            import time

            started = time.perf_counter()
            try:
                node_input = self._build_node_input(node, node_outputs, workflow_input)
                if execution_type == "tool":
                    adapter_result = await self.skill_service.execute_tool(
                        tool_name=execution_name,
                        input_data=node_input,
                        context=context,
                    )
                    result_key = "tool_output"
                else:
                    adapter_result = await self.skill_service.execute_skill(
                        skill_name=execution_name,
                        input_data=node_input,
                        context=context,
                    )
                    result_key = "skill_output"
                return branch_id, {
                    "status": "completed",
                    "node_id": branch_id,
                    result_key: adapter_result,
                    "execution": {
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        f"{execution_type}_name": execution_name,
                        "parallel": True,
                    },
                }
            except Exception as exc:
                return branch_id, {
                    "status": "failed",
                    "node_id": branch_id,
                    "error": str(exc),
                    "execution": {
                        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                        f"{execution_type}_name": execution_name,
                        "parallel": True,
                    },
                }

        results = await asyncio.gather(
            *[
                run_adapter(branch_id, node, execution_type, execution_name)
                for branch_id, node, _task, execution_type, execution_name in runnable
            ]
        )

        tasks_by_branch = {branch_id: task for branch_id, _node, task, _type, _name in runnable}
        outputs: dict[str, dict[str, Any]] = {}
        for branch_id, result in results:
            task = tasks_by_branch.get(branch_id)
            if task:
                await self.agent_run_service.update_task_status(
                    task.id,
                    (
                        AgentTaskStatus.FAILED.value
                        if result.get("status") == "failed"
                        else AgentTaskStatus.COMPLETED.value
                    ),
                    output_data=result if result.get("status") != "failed" else None,
                    error_message=result.get("error"),
                )
            await self.agent_run_service.log_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type="node_completed",
                event_data={"node_id": branch_id, "result": result, "parallel": True},
            )
            node_outputs[branch_id] = result
            outputs[branch_id] = result

        for branch_id in fallback:
            node = node_map[branch_id]
            result = await self._execute_node(run_id, node, node_outputs, workflow_input, context)
            node_outputs[branch_id] = result
            outputs[branch_id] = result

        await self.agent_run_service.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="parallel_group_completed",
            event_data={"branches": branch_ids, "completed": list(outputs.keys())},
        )
        return outputs

    async def execute_workflow(
        self,
        run_id: UUID,
        dag_json: dict[str, Any],
        input_data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a workflow DAG.

        Args:
            run_id: AgentRun UUID
            dag_json: DAG definition
            input_data: Workflow input data
            context: Optional execution context

        Returns:
            Execution result with status and outputs
        """
        dag = dag_json if isinstance(dag_json, dict) else {}
        nodes = dag.get("nodes", [])
        tenant_id = (context or {}).get("tenant_id")

        await self.agent_run_service.update_run_status(
            run_id,
            tenant_id,
            AgentRunStatus.RUNNING.value,
        )
        await self.agent_run_service.merge_run_metadata(
            run_id,
            tenant_id,
            {"execution_kind": "workflow", "node_count": len(nodes)},
        )
        await self.agent_run_service.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="workflow_started",
            event_data={"node_count": len(nodes), "input_keys": list((input_data or {}).keys())},
        )

        validation = validate_workflow_dag(dag)
        if not validation["valid"]:
            error_messages = [
                issue["message"]
                for issue in validation["issues"]
                if issue["severity"] == "error"
            ]
            error_message = "; ".join(error_messages) or "Invalid DAG"
            await self.agent_run_service.merge_run_metadata(
                run_id,
                tenant_id,
                {"execution_kind": "workflow", "status": AgentRunStatus.FAILED.value, "error": error_message},
            )
            await self.agent_run_service.update_run_status(
                run_id,
                tenant_id,
                AgentRunStatus.FAILED.value,
                error_message=error_message,
            )
            await self.agent_run_service.log_event(
                run_id=run_id,
                tenant_id=tenant_id,
                event_type="workflow_failed",
                event_data={"error": error_message, "issues": validation["issues"]},
            )
            return {
                "success": False,
                "error": error_message,
            }

        node_map = {str(node.get("id")): node for node in nodes if isinstance(node, dict)}
        dependencies, adjacency = self._dependency_graph(node_map)
        sorted_nodes = validation["execution_order"]
        preview = build_workflow_execution_preview(dag, input_data or {})
        await self.agent_run_service.merge_run_metadata(
            run_id,
            tenant_id,
            {
                "execution_order": preview["execution_order"],
                "parallel_groups": preview["parallel_groups"],
                "approval_gates": preview["approval_gates"],
                "condition_paths": preview["condition_paths"],
                "estimated_steps": preview["estimated_steps"],
                "requires_human_action": bool(preview["approval_gates"]),
                "status_hint": "requires_human_approval" if preview["approval_gates"] else None,
                "can_resume": False,
            },
        )

        # Execute nodes in topological order
        node_outputs = {}
        context = context or {}
        context["node_outputs"] = node_outputs
        context["node_map"] = node_map
        context["dependencies"] = dependencies
        context["adjacency"] = adjacency
        skipped_nodes: set[str] = set()
        skip_sources: dict[str, str] = {}

        for node_id in sorted_nodes:
            if node_id in skipped_nodes:
                result = await self._skip_node(
                    run_id,
                    tenant_id,
                    node_id,
                    "condition_unselected",
                    skip_sources.get(node_id),
                )
                node_outputs[node_id] = result
                continue

            node = node_map[node_id]
            node_type = str(node.get("type") or "").strip()
            result = await self._execute_node(run_id, node, node_outputs, input_data, context)
            node_outputs[node_id] = result

            if isinstance(result, dict) and result.get("status") == "requires_human_action":
                await self.agent_run_service.merge_run_metadata(
                    run_id,
                    tenant_id,
                    {
                        "execution_kind": "workflow",
                        "status": AgentRunStatus.PENDING.value,
                        "paused_node": node_id,
                        "requires_human_action": True,
                        "can_resume": False,
                        "status_hint": "requires_human_approval",
                    },
                )
                await self.agent_run_service.update_run_status(
                    run_id,
                    tenant_id,
                    AgentRunStatus.PENDING.value,
                )
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="workflow_paused_for_control",
                    event_data={"node_id": node_id, "reason": "requires_human_action"},
                )
                return {
                    "success": False,
                    "requires_human_action": True,
                    "paused_node": node_id,
                    "partial_outputs": node_outputs,
                }

            if isinstance(result, dict) and result.get("status") == "requires_delay":
                await self.agent_run_service.merge_run_metadata(
                    run_id,
                    tenant_id,
                    {
                        "execution_kind": "workflow",
                        "status": AgentRunStatus.PENDING.value,
                        "paused_node": node_id,
                        "requires_human_action": False,
                        "can_resume": True,
                        "status_hint": "delay_scheduled",
                        "resume_after": result.get("resume_after"),
                    },
                )
                await self.agent_run_service.update_run_status(
                    run_id,
                    tenant_id,
                    AgentRunStatus.PENDING.value,
                )
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="workflow_paused_for_delay",
                    event_data={
                        "node_id": node_id,
                        "resume_after": result.get("resume_after"),
                        "duration_seconds": result.get("control_node", {}).get("duration_seconds"),
                    },
                )
                return {
                    "success": False,
                    "requires_delay": True,
                    "paused_node": node_id,
                    "resume_after": result.get("resume_after"),
                    "partial_outputs": node_outputs,
                }

            if node_type == "condition" and isinstance(result, dict):
                selected_targets = set(result.get("selected_targets") or [])
                direct_skips = set(result.get("skipped_targets") or [])
                expanded_skips = self._expand_condition_skips(
                    direct_skips,
                    selected_targets,
                    dependencies,
                    adjacency,
                )
                for skipped_node_id in expanded_skips:
                    skipped_nodes.add(skipped_node_id)
                    skip_sources[skipped_node_id] = node_id

            if node_type == "parallel_group" and isinstance(result, dict):
                branch_ids = result.get("control_node", {}).get("branches") or []
                branch_outputs = await self._execute_parallel_skill_branches(
                    run_id,
                    tenant_id,
                    branch_ids,
                    node_map,
                    node_outputs,
                    input_data,
                    context,
                )
                failed_branch = next(
                    (
                        branch_id
                        for branch_id, branch_result in branch_outputs.items()
                        if isinstance(branch_result, dict) and branch_result.get("status") == "failed"
                    ),
                    None,
                )
                if failed_branch:
                    error_message = f"Parallel branch {failed_branch} failed: {branch_outputs[failed_branch].get('error')}"
                    await self.agent_run_service.merge_run_metadata(
                        run_id,
                        tenant_id,
                        {
                            "execution_kind": "workflow",
                            "status": AgentRunStatus.FAILED.value,
                            "failed_node": failed_branch,
                            "error": error_message,
                        },
                    )
                    await self.agent_run_service.update_run_status(
                        run_id,
                        tenant_id,
                        AgentRunStatus.FAILED.value,
                        error_message=error_message,
                    )
                    await self.agent_run_service.log_event(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        event_type="workflow_failed",
                        event_data={"failed_node": failed_branch, "error": branch_outputs[failed_branch].get("error")},
                    )
                    return {
                        "success": False,
                        "error": error_message,
                        "failed_node": failed_branch,
                        "partial_outputs": node_outputs,
                    }

            # Check if this node failed
            if isinstance(result, dict) and result.get("status") == "failed":
                error_message = f"Node {node_id} failed: {result.get('error')}"
                await self.agent_run_service.merge_run_metadata(
                    run_id,
                    tenant_id,
                    {
                        "execution_kind": "workflow",
                        "status": AgentRunStatus.FAILED.value,
                        "failed_node": node_id,
                        "error": error_message,
                    },
                )
                await self.agent_run_service.update_run_status(
                    run_id,
                    tenant_id,
                    AgentRunStatus.FAILED.value,
                    error_message=error_message,
                )
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="workflow_failed",
                    event_data={"failed_node": node_id, "error": result.get("error")},
                )
                return {
                    "success": False,
                    "error": error_message,
                    "failed_node": node_id,
                    "partial_outputs": node_outputs,
                }

        await self.agent_run_service.merge_run_metadata(
            run_id,
            tenant_id,
            {
                "execution_kind": "workflow",
                "status": AgentRunStatus.COMPLETED.value,
                "completed_nodes": sorted_nodes,
                "output_node_count": len(node_outputs),
                "requires_human_action": False,
                "can_resume": False,
                "status_hint": None,
            },
        )
        await self.agent_run_service.update_run_status(
            run_id,
            tenant_id,
            AgentRunStatus.COMPLETED.value,
        )
        await self.agent_run_service.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="workflow_completed",
            event_data={"completed_nodes": sorted_nodes},
        )
        return {
            "success": True,
            "outputs": node_outputs,
            "completed_nodes": sorted_nodes,
        }

    async def _execute_node(
        self,
        run_id: UUID,
        node: dict[str, Any],
        previous_outputs: dict[str, Any],
        workflow_input: dict[str, Any],
        context: dict[str, Any],
    ) -> dict[str, Any]:
        """Execute a single DAG node.

        Args:
            run_id: AgentRun UUID
            node: Node definition
            previous_outputs: Outputs from previously executed nodes
            workflow_input: Original workflow input
            context: Execution context

        Returns:
            Node execution result
        """
        node_id = node.get("id")
        node_type = str(node.get("type") or "").strip()
        skill_name = node.get("skill")
        tool_name = node.get("tool")
        config = node.get("config", {})
        node_data = node.get("data", {}) if isinstance(node.get("data"), dict) else {}
        if not skill_name:
            skill_name = config.get("skill") or node_data.get("skill") or node_data.get("skill_name")
        if not tool_name:
            tool_name = config.get("tool") or node_data.get("tool")

        # Gather inputs from dependencies
        depends_on = node.get("depends_on", [])
        node_input = dict(workflow_input or {})

        for dep_id in depends_on:
            if dep_id in previous_outputs:
                dep_output = previous_outputs[dep_id]
                if isinstance(dep_output, dict):
                    node_input[f"from_{dep_id}"] = dep_output

        # Add workflow-level inputs
        node_input["workflow_input"] = workflow_input

        # Merge config
        node_input.update(config)

        # Log node start
        tenant_id = context.get("tenant_id")
        task = await self.agent_run_service.get_task_for_run_node(run_id, node_id)
        if task and task.status == AgentTaskStatus.COMPLETED.value:
            return task.output_data or {"status": "completed", "node_id": node_id, "resumed_from_task": True}
        if task:
            await self.agent_run_service.update_task_status(
                task.id,
                AgentTaskStatus.RUNNING.value,
            )

        await self.agent_run_service.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="node_started",
            event_data={"node_id": node_id, "skill": skill_name, "tool": tool_name},
        )

        # Execute skill or tool
        result = {"status": "completed", "node_id": node_id}

        if not skill_name and node_type in {"human_approval", "condition", "parallel_group", "delay", "merge"}:
            result["control_node"] = {
                "type": node_type,
                "config": config,
                "depends_on": depends_on,
            }
            if node_type == "human_approval":
                result["control_node"].update(_approval_metadata(node))
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="human_approval_required",
                    event_data={"node_id": node_id, **_approval_metadata(node)},
                )
                result["status"] = "requires_human_action"
            elif node_type == "condition":
                expression = _condition_expression(node)
                condition_value = _evaluate_condition_expression(
                    expression,
                    workflow_input or {},
                    previous_outputs,
                )
                paths = _condition_paths(node)
                selected_targets: list[str] = []
                skipped_targets: list[str] = []
                if paths:
                    conditional_paths = [path for path in paths if path.get("condition")]
                    if conditional_paths:
                        for path in paths:
                            target = path.get("target")
                            if not target:
                                continue
                            path_matches = (
                                _evaluate_condition_expression(path.get("condition"), workflow_input or {}, previous_outputs)
                                if path.get("condition")
                                else False
                            )
                            if path_matches:
                                selected_targets.append(target)
                            else:
                                skipped_targets.append(target)
                    else:
                        for index, path in enumerate(paths):
                            target = path.get("target")
                            if not target:
                                continue
                            if (condition_value and index == 0) or (not condition_value and index == 1):
                                selected_targets.append(target)
                            else:
                                skipped_targets.append(target)

                result["control_node"].update(
                    {
                        "expression": expression,
                        "paths": paths,
                        "value": condition_value,
                    }
                )
                result["condition_value"] = condition_value
                result["selected_targets"] = selected_targets
                result["skipped_targets"] = skipped_targets
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="condition_evaluated",
                    event_data={
                        "node_id": node_id,
                        "expression": expression,
                        "value": condition_value,
                        "paths": paths,
                    },
                )
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="condition_routed",
                    event_data={
                        "node_id": node_id,
                        "selected_targets": selected_targets,
                        "skipped_targets": skipped_targets,
                    },
                )
            elif node_type == "parallel_group":
                result["control_node"]["branches"] = _parallel_branches(node)
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="parallel_group_scheduled",
                    event_data={"node_id": node_id, "branches": _parallel_branches(node)},
                )
            elif node_type == "delay":
                duration_seconds = config.get("duration_seconds") or config.get("delay_seconds")
                result["control_node"]["duration_seconds"] = duration_seconds
                if bool(config.get("blocking")) or str(config.get("mode") or "").lower() == "blocking":
                    resume_after = datetime.now(timezone.utc) + timedelta(seconds=float(duration_seconds or 0))
                    result["status"] = "requires_delay"
                    result["resume_after"] = resume_after.isoformat()
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="delay_scheduled",
                    event_data={
                        "node_id": node_id,
                        "duration_seconds": duration_seconds,
                        "blocking": result.get("status") == "requires_delay",
                        "resume_after": result.get("resume_after"),
                    },
                )
            elif node_type == "merge":
                merged_outputs = {
                    dependency_id: previous_outputs.get(dependency_id)
                    for dependency_id in depends_on
                    if dependency_id in previous_outputs
                }
                result["merge_strategy"] = str(config.get("strategy") or "collect")
                result["source_nodes"] = list(depends_on)
                result["merged_outputs"] = merged_outputs
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="merge_completed",
                    event_data={
                        "node_id": node_id,
                        "source_nodes": list(depends_on),
                        "merge_strategy": result["merge_strategy"],
                    },
                )
            else:
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="control_node_processed",
                    event_data={"node_id": node_id, "node_type": node_type},
                )
        elif tool_name:
            import time

            started = time.perf_counter()
            try:
                tool_result = await self.skill_service.execute_tool(
                    tool_name=tool_name,
                    input_data=node_input,
                    context=context,
                )
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                result["tool_output"] = tool_result
                artifact_refs = _artifact_refs_from_tool_result(tool_name, tool_result)
                result["artifact_refs"] = artifact_refs
                result["execution"] = {
                    "duration_ms": duration_ms,
                    "tool_name": tool_name,
                    "adapter_ref": f"tool:{tool_name}",
                }
                if artifact_refs:
                    await self.agent_run_service.log_event(
                        run_id=run_id,
                        tenant_id=tenant_id,
                        event_type="node_provider_or_tool_reference",
                        event_data={
                            "node_id": node_id,
                            "tool_name": tool_name,
                            "adapter_ref": f"tool:{tool_name}",
                            "artifact_refs": artifact_refs,
                        },
                    )
            except Exception as e:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                result = {
                    "status": "failed",
                    "node_id": node_id,
                    "error": str(e),
                    "execution": {
                        "duration_ms": duration_ms,
                        "tool_name": tool_name,
                    },
                }
        elif skill_name:
            import time

            started = time.perf_counter()
            try:
                skill_result = await self.skill_service.execute_skill(
                    skill_name=skill_name,
                    input_data=node_input,
                    context=context,
                )
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                result["skill_output"] = skill_result
                result["execution"] = {
                    "duration_ms": duration_ms,
                    "skill_name": skill_name,
                    "adapter_ref": f"skill:{skill_name}",
                }
                await self.agent_run_service.log_event(
                    run_id=run_id,
                    tenant_id=tenant_id,
                    event_type="node_provider_or_tool_reference",
                    event_data={
                        "node_id": node_id,
                        "skill_name": skill_name,
                        "adapter_ref": f"skill:{skill_name}",
                        "artifact_refs": [],
                    },
                )
            except Exception as e:
                duration_ms = round((time.perf_counter() - started) * 1000, 2)
                result = {
                    "status": "failed",
                    "node_id": node_id,
                    "error": str(e),
                    "execution": {
                        "duration_ms": duration_ms,
                        "skill_name": skill_name,
                    },
                }

        # Log node completion
        if task:
            if result.get("status") in {"requires_human_action", "requires_delay"}:
                await self.agent_run_service.update_task_status(
                    task.id,
                    AgentTaskStatus.RUNNING.value,
                    output_data=result,
                )
            else:
                await self.agent_run_service.update_task_status(
                    task.id,
                    (
                        AgentTaskStatus.FAILED.value
                        if result.get("status") == "failed"
                        else AgentTaskStatus.COMPLETED.value
                    ),
                    output_data=result if result.get("status") != "failed" else None,
                    error_message=result.get("error"),
                )

        await self.agent_run_service.log_event(
            run_id=run_id,
            tenant_id=tenant_id,
            event_type="node_completed",
            event_data={"node_id": node_id, "result": result},
        )

        return result
