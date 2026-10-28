"""Sample data for demo mode. Everything created here is marked as an example (source=demo, «Пример» prefixes)
and never points at real hh.ru vacancies or real employers."""

import json
import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import get_box
from app.db.base import utcnow
from app.models import Resume, SearchProfile, User
from app.models.enums import ResumeSource, VacancySource
from app.services.automation.policy import get_policy
from app.services.automation.scheduler import ensure_jobs
from app.services.hhru.normalize import NormalizedVacancy
from app.services.matching.engine import analyze_and_store
from app.services.resume.extraction import assess_quality, build_profile, extract_contacts
from app.services.vacancies.ingest import upsert_vacancy

SAMPLE_RESUME = """Пример Кандидат
Москва

Желаемая должность и зарплата
Junior Python-разработчик
Занятость: полная занятость, стажировка
График работы: удаленная работа
от 80 000 ₽ на руки

Опыт работы — 1 год
Октябрь 2024 — настоящее время
Пример: учебная студия «Код»
Python-разработчик (стажёр)
Разрабатывал внутренние сервисы на FastAPI и PostgreSQL, писал тесты на pytest.
Настроил Docker-окружение и CI в GitLab.

Образование
Высшее
2024
Пример: технический университет
Прикладная информатика, бакалавр

Ключевые навыки
Python, FastAPI, PostgreSQL, Docker, Git, SQL, Linux, pytest, REST API

Проекты
Пример: телеграм-бот для учёта задач — aiogram, SQLite
"""

SAMPLE_VACANCIES: list[dict] = [
    {
        "title": "Junior Python-разработчик (бэкенд)",
        "employer": "Пример: ООО «Северный код»",
        "salary": (80_000, 110_000),
        "formats": ["remote"],
        "experience": "between1And3",
        "skills": ["Python", "FastAPI", "PostgreSQL", "Docker", "Git"],
        "text": "Ищем junior бэкенд-разработчика в команду внутренних сервисов. Стек: Python, FastAPI, "
        "PostgreSQL, Docker. Опыт от 1 года, готовность писать тесты. Удалённая работа, наставник.",
    },
    {
        "title": "Стажёр-разработчик Python",
        "employer": "Пример: «Облачные решения»",
        "salary": (50_000, 60_000),
        "formats": ["hybrid"],
        "experience": "noExperience",
        "skills": ["Python", "SQL", "Git"],
        "text": "Оплачиваемая стажировка на 3 месяца с возможностью трудоустройства. Python, SQL, Git. "
        "Гибридный формат, офис в Москве два дня в неделю.",
    },
    {
        "title": "Middle Python Developer",
        "employer": "Пример: «ФинТех Лаб»",
        "salary": (220_000, 280_000),
        "formats": ["remote"],
        "experience": "between3And6",
        "skills": ["Python", "Django", "Kafka", "Kubernetes", "PostgreSQL"],
        "text": "Нужен разработчик с опытом от 3 лет: Django, Kafka, Kubernetes, высоконагруженные сервисы. "
        "Будет плюсом опыт в финтехе.",
    },
    {
        "title": "Специалист по автоматизации процессов (AI, Python)",
        "employer": "Пример: агентство «Автоматика»",
        "salary": (90_000, None),
        "formats": ["remote"],
        "experience": "between1And3",
        "skills": ["Python", "REST API", "LLM", "n8n"],
        "text": "Автоматизируем бизнес-процессы клиентов: интеграции через REST API, сценарии на Python, "
        "работа с LLM. Опыт от 1 года. Удалённо.",
    },
    {
        "title": "Оператор call-центра",
        "employer": "Пример: «Контакт-Сервис»",
        "salary": (45_000, 55_000),
        "formats": ["on_site"],
        "experience": "noExperience",
        "skills": [],
        "text": "Приём входящих звонков, консультирование клиентов. Работа в офисе, сменный график.",
    },
    {
        "title": "Python-разработчик, доход до 500 000 без опыта",
        "employer": "Пример: «Быстрый старт»",
        "salary": (300_000, 500_000),
        "formats": ["remote"],
        "experience": "noExperience",
        "skills": ["Python"],
        "text": "Опыт не нужен! Доход до 500 000 в первый месяц. Обучение платное, оплата обучения 15 000 рублей. "
        "Пишите в Telegram, анкету заполнить сегодня.",
    },
]


async def seed_demo(db: AsyncSession, user: User) -> dict:
    """Idempotent: re-running updates the same sample rows instead of duplicating them."""
    box = get_box()
    resume = (
        await db.execute(select(Resume).where(Resume.user_id == user.id, Resume.archived_at.is_(None)).limit(1))
    ).scalar_one_or_none()
    created_resume = False
    if resume is None:
        profile = build_profile(SAMPLE_RESUME)
        contacts = extract_contacts(SAMPLE_RESUME)
        resume = Resume(
            id=uuid.uuid4(),
            user_id=user.id,
            title="Пример: Junior Python-разработчик",
            source=ResumeSource.MANUAL.value,
            raw_text_enc=box.encrypt(SAMPLE_RESUME, f"resume:{user.id}"),
            contacts_enc=box.encrypt(
                json.dumps({"emails": contacts.emails, "phones": contacts.phones}), f"contacts:{user.id}"
            ),
            profile=profile.model_dump(),
            quality=assess_quality(profile),
            is_primary=True,
            version=1,
        )
        db.add(resume)
        await db.flush()
        created_resume = True
    search = (
        await db.execute(
            select(SearchProfile).where(SearchProfile.user_id == user.id, SearchProfile.name == "Пример: Python junior")
        )
    ).scalar_one_or_none()
    if search is None:
        search = SearchProfile(
            id=uuid.uuid4(),
            user_id=user.id,
            resume_id=resume.id,
            name="Пример: Python junior",
            is_active=False,
            positions=["Python-разработчик", "Junior Python"],
            skills=["Python", "FastAPI", "PostgreSQL"],
            areas=[{"id": "1", "name": "Москва"}],
            work_formats=["remote", "hybrid"],
            employment_types=[],
            experience=["noExperience", "between1And3"],
            salary_min=70_000,
            currency="RUR",
            only_with_salary=False,
            industries=[],
            excluded_employers=[],
            excluded_keywords=[],
            period_days=7,
            eligible_threshold=70,
            review_threshold=50,
            daily_apply_limit=5,
            weights={},
            letter_template="junior_developer",
            letter_tone="neutral",
            letter_length="short",
            letter_mode="always",
            search_interval_minutes=240,
        )
        db.add(search)
        await db.flush()
    policy = await get_policy(db, user.id)
    resumes = list(
        (await db.execute(select(Resume).where(Resume.user_id == user.id, Resume.archived_at.is_(None)))).scalars()
    )
    now = utcnow()
    count = 0
    for i, item in enumerate(SAMPLE_VACANCIES):
        nv = NormalizedVacancy(
            hh_id=f"demo{i + 1}",  # stored as source_ref of a private row, never as a real hh.ru id
            title=f"[Пример] {item['title']}",
            employer_name=item["employer"],
            area_name="Москва",
            salary_from=item["salary"][0],
            salary_to=item["salary"][1],
            salary_currency="RUR",
            work_formats=item["formats"],
            employment_type="full",
            experience_id=item["experience"],
            description_text=item["text"],
            key_skills=item["skills"],
            published_at=now - timedelta(hours=6 * (i + 1)),
        )
        vacancy, _ = await upsert_vacancy(db, nv, source=VacancySource.DEMO, owner_user_id=user.id)
        await analyze_and_store(
            db, user, vacancy, search, resumes, extra_excluded=policy.excluded_employers, force=True
        )
        count += 1
    await ensure_jobs(db, user)
    return {"vacancies": count, "resume_created": created_resume, "search_profile_id": str(search.id)}
