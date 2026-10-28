import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from app.api.serializers import application_out
from app.core.errors import AppError
from app.models import Application, ApplicationEvent, CoverLetter, Resume, Vacancy, VacancyMatch
from app.models.enums import ApplicationStatus as S
from app.models.enums import MatchDecision
from app.schemas.api import ApplicationStatusIn, LetterPatch, NotesIn
from app.schemas.profile import CandidateProfile
from app.security.deps import DB, CurrentUser, get_owned
from app.services.ai.service import AIService
from app.services.applications.engine import mark_sent_manually, send_application
from app.services.applications.state import transition
from app.services.audit import audit
from app.services.cover_letters.generator import generate_letter, issues_payload, validate_letter
from app.services.hhru.gateway import HhGateway

router = APIRouter(prefix="/api/applications", tags=["applications"])

EDITABLE_STATUSES = {S.MATCHED, S.AWAITING_CONFIRMATION, S.READY, S.FAILED}


async def _load(db, user, app_id: uuid.UUID) -> tuple[Application, Vacancy, CoverLetter | None]:
    app = await get_owned(db, Application, app_id, user)
    vacancy = await db.get(Vacancy, app.vacancy_id)
    letter = await db.get(CoverLetter, app.cover_letter_id) if app.cover_letter_id else None
    return app, vacancy, letter


def _manual_payload(app: Application, vacancy: Vacancy, letter: CoverLetter | None, reason: str) -> dict:
    """Assisted fallback: the user applies on hh.ru with the prepared letter, then marks it sent."""
    return {
        "mode": "manual",
        "reason": reason,
        "apply_url": vacancy.apply_url or vacancy.url,
        "letter_text": letter.text if letter else "",
        "application": application_out(app, vacancy, letter),
    }


@router.get("")
async def list_applications(
    db: DB,
    user: CurrentUser,
    status: list[str] = Query(default=[]),
    page: int = Query(default=0, ge=0),
    per_page: int = Query(default=50, ge=1, le=200),
) -> dict:
    conditions = [Application.user_id == user.id]
    if status:
        conditions.append(Application.status.in_(status))
    stmt = (
        select(Application, Vacancy, CoverLetter)
        .join(Vacancy, Vacancy.id == Application.vacancy_id)
        .outerjoin(CoverLetter, CoverLetter.id == Application.cover_letter_id)
        .where(*conditions)
    )
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (
        await db.execute(
            stmt.order_by(Application.status_changed_at.desc().nulls_last()).offset(page * per_page).limit(per_page)
        )
    ).all()
    counts = dict(
        (
            await db.execute(
                select(Application.status, func.count())
                .where(Application.user_id == user.id)
                .group_by(Application.status)
            )
        ).all()
    )
    return {"items": [application_out(a, v, c) for a, v, c in rows], "total": total, "counts": counts}


@router.get("/{app_id}")
async def get_application(app_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    events = (
        await db.execute(
            select(ApplicationEvent)
            .where(ApplicationEvent.application_id == app.id)
            .order_by(ApplicationEvent.created_at)
        )
    ).scalars()
    data = application_out(app, vacancy, letter)
    data["events"] = [
        {"from": e.from_status, "to": e.to_status, "actor": e.actor, "note": e.note, "at": e.created_at} for e in events
    ]
    return data


@router.put("/{app_id}/letter")
async def update_letter(app_id: uuid.UUID, body: LetterPatch, db: DB, user: CurrentUser) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    if S(app.status) not in EDITABLE_STATUSES:
        raise AppError("Письмо можно менять только до отправки", code="letter_locked")
    resume = await db.get(Resume, app.resume_id) if app.resume_id else None
    issues = validate_letter(body.text, CandidateProfile.model_validate(resume.profile), vacancy) if resume else []
    validation = issues_payload(issues)
    if letter is None:
        letter = CoverLetter(
            id=uuid.uuid4(),
            user_id=user.id,
            vacancy_id=vacancy.id,
            resume_id=app.resume_id,
            template_kind="custom",
            tone="neutral",
            length="short",
            text=body.text,
            generator="user",
        )
        db.add(letter)
        await db.flush()
        app.cover_letter_id = letter.id
    letter.text = body.text
    letter.edited_by_user = True
    letter.validation = validation
    return application_out(app, vacancy, letter)


@router.post("/{app_id}/letter/regenerate")
async def regenerate_letter(app_id: uuid.UUID, db: DB, user: CurrentUser, use_ai: bool = False) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    if S(app.status) not in EDITABLE_STATUSES:
        raise AppError("Письмо можно менять только до отправки", code="letter_locked")
    resume = await db.get(Resume, app.resume_id) if app.resume_id else None
    if resume is None:
        raise AppError("Нет резюме для письма", code="no_resume")
    template = letter.template_kind if letter and letter.template_kind != "custom" else "junior_developer"
    tone = letter.tone if letter else "neutral"
    length = letter.length if letter else "short"
    result = await generate_letter(
        vacancy,
        CandidateProfile.model_validate(resume.profile),
        template=template,
        tone=tone,
        length=length,
        ai=AIService(db) if use_ai else None,
        user=user,
    )
    if letter is None:
        letter = CoverLetter(
            id=uuid.uuid4(),
            user_id=user.id,
            vacancy_id=vacancy.id,
            resume_id=resume.id,
            template_kind=template,
            tone=tone,
            length=length,
            text="",
        )
        db.add(letter)
        await db.flush()
        app.cover_letter_id = letter.id
    letter.text = result.text
    letter.generator = result.generator
    letter.edited_by_user = False
    letter.validation = issues_payload(result.issues)
    return application_out(app, vacancy, letter)


@router.post("/{app_id}/approve")
async def approve(app_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """User confirms this application. Uses the official API when it works, otherwise hands off to hh.ru."""
    app, vacancy, letter = await _load(db, user, app_id)
    if letter is not None and (letter.validation or {}).get("blocking"):
        raise AppError("Письмо не прошло проверку фактов: исправьте его перед отправкой", code="letter_invalid")
    await audit(db, user_id=user.id, action="application.approved", entity_type="application", entity_id=app.id)
    outcome = await send_application(db, user, app.id, HhGateway(db, user.id), actor="user")
    app, vacancy, letter = await _load(db, user, app_id)
    if outcome.status in (S.SENT, S.SENDING, S.UNKNOWN):
        return {
            "mode": "api",
            "status": outcome.status,
            "detail": outcome.detail,
            "application": application_out(app, vacancy, letter),
        }
    if S(app.status) in (S.MATCHED, S.READY):
        await transition(db, app, S.AWAITING_CONFIRMATION, actor="user", note="отклик через сайт hh.ru")
    return _manual_payload(app, vacancy, letter, outcome.detail)


@router.post("/{app_id}/mark-sent")
async def mark_sent(app_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    if S(app.status) in (S.SENT, S.VIEWED, S.INVITATION, S.REJECTED):
        return application_out(app, vacancy, letter)
    await mark_sent_manually(db, user, app)
    await audit(db, user_id=user.id, action="application.marked_sent", entity_type="application", entity_id=app.id)
    return application_out(app, vacancy, letter)


@router.post("/{app_id}/not-sent")
async def mark_not_sent(app_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    """Resolves an UNKNOWN application after the user checked hh.ru and found nothing."""
    app, vacancy, letter = await _load(db, user, app_id)
    if S(app.status) not in (S.UNKNOWN, S.FAILED):
        raise AppError("Статус можно уточнить только для неизвестных или ошибочных откликов", code="bad_state")
    await transition(db, app, S.AWAITING_CONFIRMATION, actor="user", note="пользователь: отклика на hh.ru нет")
    return application_out(app, vacancy, letter)


@router.post("/{app_id}/status")
async def set_status(app_id: uuid.UUID, body: ApplicationStatusIn, db: DB, user: CurrentUser) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    await transition(db, app, S(body.status), actor="user", note=body.note or "изменено пользователем")
    return application_out(app, vacancy, letter)


@router.put("/{app_id}/notes")
async def set_notes(app_id: uuid.UUID, body: NotesIn, db: DB, user: CurrentUser) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    app.notes = body.notes
    return application_out(app, vacancy, letter)


@router.post("/{app_id}/skip")
async def skip(app_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    app, vacancy, letter = await _load(db, user, app_id)
    await transition(db, app, S.ARCHIVED, actor="user", note="пропущено")
    if app.match_id:
        match = await db.get(VacancyMatch, app.match_id)
        if match is not None:
            match.user_decision = MatchDecision.REJECT.value
    return application_out(app, vacancy, letter)
