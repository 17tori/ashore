import uuid

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.serializers import policy_out
from app.core.errors import AppError
from app.models import Application, AuditLog, Resume, ScheduledJob
from app.models.enums import ApplicationStatus as S
from app.models.enums import AutomationMode
from app.schemas.api import PolicyPatch
from app.security.deps import DB, CurrentUser
from app.services.ai.service import AIService
from app.services.applications.engine import process_queue
from app.services.applications.state import transition
from app.services.audit import audit
from app.services.automation.policy import (
    HARD_DAILY_CAP,
    auto_apply_active,
    confirm_auto_rules,
    get_policy,
    in_apply_window,
    pause_automation,
    resume_automation,
    rules_hash,
    sent_today,
    validate_for_auto,
)
from app.services.hhru.gateway import HhGateway

router = APIRouter(prefix="/api/automation", tags=["automation"])


class ConfirmAutoIn(BaseModel):
    """The client echoes the rules hash it displayed, so the user confirms exactly the rules they saw."""

    rules_hash: str = Field(min_length=64, max_length=64)
    acknowledged: bool


async def _state(db, user) -> dict:
    policy = await get_policy(db, user.id)
    data = policy_out(policy)
    data.update(
        rules_hash=rules_hash(policy),
        auto_active=auto_apply_active(policy),
        auto_confirmed_for_current_rules=policy.confirmed_rules_hash == rules_hash(policy),
        auto_problems=validate_for_auto(policy),
        sent_today=await sent_today(db, user),
        in_apply_window=in_apply_window(policy, user.timezone),
        hard_daily_cap=HARD_DAILY_CAP,
    )
    return data


@router.get("")
async def get_automation(db: DB, user: CurrentUser) -> dict:
    return await _state(db, user)


@router.patch("/policy")
async def patch_policy(body: PolicyPatch, db: DB, user: CurrentUser) -> dict:
    policy = await get_policy(db, user.id, for_update=True)
    data = body.model_dump(exclude_unset=True)
    if data.get("mode") == AutomationMode.AUTO:
        raise AppError("Автоотклики включаются только подтверждением правил", code="confirm_required")
    if "allowed_resume_ids" in data:
        ids = [uuid.UUID(str(x)) for x in data["allowed_resume_ids"]]
        owned = set(
            (
                await db.execute(
                    select(Resume.id).where(Resume.user_id == user.id, Resume.id.in_(ids), Resume.archived_at.is_(None))
                )
            ).scalars()
        )
        if owned != set(ids):
            raise AppError("Среди резюме есть недоступные", code="bad_resume")
        data["allowed_resume_ids"] = [str(x) for x in ids]
    if "excluded_employers" in data:
        data["excluded_employers"] = [dict(e) for e in data["excluded_employers"]]
    if "apply_windows" in data:
        data["apply_windows"] = [dict(w) for w in data["apply_windows"]]
    if "daily_limit" in data:
        data["daily_limit"] = min(data["daily_limit"], HARD_DAILY_CAP)
    for key, value in data.items():
        setattr(policy, key, value)
    # Any rule change invalidates the earlier confirmation (the hash no longer matches): Auto stops
    # sending until the user confirms the new rules.
    await audit(
        db,
        user_id=user.id,
        action="automation.policy_updated",
        entity_type="automation_policy",
        entity_id=policy.id,
        details={k: v for k, v in data.items() if k != "allowed_resume_ids"},
    )
    await db.flush()
    return await _state(db, user)


@router.post("/confirm-auto")
async def confirm_auto(body: ConfirmAutoIn, db: DB, user: CurrentUser) -> dict:
    if not body.acknowledged:
        raise AppError("Нужно подтвердить правила автооткликов", code="confirm_required")
    policy = await get_policy(db, user.id, for_update=True)
    if body.rules_hash != rules_hash(policy):
        raise AppError("Правила изменились: обновите страницу и проверьте их снова", code="rules_changed")
    await confirm_auto_rules(db, user, policy)
    return await _state(db, user)


@router.post("/disable-auto")
async def disable_auto(db: DB, user: CurrentUser, mode: AutomationMode = AutomationMode.ASSISTED) -> dict:
    policy = await get_policy(db, user.id, for_update=True)
    policy.mode = mode.value if mode != AutomationMode.AUTO else AutomationMode.ASSISTED.value
    policy.confirmed_rules_hash = None
    await audit(db, user_id=user.id, action="automation.auto_disabled")
    return await _state(db, user)


@router.post("/pause")
async def pause(db: DB, user: CurrentUser) -> dict:
    await pause_automation(db, user.id, "Пауза включена пользователем", actor="user")
    return await _state(db, user)


@router.post("/resume")
async def resume(db: DB, user: CurrentUser) -> dict:
    await resume_automation(db, user.id)
    return await _state(db, user)


@router.post("/stop-all")
async def stop_all(db: DB, user: CurrentUser) -> dict:
    """Pause All: pause everything and pull every queued application back to manual confirmation."""
    await pause_automation(db, user.id, "Остановлено пользователем (Pause All)", actor="user")
    apps = (
        (
            await db.execute(
                select(Application)
                .where(Application.user_id == user.id, Application.status == S.READY.value)
                .with_for_update()
            )
        )
        .scalars()
        .all()
    )
    for app in apps:
        await transition(db, app, S.AWAITING_CONFIRMATION, actor="user", note="очередь остановлена")
    return {"returned_to_confirmation": len(apps), **(await _state(db, user))}


@router.post("/run-queue")
async def run_queue(db: DB, user: CurrentUser) -> dict:
    return await process_queue(db, user, HhGateway(db, user.id), ai=AIService(db))


@router.get("/log")
async def log(db: DB, user: CurrentUser, limit: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    rows = (
        await db.execute(
            select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.created_at.desc()).limit(limit)
        )
    ).scalars()
    return [
        {
            "id": str(r.id),
            "action": r.action,
            "actor": r.actor,
            "entity_type": r.entity_type,
            "entity_id": r.entity_id,
            "details": r.details,
            "at": r.created_at,
        }
        for r in rows
    ]


@router.get("/jobs")
async def jobs(db: DB, user: CurrentUser) -> list[dict]:
    rows = (
        await db.execute(select(ScheduledJob).where(ScheduledJob.user_id == user.id).order_by(ScheduledJob.kind))
    ).scalars()
    return [
        {
            "id": str(j.id),
            "kind": j.kind,
            "search_profile_id": str(j.search_profile_id) if j.search_profile_id else None,
            "enabled": j.enabled,
            "interval_minutes": j.interval_minutes,
            "next_run_at": j.next_run_at,
            "last_run_at": j.last_run_at,
            "last_status": j.last_status,
            "last_error": j.last_error,
            "consecutive_failures": j.consecutive_failures,
        }
        for j in rows
    ]
