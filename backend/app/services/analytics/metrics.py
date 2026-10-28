"""Analytics computed from stored facts only. Nothing here estimates what the platform did not report."""

import uuid
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import Date, case, cast, func, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import (
    AIUsageRecord,
    Application,
    ApplicationEvent,
    CoverLetter,
    IntegrationEvent,
    Resume,
    ResumeVisibilityAction,
    Vacancy,
    VacancyMatch,
)
from app.models.enums import ApplicationStatus as S
from app.models.enums import MatchDecision

Period = Literal["day", "week", "month"]
SUITABLE = [MatchDecision.ELIGIBLE.value, MatchDecision.READY_TO_APPLY.value, MatchDecision.APPLIED.value]
SENT_LIKE = [S.SENT.value, S.VIEWED.value, S.INVITATION.value, S.REJECTED.value]


def _bucket(column, period: Period, tz: str):
    return cast(func.date_trunc(period, func.timezone(tz, column)), Date)


async def _series(db: AsyncSession, stmt) -> dict[str, int]:
    return {str(row[0]): int(row[1]) for row in (await db.execute(stmt)).all()}


async def timeseries(db: AsyncSession, user_id: uuid.UUID, *, period: Period, since: datetime, tz: str) -> list[dict]:
    found = _bucket(VacancyMatch.discovered_at, period, tz)
    sent = _bucket(Application.sent_at, period, tz)
    inv = _bucket(ApplicationEvent.created_at, period, tz)
    series = {
        "found": await _series(db, select(found, func.count()).where(VacancyMatch.user_id == user_id, VacancyMatch.discovered_at >= since).group_by(found)),
        "suitable": await _series(db, select(found, func.count()).where(VacancyMatch.user_id == user_id, VacancyMatch.discovered_at >= since, VacancyMatch.decision.in_(SUITABLE)).group_by(found)),
        "sent": await _series(db, select(sent, func.count()).where(Application.user_id == user_id, Application.sent_at >= since).group_by(sent)),
        "invitations": await _series(db, select(inv, func.count()).where(ApplicationEvent.user_id == user_id, ApplicationEvent.created_at >= since, ApplicationEvent.to_status == S.INVITATION.value).group_by(inv)),
    }  # fmt: skip
    keys = sorted(set().union(*[s.keys() for s in series.values()]))
    return [{"bucket": k, **{name: s.get(k, 0) for name, s in series.items()}} for k in keys]


async def overview(db: AsyncSession, user_id: uuid.UUID, *, since: datetime) -> dict:
    found = (
        await db.execute(
            select(func.count()).where(VacancyMatch.user_id == user_id, VacancyMatch.discovered_at >= since)
        )
    ).scalar_one()
    suitable = (
        await db.execute(
            select(func.count()).where(
                VacancyMatch.user_id == user_id,
                VacancyMatch.discovered_at >= since,
                VacancyMatch.decision.in_(SUITABLE),
            )
        )
    ).scalar_one()
    duplicates = (
        await db.execute(
            select(func.coalesce(func.sum(VacancyMatch.times_seen - 1), 0)).where(
                VacancyMatch.user_id == user_id, VacancyMatch.discovered_at >= since
            )
        )
    ).scalar_one()
    sent = (
        await db.execute(select(func.count()).where(Application.user_id == user_id, Application.sent_at >= since))
    ).scalar_one()
    platform_confirmed = (
        await db.execute(
            select(func.count()).where(
                Application.user_id == user_id, Application.sent_at >= since, Application.confirmed_by == "platform"
            )
        )
    ).scalar_one()
    viewed = (
        await db.execute(
            select(func.count(func.distinct(ApplicationEvent.application_id))).where(
                ApplicationEvent.user_id == user_id,
                ApplicationEvent.created_at >= since,
                ApplicationEvent.to_status == S.VIEWED.value,
            )
        )
    ).scalar_one()
    invitations = (
        await db.execute(
            select(func.count(func.distinct(ApplicationEvent.application_id))).where(
                ApplicationEvent.user_id == user_id,
                ApplicationEvent.created_at >= since,
                ApplicationEvent.to_status == S.INVITATION.value,
            )
        )
    ).scalar_one()
    rejections = (
        await db.execute(
            select(func.count(func.distinct(ApplicationEvent.application_id))).where(
                ApplicationEvent.user_id == user_id,
                ApplicationEvent.created_at >= since,
                ApplicationEvent.to_status == S.REJECTED.value,
            )
        )
    ).scalar_one()
    avg_score = (
        await db.execute(
            select(func.avg(VacancyMatch.score))
            .join(Application, Application.match_id == VacancyMatch.id)
            .where(Application.user_id == user_id, Application.sent_at >= since)
        )
    ).scalar_one()
    api_errors = (
        await db.execute(
            select(func.count()).where(
                IntegrationEvent.user_id == user_id,
                IntegrationEvent.created_at >= since,
                IntegrationEvent.error_type.isnot(None),
            )
        )
    ).scalar_one()
    api_calls = (
        await db.execute(
            select(func.count()).where(IntegrationEvent.user_id == user_id, IntegrationEvent.created_at >= since)
        )
    ).scalar_one()
    ai_cost = (
        await db.execute(
            select(func.coalesce(func.sum(AIUsageRecord.cost), 0)).where(
                AIUsageRecord.user_id == user_id, AIUsageRecord.created_at >= since
            )
        )
    ).scalar_one()
    paid_hh = (
        await db.execute(
            select(func.coalesce(func.sum(ResumeVisibilityAction.cost_amount), 0)).where(
                ResumeVisibilityAction.user_id == user_id, ResumeVisibilityAction.created_at >= since
            )
        )
    ).scalar_one()
    return {
        "found": found,
        "suitable": suitable,
        "suitable_rate": round(suitable / found, 3) if found else None,
        "sent": sent,
        "sent_platform_confirmed": platform_confirmed,
        "viewed": viewed,
        "invitations": invitations,
        "rejections": rejections,
        "invitation_rate": round(invitations / sent, 3) if sent else None,
        "avg_sent_score": round(float(avg_score), 1) if avg_score is not None else None,
        "duplicates": int(duplicates),
        "api_calls": api_calls,
        "api_errors": api_errors,
        "ai_cost": float(ai_cost),
        "paid_hh_cost": float(paid_hh),
    }  # fmt: skip


async def breakdowns(db: AsyncSession, user_id: uuid.UUID, *, since: datetime) -> dict:
    invited = case((Application.status == S.INVITATION.value, 1), else_=0)
    base = (Application.user_id == user_id, Application.sent_at >= since)

    async def grouped(label, *joins, limit: int = 10):
        stmt = select(
            label.label("key"), func.count().label("sent"), func.sum(invited).label("invitations")
        ).select_from(Application)
        for target, on in joins:
            stmt = stmt.outerjoin(target, on)
        rows = (await db.execute(stmt.where(*base).group_by(label).order_by(func.count().desc()).limit(limit))).all()
        return [{"key": r.key or "—", "sent": r.sent, "invitations": int(r.invitations or 0)} for r in rows]

    errors = (
        await db.execute(
            select(IntegrationEvent.operation, IntegrationEvent.error_type, func.count())
            .where(
                IntegrationEvent.user_id == user_id,
                IntegrationEvent.created_at >= since,
                IntegrationEvent.error_type.isnot(None),
            )
            .group_by(IntegrationEvent.operation, IntegrationEvent.error_type)
            .order_by(func.count().desc())
            .limit(20)
        )
    ).all()
    return {
        "companies": await grouped(Vacancy.employer_name, (Vacancy, Vacancy.id == Application.vacancy_id)),
        "positions": await grouped(Vacancy.title, (Vacancy, Vacancy.id == Application.vacancy_id)),
        "resumes": await grouped(Resume.title, (Resume, Resume.id == Application.resume_id)),
        "letters": await grouped(
            func.coalesce(CoverLetter.template_kind + literal(" · ") + CoverLetter.generator, literal("без письма")),
            (CoverLetter, CoverLetter.id == Application.cover_letter_id),
        ),
        "channels": await grouped(func.coalesce(Application.channel, literal("—"))),
        "api_errors": [{"operation": r[0], "error": r[1], "count": r[2]} for r in errors],
    }


def window(period: Period) -> timedelta:
    return {"day": timedelta(days=30), "week": timedelta(weeks=26), "month": timedelta(days=365)}[period]


async def report(db: AsyncSession, user_id: uuid.UUID, *, period: Period, tz: str) -> dict:
    since = utcnow() - window(period)
    return {
        "period": period,
        "since": since,
        "overview": await overview(db, user_id, since=since),
        "series": await timeseries(db, user_id, period=period, since=since, tz=tz),
        "breakdowns": await breakdowns(db, user_id, since=since),
    }
