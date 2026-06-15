"""ARQ Worker Queue Module

Configures the ARQ worker for background job processing with retry logic,
timeout handling, and dead letter queue support.
"""

import logfire
from arq.cron import cron

from app.workers.alert_jobs import evaluate_alert_rules, evaluate_single_rule, send_alert_notification
from app.workers.health_jobs import check_all_providers_health, check_provider_health
from app.workers.jobs import execute_agent_task, execute_workflow_run, retry_failed_task
from app.workers.outbox_jobs import process_outbox_event, retry_outbox_event_from_dlq
from app.workers.redis_config import arq_redis_settings
from app.workers.notification_jobs import escalate_overdue_notifications, process_pending_notification_deliveries
from app.workers.webhook_jobs import deliver_webhook_job, publish_outbox_job, retry_webhook_delivery


class WorkerSettings:
    """ARQ worker settings for the Consultant AI Workbench queue.

    Configures job execution parameters including retry logic,
    timeout handling, and result retention.
    """

    max_jobs: int = 10
    keep_result: int = 3600  # 1 hour
    retry_delay: int = 60  # 1 minute base delay for exponential backoff
    timeout: int = 300  # 5 minutes default job timeout
    functions = [
        execute_agent_task,
        execute_workflow_run,
        retry_failed_task,
        deliver_webhook_job,
        publish_outbox_job,
        retry_webhook_delivery,
        process_outbox_event,
        retry_outbox_event_from_dlq,
        check_provider_health,
        check_all_providers_health,
        escalate_overdue_notifications,
        evaluate_alert_rules,
        evaluate_single_rule,
        send_alert_notification,
        process_pending_notification_deliveries,
    ]
    cron_jobs = [
        cron(evaluate_alert_rules, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(escalate_overdue_notifications, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
        cron(process_pending_notification_deliveries, minute={0, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55}),
    ]

    def __init__(self) -> None:
        self.redis_settings = arq_redis_settings()

    class Config:
        arbitrary_types_allowed = True

    async def startup(self) -> None:
        """Called when the worker starts.

        Initializes connections and performs any necessary setup.
        """
        logfire.info("ARQ Worker starting up")

    async def shutdown(self) -> None:
        """Called when the worker shuts down.

        Performs cleanup of connections and resources.
        """
        logfire.info("ARQ Worker shutting down")

    async def run_job(self, ctx: dict, job: dict) -> dict | None:
        """Main job execution handler.

        Routes jobs to their appropriate handler functions based on
        the job's function name.

        Args:
            ctx: ARQ context dict containing redis and other info
            job: Job dict containing function name and arguments

        Returns:
            Job result or None
        """
        from app.workers.jobs import (
            execute_agent_task,
            execute_workflow_run,
            retry_failed_task,
        )
        from app.workers.webhook_jobs import (
            deliver_webhook_job,
            publish_outbox_job,
            retry_webhook_delivery,
        )
        from app.workers.outbox_jobs import (
            process_outbox_event,
            retry_outbox_event_from_dlq,
        )
        from app.workers.health_jobs import (
            check_provider_health,
            check_all_providers_health,
        )
        from app.workers.notification_jobs import escalate_overdue_notifications, process_pending_notification_deliveries

        function_name = job.get("function")
        job_args = job.get("args", [])
        job_kwargs = job.get("kwargs", {})

        logfire.info(f"Running job: {function_name}", job_id=job.get("job_id"))

        if function_name == "execute_agent_task":
            return await execute_agent_task(ctx, *job_args, **job_kwargs)
        elif function_name == "execute_workflow_run":
            return await execute_workflow_run(ctx, *job_args, **job_kwargs)
        elif function_name == "retry_failed_task":
            return await retry_failed_task(ctx, *job_args, **job_kwargs)
        elif function_name == "deliver_webhook_job":
            return await deliver_webhook_job(ctx, *job_args, **job_kwargs)
        elif function_name == "publish_outbox_job":
            return await publish_outbox_job(ctx, *job_args, **job_kwargs)
        elif function_name == "retry_webhook_delivery":
            return await retry_webhook_delivery(ctx, *job_args, **job_kwargs)
        elif function_name == "process_outbox_event":
            return await process_outbox_event(ctx, *job_args, **job_kwargs)
        elif function_name == "retry_outbox_event_from_dlq":
            return await retry_outbox_event_from_dlq(ctx, *job_args, **job_kwargs)
        elif function_name == "check_provider_health":
            return await check_provider_health(ctx, *job_args, **job_kwargs)
        elif function_name == "check_all_providers_health":
            return await check_all_providers_health(ctx, *job_args, **job_kwargs)
        elif function_name == "escalate_overdue_notifications":
            return await escalate_overdue_notifications(ctx, *job_args, **job_kwargs)
        elif function_name == "process_pending_notification_deliveries":
            return await process_pending_notification_deliveries(ctx, *job_args, **job_kwargs)
        else:
            logfire.error(f"Unknown job function: {function_name}")
            return None

    async def after_job(self, ctx: dict, job: dict, result: any, exception: BaseException | None) -> None:
        """Called after each job completes.

        Handles post-job processing such as logging, dead letter queue
        for failed jobs, and cleanup.

        Args:
            ctx: ARQ context dict
            job: Job dict
            result: Job result (if successful)
            exception: Exception (if job failed)
        """
        job_id = job.get("job_id", "unknown")
        function_name = job.get("function", "unknown")

        if exception:
            logfire.error(
                f"Job failed: {function_name}",
                job_id=job_id,
                error=str(exception),
            )

            # Check if job should go to DLQ
            max_retries = job.get("max_retries", 3)
            retry_count = job.get("retry", 0)

            if retry_count >= max_retries:
                logfire.error(
                    f"Job exceeded max retries, moving to DLQ: {function_name}",
                    job_id=job_id,
                    retry_count=retry_count,
                    max_retries=max_retries,
                )
                await self._move_to_dlq(ctx, job, exception)
        else:
            logfire.info(
                f"Job completed: {function_name}",
                job_id=job_id,
            )

    async def _move_to_dlq(self, ctx: dict, job: dict, exception: BaseException) -> None:
        """Move a failed job to the dead letter queue.

        Args:
            ctx: ARQ context dict
            job: Failed job dict
            exception: Exception that caused failure
        """
        import json
        from datetime import datetime, timezone

        redis = ctx.get("redis")
        if not redis:
            return

        dlq_key = "arq:dlq"
        dlq_entry = {
            "job": job,
            "error": str(exception),
            "failed_at": datetime.now(timezone.utc).isoformat(),
        }

        await redis.rpush(dlq_key, json.dumps(dlq_entry))
        logfire.info(f"Moved job to DLQ: {job.get('job_id')}")


def get_worker_settings() -> WorkerSettings:
    """Create worker settings from environment variables.

    Returns:
        WorkerSettings configured from app settings
    """
    return WorkerSettings()
