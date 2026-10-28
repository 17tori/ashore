"""Resume visibility: real hh.ru operations where the API allows them, honest reminders otherwise."""

import logging
import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import get_box
from app.db.base import utcnow
from app.models import Resume, ResumeVisibilityAction, User
from app.models.enums import (
    Capability,
    CapabilityStatus,
    ResumeSource,
    VisibilityActionKind,
    VisibilityActionStatus,
)
from app.schemas.profile import CandidateProfile, EducationItem, ExperienceItem, ProfileSkill
from app.services.audit import audit
from app.services.hhru.capabilities import capability_map, set_capability
from app.services.hhru.errors import HhAmbiguousResult, HhApiError, HhForbidden
from app.services.hhru.gateway import HhGateway
from app.services.hhru.normalize import html_to_text, parse_hh_datetime
from app.services.matching.skills import canonical_skill, extract_skills
from app.services.notifications.service import notify
from app.services.resume.extraction import assess_quality, infer_level

log = logging.getLogger(__name__)

HH_RESUMES_URL = "https://hh.ru/applicant/resumes"


def _record(
    db: AsyncSession,
    user_id: uuid.UUID,
    resume_id: uuid.UUID,
    kind: VisibilityActionKind,
    status: VisibilityActionStatus,
    detail: str = "",
    scheduled_for: datetime | None = None,
) -> None:
    db.add(
        ResumeVisibilityAction(
            id=uuid.uuid4(),
            user_id=user_id,
            resume_id=resume_id,
            action=kind.value,
            status=status.value,
            scheduled_for=scheduled_for,
            executed_at=utcnow(),
            detail=detail[:1000],
            created_at=utcnow(),
        )
    )


def hh_resume_to_profile(data: dict) -> CandidateProfile:
    """Convert the hh.ru resume payload into our profile. Data comes from hh.ru, so source='hh'."""
    profile = CandidateProfile()
    if data.get("title"):
        profile.desired_positions = [data["title"]]
    skills = [canonical_skill(s) for s in data.get("skill_set") or []]
    if data.get("skills"):
        skills += extract_skills(data["skills"])
        profile.summary = html_to_text(data["skills"])[:2000]
    profile.skills = [ProfileSkill(name=s, source="hh", confirmed=True) for s in dict.fromkeys(skills)]
    for exp in data.get("experience") or []:
        profile.experience.append(
            ExperienceItem(
                source="hh",
                confirmed=True,
                company=exp.get("company") or "",
                title=exp.get("position") or "",
                start=(exp.get("start") or "")[:7] or None,
                end=(exp.get("end") or "")[:7] or None,
                current=not exp.get("end"),
                description=exp.get("description") or "",
                technologies=extract_skills(exp.get("description") or ""),
            )
        )
    for edu in (data.get("education") or {}).get("primary") or []:
        profile.education.append(
            EducationItem(
                source="hh",
                confirmed=True,
                institution=edu.get("name") or "",
                field=edu.get("result") or "",
                year=edu.get("year"),
            )
        )
    profile.total_experience_months = int((data.get("total_experience") or {}).get("months") or 0)
    profile.has_commercial_experience = profile.total_experience_months > 0
    profile.level = infer_level(profile.total_experience_months, profile.has_commercial_experience)  # type: ignore[assignment]
    salary = data.get("salary") or {}
    if salary.get("amount"):
        profile.min_salary = int(salary["amount"])
        profile.currency = salary.get("currency") or "RUR"
    area = data.get("area") or {}
    if area.get("name"):
        profile.areas = [{"id": str(area.get("id")), "name": area["name"]}]  # type: ignore[list-item]
    return profile


async def import_hh_resumes(db: AsyncSession, user: User, gateway: HhGateway) -> int:
    caps = await capability_map(db, user.id)
    if caps[Capability.RESUMES_READ]["status"] != CapabilityStatus.VERIFIED:
        return 0
    imported = 0
    client = await gateway.user_client()
    async with client:
        mine = await client.my_resumes()
        for item in mine.get("items") or []:
            full = await client.get_resume(str(item["id"]))
            profile = hh_resume_to_profile(full)
            resume = (
                await db.execute(
                    select(Resume).where(Resume.user_id == user.id, Resume.hh_resume_id == str(item["id"]))
                )
            ).scalar_one_or_none()
            if resume is None:
                resume = Resume(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    source=ResumeSource.HH.value,
                    hh_resume_id=str(item["id"]),
                    title=item.get("title") or "Резюме hh.ru",
                    version=1,
                )
                db.add(resume)
            resume.title = item.get("title") or resume.title
            resume.profile = profile.model_dump()
            resume.quality = assess_quality(profile)
            resume.raw_text_enc = get_box().encrypt(str(full)[:50_000], f"resume:{user.id}")
            resume.hh_status = (item.get("status") or {}).get("id")
            resume.hh_can_publish = item.get("can_publish_or_update")
            resume.hh_next_publish_at = parse_hh_datetime(item.get("next_publish_at"))
            resume.hh_synced_at = utcnow()
            imported += 1
    await audit(db, user_id=user.id, action="resume.imported_from_hh", details={"count": imported})
    return imported


def next_allowed_publish(resume: Resume, last_manual: datetime | None) -> datetime | None:
    interval = timedelta(hours=get_settings().hh_resume_publish_interval_hours)
    candidates = [t for t in (resume.hh_next_publish_at,) if t]
    for last in (resume.hh_last_published_at, last_manual):
        if last:
            candidates.append(last + interval)
    return max(candidates) if candidates else None


async def last_action(db: AsyncSession, resume_id: uuid.UUID, statuses: list[str]) -> ResumeVisibilityAction | None:
    return (
        await db.execute(
            select(ResumeVisibilityAction)
            .where(ResumeVisibilityAction.resume_id == resume_id, ResumeVisibilityAction.status.in_(statuses))
            .order_by(ResumeVisibilityAction.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


async def visibility_status(db: AsyncSession, user: User, resume: Resume) -> dict:
    caps = await capability_map(db, user.id)
    publish_cap = caps[Capability.RESUME_PUBLISH]
    manual = await last_action(db, resume.id, [VisibilityActionStatus.CONFIRMED_BY_USER.value])
    confirmed = await last_action(db, resume.id, [VisibilityActionStatus.SUCCEEDED.value])
    next_at = next_allowed_publish(resume, manual.executed_at if manual else None)
    api_possible = bool(resume.hh_resume_id) and publish_cap["status"] != CapabilityStatus.UNAVAILABLE
    return {
        "resume_id": str(resume.id),
        "linked_to_hh": bool(resume.hh_resume_id),
        "hh_status": resume.hh_status,
        "can_publish": resume.hh_can_publish,
        "api_publish": publish_cap,
        "mode": "api" if api_possible and resume.hh_can_publish else "reminders",
        "last_platform_confirmed_at": confirmed.executed_at if confirmed else resume.hh_last_published_at,
        "last_user_marked_at": manual.executed_at if manual else None,
        "next_allowed_at": next_at,
        "cooldown_active": bool(next_at and next_at > utcnow()),
        "paid_operations": "Платные услуги продвижения резюме недоступны через API и покупаются только на hh.ru",
        "manual_url": HH_RESUMES_URL,
    }


async def publish_resume(db: AsyncSession, user: User, resume: Resume, gateway: HhGateway, *, actor: str) -> dict:
    """Free resume update ("поднятие") through the API. Never claims success without hh.ru's answer."""
    status = await visibility_status(db, user, resume)
    if status["mode"] != "api":
        _record(
            db,
            user.id,
            resume.id,
            VisibilityActionKind.PUBLISH,
            VisibilityActionStatus.UNAVAILABLE,
            "поднятие через API недоступно",
        )
        return {"status": "unavailable", "manual_url": HH_RESUMES_URL}
    if status["cooldown_active"]:
        return {"status": "cooldown", "next_allowed_at": status["next_allowed_at"]}
    try:
        client = await gateway.user_client()
        async with client:
            await client.publish_resume(resume.hh_resume_id)
    except HhAmbiguousResult as exc:
        _record(
            db,
            user.id,
            resume.id,
            VisibilityActionKind.PUBLISH,
            VisibilityActionStatus.FAILED,
            f"нет ответа hh.ru: {exc}",
        )
        return {"status": "unknown"}
    except HhForbidden as exc:
        await set_capability(db, user.id, Capability.RESUME_PUBLISH, CapabilityStatus.UNAVAILABLE, exc.tag)
        _record(db, user.id, resume.id, VisibilityActionKind.PUBLISH, VisibilityActionStatus.UNAVAILABLE, exc.tag)
        return {"status": "unavailable", "detail": exc.tag, "manual_url": HH_RESUMES_URL}
    except HhApiError as exc:
        await gateway.record_failure(exc)
        _record(db, user.id, resume.id, VisibilityActionKind.PUBLISH, VisibilityActionStatus.FAILED, exc.tag)
        return {"status": "failed", "detail": exc.tag}
    now = utcnow()
    resume.hh_last_published_at = now
    resume.hh_next_publish_at = now + timedelta(hours=get_settings().hh_resume_publish_interval_hours)
    _record(db, user.id, resume.id, VisibilityActionKind.PUBLISH, VisibilityActionStatus.SUCCEEDED, "hh.ru подтвердил")
    await set_capability(db, user.id, Capability.RESUME_PUBLISH, CapabilityStatus.VERIFIED, "подтверждено поднятием")
    await audit(db, user_id=user.id, action="resume.published", actor=actor, entity_type="resume", entity_id=resume.id)
    return {"status": "succeeded", "published_at": now}


async def mark_published_manually(db: AsyncSession, user: User, resume: Resume) -> None:
    _record(
        db,
        user.id,
        resume.id,
        VisibilityActionKind.MANUAL_MARK,
        VisibilityActionStatus.CONFIRMED_BY_USER,
        "пользователь поднял резюме на hh.ru",
    )
    await audit(db, user_id=user.id, action="resume.manual_publish_marked", entity_type="resume", entity_id=resume.id)


async def visibility_tick(db: AsyncSession, user: User, gateway: HhGateway) -> dict:
    """Scheduled step: API publish when enabled and verified, otherwise a reminder once the cooldown ends."""
    prefs = (user.settings or {}).get("visibility", {})
    if not prefs.get("enabled", True):
        return {"status": "disabled"}
    resumes = (
        (
            await db.execute(
                select(Resume).where(
                    Resume.user_id == user.id, Resume.archived_at.is_(None), Resume.is_primary.is_(True)
                )
            )
        )
        .scalars()
        .all()
    )
    result = {"published": 0, "reminded": 0}
    for resume in resumes:
        status = await visibility_status(db, user, resume)
        if status["cooldown_active"]:
            continue
        caps = await capability_map(db, user.id)
        if (
            status["mode"] == "api"
            and prefs.get("auto_publish")
            and caps[Capability.RESUME_PUBLISH]["status"] == CapabilityStatus.VERIFIED
        ):
            outcome = await publish_resume(db, user, resume, gateway, actor="system")
            result["published"] += outcome["status"] == "succeeded"
            continue
        reminded = await last_action(db, resume.id, [VisibilityActionStatus.REMINDED.value])
        interval = timedelta(hours=get_settings().hh_resume_publish_interval_hours)
        if reminded and reminded.executed_at and utcnow() - reminded.executed_at < interval:
            continue
        _record(db, user.id, resume.id, VisibilityActionKind.REMINDER, VisibilityActionStatus.REMINDED)
        await notify(
            db,
            user.id,
            kind="visibility_reminder",
            title="Можно поднять резюме",
            body=f"«{resume.title}»: поднимите резюме на hh.ru, чтобы оно было выше в поиске.",
            payload={"resume_id": str(resume.id), "url": HH_RESUMES_URL},
            dedupe_key=f"visibility:{resume.id}:{utcnow().isoformat(timespec='hours')}",
        )
        result["reminded"] += 1
    return result
