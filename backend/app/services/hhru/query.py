from datetime import datetime, timedelta
from typing import Any

from app.models import SearchProfile

PER_PAGE = 100
MAX_DEPTH = 2000  # hh.ru refuses page * per_page beyond 2000

_WORK_FORMAT = {"remote": "REMOTE", "on_site": "ON_SITE", "hybrid": "HYBRID", "field_work": "FIELD_WORK"}
_EMPLOYMENT_FORM = {"full": "FULL", "part": "PART", "project": "PROJECT", "fly_in_fly_out": "FLY_IN_FLY_OUT"}
_LEGACY_SCHEDULE = {"remote": "remote", "on_site": "fullDay", "field_work": "flyInFlyOut"}
_LEGACY_EMPLOYMENT = {"full": "full", "part": "part", "project": "project", "internship": "probation"}


def build_text_query(positions: list[str], skills: list[str]) -> str:
    """hh.ru query language: quoted phrases joined with OR."""
    terms = [p.strip() for p in positions if p.strip()] or [s.strip() for s in skills[:5] if s.strip()]
    return " OR ".join(f'"{t.replace(chr(34), "")}"' for t in terms)


def build_search_params(
    profile: SearchProfile, *, page: int, since: datetime | None, legacy: bool = False
) -> list[tuple[str, Any]]:
    params: list[tuple[str, Any]] = [("per_page", PER_PAGE), ("page", page), ("order_by", "publication_time")]
    text = build_text_query(profile.positions or [], profile.skills or [])
    if text:
        params.append(("text", text))
        if profile.positions:
            params.append(("search_field", "name"))
    for area in profile.areas or []:
        if area.get("id"):
            params.append(("area", area["id"]))
    for exp in profile.experience or []:
        params.append(("experience", exp))
    if legacy:
        for fmt in profile.work_formats or []:
            if fmt in _LEGACY_SCHEDULE:
                params.append(("schedule", _LEGACY_SCHEDULE[fmt]))
        for emp in profile.employment_types or []:
            if emp in _LEGACY_EMPLOYMENT:
                params.append(("employment", _LEGACY_EMPLOYMENT[emp]))
    else:
        for fmt in profile.work_formats or []:
            if fmt in _WORK_FORMAT:
                params.append(("work_format", _WORK_FORMAT[fmt]))
        for emp in profile.employment_types or []:
            if emp in _EMPLOYMENT_FORM:
                params.append(("employment_form", _EMPLOYMENT_FORM[emp]))
            elif emp == "internship":
                params.append(("internship", "true"))
    if profile.salary_min:
        params.append(("salary", profile.salary_min))
        params.append(("currency", profile.currency or "RUR"))
    if profile.only_with_salary:
        params.append(("only_with_salary", "true"))
    for industry in profile.industries or []:
        params.append(("industry", industry))
    if since is not None:
        params.append(("date_from", since.replace(microsecond=0).isoformat()))
    else:
        params.append(("period", max(1, min(profile.period_days or 7, 30))))
    return params


def max_pages(found: int) -> int:
    return min((found + PER_PAGE - 1) // PER_PAGE, MAX_DEPTH // PER_PAGE)


def since_for(profile: SearchProfile) -> datetime | None:
    """Overlap the previous run by an hour so late-indexed vacancies are not missed."""
    return profile.last_run_at - timedelta(hours=1) if profile.last_run_at else None
