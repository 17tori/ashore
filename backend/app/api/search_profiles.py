import uuid

from fastapi import APIRouter, Request
from sqlalchemy import select

from app.api.serializers import search_profile_out
from app.core.errors import AppError, Conflict, IntegrationUnavailable
from app.models import Resume, SearchProfile, Vacancy, VacancyMatch
from app.models.enums import MatchDecision
from app.schemas.api import SearchProfileIn
from app.security.deps import DB, CurrentUser, get_owned
from app.services.audit import audit
from app.services.automation.policy import get_policy
from app.services.automation.scheduler import ensure_jobs
from app.services.hhru.gateway import HhGateway
from app.services.matching.engine import analyze_and_store
from app.services.vacancies.discovery import run_discovery

router = APIRouter(prefix="/api/search-profiles", tags=["search profiles"])


def _apply(profile: SearchProfile, body: SearchProfileIn) -> None:
    if body.review_threshold > body.eligible_threshold:
        raise AppError("Порог «проверить» не может быть выше порога «подходит»", code="bad_thresholds")
    data = body.model_dump()
    data["areas"] = [a for a in data["areas"]]
    data["excluded_employers"] = [e for e in data["excluded_employers"]]
    for key, value in data.items():
        setattr(profile, key, value)


async def _check_resume(db, user, resume_id: uuid.UUID | None) -> None:
    if resume_id is not None:
        await get_owned(db, Resume, resume_id, user)


@router.get("")
async def list_profiles(db: DB, user: CurrentUser) -> list[dict]:
    rows = (
        await db.execute(
            select(SearchProfile).where(SearchProfile.user_id == user.id).order_by(SearchProfile.created_at)
        )
    ).scalars()
    return [search_profile_out(p) for p in rows]


@router.post("", status_code=201)
async def create(body: SearchProfileIn, db: DB, user: CurrentUser) -> dict:
    await _check_resume(db, user, body.resume_id)
    exists = (
        await db.execute(
            select(SearchProfile.id).where(SearchProfile.user_id == user.id, SearchProfile.name == body.name)
        )
    ).first()
    if exists:
        raise Conflict("Профиль с таким названием уже есть")
    profile = SearchProfile(id=uuid.uuid4(), user_id=user.id)
    _apply(profile, body)
    db.add(profile)
    await db.flush()
    await ensure_jobs(db, user)
    await audit(
        db, user_id=user.id, action="search_profile.created", entity_type="search_profile", entity_id=profile.id
    )
    return search_profile_out(profile)


@router.get("/{profile_id}")
async def get_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    return search_profile_out(await get_owned(db, SearchProfile, profile_id, user))


@router.put("/{profile_id}")
async def update_profile(profile_id: uuid.UUID, body: SearchProfileIn, db: DB, user: CurrentUser) -> dict:
    profile = await get_owned(db, SearchProfile, profile_id, user)
    await _check_resume(db, user, body.resume_id)
    _apply(profile, body)
    await ensure_jobs(db, user)
    await audit(
        db, user_id=user.id, action="search_profile.updated", entity_type="search_profile", entity_id=profile.id
    )
    return search_profile_out(profile)


@router.delete("/{profile_id}", status_code=204)
async def delete_profile(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> None:
    profile = await get_owned(db, SearchProfile, profile_id, user)
    await db.delete(profile)
    await audit(db, user_id=user.id, action="search_profile.deleted", entity_id=profile_id)


@router.post("/{profile_id}/run")
async def run_now(profile_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    profile = await get_owned(db, SearchProfile, profile_id, user)
    stats = await run_discovery(db, user, profile, HhGateway(db, user.id))
    if stats.status == "unavailable":
        raise IntegrationUnavailable(stats.detail)
    return stats.as_dict()


@router.post("/{profile_id}/reanalyze")
async def reanalyze(profile_id: uuid.UUID, request: Request, db: DB, user: CurrentUser) -> dict:
    """Re-score this profile's inbox after thresholds, weights or the resume changed."""
    profile = await get_owned(db, SearchProfile, profile_id, user)
    resumes = list(
        (await db.execute(select(Resume).where(Resume.user_id == user.id, Resume.archived_at.is_(None)))).scalars()
    )
    policy = await get_policy(db, user.id)
    rows = (
        (
            await db.execute(
                select(Vacancy)
                .join(VacancyMatch, VacancyMatch.vacancy_id == Vacancy.id)
                .where(
                    VacancyMatch.user_id == user.id,
                    VacancyMatch.search_profile_id == profile.id,
                    VacancyMatch.decision != MatchDecision.APPLIED.value,
                )
                .limit(1000)
            )
        )
        .scalars()
        .all()
    )
    for vacancy in rows:
        await analyze_and_store(
            db, user, vacancy, profile, resumes, extra_excluded=policy.excluded_employers, force=True
        )
    return {"reanalyzed": len(rows)}
