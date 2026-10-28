"""Continuous vacancy discovery for one search profile through the official API."""

import logging
from dataclasses import asdict, dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import AutomationPolicy, Resume, SearchProfile, User, Vacancy, VacancyMatch
from app.models.enums import Capability, CapabilityStatus, MatchDecision, VacancySource
from app.services.ai.service import AIService
from app.services.hhru.capabilities import capability_map
from app.services.hhru.client import HhClient
from app.services.hhru.errors import HhApiError, HhNotConfigured, HhNotFound
from app.services.hhru.gateway import HhGateway
from app.services.hhru.normalize import normalize_hh_vacancy
from app.services.hhru.query import build_search_params, max_pages, since_for
from app.services.matching.engine import analyze, analyze_and_store
from app.services.notifications.service import notify
from app.services.vacancies.ingest import upsert_vacancy

log = logging.getLogger(__name__)

MAX_PAGES_PER_RUN = 5
MAX_DETAIL_FETCHES = 40
_NEW_STYLE_PARAMS = {"work_format", "employment_form", "internship"}


@dataclass(slots=True)
class DiscoveryStats:
    status: str = "ok"
    found: int = 0
    new: int = 0
    duplicates: int = 0
    analyzed: int = 0
    eligible: int = 0
    details_fetched: int = 0
    detail: str = ""

    def as_dict(self) -> dict:
        return asdict(self)


async def search_client(db: AsyncSession, user: User, gateway: HhGateway) -> HhClient | None:
    caps = await capability_map(db, user.id)
    if caps[Capability.VACANCY_SEARCH]["status"] != CapabilityStatus.VERIFIED:
        return None
    if "токен user" in caps[Capability.VACANCY_SEARCH]["detail"]:
        try:
            return await gateway.user_client()
        except (HhNotConfigured, HhApiError):
            pass
    return gateway.app_client()


async def _search_page(client: HhClient, profile: SearchProfile, page: int, since, legacy: bool) -> tuple[dict, bool]:
    try:
        return await client.search_vacancies(
            build_search_params(profile, page=page, since=since, legacy=legacy)
        ), legacy
    except HhApiError as exc:
        if not legacy and exc.status == 400 and exc.error_value in _NEW_STYLE_PARAMS:
            params = build_search_params(profile, page=page, since=since, legacy=True)
            return await client.search_vacancies(params), True
        raise


async def run_discovery(
    db: AsyncSession, user: User, profile: SearchProfile, gateway: HhGateway, ai: AIService | None = None
) -> DiscoveryStats:
    stats = DiscoveryStats()
    client = await search_client(db, user, gateway)
    if client is None:
        stats.status = "unavailable"
        stats.detail = "Поиск через API hh.ru недоступен: добавляйте вакансии вручную или букмарклетом"
        return stats

    resumes = list(
        (await db.execute(select(Resume).where(Resume.user_id == user.id, Resume.archived_at.is_(None)))).scalars()
    )
    policy = (
        await db.execute(select(AutomationPolicy).where(AutomationPolicy.user_id == user.id))
    ).scalar_one_or_none()
    extra_excluded = list(policy.excluded_employers) if policy else []
    started_at = utcnow()
    since = since_for(profile)
    legacy = False
    candidates: list[Vacancy] = []

    try:
        page, pages = 0, 1
        while page < min(pages, MAX_PAGES_PER_RUN):
            result, legacy = await _search_page(client, profile, page, since, legacy)
            pages = max_pages(int(result.get("found") or 0))
            for item in result.get("items") or []:
                stats.found += 1
                nv = normalize_hh_vacancy(item)
                vacancy, changed = await upsert_vacancy(db, nv, source=VacancySource.HH_API)
                existing = (
                    await db.execute(
                        select(VacancyMatch.id).where(
                            VacancyMatch.user_id == user.id, VacancyMatch.vacancy_id == vacancy.id
                        )
                    )
                ).scalar_one_or_none()
                if existing and not changed:
                    stats.duplicates += 1
                    continue
                if not existing:
                    stats.new += 1
                candidates.append(vacancy)
            page += 1

        for vacancy in candidates:
            preview = analyze(vacancy, profile, resumes, extra_excluded=extra_excluded)
            promising = not preview["hard_filter_failures"] and preview["score"] >= profile.review_threshold - 15
            if promising and stats.details_fetched < MAX_DETAIL_FETCHES and vacancy.hh_id:
                try:
                    full = await client.get_vacancy(vacancy.hh_id)
                    vacancy, _ = await upsert_vacancy(db, normalize_hh_vacancy(full), source=VacancySource.HH_API)
                    stats.details_fetched += 1
                except HhNotFound:
                    vacancy.archived = True
            match = await analyze_and_store(
                db, user, vacancy, profile, resumes, ai=ai if promising else None, extra_excluded=extra_excluded
            )
            stats.analyzed += 1
            if match.decision in (MatchDecision.ELIGIBLE, MatchDecision.READY_TO_APPLY):
                stats.eligible += 1
        await gateway.record_success()
    except HhApiError as exc:
        await gateway.record_failure(exc)
        stats.status = "error"
        stats.detail = exc.tag
        log.warning("discovery failed", extra={"profile_id": str(profile.id), "error": exc.tag})
        return stats
    finally:
        if client is not None:
            await client.aclose()

    profile.last_run_at = started_at
    if stats.eligible:
        await notify(
            db,
            user.id,
            kind="new_matches",
            title=f"Новые подходящие вакансии: {stats.eligible}",
            body=f"Профиль «{profile.name}»: найдено {stats.found}, новых {stats.new}, подходит {stats.eligible}.",
            payload={"search_profile_id": str(profile.id)},
            dedupe_key=f"new_matches:{profile.id}:{started_at.isoformat(timespec='minutes')}",
        )
    return stats
