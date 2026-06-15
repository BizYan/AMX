"""Regression tests for workflow activation and ARQ enqueue wiring."""

import os
from types import SimpleNamespace
from uuid import uuid4

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test-agent-runtime.db"
os.environ["REDIS_URL"] = "redis://localhost:6379/0"
os.environ["ARQ_REDIS_URL"] = "redis://localhost:6379/1"
os.environ["JWT_SECRET_KEY"] = "test-agent-runtime-secret"

from app.core.settings import settings

settings.DATABASE_URL = os.environ["DATABASE_URL"]
settings.REDIS_URL = os.environ["REDIS_URL"]
settings.ARQ_REDIS_URL = os.environ["ARQ_REDIS_URL"]

import pytest

import app.domains.knowledge.models  # noqa: F401 - register FK targets before worker queue imports
from app.domains.agent.router import enqueue_workflow_run_job
from app.domains.agent.service import WorkflowService
from app.workers.queue import WorkerSettings


class _ScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class _FakeSession:
    def __init__(self, active_version):
        self.active_version = active_version
        self.executed = []
        self.flushed = False
        self.refreshed = None

    async def execute(self, statement):
        self.executed.append(statement)
        if len(self.executed) == 1:
            return _ScalarResult(self.active_version)
        return _ScalarResult(None)

    async def flush(self):
        self.flushed = True

    async def refresh(self, obj):
        self.refreshed = obj


@pytest.mark.asyncio
async def test_activate_version_uses_update_statement_without_select_update():
    version_id = uuid4()
    tenant_id = uuid4()
    version = SimpleNamespace(
        id=version_id,
        workflow_definition_id=uuid4(),
        is_active=0,
    )
    db = _FakeSession(version)

    result = await WorkflowService(db).activate_version(version_id, tenant_id)

    assert result is version
    assert version.is_active == 1
    assert db.flushed is True
    assert db.refreshed is version
    assert len(db.executed) == 2
    update_stmt = db.executed[1]
    assert update_stmt.__class__.__name__ == "Update"

    values = {
        column.name: value.value if hasattr(value, "value") else value
        for column, value in update_stmt._values.items()
    }
    assert values == {"is_active": 0}


@pytest.mark.asyncio
async def test_enqueue_workflow_run_job_uses_arq_pool_enqueue(monkeypatch):
    run_id = uuid4()
    calls = []

    class FakeRedis:
        async def enqueue_job(self, name, *args):
            calls.append((name, args))

        async def aclose(self):
            calls.append(("closed", ()))

    async def fake_create_pool(redis_settings):
        calls.append(("pool", (redis_settings,)))
        return FakeRedis()

    monkeypatch.setattr("arq.create_pool", fake_create_pool)

    await enqueue_workflow_run_job(run_id)

    assert calls[0][0] == "pool"
    assert calls[1] == ("execute_workflow_run", (str(run_id),))
    assert calls[2] == ("closed", ())


@pytest.mark.asyncio
async def test_enqueue_workflow_run_job_requires_arq_redis_url(monkeypatch):
    monkeypatch.setattr(settings, "ARQ_REDIS_URL", "")

    with pytest.raises(RuntimeError, match="ARQ_REDIS_URL"):
        await enqueue_workflow_run_job(uuid4())


def test_worker_settings_requires_arq_redis_url(monkeypatch):
    from app.workers.queue import get_worker_settings

    monkeypatch.setattr(settings, "ARQ_REDIS_URL", "")

    with pytest.raises(RuntimeError, match="ARQ_REDIS_URL"):
        get_worker_settings()


def test_worker_settings_exposes_arq_cli_class_redis_settings():
    assert WorkerSettings.redis_settings.host == "localhost"
    assert WorkerSettings.redis_settings.port == 6379
    assert WorkerSettings.redis_settings.database == 1


@pytest.mark.asyncio
async def test_execute_workflow_api_enqueues_job(monkeypatch):
    version_id = uuid4()
    workflow_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()
    tenant_id = uuid4()

    # Mock WorkflowService
    class MockWorkflowService:
        def __init__(self, db):
            pass

        async def get_version(self, version_id, tenant_id):
            return SimpleNamespace(id=version_id, workflow_definition_id=workflow_id)

        async def get_active_version(self, workflow_id, tenant_id):
            return SimpleNamespace(id=version_id)

    # Mock AgentRunService
    class MockAgentRunService:
        def __init__(self, db):
            pass

        async def create_run(self, tenant_id, project_id, workflow_version_id, input_data=None):
            return SimpleNamespace(id=run_id, status="pending")

        async def log_event(self, run_id, tenant_id, event_type, event_data):
            return SimpleNamespace(id=uuid4())

    monkeypatch.setattr("app.domains.agent.router.WorkflowService", MockWorkflowService)
    monkeypatch.setattr("app.domains.agent.router.AgentRunService", MockAgentRunService)

    # Mock enqueue_workflow_run_job
    enqueue_calls = []

    async def mock_enqueue(rid):
        enqueue_calls.append(rid)

    monkeypatch.setattr("app.domains.agent.router.enqueue_workflow_run_job", mock_enqueue)

    from app.domains.agent.router import execute_workflow
    from app.domains.agent.schemas import WorkflowExecuteRequest
    from app.models.identity import User

    req = WorkflowExecuteRequest(
        workflow_id=workflow_id,
        version_id=version_id,
        project_id=project_id,
    )
    user = User(id=uuid4(), tenant_id=tenant_id)
    db = None

    res = await execute_workflow(data=req, db=db, current_user=user)

    assert res.run_id == run_id
    assert res.status == "pending"
    assert enqueue_calls == [run_id]


@pytest.mark.asyncio
async def test_create_agent_run_uses_active_version_from_workflow_id(monkeypatch):
    workflow_id = uuid4()
    version_id = uuid4()
    project_id = uuid4()
    run_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    calls = []

    class MockWorkflowService:
        def __init__(self, db):
            pass

        async def get_active_version(self, workflow_id, tenant_id):
            calls.append(("active_version", workflow_id, tenant_id))
            return SimpleNamespace(id=version_id, workflow_definition_id=workflow_id)

        async def get_version(self, requested_version_id, tenant_id):
            calls.append(("version", requested_version_id, tenant_id))
            return SimpleNamespace(id=version_id, workflow_definition_id=workflow_id)

    class MockAgentRunService:
        def __init__(self, db):
            pass

        async def create_run(self, tenant_id, project_id, workflow_version_id, created_by, input_data=None):
            calls.append(("create_run", tenant_id, project_id, workflow_version_id, created_by, input_data))
            return SimpleNamespace(id=run_id, status="pending")

    monkeypatch.setattr("app.domains.agent.router.WorkflowService", MockWorkflowService)
    monkeypatch.setattr("app.domains.agent.router.AgentRunService", MockAgentRunService)

    from app.domains.agent.router import create_run
    from app.domains.agent.schemas import AgentRunCreate
    from app.models.identity import User

    response = await create_run(
        data=AgentRunCreate(
            workflow_id=workflow_id,
            project_id=project_id,
            input_data={"scope": "release"},
        ),
        db=None,
        current_user=User(id=user_id, tenant_id=tenant_id),
    )

    assert response.run_id == run_id
    assert response.status == "pending"
    assert calls == [
        ("active_version", workflow_id, tenant_id),
        ("version", version_id, tenant_id),
        ("create_run", tenant_id, project_id, version_id, user_id, {"scope": "release"}),
    ]
