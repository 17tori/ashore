import uuid
from datetime import timedelta

import pytest
import redis.asyncio as aioredis
from sqlalchemy import func, select

import app.core.redis as redis_mod
from app.db.base import utcnow
from app.models import Notification, ScheduledJob, User
from app.services.automation.scheduler import claim_due_jobs, daily_report, ensure_jobs, run_job
from tests.factories import search as make_search


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        timezone="Asia/Yekaterinburg",
        settings={},
        pd_consent_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    return user


async def test_ensure_jobs_is_idempotent(db):
    user = await _user(db)
    db.add(make_search(user_id=user.id, search_interval_minutes=10))
    await db.flush()
    await ensure_jobs(db, user)
    await ensure_jobs(db, user)
    jobs = (await db.execute(select(ScheduledJob).where(ScheduledJob.user_id == user.id))).scalars().all()
    kinds = sorted(j.kind for j in jobs)
    assert kinds == sorted(
        ["discover", "process_queue", "sync_negotiations", "check_oauth", "visibility", "daily_report"]
    )
    discover = next(j for j in jobs if j.kind == "discover")
    assert discover.interval_minutes == 30  # never more often than every 30 minutes
    report = next(j for j in jobs if j.kind == "daily_report")
    assert report.next_run_at > utcnow()


async def test_claim_is_exclusive(db):
    user = await _user(db)
    await ensure_jobs(db, user)
    await db.commit()
    first = await claim_due_jobs(db)
    await db.commit()
    second = await claim_due_jobs(db)
    assert first and not set(first) & set(second)


async def test_disabled_profile_job_is_skipped(db):
    user = await _user(db)
    profile = make_search(user_id=user.id, is_active=False)
    db.add(profile)
    await db.flush()
    job = ScheduledJob(
        id=uuid.uuid4(),
        user_id=user.id,
        kind="discover",
        search_profile_id=profile.id,
        enabled=True,
        interval_minutes=60,
        next_run_at=utcnow(),
        consecutive_failures=0,
    )
    db.add(job)
    await db.flush()
    assert (await run_job(db, job.id))["status"] == "disabled"


async def test_jobs_without_hh_do_not_fail(db):
    """With no hh.ru connection every job finishes cleanly instead of erroring and backing off."""
    user = await _user(db)
    await ensure_jobs(db, user)
    await db.flush()
    jobs = (await db.execute(select(ScheduledJob).where(ScheduledJob.user_id == user.id))).scalars().all()
    for job in jobs:
        result = await run_job(db, job.id)
        assert result.get("status") != "error", (job.kind, result)


async def test_daily_report_deduplicated(db):
    user = await _user(db)
    await daily_report(db, user)
    await daily_report(db, user)
    count = (await db.execute(select(func.count()).where(Notification.user_id == user.id))).scalar_one()
    assert count == 1


@pytest.fixture
def redis_down(monkeypatch):
    broken = aioredis.from_url("redis://127.0.0.1:1/0", socket_connect_timeout=0.2, socket_timeout=0.2)
    monkeypatch.setattr(redis_mod, "_client", broken)
    monkeypatch.setattr(redis_mod, "_memory", redis_mod._MemoryWindow())
    yield
    monkeypatch.setattr(redis_mod, "_client", None)


async def test_rate_limit_falls_back_to_memory(redis_down):
    results = [await redis_mod.rate_limit_hit("k", 3, 60) for _ in range(4)]
    assert results == [True, True, True, False]


async def test_lock_skipped_when_redis_down(redis_down):
    async with redis_mod.redis_lock("x"):
        pass
    assert not await redis_mod.redis_healthy()


async def test_api_degrades_without_redis(redis_down, api, resume_text):
    await api.register()
    r = await api.post("/api/resumes/text", json={"title": "x", "text": resume_text})
    assert r.status_code == 201
    ready = await api.get("/api/health/ready")
    assert ready.status_code == 200 and ready.json()["status"] == "degraded"


async def test_lock_is_exclusive():
    if not await redis_mod.redis_healthy():
        pytest.skip("redis not available")
    async with redis_mod.redis_lock("excl", ttl_seconds=5):
        with pytest.raises(redis_mod.LockNotAcquired):
            async with redis_mod.redis_lock("excl", ttl_seconds=5):
                pass


async def test_backoff_grows(db):
    from app.services.automation.scheduler import backoff

    job = ScheduledJob(interval_minutes=30, consecutive_failures=0)
    small = backoff(job)
    job.consecutive_failures = 4
    assert backoff(job) > small
    job.consecutive_failures = 50
    assert backoff(job) <= timedelta(hours=24)
