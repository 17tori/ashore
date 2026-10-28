"""In-memory model builders for pure unit tests (no database)."""

import uuid
from datetime import UTC, datetime
from typing import Any

from app.models import SearchProfile, Vacancy


def vacancy(**kw: Any) -> Vacancy:
    data: dict[str, Any] = {
        "id": uuid.uuid4(),
        "source": "hh_api",
        "hh_id": "100",
        "url": "https://hh.ru/vacancy/100",
        "apply_url": "https://hh.ru/applicant/vacancy_response?vacancyId=100",
        "title": "Junior Python-разработчик",
        "employer_name": "ООО Тест",
        "employer_hh_id": "1",
        "area_id": "1",
        "area_name": "Москва",
        "salary_from": 90_000,
        "salary_to": 120_000,
        "salary_currency": "RUR",
        "salary_gross": False,
        "work_formats": ["remote"],
        "employment_type": "full",
        "experience_id": "between1And3",
        "schedule": None,
        "description_text": "Разработка сервисов на Python и FastAPI, PostgreSQL, Docker. Опыт от 1 года.",
        "key_skills": ["Python", "FastAPI", "PostgreSQL", "Docker"],
        "professional_roles": [],
        "published_at": datetime.now(UTC),
        "archived": False,
        "has_test": False,
        "response_letter_required": False,
        "content_hash": "x",
    }
    data.update(kw)
    return Vacancy(**data)


def search(**kw: Any) -> SearchProfile:
    data: dict[str, Any] = {
        "id": uuid.uuid4(),
        "user_id": uuid.uuid4(),
        "name": "Тест",
        "is_active": True,
        "resume_id": None,
        "positions": ["Python-разработчик"],
        "skills": [],
        "areas": [{"id": "1", "name": "Москва"}],
        "work_formats": ["remote", "hybrid"],
        "employment_types": [],
        "experience": [],
        "salary_min": 80_000,
        "currency": "RUR",
        "only_with_salary": False,
        "industries": [],
        "excluded_employers": [],
        "excluded_keywords": [],
        "period_days": 7,
        "eligible_threshold": 70,
        "review_threshold": 50,
        "daily_apply_limit": 10,
        "weights": {},
        "letter_template": "junior_developer",
        "letter_tone": "neutral",
        "letter_length": "short",
        "letter_mode": "always",
        "search_interval_minutes": 120,
    }
    data.update(kw)
    return SearchProfile(**data)
