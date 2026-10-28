"""Matching pipeline: hard filters → scoring per candidate resume → optional AI review → decision."""

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import Resume, SearchProfile, User, Vacancy, VacancyMatch
from app.models.enums import MatchDecision
from app.schemas.profile import CandidateProfile
from app.services.ai.provider import AIError, AINotAvailable
from app.services.ai.service import AIService, wrap_untrusted
from app.services.matching.scoring import hard_filters, score_vacancy, summarize

log = logging.getLogger(__name__)

AI_ADJUSTMENT_LIMIT = 10

AI_SYSTEM = """Ты карьерный аналитик. Сравни вакансию с профилем кандидата и верни JSON:
{"risks": [string], "reasoning_summary": string, "adjustment": integer от -10 до 10}
adjustment корректирует автоматическую оценку, только если она явно не учитывает важное обстоятельство.
Пиши по-русски, коротко. Не выдумывай сведения: если чего-то нет в тексте, так и скажи."""


def decide(score: int, failures: list[str], review_reasons: list[str], search: SearchProfile) -> MatchDecision:
    if failures:
        return MatchDecision.REJECT
    if score >= search.eligible_threshold:
        return MatchDecision.REVIEW if review_reasons else MatchDecision.ELIGIBLE
    if score >= search.review_threshold:
        return MatchDecision.REVIEW
    return MatchDecision.REJECT


def _candidate_resumes(resumes: list[Resume], search: SearchProfile) -> list[Resume]:
    active = [r for r in resumes if r.archived_at is None and r.profile]
    if search.resume_id:
        chosen = [r for r in active if r.id == search.resume_id]
        if chosen:
            return chosen
    return active


def analyze(
    vacancy: Vacancy, search: SearchProfile, resumes: list[Resume], *, extra_excluded: list | None = None
) -> dict[str, Any]:
    """Pure function: no I/O. Picks the best-scoring resume among the allowed ones."""
    best: dict[str, Any] | None = None
    for resume in _candidate_resumes(resumes, search):
        candidate = CandidateProfile.model_validate(resume.profile)
        filters = hard_filters(vacancy, search, candidate, extra_excluded_employers=extra_excluded)
        scored = score_vacancy(vacancy, search, candidate)
        result = {
            **scored,
            "recommended_resume_id": str(resume.id),
            "resume_version": resume.version,
            "hard_filter_failures": filters.failures,
            "risks": filters.risks + scored.pop("extra_risks", []),
            "review_reasons": filters.review_reasons,
        }
        result.pop("extra_risks", None)
        rank = (not filters.failures, scored["score"])
        if best is None or rank > (not best["hard_filter_failures"], best["score"]):
            best = result
    if best is None:
        return {
            "score": 0,
            "hard_filter_failures": ["нет резюме с заполненным профилем"],
            "risks": [],
            "review_reasons": [],
            "matched_skills": [],
            "missing_skills": [],
            "salary_match": "unknown",
            "experience_match": "unknown",
            "recommended_resume_id": None,
        }
    return best


async def ai_review(ai: AIService, user: User, vacancy: Vacancy, resume: Resume, analysis: dict[str, Any]) -> bool:
    """Bounded AI second opinion. It cannot override hard filters or move the score more than ±10."""
    candidate = CandidateProfile.model_validate(resume.profile)
    prompt = (
        f"Автоматическая оценка: {analysis['score']}/100.\n"
        f"Совпавшие навыки: {', '.join(analysis['matched_skills'][:15]) or 'нет'}.\n"
        f"Недостающие: {', '.join(analysis['missing_skills'][:15]) or 'нет'}.\n"
        f"Навыки кандидата: {', '.join(candidate.skill_names()[:40])}.\n"
        f"Стаж: {candidate.total_experience_months} мес., уровень: {candidate.level}.\n\n"
        + wrap_untrusted("vacancy", f"{vacancy.title}\n{vacancy.employer_name}\n{vacancy.description_text}", 8000)
    )
    try:
        data = await ai.complete_json(user, purpose="vacancy_analysis", system=AI_SYSTEM, prompt=prompt)
    except (AINotAvailable, AIError) as exc:
        log.info("ai review skipped: %s", exc)
        return False
    adjustment = data.get("adjustment")
    if isinstance(adjustment, int | float):
        delta = max(-AI_ADJUSTMENT_LIMIT, min(AI_ADJUSTMENT_LIMIT, int(adjustment)))
        analysis["ai_adjustment"] = delta
        analysis["score"] = max(0, min(100, analysis["score"] + delta))
    risks = [r[:200] for r in data.get("risks") or [] if isinstance(r, str)][:5]
    analysis["risks"] = list(dict.fromkeys(analysis["risks"] + risks))
    if isinstance(data.get("reasoning_summary"), str):
        analysis["ai_summary"] = data["reasoning_summary"][:1000]
    return True


async def analyze_and_store(
    db: AsyncSession,
    user: User,
    vacancy: Vacancy,
    search: SearchProfile,
    resumes: list[Resume],
    *,
    ai: AIService | None = None,
    extra_excluded: list | None = None,
    force: bool = False,
) -> VacancyMatch:
    """Create or refresh the user's match. Re-analysis happens only when content or resume changed."""
    match = (
        await db.execute(
            select(VacancyMatch)
            .where(VacancyMatch.user_id == user.id, VacancyMatch.vacancy_id == vacancy.id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    now = utcnow()
    if match is not None and not force:
        same_content = match.analyzed_content_hash == vacancy.content_hash
        resume_versions = {str(r.id): r.version for r in resumes}
        rec = match.analysis.get("recommended_resume_id")
        same_resume = rec is None or resume_versions.get(rec) == match.analysis.get("resume_version")
        if same_content and same_resume:
            match.times_seen += 1
            return match
        if match.decision == MatchDecision.APPLIED:
            match.times_seen += 1
            return match

    analysis = analyze(vacancy, search, resumes, extra_excluded=extra_excluded)
    source = "local"
    if ai is not None and not analysis["hard_filter_failures"] and analysis.get("recommended_resume_id"):
        if analysis["score"] >= search.review_threshold - 10:
            resume = next(r for r in resumes if str(r.id) == analysis["recommended_resume_id"])
            if await ai_review(ai, user, vacancy, resume, analysis):
                source = "ai"
    decision = decide(analysis["score"], analysis["hard_filter_failures"], analysis["review_reasons"], search)
    analysis["decision"] = decision.value
    analysis["reasoning_summary"] = summarize(analysis, decision)

    if match is None:
        match = VacancyMatch(
            id=uuid.uuid4(),
            user_id=user.id,
            vacancy_id=vacancy.id,
            search_profile_id=search.id,
            discovered_at=now,
            times_seen=1,
        )
        db.add(match)
    else:
        match.times_seen += 1
    match.search_profile_id = search.id
    match.resume_id = uuid.UUID(analysis["recommended_resume_id"]) if analysis.get("recommended_resume_id") else None
    match.score = analysis["score"]
    match.decision = decision.value
    match.analysis = analysis
    match.analysis_source = source
    match.analyzed_content_hash = vacancy.content_hash
    await db.flush()
    return match
