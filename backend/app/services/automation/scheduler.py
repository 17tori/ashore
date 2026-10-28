"""Per-user scheduled jobs: claimed with SKIP LOCKED, executed under a per-user lock, backed off on errors."""

import logging
import random
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import (
    Application,
    IntegrationEvent,
    Notification,
    OAuthConnection,
    OAuthState,
    ScheduledJob,
    SearchProfile,
    TelegramLinkCode,
    User,
    UserSession,
)
from app.models.enums import ApplicationStatus as S
from app.models.enums import JobKind
from app.services.ai.service import AIService
from app.services.analytics.metrics import overview
from app.services.applications.engine import process_queue, reconcile, sync_statuses
from app.services.automation.policy import get_policy, local_day_start
from app.services.hhru.capabilities import probe_capabilities
from app.services.hhru.errors import HhApiError, HhNotConfigured
from app.services.hhru.gateway import HhGateway
from app.services.notifications.service import notify
from app.services.vacancies.discovery import run_discovery
from app.services.visibility.manager import visibility_tick

log = logging.getLogger(__name__)

DEFAULT_INTERVALS = {
    JobKind.PROCESS_QUEUE: 30,
    JobKind.SYNC_NEGOTIATIONS: 180,
    JobKind.CHECK_OAUTH: 12 * 60,
    JobKind.VISIBILITY: 60,
    JobKind.DAILY_REPORT: 24 * 60,
}
MAX_BACKOFF = timedelta(hours=24)


def next_daily(tz_name: str, at: time, now: datetime | None = None) -> datetime:
    tz = ZoneInfo(tz_name)
    local_now = (now or utcnow()).astimezone(tz)
    candidate = local_now.replace(hour=at.hour, minute=at.minute, second=0, microsecond=0)
    if candidate <= local_now:
        candidate += timedelta(days=1)
    return candidate


async def _upsert_job(
    db: AsyncSession,
    user_id: uuid.UUID,
    kind: JobKind,
    interval: int,
    profile_id: uuid.UUID | None,
    first_run: datetime,
) -> None:
    existing = (
        await db.execute(
            select(ScheduledJob.id).where(
                ScheduledJob.user_id == user_id,
                ScheduledJob.kind == kind.value,
                ScheduledJob.search_profile_id.is_(None)
                if profile_id is None
                else ScheduledJob.search_profile_id == profile_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        await db.execute(
            ScheduledJob.__table__.update().where(ScheduledJob.id == existing).values(interval_minutes=interval)
        )
        return
    await db.execute(
        insert(ScheduledJob)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind.value,
            search_profile_id=profile_id,
            interval_minutes=interval,
            next_run_at=first_run,
            enabled=True,
        )
        .on_conflict_do_nothing()
    )


async def ensure_jobs(db: AsyncSession, user: User) -> None:
    """Idempotently create the job set for a user from their search profiles and settings."""
    now = utcnow()
    profiles = (await db.execute(select(SearchProfile).where(SearchProfile.user_id == user.id))).scalars().all()
    for profile in profiles:
        await _upsert_job(db, user.id, JobKind.DISCOVER, max(30, profile.search_interval_minutes), profile.id, now)
        await db.execute(
            ScheduledJob.__table__.update()
            .where(ScheduledJob.user_id == user.id, ScheduledJob.search_profile_id == profile.id)
            .values(enabled=profile.is_active)
        )
    for kind, interval in DEFAULT_INTERVALS.items():
        first = next_daily(user.timezone, time(9, 0), now) if kind == JobKind.DAILY_REPORT else now
        await _upsert_job(db, user.id, kind, interval, None, first)


async def claim_due_jobs(db: AsyncSession, limit: int = 100) -> list[uuid.UUID]:
    """Atomically move due jobs' next_run_at forward so concurrent schedulers never double-run them."""
    now = utcnow()
    jobs = (
        (
            await db.execute(
                select(ScheduledJob)
                .where(ScheduledJob.enabled.is_(True), ScheduledJob.next_run_at <= now)
                .order_by(ScheduledJob.next_run_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        )
        .scalars()
        .all()
    )
    for job in jobs:
        job.next_run_at = now + timedelta(minutes=job.interval_minutes)
    return [job.id for job in jobs]


def backoff(job: ScheduledJob) -> timedelta:
    base = timedelta(minutes=job.interval_minutes) * (2 ** min(job.consecutive_failures, 6))
    jitter = random.uniform(0, 0.2) * base.total_seconds()  # noqa: S311 - scheduling jitter
    return min(MAX_BACKOFF, base + timedelta(seconds=jitter))


async def daily_report(db: AsyncSession, user: User) -> None:
    since = local_day_start(user.timezone) - timedelta(days=1)
    stats = await overview(db, user.id, since=since)
    queue = (
        await db.execute(
            select(Application.id).where(
                Application.user_id == user.id, Application.status == S.AWAITING_CONFIRMATION.value
            )
        )
    ).all()
    body = (
        f"Найдено: {stats['found']}, подходит: {stats['suitable']}, отправлено: {stats['sent']}, "
        f"приглашений: {stats['invitations']}. Ждут подтверждения: {len(queue)}."
    )
    await notify(
        db,
        user.id,
        kind="daily_report",
        title="Сводка за сутки",
        body=body,
        payload=stats,
        dedupe_key=f"daily:{local_day_start(user.timezone).date()}",
    )


async def run_job(db: AsyncSession, job_id: uuid.UUID) -> dict:
    job = await db.get(ScheduledJob, job_id)
    if job is None or not job.enabled:
        return {"status": "skipped"}
    user = await db.get(User, job.user_id)
    if user is None or user.deleted_at is not None:
        job.enabled = False
        return {"status": "skipped"}
    gateway = HhGateway(db, user.id)
    ai = AIService(db)
    result: dict
    try:
        kind = JobKind(job.kind)
        if kind == JobKind.DISCOVER:
            profile = await db.get(SearchProfile, job.search_profile_id)
            if profile is None or not profile.is_active:
                job.enabled = False
                return {"status": "disabled"}
            result = (await run_discovery(db, user, profile, gateway, ai)).as_dict()
            await db.commit()
            result["queue"] = await process_queue(db, user, gateway, ai)
        elif kind == JobKind.PROCESS_QUEUE:
            result = await process_queue(db, user, gateway, ai)
        elif kind == JobKind.SYNC_NEGOTIATIONS:
            result = await sync_statuses(db, user, gateway)
            stuck = (
                (
                    await db.execute(
                        select(Application).where(
                            Application.user_id == user.id, Application.status.in_([S.UNKNOWN.value, S.SENDING.value])
                        )
                    )
                )
                .scalars()
                .all()
            )
            for app in stuck:
                await reconcile(db, user, app, gateway)
        elif kind == JobKind.CHECK_OAUTH:
            conn = (
                await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))
            ).scalar_one_or_none()
            if conn is None:
                result = {"status": "not_connected"}
            else:
                try:
                    client = await gateway.user_client()
                    async with client:
                        await client.me()
                    caps = await probe_capabilities(db, user.id, gateway)
                    result = {"status": "ok", "capabilities": {k: v["status"] for k, v in caps.items()}}
                except (HhApiError, HhNotConfigured) as exc:
                    if isinstance(exc, HhApiError):
                        await gateway.record_failure(exc)
                    result = {"status": "error", "detail": str(exc)}
        elif kind == JobKind.VISIBILITY:
            result = await visibility_tick(db, user, gateway)
        elif kind == JobKind.DAILY_REPORT:
            await daily_report(db, user)
            job.next_run_at = next_daily(user.timezone, time(9, 0))
            result = {"status": "ok"}
        else:
            result = {"status": "unknown_kind"}
        job = await db.get(ScheduledJob, job_id)
        job.last_status = "ok"
        job.last_error = None
        job.consecutive_failures = 0
    except Exception as exc:
        await db.rollback()
        job = await db.get(ScheduledJob, job_id)
        job.consecutive_failures += 1
        job.last_status = "error"
        job.last_error = f"{exc.__class__.__name__}: {exc}"[:500]
        job.next_run_at = utcnow() + backoff(job)
        log.exception("job failed", extra={"job_id": str(job_id), "kind": job.kind})
        result = {"status": "error", "detail": job.last_error}
    job.last_run_at = utcnow()
    return result


async def cleanup(db: AsyncSession) -> None:
    now = utcnow()
    await db.execute(delete(UserSession).where(UserSession.expires_at < now))
    await db.execute(delete(OAuthState).where(OAuthState.expires_at < now - timedelta(days=1)))
    await db.execute(delete(TelegramLinkCode).where(TelegramLinkCode.expires_at < now - timedelta(days=1)))
    await db.execute(delete(IntegrationEvent).where(IntegrationEvent.created_at < now - timedelta(days=90)))
    await db.execute(delete(Notification).where(Notification.created_at < now - timedelta(days=180)))


async def policy_allows_jobs(db: AsyncSession, user: User) -> bool:
    policy = await get_policy(db, user.id)
    return not policy.paused
