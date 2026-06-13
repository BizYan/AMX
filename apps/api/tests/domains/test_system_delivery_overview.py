"""Tests for the system delivery command-center aggregation."""

import os
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-system-delivery-overview.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-system-delivery-overview-secret"

import pytest

from app.core.settings import settings
from app.domains.projects.service import ProjectService

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]


def _project(name: str):
    return SimpleNamespace(
        id=uuid4(),
        name=name,
        status="active",
        updated_at=datetime(2026, 5, 21, 10, 0, tzinfo=timezone.utc),
    )


def _workbench(
    *,
    documents: int,
    source_files: int,
    knowledge_entries: int,
    blockers: list[str],
    risks: list[dict],
    review_queue: int,
    open_changes: int,
    export_ready: bool,
    next_actions: list[dict],
    required_documents: int = 5,
    completed_documents: int | None = None,
    pending_sync: int = 0,
):
    completed_documents = documents if completed_documents is None else completed_documents
    return {
        "totals": {
            "documents": documents,
            "source_files": source_files,
            "knowledge_entries": knowledge_entries,
        },
        "readiness": {"blockers": blockers},
        "export_package": {
            "ready": export_ready,
            "required_document_count": required_documents,
            "completed_document_count": completed_documents,
        },
        "collaboration_summary": {
            "review_queue_count": review_queue,
            "open_change_count": open_changes,
        },
        "traceability": {
            "pending_sync_proposals": pending_sync,
        },
        "source_coverage": {"status": "ready" if source_files else "missing"},
        "risks": risks,
        "next_actions": next_actions,
    }


@pytest.mark.asyncio
async def test_system_delivery_overview_aggregates_projects_and_actions():
    tenant_id = uuid4()
    user_id = uuid4()
    healthy_project = _project("合同履约系统升级")
    blocked_project = _project("仓储升级咨询项目")
    service = ProjectService(AsyncMock())
    service.list_projects = AsyncMock(return_value=([healthy_project, blocked_project], 2))
    service.get_document_workbench = AsyncMock(
        side_effect=[
            _workbench(
                documents=5,
                source_files=3,
                knowledge_entries=4,
                blockers=[],
                risks=[],
                review_queue=0,
                open_changes=0,
                export_ready=True,
                next_actions=[
                    {
                        "code": "open_traceability_matrix",
                        "label": "检查可追溯链路",
                        "description": "复核文档和知识条目的追溯关系。",
                        "href": f"/projects/{healthy_project.id}/traceability",
                        "priority": "low",
                    }
                ],
            ),
            _workbench(
                documents=1,
                source_files=0,
                knowledge_entries=1,
                blockers=["仍缺少核心交付文档"],
                risks=[{"code": "review_blocked"}],
                review_queue=2,
                open_changes=1,
                export_ready=False,
                next_actions=[
                    {
                        "code": "generate_missing_documents",
                        "label": "补齐交付文档",
                        "description": "生成缺失的 BRD、PRD、设计或测试交付物。",
                        "href": f"/projects/{blocked_project.id}/documents/generate",
                        "priority": "high",
                    }
                ],
            ),
        ]
    )

    overview = await service.get_system_delivery_overview(
        tenant_id=tenant_id,
        user_id=user_id,
        limit=8,
    )

    assert overview["totals"] == {
        "projects": 2,
        "documents": 6,
        "source_files": 3,
        "knowledge_entries": 5,
        "open_changes": 1,
        "review_queue": 2,
        "export_ready_projects": 1,
        "blocked_projects": 1,
    }
    assert overview["projects"][0]["project_id"] == blocked_project.id
    assert overview["projects"][0]["next_action_label"] == "补齐交付文档"
    assert overview["projects"][1]["project_id"] == healthy_project.id
    assert overview["critical_actions"][0]["priority"] == "high"
    assert overview["critical_actions"][0]["project_name"] == "仓储升级咨询项目"
    assert {module["key"] for module in overview["module_health"]} == {
        "sources",
        "knowledge",
        "documents",
        "review",
        "changes",
        "export",
    }
    service.list_projects.assert_awaited_once_with(
        tenant_id=tenant_id,
        user_id=user_id,
        skip=0,
        limit=8,
    )


@pytest.mark.asyncio
async def test_system_delivery_overview_returns_empty_operational_state():
    service = ProjectService(AsyncMock())
    service.list_projects = AsyncMock(return_value=([], 0))
    service.get_document_workbench = AsyncMock()

    overview = await service.get_system_delivery_overview(
        tenant_id=uuid4(),
        user_id=uuid4(),
        limit=8,
    )

    assert overview["readiness_score"] == 0
    assert overview["totals"]["projects"] == 0
    assert overview["projects"] == []
    assert overview["critical_actions"] == []
    assert overview["module_health"][0]["label"] == "项目资料"
    service.get_document_workbench.assert_not_awaited()


@pytest.mark.asyncio
async def test_system_delivery_overview_includes_visible_portfolio_milestones():
    tenant_id = uuid4()
    user_id = uuid4()
    project = _project("Portfolio Project")
    milestone_id = uuid4()
    service = ProjectService(AsyncMock())
    service.list_projects = AsyncMock(return_value=([project], 1))
    service.get_document_workbench = AsyncMock(
        return_value=_workbench(
            documents=1,
            source_files=1,
            knowledge_entries=1,
            blockers=[],
            risks=[],
            review_queue=0,
            open_changes=0,
            export_ready=False,
            next_actions=[],
            required_documents=1,
        )
    )
    service._build_milestone_portfolio = AsyncMock(
        return_value={
            "totals": {
                "total": 4,
                "active": 2,
                "completed": 1,
                "blocked": 1,
                "overdue": 1,
                "unassigned": 0,
            },
            "status_counts": {"planned": 1, "in_progress": 1, "blocked": 1, "completed": 1},
            "upcoming": [
                {
                    "milestone_id": milestone_id,
                    "project_id": project.id,
                    "project_name": project.name,
                    "title": "Review and traceability",
                    "status": "blocked",
                    "priority": "high",
                    "owner_id": user_id,
                    "owner_name": "Delivery Lead",
                    "due_at": datetime(2026, 5, 20, 10, 0, tzinfo=timezone.utc),
                    "is_overdue": True,
                    "gate_blocker_count": 2,
                    "action_href": f"/projects/{project.id}/plan",
                }
            ],
            "blocked": [],
            "owner_load": [
                {
                    "owner_id": user_id,
                    "owner_name": "Delivery Lead",
                    "active_count": 2,
                    "blocked_count": 1,
                    "overdue_count": 1,
                    "project_count": 1,
                    "action_href": "/collaboration",
                }
            ],
        }
    )

    overview = await service.get_system_delivery_overview(
        tenant_id=tenant_id,
        user_id=user_id,
        limit=8,
    )

    assert overview["milestone_portfolio"]["totals"]["overdue"] == 1
    assert overview["milestone_portfolio"]["upcoming"][0]["milestone_id"] == milestone_id
    assert overview["milestone_portfolio"]["owner_load"][0]["blocked_count"] == 1
    service._build_milestone_portfolio.assert_awaited_once_with(
        tenant_id=tenant_id,
        projects=[project],
    )


@pytest.mark.asyncio
async def test_system_delivery_overview_builds_phase_gates_and_operating_plan():
    tenant_id = uuid4()
    user_id = uuid4()
    intake_project = _project("客户资料待补齐")
    review_project = _project("评审待处理项目")
    release_project = _project("可发布交付项目")
    service = ProjectService(AsyncMock())
    service.list_projects = AsyncMock(return_value=([intake_project, review_project, release_project], 3))
    service.get_document_workbench = AsyncMock(
        side_effect=[
            _workbench(
                documents=0,
                source_files=0,
                knowledge_entries=0,
                blockers=["缺少项目资料"],
                risks=[{"code": "missing_sources"}],
                review_queue=0,
                open_changes=0,
                export_ready=False,
                next_actions=[
                    {
                        "code": "upload_source_files",
                        "label": "上传项目资料",
                        "description": "补齐项目输入。",
                        "href": f"/projects/{intake_project.id}/files",
                        "priority": "high",
                    }
                ],
                completed_documents=0,
            ),
            _workbench(
                documents=5,
                source_files=3,
                knowledge_entries=8,
                blockers=["仍有评审项"],
                risks=[],
                review_queue=2,
                open_changes=1,
                export_ready=False,
                next_actions=[
                    {
                        "code": "review_documents",
                        "label": "处理文档评审",
                        "description": "清理评审队列。",
                        "href": f"/projects/{review_project.id}/documents",
                        "priority": "high",
                    }
                ],
                pending_sync=1,
            ),
            _workbench(
                documents=6,
                source_files=4,
                knowledge_entries=10,
                blockers=[],
                risks=[],
                review_queue=0,
                open_changes=0,
                export_ready=True,
                next_actions=[
                    {
                        "code": "open_traceability_matrix",
                        "label": "检查可追溯链路",
                        "description": "复核交付证据。",
                        "href": f"/projects/{release_project.id}/traceability",
                        "priority": "low",
                    }
                ],
            ),
        ]
    )

    overview = await service.get_system_delivery_overview(
        tenant_id=tenant_id,
        user_id=user_id,
        limit=8,
    )

    assert [phase["key"] for phase in overview["phase_summary"]] == [
        "intake",
        "authoring",
        "review",
        "release",
    ]
    assert overview["phase_summary"][0]["project_count"] == 1
    assert overview["phase_summary"][2]["project_count"] == 1
    assert overview["release_gates"][0]["key"] == "sources_ready"
    assert overview["release_gates"][0]["status"] == "blocked"
    assert overview["release_gates"][-1]["key"] == "export_ready"
    assert overview["release_gates"][-1]["passed_count"] == 1
    assert overview["operating_plan"][0]["project_name"] == "客户资料待补齐"
    assert overview["operating_plan"][0]["phase_key"] == "intake"
    assert overview["operating_plan"][0]["action_href"].endswith("/files")
    assert overview["projects"][0]["delivery_phase_key"] == "intake"
    assert overview["projects"][-1]["release_gate_status"] == "passed"

    capabilities = {item["key"]: item for item in overview["completion_capabilities"]}
    assert capabilities["team_permissions"]["action_href"] == "/team"
    assert "system_operations" in capabilities
    assert capabilities["system_operations"]["action_href"] == "/system-health"


def test_completion_capabilities_cover_production_execution_loops():
    totals = {
        "projects": 2,
        "documents": 8,
        "source_files": 6,
        "knowledge_entries": 18,
        "open_changes": 0,
        "review_queue": 0,
        "export_ready_projects": 2,
        "blocked_projects": 0,
    }
    counts = {
        "published_skills": 5,
        "active_agents": 3,
        "active_workflows": 2,
        "providers": 2,
        "live_providers": 2,
        "active_templates": 4,
        "template_versions": 4,
        "template_sections": 20,
        "completed_exports": 3,
        "roles": 3,
        "users": 4,
        "audit_logs": 12,
        "metric_events": 20,
        "quota_usages": 3,
        "active_alert_rules": 2,
        "enabled_integrations": 2,
        "integration_bindings": 2,
        "completed_sync_runs": 3,
        "synced_assets": 24,
        "collaboration_work_items": 9,
        "completed_work_items": 7,
        "open_work_items": 2,
        "blocked_work_items": 0,
        "overdue_work_items": 0,
        "notification_preferences": 4,
        "unacknowledged_notifications": 0,
        "escalated_notifications": 0,
        "notification_deliveries": 8,
        "sent_notification_deliveries": 8,
        "failed_notification_deliveries": 0,
    }

    capabilities = {
        item["key"]: item
        for item in ProjectService._build_completion_capabilities(totals, counts)
    }

    assert capabilities["external_integration_sync"]["status"] == "ready"
    assert capabilities["collaboration_execution"]["status"] == "ready"
    assert capabilities["notification_alert_handling"]["status"] == "ready"
    assert capabilities["notification_alert_handling"]["action_href"] == "/notifications"


def test_production_gate_blocks_on_escalation_and_failed_delivery():
    capabilities = [
        {
            "key": "project_documents",
            "label": "项目文档闭环",
            "status": "ready",
            "score": 95,
            "summary": "ready",
            "evidence": {},
            "blockers": [],
            "action_label": "进入项目文档",
            "action_href": "/projects",
        },
        {
            "key": "notification_alert_handling",
            "label": "通知确认与告警处置",
            "status": "attention",
            "score": 70,
            "summary": "attention",
            "evidence": {
                "escalated_notifications": 1,
                "failed_notification_deliveries": 2,
            },
            "blockers": ["1 条升级通知尚未确认。", "2 条通知投递失败。"],
            "action_label": "处理通知与告警",
            "action_href": "/notifications",
        },
    ]

    gate = ProjectService._build_production_gate(capabilities)

    assert gate["status"] == "blocked"
    assert gate["blocking_count"] == 1
    assert gate["ready_count"] == 1
    assert gate["checks"][0]["capability_key"] == "notification_alert_handling"
    assert gate["checks"][0]["action_href"] == "/notifications"
