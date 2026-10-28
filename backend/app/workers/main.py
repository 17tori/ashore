"""ARQ worker: ``arq app.workers.main.WorkerSettings``."""

import logging
import uuid
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlalchemy import select

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.core.redis import LockNotAcquired, redis_lock
from app.db.session import dispose_engine, session_scope
from app.models import ScheduledJob, User
from app.services.automation.scheduler import claim_due_jobs, cleanup, ensure_jobs, run_job
from app.services.notifications.telegram import dispatch_pending

log = logging.getLogger("worker")


async def scheduler_tick(ctx: dict[str, Any]) -> int:
    async with session_scope() as db:
        users = (await db.execute(select(User).where(User.deleted_at.is_(None)))).scalars().all()
        for user in users:
            await ensure_jobs(db, user)
    async with session_scope() as db:
        job_ids = await claim_due_jobs(db)
    for job_id in job_ids:
        await ctx["redis"].enqueue_job("execute_job", str(job_id), _job_id=f"job:{job_id}")
    return len(job_ids)


async def execute_job(ctx: dict[str, Any], job_id: str) -> dict:
    async with session_scope() as db:
        job = await db.get(ScheduledJob, uuid.UUID(job_id))
        if job is None:
            return {"status": "missing"}
        user_id = job.user_id
    try:
        # One job per user at a time: discovery, sending and sync never interleave for the same account.
        async with redis_lock(f"user:{user_id}", ttl_seconds=900):
            async with session_scope() as db:
                return await run_job(db, uuid.UUID(job_id))
    except LockNotAcquired:
        return {"status": "busy"}


async def telegram_dispatch(ctx: dict[str, Any]) -> int:
    async with session_scope() as db:
        return await dispatch_pending(db)


async def nightly_cleanup(ctx: dict[str, Any]) -> None:
    async with session_scope() as db:
        await cleanup(db)


async def startup(ctx: dict[str, Any]) -> None:
    configure_logging(get_settings().log_level)


async def shutdown(ctx: dict[str, Any]) -> None:
    await dispose_engine()


class WorkerSettings:
    functions = [execute_job]
    cron_jobs = [
        cron(scheduler_tick, minute=set(range(0, 60, 5)), run_at_startup=True),
        cron(telegram_dispatch, second={0, 30}),
        cron(nightly_cleanup, hour={3}, minute={17}),
    ]
    on_startup = startup
    on_shutdown = shutdown
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_jobs = get_settings().worker_max_jobs
    job_timeout = 900
    keep_result = 3600
