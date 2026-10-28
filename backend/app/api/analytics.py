from datetime import timedelta

from fastapi import APIRouter
from sqlalchemy import func, select

from app.api.serializers import notification_out
from app.core.config import get_settings
from app.db.base import utcnow
from app.models import Application, Notification, OAuthConnection, Resume, VacancyMatch
from app.models.enums import ApplicationStatus as S
from app.security.deps import DB, CurrentUser
from app.services.analytics.metrics import Period, overview, report
from app.services.automation.policy import auto_apply_active, get_policy, local_day_start, sent_today
from app.services.hhru.capabilities import capability_map
from app.services.visibility.manager import visibility_status

router = APIRouter(prefix="/api", tags=["analytics"])


@router.get("/analytics")
async def analytics(db: DB, user: CurrentUser, period: Period = "week") -> dict:
    return await report(db, user.id, period=period, tz=user.timezone)


@router.get("/dashboard")
async def dashboard(db: DB, user: CurrentUser) -> dict:
    effective = func.coalesce(VacancyMatch.user_decision, VacancyMatch.decision)
    decisions = dict(
        (await db.execute(
            select(effective, func.count()).where(VacancyMatch.user_id == user.id, VacancyMatch.hidden.is_(False)).group_by(effective)
        )).all()
    )  # fmt: skip
    statuses = dict(
        (
            await db.execute(
                select(Application.status, func.count())
                .where(Application.user_id == user.id)
                .group_by(Application.status)
            )
        ).all()
    )
    policy = await get_policy(db, user.id)
    conn = (await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))).scalar_one_or_none()
    primary = (
        await db.execute(
            select(Resume).where(Resume.user_id == user.id, Resume.is_primary.is_(True), Resume.archived_at.is_(None))
        )
    ).scalar_one_or_none()
    notifications = (
        await db.execute(
            select(Notification).where(Notification.user_id == user.id, Notification.read_at.is_(None))
            .order_by(Notification.created_at.desc()).limit(5)
        )
    ).scalars()  # fmt: skip
    settings = get_settings()
    return {
        "today": await overview(db, user.id, since=local_day_start(user.timezone)),
        "week": await overview(db, user.id, since=utcnow() - timedelta(days=7)),
        "decisions": decisions,
        "applications": statuses,
        "awaiting_confirmation": statuses.get(S.AWAITING_CONFIRMATION.value, 0),
        "unknown": statuses.get(S.UNKNOWN.value, 0),
        "automation": {
            "mode": policy.mode,
            "paused": policy.paused,
            "paused_reason": policy.paused_reason,
            "auto_active": auto_apply_active(policy),
            "sent_today": await sent_today(db, user),
            "daily_limit": policy.daily_limit,
        },
        "hh": {
            "configured": settings.hh_configured,
            "connected": conn is not None and conn.status == "active",
            "capabilities": await capability_map(db, user.id),
        },
        "resume": {
            "id": str(primary.id),
            "title": primary.title,
            "visibility": await visibility_status(db, user, primary),
        }
        if primary
        else None,
        "notifications": [notification_out(n) for n in notifications],
        "demo_mode": settings.demo_mode,
    }
