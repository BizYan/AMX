"""ARQ Worker Job Functions

Job functions for agent task execution, workflow runs, and retry handling.
Implements exponential backoff, timeout handling, and dead letter queue.
"""

import asyncio
import json
import logging
import time
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from arq.connections import RedisSettings
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.settings import settings
from app.db.session import AsyncSessionLocal
from app.domains.agent.models import (
    AgentRun,
    AgentTask,
    AgentTaskStatus,
    AgentRunStatus,
)
from app.domains.agent.service import SkillService, DAGExecutor
from app.domains.agent.tools import TOOL_ADAPTERS
from app.domains.ops.models import MetricEvent
from app.domains.notifications.service import UserNotificationService


logger = logging.getLogger(__name__)

try:
    import logfire  # type: ignore
except ModuleNotFoundError:
    class _LogfireFallback:
        def info(self, message: str, **kwargs: Any) -> None:
            logger.info(message, extra=kwargs)

        def warning(self, message: str, **kwargs: Any) -> None:
            logger.warning(message, extra=kwargs)

        def error(self, message: str, **kwargs: Any) -> None:
            logger.error(message, extra=kwargs)

    logfire = _LogfireFallback()


# Exponential backoff delays in seconds
BACKOFF_DELAYS = [1, 5, 15, 30, 60]


def _optional_uuid(value: Any) -> UUID | None:
    if value is None or isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


async def _notify_run_terminal_best_effort(db, run: AgentRun) -> None:
    metadata = dict(run.metadata_json or {})
    try:
        async with db.begin_nested():
            await UserNotificationService(db).notify_agent_run_terminal(
                tenant_id=run.tenant_id,
                run_id=run.id,
                user_id=_optional_uuid(metadata.get("created_by")),
                status=run.status,
                project_id=run.project_id,
                run_name=metadata.get("workflow_name") or metadata.get("agent_profile_name"),
                error_message=run.error_message,
            )
    except Exception as notification_error:
        logfire.error(
            "Failed to create terminal notification for Agent run",
            run_id=str(run.id),
            error=str(notification_error),
        )


def register_tool_adapter(tool_name: str, adapter_class):
    """Register a tool adapter for a given tool name.

    Args:
        tool_name: Name of the tool
        adapter_class: Adapter class implementing the tool contract
    """
    TOOL_ADAPTERS[tool_name] = adapter_class


async def execute_tool(
    tool_name: str,
    tool_input: dict[str, Any],
    tenant_id: UUID,
    db,
) -> dict[str, Any]:
    """Execute a tool by dispatching to the appropriate adapter.

    Args:
        tool_name: Name of the tool to execute
        tool_input: Input data for the tool
        tenant_id: Tenant UUID for audit logging
        db: Database session

    Returns:
        Dict with tool execution result including output, duration, and success status
    """
    start_time = time.time()
    error_message = None
    output_data = None
    success = False

    try:
        adapter_class = TOOL_ADAPTERS.get(tool_name)
        if not adapter_class:
            raise ValueError(f"No adapter registered for tool: {tool_name}")

        adapter = adapter_class()
        result = await adapter.execute(tool_input)

        output_data = result if isinstance(result, dict) else {"result": result}
        success = True
        logfire.info(f"Tool executed successfully: {tool_name}")

    except Exception as e:
        error_message = str(e)
        logfire.error(f"Tool execution failed: {tool_name}", error=error_message)
        output_data = {"error": error_message}

    duration_ms = int((time.time() - start_time) * 1000)

    # Record metric event for audit
    metric_event = MetricEvent(
        tenant_id=tenant_id,
        metric_type="tool",
        metric_name="execute",
        value=duration_ms,
        dimensions={
            "tool_name": tool_name,
            "success": str(success),
            "error": error_message or "",
        },
        recorded_at=datetime.now(timezone.utc),
    )
    db.add(metric_event)

    return {
        "tool": tool_name,
        "input": tool_input,
        "output": output_data,
        "duration_ms": duration_ms,
        "success": success,
        "error": error_message,
    }


async def execute_agent_task(ctx: dict, task_id: str) -> dict[str, Any]:
    """Execute an agent task.

    Implements retry logic with exponential backoff and timeout handling.
    Tasks that exceed max_retries are moved to the dead letter queue.

    Args:
        ctx: ARQ context dict containing redis connection
        task_id: UUID of the task to execute

    Returns:
        Dict with execution result
    """
    logfire.info(f"Executing agent task: {task_id}")

    async with AsyncSessionLocal() as db:
        # Get task
        result = await db.execute(
            select(AgentTask).where(AgentTask.id == UUID(task_id))
        )
        task = result.scalar_one_or_none()

        if not task:
            logfire.error(f"Task not found: {task_id}")
            return {"success": False, "error": "Task not found"}

        # Check if task has exceeded retries
        if task.retries >= task.max_retries:
            logfire.warning(
                f"Task exceeded max retries: {task_id}",
                retries=task.retries,
                max_retries=task.max_retries,
            )
            return {
                "success": False,
                "error": "Max retries exceeded",
                "task_id": task_id,
                "retries": task.retries,
            }

        # Update task status to running
        task.status = AgentTaskStatus.RUNNING.value
        task.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # Execute the skill or tool
            skill_service = SkillService(db)

            if task.skill_name:
                # Execute skill
                skill = skill_service.get_skill(task.skill_name)
                if not skill:
                    raise ValueError(f"Unknown skill: {task.skill_name}")

                result = await skill_service.execute_skill(
                    skill_name=task.skill_name,
                    input_data=task.input_data or {},
                    context={"task_id": task_id},
                )

                # Update task as completed
                task.status = AgentTaskStatus.COMPLETED.value
                task.completed_at = datetime.now(timezone.utc)
                task.output_data = result
                await db.commit()

                logfire.info(f"Task completed successfully: {task_id}")
                return {"success": True, "task_id": task_id, "result": result}

            elif task.tool_name:
                # Execute tool by dispatching to appropriate adapter
                tool_result = await execute_tool(
                    tool_name=task.tool_name,
                    tool_input=task.input_data or {},
                    tenant_id=task.tenant_id,
                    db=db,
                )

                # Record tool execution result
                task.status = AgentTaskStatus.COMPLETED.value if tool_result["success"] else AgentTaskStatus.FAILED.value
                task.completed_at = datetime.now(timezone.utc)
                task.output_data = {
                    "tool": task.tool_name,
                    "executed": True,
                    "output": tool_result.get("output"),
                    "duration_ms": tool_result.get("duration_ms"),
                }
                if not tool_result["success"]:
                    task.error_message = tool_result.get("error")

                await db.commit()

                if tool_result["success"]:
                    return {"success": True, "task_id": task_id, "tool_result": tool_result}
                else:
                    raise ValueError(f"Tool execution failed: {tool_result.get('error')}")

            else:
                raise ValueError("Task has no skill_name or tool_name")

        except Exception as e:
            logfire.error(f"Task execution failed: {task_id}", error=str(e))

            # Increment retry count
            task.retries += 1
            task.error_message = str(e)
            task.status = AgentTaskStatus.FAILED.value
            task.completed_at = datetime.now(timezone.utc)
            await db.commit()

            # Check if we should retry
            if task.retries < task.max_retries:
                # Schedule retry with exponential backoff
                delay = BACKOFF_DELAYS[min(task.retries - 1, len(BACKOFF_DELAYS) - 1)]

                logfire.info(
                    f"Scheduling task retry: {task_id}",
                    retry=task.retries,
                    delay=delay,
                )

                # Re-queue the task for retry
                await schedule_task_retry(ctx, task_id, delay)

                return {
                    "success": False,
                    "error": str(e),
                    "task_id": task_id,
                    "retry_scheduled": True,
                    "retry_delay": delay,
                }
            else:
                # Max retries exceeded, move to DLQ
                await move_task_to_dlq(ctx, task_id, str(e))
                return {
                    "success": False,
                    "error": str(e),
                    "task_id": task_id,
                    "moved_to_dlq": True,
                }


async def execute_workflow_run(ctx: dict, run_id: str) -> dict[str, Any]:
    """Execute a workflow run.

    Processes the workflow DAG, executing nodes in topological order
    and handling dependencies.

    Args:
        ctx: ARQ context dict containing redis connection
        run_id: UUID of the agent run to execute

    Returns:
        Dict with execution result
    """
    logfire.info(f"Executing workflow run: {run_id}")

    async with AsyncSessionLocal() as db:
        # Get run
        result = await db.execute(
            select(AgentRun)
            .options(selectinload(AgentRun.workflow_version))
            .where(AgentRun.id == UUID(run_id))
        )
        run = result.scalar_one_or_none()

        if not run:
            logfire.error(f"Agent run not found: {run_id}")
            return {"success": False, "error": "Agent run not found"}

        # Update run status to running
        run.status = AgentRunStatus.RUNNING.value
        run.started_at = datetime.now(timezone.utc)
        await db.commit()

        try:
            # Get workflow version with DAG
            workflow_version = run.workflow_version
            if not workflow_version:
                raise ValueError("Workflow version not found")

            dag_json = workflow_version.dag_json or {}
            input_data = run.input_data or {}

            # Execute DAG
            executor = DAGExecutor(db)
            result = await executor.execute_workflow(
                run_id=run.id,
                dag_json=dag_json,
                input_data=input_data,
                context={"tenant_id": run.tenant_id},
            )

            # Update run status based on result
            if result.get("success"):
                run.status = AgentRunStatus.COMPLETED.value
                run.completed_at = datetime.now(timezone.utc)
            elif result.get("requires_human_action"):
                run.status = AgentRunStatus.PENDING.value
                run.completed_at = None
                run.error_message = None
            else:
                run.status = AgentRunStatus.FAILED.value
                run.completed_at = datetime.now(timezone.utc)
                run.error_message = result.get("error")

            if run.status in {AgentRunStatus.COMPLETED.value, AgentRunStatus.FAILED.value}:
                await _notify_run_terminal_best_effort(db, run)
            await db.commit()

            logfire.info(
                f"Workflow run completed: {run_id}",
                success=result.get("success"),
            )

            return {
                "success": result.get("success", False),
                "run_id": run_id,
                "requires_human_action": result.get("requires_human_action", False),
                "paused_node": result.get("paused_node"),
                "error": result.get("error"),
                "completed_nodes": result.get("completed_nodes", []),
            }

        except Exception as e:
            logfire.error(f"Workflow run failed: {run_id}", error=str(e))

            run.status = AgentRunStatus.FAILED.value
            run.completed_at = datetime.now(timezone.utc)
            run.error_message = str(e)
            await _notify_run_terminal_best_effort(db, run)
            await db.commit()

            return {
                "success": False,
                "run_id": run_id,
                "error": str(e),
            }


async def retry_failed_task(ctx: dict, task_id: str) -> dict[str, Any]:
    """Retry a failed task.

    Specifically handles manual retry requests for failed tasks,
    bypassing the normal retry mechanism but still respecting max_retries.

    Args:
        ctx: ARQ context dict containing redis connection
        task_id: UUID of the task to retry

    Returns:
        Dict with retry result
    """
    logfire.info(f"Retrying failed task: {task_id}")

    async with AsyncSessionLocal() as db:
        # Get task
        result = await db.execute(
            select(AgentTask).where(AgentTask.id == UUID(task_id))
        )
        task = result.scalar_one_or_none()

        if not task:
            logfire.error(f"Task not found for retry: {task_id}")
            return {"success": False, "error": "Task not found"}

        # Check if task can be retried
        if task.status == AgentTaskStatus.COMPLETED.value:
            return {
                "success": False,
                "error": "Task already completed",
                "task_id": task_id,
            }

        if task.retries >= task.max_retries:
            return {
                "success": False,
                "error": "Max retries exceeded",
                "task_id": task_id,
                "retries": task.retries,
                "max_retries": task.max_retries,
            }

        # Reset task status and increment retries
        task.status = AgentTaskStatus.PENDING.value
        task.retries += 1
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        await db.commit()

        # Enqueue for execution
        await enqueue_agent_task(ctx, task_id)

        logfire.info(f"Failed task re-queued for retry: {task_id}", retry=task.retries)

        return {
            "success": True,
            "task_id": task_id,
            "retry": task.retries,
            "message": "Task re-queued for retry",
        }


# Helper functions for job queue management


async def schedule_task_retry(ctx: dict, task_id: str, delay: int) -> None:
    """Schedule a task for retry after a delay.

    Args:
        ctx: ARQ context dict
        task_id: UUID of the task
        delay: Delay in seconds before retry
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.error("Redis not available for scheduling retry")
        return

    from arq import enqueue_job

    # Use ARQ's delay mechanism to schedule retry
    try:
        await enqueue_job(
            "execute_agent_task",
            task_id,
            _job_try=1,
            _delay=delay,
            redis=redis,
        )
        logfire.info(f"Scheduled task retry: {task_id} in {delay}s")
    except Exception as e:
        logfire.error(f"Failed to schedule task retry: {task_id}", error=str(e))


async def enqueue_agent_task(ctx: dict, task_id: str) -> None:
    """Enqueue an agent task for execution.

    Args:
        ctx: ARQ context dict
        task_id: UUID of the task to enqueue
    """
    redis = ctx.get("redis")
    if not redis:
        logfire.error("Redis not available for enqueuing")
        return

    from arq import enqueue_job

    try:
        await enqueue_job(
            "execute_agent_task",
            task_id,
            redis=redis,
        )
        logfire.info(f"Enqueued agent task: {task_id}")
    except Exception as e:
        logfire.error(f"Failed to enqueue agent task: {task_id}", error=str(e))


async def move_task_to_dlq(ctx: dict, task_id: str, error: str) -> None:
    """Move a task to the dead letter queue.

    Args:
        ctx: ARQ context dict
        task_id: UUID of the failed task
        error: Error message from the failure
    """
    import json

    redis = ctx.get("redis")
    if not redis:
        logfire.error("Redis not available for DLQ")
        return

    dlq_key = "arq:dlq"
    dlq_entry = {
        "task_id": task_id,
        "error": error,
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }

    await redis.rpush(dlq_key, json.dumps(dlq_entry))
    logfire.info(f"Moved task to DLQ: {task_id}")


async def get_dlq_entries(ctx: dict, limit: int = 100) -> list[dict[str, Any]]:
    """Get entries from the dead letter queue.

    Args:
        ctx: ARQ context dict
        limit: Maximum number of entries to return

    Returns:
        List of DLQ entries
    """
    import json

    redis = ctx.get("redis")
    if not redis:
        return []

    dlq_key = "arq:dlq"
    entries = await redis.lrange(dlq_key, 0, limit - 1)

    return [json.loads(entry) for entry in entries]


async def clear_dlq_entry(ctx: dict, task_id: str) -> bool:
    """Clear a specific entry from the DLQ.

    Args:
        ctx: ARQ context dict
        task_id: UUID of the task to clear

    Returns:
        True if entry was found and removed, False otherwise
    """
    import json

    redis = ctx.get("redis")
    if not redis:
        return False

    dlq_key = "arq:dlq"
    entries = await redis.lrange(dlq_key, 0, -1)

    for entry in entries:
        parsed = json.loads(entry)
        if parsed.get("task_id") == task_id:
            await redis.lrem(dlq_key, 1, entry)
            return True

    return False
