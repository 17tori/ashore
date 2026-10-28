from typing import Any

from app.models import (
    Application,
    AutomationPolicy,
    CoverLetter,
    Notification,
    Resume,
    SearchProfile,
    User,
    Vacancy,
    VacancyMatch,
)


def user_out(user: User) -> dict[str, Any]:
    return {
        "id": str(user.id),
        "email": user.email,
        "display_name": user.display_name,
        "timezone": user.timezone,
        "is_demo": user.is_demo,
        "ai_external_consent": user.ai_external_consent_at is not None,
        "settings": user.settings or {},
        "created_at": user.created_at,
    }


def vacancy_out(v: Vacancy) -> dict[str, Any]:
    return {
        "id": str(v.id),
        "source": v.source,
        "is_sample": v.source == "demo",
        "hh_id": v.hh_id or v.source_ref,
        "url": v.url,
        "apply_url": v.apply_url,
        "title": v.title,
        "employer_name": v.employer_name,
        "area_name": v.area_name,
        "salary_from": v.salary_from,
        "salary_to": v.salary_to,
        "salary_currency": v.salary_currency,
        "salary_gross": v.salary_gross,
        "work_formats": v.work_formats,
        "employment_type": v.employment_type,
        "experience_id": v.experience_id,
        "key_skills": v.key_skills,
        "published_at": v.published_at,
        "archived": v.archived,
        "has_test": v.has_test,
        "response_letter_required": v.response_letter_required,
        "first_seen_at": v.first_seen_at,
    }


def match_out(m: VacancyMatch, v: Vacancy, app: Application | None = None, *, full: bool = False) -> dict[str, Any]:
    analysis = m.analysis or {}
    data = {
        "id": str(m.id),
        "vacancy": vacancy_out(v),
        "score": m.score,
        "decision": m.effective_decision,
        "ai_decision": m.decision,
        "user_decision": m.user_decision,
        "matched_skills": analysis.get("matched_skills", []),
        "missing_skills": analysis.get("missing_skills", []),
        "risks": analysis.get("risks", []),
        "salary_match": analysis.get("salary_match", "unknown"),
        "experience_match": analysis.get("experience_match", "unknown"),
        "reasoning_summary": analysis.get("reasoning_summary", ""),
        "recommended_resume_id": analysis.get("recommended_resume_id"),
        "search_profile_id": str(m.search_profile_id) if m.search_profile_id else None,
        "analysis_source": m.analysis_source,
        "hidden": m.hidden,
        "times_seen": m.times_seen,
        "discovered_at": m.discovered_at,
        "application": {"id": str(app.id), "status": app.status} if app else None,
    }
    if full:
        data["analysis"] = analysis
        data["vacancy"]["description_text"] = v.description_text
    return data


def resume_out(r: Resume, *, full: bool = False) -> dict[str, Any]:
    data = {
        "id": str(r.id),
        "title": r.title,
        "source": r.source,
        "version": r.version,
        "parent_id": str(r.parent_id) if r.parent_id else None,
        "file_name": r.file_name,
        "is_primary": r.is_primary,
        "profile_confirmed": r.profile_confirmed,
        "quality": r.quality,
        "hh_resume_id": r.hh_resume_id,
        "hh_status": r.hh_status,
        "archived": r.archived_at is not None,
        "created_at": r.created_at,
        "updated_at": r.updated_at,
        "skills_count": len((r.profile or {}).get("skills", [])),
        "level": (r.profile or {}).get("level"),
    }
    if full:
        data["profile"] = r.profile
    return data


def search_profile_out(p: SearchProfile) -> dict[str, Any]:
    fields = (
        "name", "is_active", "positions", "skills", "areas", "work_formats", "employment_types", "experience",
        "salary_min", "currency", "only_with_salary", "industries", "excluded_employers", "excluded_keywords",
        "period_days", "eligible_threshold", "review_threshold", "daily_apply_limit", "weights", "letter_template",
        "letter_tone", "letter_length", "letter_mode", "search_interval_minutes", "last_run_at",
    )  # fmt: skip
    data = {f: getattr(p, f) for f in fields}
    data["id"] = str(p.id)
    data["resume_id"] = str(p.resume_id) if p.resume_id else None
    return data


def letter_out(letter: CoverLetter | None) -> dict[str, Any] | None:
    if letter is None:
        return None
    return {
        "id": str(letter.id),
        "text": letter.text,
        "template_kind": letter.template_kind,
        "tone": letter.tone,
        "generator": letter.generator,
        "validation": letter.validation,
        "edited_by_user": letter.edited_by_user,
    }


def application_out(a: Application, v: Vacancy, letter: CoverLetter | None = None) -> dict[str, Any]:
    return {
        "id": str(a.id),
        "status": a.status,
        "channel": a.channel,
        "confirmed_by": a.confirmed_by,
        "vacancy": vacancy_out(v),
        "resume_id": str(a.resume_id) if a.resume_id else None,
        "match_id": str(a.match_id) if a.match_id else None,
        "search_profile_id": str(a.search_profile_id) if a.search_profile_id else None,
        "attempts": a.attempts,
        "sent_at": a.sent_at,
        "status_changed_at": a.status_changed_at,
        "last_error": a.last_error,
        "notes": a.notes,
        "letter": letter_out(letter),
        "created_at": a.created_at,
    }


def policy_out(p: AutomationPolicy) -> dict[str, Any]:
    fields = (
        "mode", "paused", "paused_reason", "paused_at", "allowed_positions", "min_score", "salary_min",
        "employment_types", "excluded_employers", "daily_limit", "letter_rules", "stop_conditions", "apply_windows",
        "confirmed_at",
    )  # fmt: skip
    data = {f: getattr(p, f) for f in fields}
    data["allowed_resume_ids"] = [str(x) for x in p.allowed_resume_ids]
    data["ai_monthly_budget"] = float(p.ai_monthly_budget or 0)
    return data


def notification_out(n: Notification) -> dict[str, Any]:
    return {
        "id": str(n.id),
        "kind": n.kind,
        "title": n.title,
        "body": n.body,
        "payload": n.payload,
        "read": n.read_at is not None,
        "created_at": n.created_at,
    }
