import json
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.serializers import (
    application_out,
    notification_out,
    policy_out,
    resume_out,
    search_profile_out,
    user_out,
    vacancy_out,
)
from app.core.config import get_settings
from app.core.crypto import get_box
from app.core.errors import AppError, Unauthorized
from app.db.base import utcnow
from app.models import (
    Application,
    ApplicationEvent,
    AuditLog,
    CoverLetter,
    Notification,
    Resume,
    SearchProfile,
    TelegramLink,
    Vacancy,
    VacancyMatch,
)
from app.schemas.api import DeleteAccountIn, SettingsPatch
from app.security.deps import DB, CurrentUser
from app.security.passwords import verify_password
from app.security.sessions import destroy_session
from app.services.audit import audit
from app.services.automation.policy import get_policy

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
async def get_user_settings(db: DB, user: CurrentUser) -> dict:
    settings = get_settings()
    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user.id))).scalar_one_or_none()
    return {
        "user": user_out(user),
        "telegram": {
            "configured": settings.telegram_configured,
            "bot_username": settings.telegram_bot_username or None,
            "linked": link is not None,
            "username": link.username if link else None,
            "notifications_enabled": link.notifications_enabled if link else False,
        },
        "ai": {
            "provider": settings.ai_provider,
            "external": settings.ai_provider != "local",
            "consent": user.ai_external_consent_at is not None,
            "consent_at": user.ai_external_consent_at,
        },
        "pd_consent_at": user.pd_consent_at,
    }


@router.patch("")
async def patch_settings(body: SettingsPatch, db: DB, user: CurrentUser) -> dict:
    if body.display_name is not None:
        user.display_name = body.display_name
    if body.timezone is not None:
        try:
            ZoneInfo(body.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise AppError("Неизвестный часовой пояс", code="bad_timezone") from exc
        user.timezone = body.timezone
    if body.ai_external_consent is not None:
        # Consent to send personal data to an external AI provider is separate and revocable (152-ФЗ).
        user.ai_external_consent_at = utcnow() if body.ai_external_consent else None
        await audit(db, user_id=user.id, action="consent.ai_external", details={"granted": body.ai_external_consent})
    merged = dict(user.settings or {})
    if body.notifications is not None:
        merged["notifications"] = {**merged.get("notifications", {}), **body.notifications}
    if body.visibility is not None:
        merged["visibility"] = {**merged.get("visibility", {}), **body.visibility}
    user.settings = merged
    return await get_user_settings(db, user)


@router.get("/export")
async def export_data(db: DB, user: CurrentUser) -> Response:
    """Everything stored about the user, decrypted, as one JSON file (right of access, 152-ФЗ ст. 14)."""
    box = get_box()
    resumes = []
    for r in (await db.execute(select(Resume).where(Resume.user_id == user.id))).scalars():
        item = resume_out(r, full=True)
        item["raw_text"] = box.decrypt(r.raw_text_enc, f"resume:{user.id}") if r.raw_text_enc else None
        item["contacts"] = json.loads(box.decrypt(r.contacts_enc, f"contacts:{user.id}")) if r.contacts_enc else None
        resumes.append(item)
    apps = []
    for a, v, c in (
        await db.execute(
            select(Application, Vacancy, CoverLetter)
            .join(Vacancy, Vacancy.id == Application.vacancy_id)
            .outerjoin(CoverLetter, CoverLetter.id == Application.cover_letter_id)
            .where(Application.user_id == user.id)
        )
    ).all():
        item = application_out(a, v, c)
        events = (await db.execute(select(ApplicationEvent).where(ApplicationEvent.application_id == a.id))).scalars()
        item["events"] = [
            {"from": e.from_status, "to": e.to_status, "actor": e.actor, "note": e.note, "at": e.created_at}
            for e in events
        ]
        apps.append(item)
    matches = [
        {"vacancy": vacancy_out(v), "score": m.score, "decision": m.effective_decision, "analysis": m.analysis}
        for m, v in (await db.execute(
            select(VacancyMatch, Vacancy).join(Vacancy, Vacancy.id == VacancyMatch.vacancy_id).where(VacancyMatch.user_id == user.id)
        )).all()
    ]  # fmt: skip
    audit_rows = (
        await db.execute(select(AuditLog).where(AuditLog.user_id == user.id).order_by(AuditLog.created_at))
    ).scalars()
    payload = {
        "exported_at": utcnow(),
        "user": user_out(user) | {"pd_consent_at": user.pd_consent_at},
        "resumes": resumes,
        "search_profiles": [
            search_profile_out(p)
            for p in (await db.execute(select(SearchProfile).where(SearchProfile.user_id == user.id))).scalars()
        ],
        "matches": matches,
        "applications": apps,
        "automation_policy": policy_out(await get_policy(db, user.id)),
        "notifications": [
            notification_out(n)
            for n in (await db.execute(select(Notification).where(Notification.user_id == user.id))).scalars()
        ],
        "audit_log": [
            {"action": r.action, "actor": r.actor, "details": r.details, "at": r.created_at} for r in audit_rows
        ],
    }
    await audit(db, user_id=user.id, action="account.exported")
    body = json.dumps(payload, ensure_ascii=False, default=str, indent=2)
    return Response(
        body,
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="ashore-export.json"', "Cache-Control": "no-store"},
    )


@router.post("/delete-account", status_code=204)
async def delete_account(
    body: DeleteAccountIn, request: Request, response: Response, db: DB, user: CurrentUser
) -> Response:
    """Erases the account and everything tied to it (ON DELETE CASCADE), including hh.ru tokens."""
    if not verify_password(user.password_hash, body.password):
        raise Unauthorized("Неверный пароль", code="bad_credentials")
    await destroy_session(db, request, response)
    await db.delete(user)
    await audit(db, user_id=None, action="account.deleted", actor="user")
    response.status_code = 204
    return response
