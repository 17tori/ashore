"""Interpretable vacancy scoring: hard filters first, then a weighted 0–100 score with explanations."""

import re
from dataclasses import dataclass, field
from typing import Any

from app.models import SearchProfile, Vacancy
from app.schemas.profile import CandidateProfile
from app.services.ai.embeddings import similarity, tokens
from app.services.hhru.normalize import EXPERIENCE_RANGES
from app.services.matching.fraud import fraud_signals
from app.services.matching.skills import extract_skills, skill_key

DEFAULT_WEIGHTS: dict[str, float] = {
    "skills": 30,
    "experience": 20,
    "title": 15,
    "salary": 15,
    "format_region": 10,
    "education_other": 10,
}
EXPERIENCE_TOLERANCE_YEARS = 1.0

_EDU_REQUIRED = re.compile(
    r"(высше\w+\s+(техническ\w+\s+)?образовани\w*\s+(обязательн|требует)|"
    r"обязательно\s+высше\w+|диплом\s+(обязател|о\s+высшем))",
    re.I,
)
_EDU_MENTIONED = re.compile(r"высше\w+\s+(техническ\w+\s+)?образовани", re.I)
_ENGLISH_REQ = re.compile(r"(английск\w+|english)[^.\n]{0,40}?\b(b2|c1|upper|advanced|свободн|fluent)", re.I)
_EXP_YEARS_IN_TEXT = re.compile(
    r"опыт\w*\s+(?:работы\s+|коммерческой\s+разработки\s+)?(?:от\s+)?(\d+)\+?\s*(?:год|лет)", re.I
)


def normalize_weights(custom: dict[str, Any] | None) -> dict[str, float]:
    weights = dict(DEFAULT_WEIGHTS)
    for key, value in (custom or {}).items():
        if key in weights and isinstance(value, int | float) and value >= 0:
            weights[key] = float(value)
    total = sum(weights.values()) or 1.0
    return {k: v * 100 / total for k, v in weights.items()}


@dataclass(slots=True)
class HardFilterResult:
    passed: bool = True
    failures: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    review_reasons: list[str] = field(default_factory=list)

    def fail(self, reason: str) -> None:
        self.passed = False
        self.failures.append(reason)


def employer_excluded(vacancy: Vacancy, excluded: list[dict | str]) -> bool:
    name = vacancy.employer_name.strip().lower()
    for item in excluded:
        if isinstance(item, str):
            if item.strip().lower() and item.strip().lower() == name:
                return True
            continue
        if item.get("id") and vacancy.employer_hh_id and str(item["id"]) == vacancy.employer_hh_id:
            return True
        if item.get("name") and item["name"].strip().lower() == name:
            return True
    return False


def offered_salary(vacancy: Vacancy) -> int | None:
    return vacancy.salary_to or vacancy.salary_from


def hard_filters(
    vacancy: Vacancy,
    search: SearchProfile,
    candidate: CandidateProfile,
    *,
    extra_excluded_employers: list | None = None,
) -> HardFilterResult:
    result = HardFilterResult()
    text = f"{vacancy.title}\n{vacancy.description_text}"

    if vacancy.archived:
        result.fail("вакансия в архиве")
    if employer_excluded(vacancy, list(search.excluded_employers or []) + list(extra_excluded_employers or [])):
        result.fail(f"работодатель «{vacancy.employer_name}» в стоп-листе")
    for word in search.excluded_keywords or []:
        if word and re.search(rf"(?<!\w){re.escape(word)}", text, re.I):
            result.fail(f"содержит исключённое слово «{word}»")

    # Salary: unknown is never treated as a mismatch.
    offer = offered_salary(vacancy)
    if search.salary_min:
        if offer is None:
            if search.only_with_salary:
                result.fail("зарплата не указана, а в профиле включено «только с зарплатой»")
            else:
                result.risks.append("зарплата не указана")
        elif vacancy.salary_currency and vacancy.salary_currency != (search.currency or "RUR"):
            result.risks.append(f"зарплата в другой валюте ({vacancy.salary_currency})")
        elif offer < search.salary_min:
            result.fail(f"зарплата до {offer:,} ниже минимума {search.salary_min:,}".replace(",", " "))

    # Location and format.
    allowed_areas = {str(a.get("id")) for a in search.areas or [] if a.get("id")}
    is_remote = "remote" in (vacancy.work_formats or [])
    wants_remote = "remote" in (search.work_formats or [])
    if allowed_areas and vacancy.area_id and vacancy.area_id not in allowed_areas and not (is_remote and wants_remote):
        result.fail(f"регион «{vacancy.area_name}» не из списка")
    if search.work_formats and vacancy.work_formats:
        if not set(search.work_formats) & set(vacancy.work_formats):
            result.fail("формат работы не подходит")
    elif search.work_formats and not vacancy.work_formats:
        result.risks.append("формат работы не указан")

    if search.employment_types and vacancy.employment_type and vacancy.employment_type not in search.employment_types:
        result.fail("тип занятости не подходит")

    # Experience.
    candidate_years = candidate.total_experience_months / 12
    if vacancy.experience_id in EXPERIENCE_RANGES:
        if search.experience and vacancy.experience_id not in search.experience:
            result.fail("требуемый опыт вне выбранных диапазонов")
        min_years = EXPERIENCE_RANGES[vacancy.experience_id][0]
        if min_years > candidate_years + EXPERIENCE_TOLERANCE_YEARS:
            result.fail(f"нужен опыт от {int(min_years)} лет, в профиле {candidate_years:.1f}")
        stated = _EXP_YEARS_IN_TEXT.search(vacancy.description_text or "")
        if stated:
            years = int(stated.group(1))
            lo, hi = EXPERIENCE_RANGES[vacancy.experience_id]
            if years > hi + 1 or (vacancy.experience_id == "noExperience" and years >= 2):
                result.risks.append(f"противоречивые требования: в описании опыт от {years} лет")
                result.review_reasons.append("противоречивые требования к опыту")

    strong, weak = fraud_signals(
        vacancy.title, vacancy.description_text, salary_from=vacancy.salary_from, experience_id=vacancy.experience_id
    )
    for label in strong:
        result.fail(f"признаки мошенничества: {label}")
    for label in weak:
        result.risks.append(f"подозрительно: {label}")
        result.review_reasons.append("признаки недобросовестной вакансии")

    if vacancy.has_test:
        result.review_reasons.append("для отклика нужен тест работодателя: через API отправить нельзя")
    return result


def vacancy_skills(vacancy: Vacancy) -> list[str]:
    seen: dict[str, str] = {}
    for name in list(vacancy.key_skills or []) + extract_skills(f"{vacancy.title}\n{vacancy.description_text}"):
        seen.setdefault(skill_key(name), name)
    return list(seen.values())


def _title_score(title: str, positions: list[str]) -> float:
    if not positions:
        return 0.5
    title_tokens = set(tokens(title))
    best = 0.0
    for position in positions:
        pos_tokens = set(tokens(position))
        if not pos_tokens:
            continue
        overlap = len(title_tokens & pos_tokens) / len(pos_tokens)
        best = max(best, 0.6 * overlap + 0.4 * similarity(title, position))
    return min(1.0, best)


def _experience_component(vacancy: Vacancy, candidate: CandidateProfile) -> tuple[float, str]:
    if vacancy.experience_id not in EXPERIENCE_RANGES:
        return 0.6, "unknown"
    lo, hi = EXPERIENCE_RANGES[vacancy.experience_id]
    years = candidate.total_experience_months / 12
    if lo <= years <= hi or (lo == 0 and years <= 1):
        return 1.0, "good"
    if years < lo:
        return (0.55, "partial") if lo - years <= EXPERIENCE_TOLERANCE_YEARS else (0.1, "insufficient")
    return 0.8, "overqualified"


def _salary_component(vacancy: Vacancy, salary_min: int | None, currency: str) -> tuple[float, str]:
    offer = offered_salary(vacancy)
    if offer is None:
        return 0.5, "unknown"
    if vacancy.salary_currency and vacancy.salary_currency != currency:
        return 0.5, "unknown"
    if not salary_min:
        return 0.75, "no_expectation"
    if offer >= salary_min:
        return 1.0, "good"
    if offer >= salary_min * 0.9:
        return 0.5, "below"
    return 0.0, "below"


def _format_region_component(vacancy: Vacancy, search: SearchProfile) -> float:
    parts = []
    if search.work_formats:
        if not vacancy.work_formats:
            parts.append(0.6)
        else:
            parts.append(1.0 if set(search.work_formats) & set(vacancy.work_formats) else 0.0)
    if search.areas:
        ids = {str(a.get("id")) for a in search.areas if a.get("id")}
        if not vacancy.area_id:
            parts.append(0.6)
        else:
            parts.append(1.0 if vacancy.area_id in ids or "remote" in (vacancy.work_formats or []) else 0.0)
    return sum(parts) / len(parts) if parts else 0.8


def _education_other_component(vacancy: Vacancy, candidate: CandidateProfile) -> tuple[float, list[str]]:
    risks: list[str] = []
    text = vacancy.description_text or ""
    score = 0.8
    if _EDU_REQUIRED.search(text):
        score = 1.0 if candidate.education else 0.2
        if not candidate.education:
            risks.append("требуется высшее образование, в профиле его нет")
    elif _EDU_MENTIONED.search(text):
        score = 1.0 if candidate.education else 0.6
    if _ENGLISH_REQ.search(text):
        english = next((lang for lang in candidate.languages if lang.name.lower() in {"английский", "english"}), None)
        level = (english.level if english else "").upper()
        if not english or not any(x in level for x in ("B2", "C1", "C2", "UPPER", "ADVANCED", "FLUENT", "СВОБОД")):
            score = min(score, 0.4)
            risks.append("требуется английский не ниже B2")
    return score, risks


def score_vacancy(vacancy: Vacancy, search: SearchProfile, candidate: CandidateProfile) -> dict[str, Any]:
    weights = normalize_weights(search.weights)
    v_skills = vacancy_skills(vacancy)
    c_skill_keys = {skill_key(s) for s in candidate.skill_names()}
    matched = [s for s in v_skills if skill_key(s) in c_skill_keys]
    missing = [s for s in v_skills if skill_key(s) not in c_skill_keys]

    resume_text = " ".join(
        [candidate.summary, " ".join(candidate.keywords), " ".join(candidate.skill_names())]
        + [f"{e.title} {e.description}" for e in candidate.experience]
        + [f"{p.name} {p.description}" for p in candidate.projects]
    )
    semantic = similarity(resume_text, f"{vacancy.title}\n{vacancy.description_text}")
    overlap = len(matched) / len(v_skills) if v_skills else 0.0
    skills_component = 0.75 * overlap + 0.25 * min(1.0, semantic * 2.5) if v_skills else min(1.0, semantic * 2.5)

    exp_component, experience_match = _experience_component(vacancy, candidate)
    positions = list(search.positions or []) or candidate.desired_positions
    title_component = _title_score(vacancy.title, positions)
    salary_min = search.salary_min or candidate.min_salary
    salary_component, salary_match = _salary_component(vacancy, salary_min, search.currency or candidate.currency)
    format_component = _format_region_component(vacancy, search)
    edu_component, edu_risks = _education_other_component(vacancy, candidate)

    components = {
        "skills": skills_component,
        "experience": exp_component,
        "title": title_component,
        "salary": salary_component,
        "format_region": format_component,
        "education_other": edu_component,
    }
    score = round(sum(weights[k] * v for k, v in components.items()))
    return {
        "score": max(0, min(100, score)),
        "components": {k: round(v, 3) for k, v in components.items()},
        "weights": {k: round(v, 1) for k, v in weights.items()},
        "matched_skills": matched,
        "missing_skills": missing[:20],
        "semantic_similarity": round(semantic, 3),
        "salary_match": salary_match,
        "experience_match": experience_match,
        "extra_risks": edu_risks,
    }


def summarize(analysis: dict[str, Any], decision: str) -> str:
    parts = []
    if analysis.get("hard_filter_failures"):
        return "Не проходит обязательные условия: " + "; ".join(analysis["hard_filter_failures"]) + "."
    matched, missing = analysis.get("matched_skills", []), analysis.get("missing_skills", [])
    if matched:
        parts.append(f"совпадают навыки: {', '.join(matched[:6])}")
    if missing:
        parts.append(f"не хватает: {', '.join(missing[:4])}")
    exp = {
        "good": "опыт подходит",
        "partial": "опыта немного меньше требуемого",
        "insufficient": "опыта недостаточно",
        "overqualified": "опыт выше требуемого",
        "unknown": "требования к опыту не указаны",
    }
    parts.append(exp.get(analysis.get("experience_match", "unknown"), ""))
    sal = {
        "good": "зарплата подходит",
        "below": "зарплата ниже ожиданий",
        "unknown": "зарплата не указана",
        "no_expectation": "минимальная зарплата не задана",
    }
    parts.append(sal.get(analysis.get("salary_match", "unknown"), ""))
    text = "; ".join(p for p in parts if p)
    return (text[0].upper() + text[1:] + ".") if text else ""
