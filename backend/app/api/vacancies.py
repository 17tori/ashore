import uuid
from typing import Literal

from fastapi import APIRouter, Query
from sqlalchemy import and_, func, or_, select

from app.api.serializers import application_out, match_out, search_profile_out
from app.core.config import get_settings
from app.core.errors import AppError, NotFound
from app.models import Application, CoverLetter, Resume, SearchProfile, Vacancy, VacancyMatch
from app.models.enums import ApplicationStatus as S
from app.models.enums import MatchDecision, VacancySource
from app.schemas.api import DecisionIn, SearchProfileIn, VacancyImportIn
from app.schemas.profile import CandidateProfile
from app.security.deps import DB, CurrentUser, get_owned
from app.services.ai.service import AIService
from app.services.applications.engine import prepare_application
from app.services.audit import audit
from app.services.automation.policy import get_policy
from app.services.hhru.errors import HhApiError
from app.services.hhru.gateway import HhGateway
from app.services.hhru.normalize import extract_hh_vacancy_id, normalize_hh_vacancy, normalize_manual
from app.services.matching.engine import analyze_and_store
from app.services.vacancies.discovery import search_client
from app.services.vacancies.ingest import upsert_vacancy

router = APIRouter(prefix="/api/vacancies", tags=["vacancies"])


async def default_search_profile(db, user) -> SearchProfile:
    profile = (
        await db.execute(
            select(SearchProfile)
            .where(SearchProfile.user_id == user.id)
            .order_by(SearchProfile.is_active.desc(), SearchProfile.created_at)
            .limit(1)
        )
    ).scalar_one_or_none()
    if profile is not None:
        return profile
    resume = (
        await db.execute(
            select(Resume)
            .where(Resume.user_id == user.id, Resume.archived_at.is_(None))
            .order_by(Resume.is_primary.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    positions: list[str] = []
    if resume is not None:
        positions = CandidateProfile.model_validate(resume.profile).desired_positions[:3]
    profile = SearchProfile(id=uuid.uuid4(), user_id=user.id, resume_id=resume.id if resume else None)
    for key, value in SearchProfileIn(name="Основной", positions=positions).model_dump().items():
        setattr(profile, key, value)
    profile.resume_id = resume.id if resume else None
    db.add(profile)
    await db.flush()
    return profile


@router.get("")
async def inbox(
    db: DB,
    user: CurrentUser,
    decision: list[str] = Query(default=[]),
    search_profile_id: uuid.UUID | None = None,
    q: str | None = Query(default=None, max_length=100),
    min_score: int | None = Query(default=None, ge=0, le=100),
    include_hidden: bool = False,
    sort: Literal["score", "date", "salary"] = "score",
    page: int = Query(default=0, ge=0),
    per_page: int = Query(default=30, ge=1, le=100),
) -> dict:
    effective = func.coalesce(VacancyMatch.user_decision, VacancyMatch.decision)
    conditions = [VacancyMatch.user_id == user.id]
    if decision:
        conditions.append(effective.in_(decision))
    if search_profile_id:
        conditions.append(VacancyMatch.search_profile_id == search_profile_id)
    if min_score is not None:
        conditions.append(VacancyMatch.score >= min_score)
    if not include_hidden:
        conditions.append(VacancyMatch.hidden.is_(False))
    if q:
        like = f"%{q.replace('%', '').replace('_', '')}%"
        conditions.append(or_(Vacancy.title.ilike(like), Vacancy.employer_name.ilike(like)))
    order = {
        "score": [VacancyMatch.score.desc().nulls_last(), VacancyMatch.discovered_at.desc()],
        "date": [func.coalesce(Vacancy.published_at, VacancyMatch.discovered_at).desc()],
        "salary": [func.coalesce(Vacancy.salary_to, Vacancy.salary_from).desc().nulls_last()],
    }[sort]
    base = (
        select(VacancyMatch, Vacancy, Application)
        .join(Vacancy, Vacancy.id == VacancyMatch.vacancy_id)
        .outerjoin(Application, and_(Application.user_id == user.id, Application.vacancy_id == Vacancy.id))
        .where(*conditions)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    rows = (await db.execute(base.order_by(*order).offset(page * per_page).limit(per_page))).all()
    counts = dict(
        (await db.execute(
            select(effective, func.count()).where(VacancyMatch.user_id == user.id, VacancyMatch.hidden.is_(False)).group_by(effective)
        )).all()
    )  # fmt: skip
    return {
        "items": [match_out(m, v, a) for m, v, a in rows],
        "total": total,
        "page": page,
        "per_page": per_page,
        "counts": counts,
    }


@router.post("/import", status_code=201)
async def import_vacancy(body: VacancyImportIn, db: DB, user: CurrentUser) -> dict:
    """Manual or bookmarklet import. If the official API can fetch the vacancy, it is used instead of the text."""
    profile = (
        await get_owned(db, SearchProfile, body.search_profile_id, user)
        if body.search_profile_id
        else await default_search_profile(db, user)
    )
    hh_id = extract_hh_vacancy_id(body.url) if body.url else None
    vacancy = None
    if hh_id:
        gateway = HhGateway(db, user.id)
        client = await search_client(db, user, gateway)
        if client is not None:
            try:
                async with client:
                    payload = await client.get_vacancy(hh_id)
                vacancy, _ = await upsert_vacancy(db, normalize_hh_vacancy(payload), source=VacancySource.HH_API)
            except HhApiError:
                vacancy = None
    if vacancy is None:
        if len(body.title.strip()) < 2 or len(body.description.strip()) < 50:
            raise AppError("Нужны название и текст вакансии (от 50 символов)", code="vacancy_text_required")
        nv = normalize_manual(
            title=body.title,
            description=body.description,
            url=body.url,
            employer_name=body.employer_name,
            salary_text=body.salary_text,
            area_name=body.area_name,
        )
        source = VacancySource.BOOKMARKLET if body.source == "bookmarklet" else VacancySource.MANUAL
        vacancy, _ = await upsert_vacancy(db, nv, source=source, owner_user_id=user.id)
    resumes = list(
        (await db.execute(select(Resume).where(Resume.user_id == user.id, Resume.archived_at.is_(None)))).scalars()
    )
    policy = await get_policy(db, user.id)
    match = await analyze_and_store(
        db, user, vacancy, profile, resumes, ai=AIService(db), extra_excluded=policy.excluded_employers, force=True
    )
    await audit(
        db,
        user_id=user.id,
        action="vacancy.imported",
        entity_type="vacancy",
        entity_id=vacancy.id,
        details={"source": vacancy.source},
    )
    return match_out(match, vacancy, full=True)


@router.get("/bookmarklet")
async def bookmarklet(user: CurrentUser) -> dict:
    base = get_settings().public_base_url
    # Runs on the vacancy page the user opened. Data goes into the URL fragment, which browsers do not
    # send to any server; the Ashore /clip page (same origin, logged in) reads it and asks to confirm.
    code = (
        "javascript:(()=>{const q=s=>document.querySelector(s);"
        "const t=(q('[data-qa=\"vacancy-title\"]')||q('h1')||{}).innerText||document.title;"
        "const e=(q('[data-qa=\"vacancy-company-name\"]')||{}).innerText||'';"
        "const s=(q('[data-qa=\"vacancy-salary\"]')||{}).innerText||'';"
        "const d=(q('[data-qa=\"vacancy-description\"]')||q('main')||document.body).innerText.slice(0,20000);"
        "const p={url:location.href.split('?')[0],title:t.trim(),employer_name:e.trim(),salary_text:s.trim(),description:d};"
        f"window.open('{base}/clip#'+encodeURIComponent(JSON.stringify(p)),'_blank');}})()"
    )
    return {"code": code}


async def _owned_match(db, user, match_id: uuid.UUID) -> tuple[VacancyMatch, Vacancy]:
    match = await get_owned(db, VacancyMatch, match_id, user)
    vacancy = await db.get(Vacancy, match.vacancy_id)
    if vacancy is None:
        raise NotFound("Вакансия не найдена")
    return match, vacancy


@router.get("/{match_id}")
async def get_match(match_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    match, vacancy = await _owned_match(db, user, match_id)
    app = (
        await db.execute(
            select(Application).where(Application.user_id == user.id, Application.vacancy_id == vacancy.id)
        )
    ).scalar_one_or_none()
    data = match_out(match, vacancy, app, full=True)
    if match.search_profile_id:
        sp = await db.get(SearchProfile, match.search_profile_id)
        data["search_profile"] = search_profile_out(sp) if sp else None
    return data


@router.post("/{match_id}/decision")
async def set_decision(match_id: uuid.UUID, body: DecisionIn, db: DB, user: CurrentUser) -> dict:
    match, vacancy = await _owned_match(db, user, match_id)
    match.user_decision = body.decision
    await audit(
        db,
        user_id=user.id,
        action="match.decision_overridden",
        entity_type="match",
        entity_id=match.id,
        details={"decision": body.decision, "ai_decision": match.decision},
    )
    return match_out(match, vacancy)


@router.post("/{match_id}/hide")
async def hide(match_id: uuid.UUID, db: DB, user: CurrentUser, hidden: bool = True) -> dict:
    match, vacancy = await _owned_match(db, user, match_id)
    match.hidden = hidden
    return match_out(match, vacancy)


@router.post("/{match_id}/exclude-employer")
async def exclude_employer(match_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    match, vacancy = await _owned_match(db, user, match_id)
    policy = await get_policy(db, user.id, for_update=True)
    ref = {"id": vacancy.employer_hh_id, "name": vacancy.employer_name}
    if ref not in policy.excluded_employers:
        policy.excluded_employers = [*policy.excluded_employers, ref]
    match.user_decision = MatchDecision.REJECT.value
    match.hidden = True
    await audit(db, user_id=user.id, action="employer.excluded", details=ref)
    return {"excluded_employers": policy.excluded_employers}


@router.post("/{match_id}/reanalyze")
async def reanalyze(match_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    match, vacancy = await _owned_match(db, user, match_id)
    profile = (
        await db.get(SearchProfile, match.search_profile_id)
        if match.search_profile_id
        else await default_search_profile(db, user)
    )
    resumes = list(
        (await db.execute(select(Resume).where(Resume.user_id == user.id, Resume.archived_at.is_(None)))).scalars()
    )
    policy = await get_policy(db, user.id)
    match = await analyze_and_store(
        db, user, vacancy, profile, resumes, ai=AIService(db), extra_excluded=policy.excluded_employers, force=True
    )
    return match_out(match, vacancy, full=True)


@router.post("/{match_id}/prepare", status_code=201)
async def prepare(match_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    match, vacancy = await _owned_match(db, user, match_id)
    if match.resume_id is None:
        raise AppError("Нет резюме для отклика: загрузите резюме", code="no_resume")
    app = await prepare_application(db, user, match, target=S.AWAITING_CONFIRMATION, ai=AIService(db), actor="user")
    letter = await db.get(CoverLetter, app.cover_letter_id) if app.cover_letter_id else None
    return application_out(app, vacancy, letter)
