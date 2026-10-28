import hashlib
import json
import uuid
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError
from app.db.base import utcnow
from app.models import Application, AutomationPolicy, User
from app.models.enums import ApplicationStatus, AutomationMode
from app.services.audit import audit
from app.services.notifications.service import notify

RULE_FIELDS = (
    "allowed_resume_ids",
    "allowed_positions",
    "min_score",
    "salary_min",
    "employment_types",
    "excluded_employers",
    "daily_limit",
    "letter_rules",
    "stop_conditions",
)
DEFAULT_STOP_CONDITIONS = {"max_consecutive_failures": 3, "stop_on_captcha": True, "stop_on_auth_error": True}
HARD_DAILY_CAP = 50  # Upper bound no setting (and no AI) can raise.
SENT_STATUSES = (
    ApplicationStatus.SENT,
    ApplicationStatus.VIEWED,
    ApplicationStatus.INVITATION,
    ApplicationStatus.REJECTED,
)


def rules_hash(policy: AutomationPolicy) -> str:
    material = {f: getattr(policy, f) for f in RULE_FIELDS}
    return hashlib.sha256(json.dumps(material, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


async def get_policy(db: AsyncSession, user_id: uuid.UUID, *, for_update: bool = False) -> AutomationPolicy:
    stmt = select(AutomationPolicy).where(AutomationPolicy.user_id == user_id)
    if for_update:
        stmt = stmt.with_for_update()
    policy = (await db.execute(stmt)).scalar_one_or_none()
    if policy is None:
        policy = AutomationPolicy(
            id=uuid.uuid4(),
            user_id=user_id,
            mode=AutomationMode.MANUAL.value,
            stop_conditions=dict(DEFAULT_STOP_CONDITIONS),
            letter_rules={"mode": "always", "tone": "neutral", "length": "short"},
            allowed_resume_ids=[],
            allowed_positions=[],
            employment_types=[],
            excluded_employers=[],
            apply_windows=[],
            daily_limit=10,
            min_score=75,
            ai_monthly_budget=5,
        )
        db.add(policy)
        await db.flush()
    return policy


class AutoApplyNotConfirmed(AppError):
    code = "auto_apply_not_confirmed"


def validate_for_auto(policy: AutomationPolicy) -> list[str]:
    problems = []
    if not policy.allowed_resume_ids:
        problems.append("не выбраны резюме для автооткликов")
    if not policy.allowed_positions:
        problems.append("не указаны разрешённые должности")
    if policy.min_score < 50:
        problems.append("минимальный score для автооткликов должен быть не ниже 50")
    if not 1 <= policy.daily_limit <= HARD_DAILY_CAP:
        problems.append(f"дневной лимит должен быть от 1 до {HARD_DAILY_CAP}")
    return problems


async def confirm_auto_rules(db: AsyncSession, user: User, policy: AutomationPolicy) -> None:
    problems = validate_for_auto(policy)
    if problems:
        raise AutoApplyNotConfirmed("Нельзя включить автоотклики: " + "; ".join(problems))
    policy.confirmed_at = utcnow()
    policy.confirmed_rules_hash = rules_hash(policy)
    policy.mode = AutomationMode.AUTO.value
    await audit(
        db,
        user_id=user.id,
        action="automation.auto_confirmed",
        entity_type="automation_policy",
        entity_id=policy.id,
        details={f: getattr(policy, f) for f in RULE_FIELDS},
    )


def auto_apply_active(policy: AutomationPolicy) -> bool:
    return (
        policy.mode == AutomationMode.AUTO
        and not policy.paused
        and policy.confirmed_rules_hash is not None
        and policy.confirmed_rules_hash == rules_hash(policy)
    )


def in_apply_window(policy: AutomationPolicy, tz_name: str, now: datetime | None = None) -> bool:
    """Smart Apply Windows: spread activity over the day instead of sending everything at once."""
    if not policy.apply_windows:
        return True
    local = (now or utcnow()).astimezone(ZoneInfo(tz_name))
    for window in policy.apply_windows:
        days = window.get("days") or list(range(7))
        if local.weekday() not in days:
            continue
        start = time.fromisoformat(window.get("start", "00:00"))
        end = time.fromisoformat(window.get("end", "23:59"))
        if start <= local.time() <= end:
            return True
    return False


def local_day_start(tz_name: str, now: datetime | None = None) -> datetime:
    local = (now or utcnow()).astimezone(ZoneInfo(tz_name))
    return local.replace(hour=0, minute=0, second=0, microsecond=0)


async def sent_today(db: AsyncSession, user: User, *, search_profile_id: uuid.UUID | None = None) -> int:
    start = local_day_start(user.timezone)
    stmt = select(func.count(Application.id)).where(
        Application.user_id == user.id,
        Application.sent_at >= start,
        Application.sent_at < start + timedelta(days=1),
        Application.status.in_([s.value for s in SENT_STATUSES]),
    )
    if search_profile_id is not None:
        stmt = stmt.where(Application.search_profile_id == search_profile_id)
    return int((await db.execute(stmt)).scalar_one())


async def pause_automation(db: AsyncSession, user_id: uuid.UUID, reason: str, *, actor: str = "system") -> None:
    policy = await get_policy(db, user_id, for_update=True)
    if policy.paused:
        return
    policy.paused = True
    policy.paused_reason = reason[:300]
    policy.paused_at = utcnow()
    await audit(db, user_id=user_id, action="automation.paused", actor=actor, details={"reason": reason})
    await notify(
        db,
        user_id,
        kind="automation_paused",
        title="Автоматизация приостановлена",
        body=reason,
        dedupe_key=f"paused:{policy.paused_at.isoformat(timespec='minutes')}",
    )


async def resume_automation(db: AsyncSession, user_id: uuid.UUID, *, actor: str = "user") -> None:
    policy = await get_policy(db, user_id, for_update=True)
    policy.paused = False
    policy.paused_reason = None
    policy.paused_at = None
    await audit(db, user_id=user_id, action="automation.resumed", actor=actor)
