"""Application pipeline with idempotent, write-ahead sending.

Guarantees:
* One application per (user, vacancy): a unique constraint, not a convention.
* Before calling hh.ru the row is committed as ``sending``. A crash or timeout after that point leaves
  ``sending``/``unknown``, which is reconciled against hh.ru (or the user) and never blindly re-sent.
* Auto-Apply sends only when every user-confirmed rule holds and hh.ru has verified the operation.
"""

import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import (
    Application,
    AutomationPolicy,
    CoverLetter,
    Resume,
    SearchProfile,
    User,
    Vacancy,
    VacancyMatch,
)
from app.models.enums import ApplicationStatus as S
from app.models.enums import AutomationMode, Capability, CapabilityStatus, MatchDecision
from app.schemas.profile import CandidateProfile
from app.services.ai.embeddings import similarity
from app.services.ai.service import AIService
from app.services.applications.state import can_transition, transition
from app.services.audit import audit
from app.services.automation.policy import (
    HARD_DAILY_CAP,
    auto_apply_active,
    get_policy,
    in_apply_window,
    pause_automation,
    sent_today,
)
from app.services.cover_letters.generator import generate_letter, issues_payload, validate_letter
from app.services.hhru.capabilities import capability_map, is_verified, set_capability
from app.services.hhru.errors import (
    HhAmbiguousResult,
    HhApiError,
    HhAuthError,
    HhCaptchaRequired,
    HhCircuitOpen,
    HhForbidden,
    HhNotConfigured,
)
from app.services.hhru.gateway import HhGateway
from app.services.matching.scoring import employer_excluded, offered_salary
from app.services.notifications.service import notify

log = logging.getLogger(__name__)

STALE_SENDING_AFTER = timedelta(minutes=10)
POSITION_MATCH_THRESHOLD = 0.45


def idempotency_key(user_id: uuid.UUID, vacancy_id: uuid.UUID) -> str:
    return hashlib.sha256(f"apply:{user_id}:{vacancy_id}".encode()).hexdigest()


@dataclass(slots=True)
class SendOutcome:
    status: str
    detail: str = ""


async def _lock_app(db: AsyncSession, app_id: uuid.UUID) -> Application:
    return (await db.execute(select(Application).where(Application.id == app_id).with_for_update())).scalar_one()


async def prepare_application(
    db: AsyncSession,
    user: User,
    match: VacancyMatch,
    *,
    target: S,
    ai: AIService | None = None,
    actor: str = "system",
) -> Application:
    """Create the application (or return the existing one) and generate its cover letter."""
    existing = (
        await db.execute(
            select(Application).where(Application.user_id == user.id, Application.vacancy_id == match.vacancy_id)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    vacancy = await db.get(Vacancy, match.vacancy_id)
    resume = await db.get(Resume, match.resume_id) if match.resume_id else None
    search = await db.get(SearchProfile, match.search_profile_id) if match.search_profile_id else None
    app = Application(
        id=uuid.uuid4(),
        user_id=user.id,
        vacancy_id=match.vacancy_id,
        match_id=match.id,
        search_profile_id=match.search_profile_id,
        resume_id=match.resume_id,
        status=S.MATCHED.value,
        idempotency_key=idempotency_key(user.id, match.vacancy_id),
        status_changed_at=utcnow(),
    )
    db.add(app)
    await db.flush()
    letter_mode = search.letter_mode if search else "always"
    needs_letter = letter_mode == "always" or (letter_mode == "when_required" and vacancy.response_letter_required)
    if vacancy.response_letter_required:
        needs_letter = True
    if needs_letter and resume is not None:
        profile = CandidateProfile.model_validate(resume.profile)
        result = await generate_letter(
            vacancy,
            profile,
            template=search.letter_template if search else "junior_developer",
            tone=search.letter_tone if search else "neutral",
            length=search.letter_length if search else "short",
            ai=ai,
            user=user,
        )
        letter = CoverLetter(
            id=uuid.uuid4(),
            user_id=user.id,
            vacancy_id=vacancy.id,
            resume_id=resume.id,
            template_kind=search.letter_template if search else "junior_developer",
            tone=search.letter_tone if search else "neutral",
            length=search.letter_length if search else "short",
            text=result.text,
            generator=result.generator,
            validation=issues_payload(result.issues),
        )
        db.add(letter)
        await db.flush()
        app.cover_letter_id = letter.id
    await transition(db, app, target, actor=actor, note="подготовлен отклик")
    return app


async def auto_rule_violations(
    db: AsyncSession,
    user: User,
    policy: AutomationPolicy,
    app: Application,
    vacancy: Vacancy,
    match: VacancyMatch | None,
) -> list[str]:
    """Every user-confirmed Auto-Apply rule, checked right before sending."""
    problems: list[str] = []
    if not auto_apply_active(policy):
        problems.append("автоотклики выключены, на паузе или правила изменены без подтверждения")
    if str(app.resume_id) not in {str(x) for x in policy.allowed_resume_ids}:
        problems.append("резюме не разрешено для автооткликов")
    if not any(
        p.lower() in vacancy.title.lower() or similarity(vacancy.title, p) >= POSITION_MATCH_THRESHOLD
        for p in policy.allowed_positions
    ):
        problems.append("должность не входит в разрешённые")
    if match is None or match.score is None or match.score < policy.min_score:
        problems.append("score ниже порога автооткликов")
    if match is not None and match.effective_decision not in (MatchDecision.ELIGIBLE, MatchDecision.READY_TO_APPLY):
        problems.append("вакансия не помечена как подходящая")
    if policy.salary_min:
        offer = offered_salary(vacancy)
        if offer is not None and offer < policy.salary_min:
            problems.append("зарплата ниже минимума автооткликов")
    if policy.employment_types and vacancy.employment_type and vacancy.employment_type not in policy.employment_types:
        problems.append("тип занятости не разрешён")
    if employer_excluded(vacancy, list(policy.excluded_employers or [])):
        problems.append("работодатель в списке исключений")
    if not in_apply_window(policy, user.timezone):
        problems.append("сейчас вне окна отправки")
    limit = min(policy.daily_limit, HARD_DAILY_CAP)
    if await sent_today(db, user) >= limit:
        problems.append("достигнут дневной лимит откликов")
    if app.search_profile_id:
        search = await db.get(SearchProfile, app.search_profile_id)
        if search and await sent_today(db, user, search_profile_id=search.id) >= search.daily_apply_limit:
            problems.append(f"достигнут лимит профиля «{search.name}»")
    return problems


async def platform_blockers(
    db: AsyncSession, user: User, app: Application, vacancy: Vacancy, *, require_verified: bool
) -> list[str]:
    problems: list[str] = []
    caps = await capability_map(db, user.id)
    apply_status = caps[Capability.APPLY]["status"]
    if apply_status == CapabilityStatus.UNAVAILABLE or (require_verified and apply_status != CapabilityStatus.VERIFIED):
        problems.append("отклик через API hh.ru недоступен для этого аккаунта")
    if not vacancy.hh_id:
        problems.append("вакансия добавлена вручную: отклик только на сайте hh.ru")
    if vacancy.has_test:
        problems.append("работодатель требует тест: отклик только на сайте hh.ru")
    if vacancy.archived:
        problems.append("вакансия в архиве")
    resume = await db.get(Resume, app.resume_id) if app.resume_id else None
    if resume is None or not resume.hh_resume_id:
        problems.append("резюме не связано с резюме на hh.ru")
    letter = await db.get(CoverLetter, app.cover_letter_id) if app.cover_letter_id else None
    if vacancy.response_letter_required and letter is None:
        problems.append("работодатель требует сопроводительное письмо")
    if letter is not None and resume is not None:
        issues = validate_letter(letter.text, CandidateProfile.model_validate(resume.profile), vacancy)
        if any(i.severity == "error" for i in issues):
            problems.append("письмо не прошло проверку фактов")
    return problems


async def reconcile(db: AsyncSession, user: User, app: Application, gateway: HhGateway) -> str:
    """Resolve ``sending``/``unknown`` by asking hh.ru. Without read access the user must confirm."""
    vacancy = await db.get(Vacancy, app.vacancy_id)
    if not await is_verified(db, user.id, Capability.NEGOTIATIONS_READ) or not vacancy.hh_id:
        if app.status == S.SENDING:
            await transition(db, app, S.UNKNOWN, actor="system", note="результат отправки неизвестен")
        await notify(
            db,
            user.id,
            kind="manual_action",
            title="Проверьте отклик на hh.ru",
            body=f"Не удалось подтвердить отклик на «{vacancy.title}». Проверьте на hh.ru и отметьте статус.",
            payload={"application_id": str(app.id)},
            dedupe_key=f"reconcile:{app.id}",
        )
        return app.status
    try:
        client = await gateway.user_client()
        async with client:
            data = await client.negotiations(vacancy_id=vacancy.hh_id, per_page=20)
    except HhApiError as exc:
        await gateway.record_failure(exc)
        if app.status == S.SENDING:
            await transition(db, app, S.UNKNOWN, actor="system", note=f"сверка не удалась: {exc.tag}")
        return app.status
    resume = await db.get(Resume, app.resume_id) if app.resume_id else None
    for item in data.get("items") or []:
        same_vacancy = str((item.get("vacancy") or {}).get("id")) == vacancy.hh_id
        same_resume = resume is None or str((item.get("resume") or {}).get("id")) == resume.hh_resume_id
        if same_vacancy and same_resume:
            app.hh_negotiation_id = str(item.get("id"))
            app.confirmed_by = "platform"
            app.channel = "api"
            await transition(db, app, S.SENT, actor="platform", note="отклик найден на hh.ru при сверке")
            return app.status
    # hh.ru has no such negotiation: the earlier attempt did not go through, it is safe to retry.
    await transition(db, app, S.READY, actor="system", note="при сверке отклик на hh.ru не найден")
    return app.status


async def send_application(
    db: AsyncSession, user: User, app_id: uuid.UUID, gateway: HhGateway, *, actor: str
) -> SendOutcome:
    """Send through the official API. ``actor='user'`` means the user explicitly confirmed this send."""
    app = await _lock_app(db, app_id)
    if app.status in (S.SENT, S.VIEWED, S.INVITATION, S.REJECTED, S.ARCHIVED):
        return SendOutcome(app.status, "отклик уже отправлен")
    if app.status in (S.SENDING, S.UNKNOWN):
        stale = app.last_attempt_at is None or utcnow() - app.last_attempt_at > STALE_SENDING_AFTER
        if app.status == S.SENDING and not stale:
            return SendOutcome(app.status, "отправка уже выполняется")
        status = await reconcile(db, user, app, gateway)
        if status != S.READY:
            return SendOutcome(status, "статус сверен с hh.ru")
    vacancy = await db.get(Vacancy, app.vacancy_id)
    match = await db.get(VacancyMatch, app.match_id) if app.match_id else None
    policy = await get_policy(db, user.id)

    user_confirmed = actor in ("user", "telegram")
    if policy.paused and not user_confirmed:
        return SendOutcome(app.status, "автоматизация на паузе")
    blockers = await platform_blockers(db, user, app, vacancy, require_verified=not user_confirmed)
    if not user_confirmed:
        blockers += await auto_rule_violations(db, user, policy, app, vacancy, match)
    if blockers:
        if app.status == S.READY and not user_confirmed:
            await transition(db, app, S.AWAITING_CONFIRMATION, actor="system", note="; ".join(blockers))
        return SendOutcome("blocked", "; ".join(blockers))

    if app.status != S.READY:
        await transition(db, app, S.READY, actor=actor, note="подтверждено к отправке")
    resume = await db.get(Resume, app.resume_id)
    letter = await db.get(CoverLetter, app.cover_letter_id) if app.cover_letter_id else None

    # Write-ahead: persist "sending" before the request can reach hh.ru.
    await transition(db, app, S.SENDING, actor=actor)
    app.attempts += 1
    app.last_attempt_at = utcnow()
    await db.commit()

    try:
        client = await gateway.user_client()
        async with client:
            response = await client.apply(
                vacancy_id=vacancy.hh_id, resume_id=resume.hh_resume_id, message=letter.text if letter else None
            )
    except HhAmbiguousResult as exc:
        app = await _lock_app(db, app_id)
        app.last_error = str(exc)[:500]
        await transition(db, app, S.UNKNOWN, actor="system", note="нет ответа hh.ru после отправки")
        await audit(
            db,
            user_id=user.id,
            action="application.unknown",
            actor="system",
            entity_type="application",
            entity_id=app.id,
        )
        return SendOutcome(S.UNKNOWN, "результат неизвестен, будет сверен перед повтором")
    except HhApiError as exc:
        app = await _lock_app(db, app_id)
        return await _handle_send_error(db, user, app, gateway, exc)

    app = await _lock_app(db, app_id)
    app.channel = "api"
    app.confirmed_by = "platform"
    app.last_error = None
    location = response.get("_location") if isinstance(response, dict) else None
    if location:
        app.hh_negotiation_id = location.rstrip("/").rsplit("/", 1)[-1]
    app.platform_response = {"status": response.get("_status") if isinstance(response, dict) else None}
    await transition(db, app, S.SENT, actor="platform", note="hh.ru подтвердил отклик")
    if match is not None:
        match = await db.get(VacancyMatch, match.id)
        match.decision = MatchDecision.APPLIED.value
    await set_capability(db, user.id, Capability.APPLY, CapabilityStatus.VERIFIED, "подтверждено успешным откликом")
    await gateway.record_success()
    await audit(
        db, user_id=user.id, action="application.sent", actor=actor, entity_type="application", entity_id=app.id
    )
    return SendOutcome(S.SENT)


async def _handle_send_error(
    db: AsyncSession, user: User, app: Application, gateway: HhGateway, exc: HhApiError
) -> SendOutcome:
    app.last_error = exc.tag[:500]
    value = exc.error_value or ""
    if value == "already_applied":
        app.confirmed_by = "platform"
        app.channel = "api"
        await transition(db, app, S.SENT, actor="platform", note="hh.ru: отклик на эту вакансию уже был")
        return SendOutcome(S.SENT, "отклик уже существовал")
    if value in (
        "test_required",
        "resume_visibility_conflict",
        "invalid_vacancy",
        "resume_not_found",
        "vacancy_not_found",
    ):
        await transition(db, app, S.FAILED, actor="platform", note=f"hh.ru отклонил отклик: {value}")
        await notify(
            db,
            user.id,
            kind="application_failed",
            title="Отклик не отправлен",
            body=f"hh.ru отклонил отклик ({value}). Можно откликнуться вручную на сайте.",
            payload={"application_id": str(app.id)},
            dedupe_key=f"failed:{app.id}",
        )
        return SendOutcome(S.FAILED, value)
    if value == "limit_exceeded":
        await transition(db, app, S.READY, actor="system", note="лимит откликов hh.ru")
        await pause_automation(
            db, user.id, "hh.ru сообщил о превышении лимита откликов. Автоотклики на паузе до завтра."
        )
        return SendOutcome(S.READY, "лимит hh.ru")
    if isinstance(exc, HhCaptchaRequired):
        await transition(db, app, S.READY, actor="system", note="hh.ru запросил капчу")
        await gateway.record_failure(exc)
        await pause_automation(db, user.id, "hh.ru запросил прохождение капчи. Выполните действие на сайте hh.ru.")
        return SendOutcome(S.READY, "captcha")
    if isinstance(exc, HhAuthError | HhNotConfigured | HhCircuitOpen):
        await transition(db, app, S.READY, actor="system", note=exc.tag)
        await gateway.record_failure(exc)
        return SendOutcome(S.READY, exc.tag)
    if isinstance(exc, HhForbidden):
        # The applicant API may be closed for this application: record it, fall back to manual.
        await set_capability(db, user.id, Capability.APPLY, CapabilityStatus.UNAVAILABLE, f"hh.ru: {exc.tag}")
        await transition(
            db, app, S.AWAITING_CONFIRMATION, actor="system", note="отклик через API запрещён, отправьте вручную"
        )
        return SendOutcome(S.AWAITING_CONFIRMATION, exc.tag)
    # Connect errors: the request never reached hh.ru.
    await transition(db, app, S.READY, actor="system", note=f"временная ошибка: {exc.tag}")
    await gateway.record_failure(exc)
    await _check_failure_streak(db, user)
    return SendOutcome(S.READY, exc.tag)


async def _check_failure_streak(db: AsyncSession, user: User) -> None:
    policy = await get_policy(db, user.id)
    limit = int((policy.stop_conditions or {}).get("max_consecutive_failures", 3))
    recent = (
        (
            await db.execute(
                select(Application.last_error)
                .where(Application.user_id == user.id, Application.last_attempt_at.isnot(None))
                .order_by(Application.last_attempt_at.desc())
                .limit(limit)
            )
        )
        .scalars()
        .all()
    )
    if len(recent) >= limit and all(recent):
        await pause_automation(db, user.id, f"{limit} ошибок отправки подряд. Проверьте подключение hh.ru.")


async def mark_sent_manually(db: AsyncSession, user: User, app: Application, *, actor: str = "user") -> None:
    """The user applied on hh.ru themselves. Stored as user-confirmed, not platform-confirmed."""
    app.channel = "manual"
    app.confirmed_by = "user"
    await transition(db, app, S.SENT, actor=actor, note="пользователь отметил отклик отправленным на hh.ru")
    if app.match_id:
        match = await db.get(VacancyMatch, app.match_id)
        if match:
            match.decision = MatchDecision.APPLIED.value


async def process_queue(db: AsyncSession, user: User, gateway: HhGateway, ai: AIService | None = None) -> dict:
    """One pass of the pipeline for a user, honouring the automation mode."""
    policy = await get_policy(db, user.id)
    stats = {"prepared": 0, "sent": 0, "blocked": 0, "unknown": 0, "mode": policy.mode, "paused": policy.paused}
    if policy.paused or policy.mode == AutomationMode.MANUAL:
        return stats

    target = S.READY if auto_apply_active(policy) else S.AWAITING_CONFIRMATION
    min_score = policy.min_score if target == S.READY else 0
    matches = (
        (
            await db.execute(
                select(VacancyMatch)
                .outerjoin(
                    Application,
                    (Application.user_id == VacancyMatch.user_id) & (Application.vacancy_id == VacancyMatch.vacancy_id),
                )
                .where(
                    VacancyMatch.user_id == user.id,
                    VacancyMatch.hidden.is_(False),
                    Application.id.is_(None),
                    VacancyMatch.decision.in_([MatchDecision.ELIGIBLE.value, MatchDecision.READY_TO_APPLY.value]),
                    VacancyMatch.score >= min_score,
                )
                .order_by(VacancyMatch.score.desc())
                .limit(min(policy.daily_limit, HARD_DAILY_CAP) * 2)
            )
        )
        .scalars()
        .all()
    )
    for match in matches:
        if match.user_decision and match.user_decision == MatchDecision.REJECT:
            continue
        await prepare_application(db, user, match, target=target, ai=ai)
        if target == S.READY:
            match.decision = MatchDecision.READY_TO_APPLY.value
        stats["prepared"] += 1
    if stats["prepared"] and target == S.AWAITING_CONFIRMATION:
        await notify(
            db,
            user.id,
            kind="awaiting_confirmation",
            title=f"Ждут подтверждения: {stats['prepared']}",
            body="Письма подготовлены. Проверьте и подтвердите отклики.",
            dedupe_key=f"awaiting:{utcnow().isoformat(timespec='hours')}",
        )
    await db.commit()

    if target != S.READY:
        return stats
    ready_ids = (
        (
            await db.execute(
                select(Application.id)
                .where(Application.user_id == user.id, Application.status.in_([S.READY.value, S.UNKNOWN.value]))
                .order_by(Application.created_at)
                .limit(min(policy.daily_limit, HARD_DAILY_CAP))
            )
        )
        .scalars()
        .all()
    )
    for app_id in ready_ids:
        outcome = await send_application(db, user, app_id, gateway, actor="system")
        await db.commit()
        if outcome.status == S.SENT:
            stats["sent"] += 1
        elif outcome.status == S.UNKNOWN:
            stats["unknown"] += 1
        else:
            stats["blocked"] += 1
        policy = await get_policy(db, user.id)
        if policy.paused or "лимит" in outcome.detail:
            break
    return stats


HH_STATE_MAP = {"response": S.SENT, "invitation": S.INVITATION, "discard": S.REJECTED, "hidden": S.ARCHIVED}


async def sync_statuses(db: AsyncSession, user: User, gateway: HhGateway) -> dict:
    """Pull real statuses from hh.ru. Nothing is updated without a platform answer."""
    stats = {"checked": 0, "updated": 0, "status": "ok"}
    if not await is_verified(db, user.id, Capability.NEGOTIATIONS_READ):
        stats["status"] = "unavailable"
        return stats
    apps = (
        await db.execute(
            select(Application, Vacancy)
            .join(Vacancy, Vacancy.id == Application.vacancy_id)
            .where(
                Application.user_id == user.id,
                Vacancy.hh_id.isnot(None),
                Application.status.in_([S.SENT.value, S.VIEWED.value, S.INVITATION.value, S.UNKNOWN.value]),
            )
        )
    ).all()
    by_hh = {vacancy.hh_id: app for app, vacancy in apps}
    if not by_hh:
        return stats
    try:
        client = await gateway.user_client()
        async with client:
            page, pages = 0, 1
            while page < min(pages, 10):
                data = await client.negotiations(page=page, per_page=100)
                pages = int(data.get("pages") or 1)
                for item in data.get("items") or []:
                    hh_vacancy_id = str((item.get("vacancy") or {}).get("id"))
                    app = by_hh.get(hh_vacancy_id)
                    if app is None:
                        continue
                    stats["checked"] += 1
                    state = (item.get("state") or {}).get("id")
                    target = HH_STATE_MAP.get(state)
                    if target == S.SENT and item.get("viewed_by_opponent"):
                        target = S.VIEWED
                    if app.status == S.UNKNOWN and target is not None:
                        app.confirmed_by = "platform"
                        await transition(db, app, S.SENT, actor="platform", note="подтверждено синхронизацией")
                    if target is None or target == app.status or target == S.SENT:
                        continue
                    if can_transition(app.status, target):
                        await transition(db, app, target, actor="platform", note=f"hh.ru: {state}")
                        stats["updated"] += 1
                        if target == S.INVITATION:
                            vacancy = await db.get(Vacancy, app.vacancy_id)
                            await notify(
                                db,
                                user.id,
                                kind="invitation",
                                title="Приглашение от работодателя",
                                body=f"{vacancy.employer_name}: «{vacancy.title}»",
                                payload={"application_id": str(app.id), "url": vacancy.url},
                                dedupe_key=f"invitation:{app.id}",
                            )
                page += 1
        await gateway.record_success()
    except HhApiError as exc:
        await gateway.record_failure(exc)
        stats["status"] = f"error: {exc.tag}"
    return stats
