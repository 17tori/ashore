import json
import uuid

from fastapi import APIRouter, File, Form, UploadFile
from sqlalchemy import select, update

from app.api.serializers import resume_out
from app.core.config import get_settings
from app.core.crypto import get_box
from app.core.errors import AppError
from app.db.base import utcnow
from app.models import AutomationPolicy, Resume, SearchProfile
from app.models.enums import ResumeSource
from app.schemas.api import ResumeLinkHh, ResumeProfilePatch, ResumeTextIn
from app.schemas.profile import CandidateProfile
from app.security.deps import DB, CurrentUser, get_owned
from app.services.ai.service import AIService
from app.services.audit import audit
from app.services.hhru.gateway import HhGateway
from app.services.resume.ai_enrich import enrich_profile
from app.services.resume.extraction import assess_quality, build_profile, extract_contacts
from app.services.resume.parsing import extract_text
from app.services.visibility.manager import mark_published_manually, publish_resume, visibility_status

router = APIRouter(prefix="/api/resumes", tags=["resumes"])


async def _create_from_text(db, user, *, title: str, text: str, file_name: str | None, use_ai: bool) -> Resume:
    profile = build_profile(text)
    used_ai = False
    if use_ai:
        profile, used_ai = await enrich_profile(AIService(db), user, profile, text)
    contacts = extract_contacts(text)
    has_primary = (
        await db.execute(
            select(Resume.id).where(
                Resume.user_id == user.id, Resume.is_primary.is_(True), Resume.archived_at.is_(None)
            )
        )
    ).first()
    box = get_box()
    resume = Resume(
        id=uuid.uuid4(),
        user_id=user.id,
        title=title[:200],
        source=ResumeSource.UPLOAD.value if file_name else ResumeSource.MANUAL.value,
        file_name=file_name,
        raw_text_enc=box.encrypt(text, f"resume:{user.id}"),
        contacts_enc=box.encrypt(
            json.dumps({"emails": contacts.emails, "phones": contacts.phones}), f"contacts:{user.id}"
        ),
        profile=profile.model_dump(),
        quality=assess_quality(profile),
        is_primary=not has_primary,
        version=1,
    )
    db.add(resume)
    await db.flush()
    await audit(
        db,
        user_id=user.id,
        action="resume.created",
        entity_type="resume",
        entity_id=resume.id,
        details={"ai_enrichment": used_ai, "skills": len(profile.skills)},
    )
    return resume


@router.get("")
async def list_resumes(db: DB, user: CurrentUser, include_archived: bool = False) -> list[dict]:
    stmt = select(Resume).where(Resume.user_id == user.id).order_by(Resume.created_at.desc())
    if not include_archived:
        stmt = stmt.where(Resume.archived_at.is_(None))
    return [resume_out(r) for r in (await db.execute(stmt)).scalars()]


@router.post("/upload", status_code=201)
async def upload(
    db: DB, user: CurrentUser, file: UploadFile = File(...), title: str = Form(""), use_ai: bool = Form(False)
) -> dict:
    limit = get_settings().upload_max_bytes
    data = await file.read(limit + 1)
    if len(data) > limit:
        raise AppError(f"Файл больше {limit // (1024 * 1024)} МБ", code="file_too_large")
    text = extract_text(file.filename or "resume.txt", data)
    resume = await _create_from_text(
        db,
        user,
        title=title or (file.filename or "Резюме").rsplit(".", 1)[0],
        text=text,
        file_name=file.filename,
        use_ai=use_ai,
    )
    return resume_out(resume, full=True)


@router.post("/text", status_code=201)
async def from_text(body: ResumeTextIn, db: DB, user: CurrentUser, use_ai: bool = False) -> dict:
    resume = await _create_from_text(db, user, title=body.title, text=body.text, file_name=None, use_ai=use_ai)
    return resume_out(resume, full=True)


@router.get("/{resume_id}")
async def get_resume(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    resume = await get_owned(db, Resume, resume_id, user)
    data = resume_out(resume, full=True)
    data["visibility"] = await visibility_status(db, user, resume)
    return data


@router.get("/{resume_id}/versions")
async def versions(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> list[dict]:
    resume = await get_owned(db, Resume, resume_id, user)
    chain = [resume]
    while chain[-1].parent_id:
        parent = await db.get(Resume, chain[-1].parent_id)
        if parent is None or parent.user_id != user.id:
            break
        chain.append(parent)
    return [resume_out(r) for r in chain]


@router.put("/{resume_id}/profile")
async def update_profile(resume_id: uuid.UUID, body: ResumeProfilePatch, db: DB, user: CurrentUser) -> dict:
    """Editing creates a new version; the previous one is archived and kept for history."""
    old = await get_owned(db, Resume, resume_id, user)
    profile = body.profile
    if body.confirm_all:
        for group in (profile.skills, profile.experience, profile.education, profile.projects, profile.certificates):
            for item in group:
                item.confirmed = True
        profile.assumptions = []
    new = Resume(
        id=uuid.uuid4(),
        user_id=user.id,
        parent_id=old.id,
        version=old.version + 1,
        title=body.title or old.title,
        source=old.source,
        file_name=old.file_name,
        raw_text_enc=old.raw_text_enc,
        contacts_enc=old.contacts_enc,
        profile=profile.model_dump(),
        profile_confirmed=body.confirm_all or old.profile_confirmed,
        quality=assess_quality(profile),
        is_primary=old.is_primary,
        hh_resume_id=old.hh_resume_id,
        hh_status=old.hh_status,
        hh_can_publish=old.hh_can_publish,
        hh_next_publish_at=old.hh_next_publish_at,
        hh_last_published_at=old.hh_last_published_at,
    )
    old.archived_at = utcnow()
    old.is_primary = False
    db.add(new)
    await db.flush()
    # Keep references pointing to the live version.
    await db.execute(update(SearchProfile).where(SearchProfile.resume_id == old.id).values(resume_id=new.id))
    policy = (
        await db.execute(select(AutomationPolicy).where(AutomationPolicy.user_id == user.id))
    ).scalar_one_or_none()
    if policy and str(old.id) in {str(x) for x in policy.allowed_resume_ids}:
        policy.allowed_resume_ids = [
            str(new.id) if str(x) == str(old.id) else str(x) for x in policy.allowed_resume_ids
        ]
        policy.confirmed_rules_hash = None  # rules changed: Auto-Apply needs reconfirmation
    await audit(
        db,
        user_id=user.id,
        action="resume.version_created",
        entity_type="resume",
        entity_id=new.id,
        details={"parent": str(old.id), "confirmed": body.confirm_all},
    )
    return resume_out(new, full=True)


@router.post("/{resume_id}/primary")
async def make_primary(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    resume = await get_owned(db, Resume, resume_id, user)
    await db.execute(update(Resume).where(Resume.user_id == user.id).values(is_primary=False))
    resume.is_primary = True
    return resume_out(resume)


@router.post("/{resume_id}/link-hh")
async def link_hh(resume_id: uuid.UUID, body: ResumeLinkHh, db: DB, user: CurrentUser) -> dict:
    """Associate with a resume on hh.ru (id from its URL). Needed for API applies and reminders."""
    resume = await get_owned(db, Resume, resume_id, user)
    resume.hh_resume_id = body.hh_resume_id
    return resume_out(resume)


@router.delete("/{resume_id}", status_code=204)
async def archive(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    resume = await get_owned(db, Resume, resume_id, user)
    resume.archived_at = utcnow()
    resume.is_primary = False
    await audit(db, user_id=user.id, action="resume.archived", entity_type="resume", entity_id=resume.id)


@router.get("/{resume_id}/visibility")
async def visibility(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    return await visibility_status(db, user, await get_owned(db, Resume, resume_id, user))


@router.post("/{resume_id}/visibility/publish")
async def publish(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    resume = await get_owned(db, Resume, resume_id, user)
    return await publish_resume(db, user, resume, HhGateway(db, user.id), actor="user")


@router.post("/{resume_id}/visibility/mark-manual")
async def mark_manual(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    resume = await get_owned(db, Resume, resume_id, user)
    await mark_published_manually(db, user, resume)
    await db.flush()
    return await visibility_status(db, user, resume)


@router.get("/{resume_id}/profile-schema")
async def profile_schema(resume_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    await get_owned(db, Resume, resume_id, user)
    return CandidateProfile.model_json_schema()
