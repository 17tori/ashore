import re
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import Employer, Vacancy, VacancySnapshot
from app.models.enums import VacancySource
from app.services.hhru.normalize import NormalizedVacancy


def normalize_employer_name(name: str) -> str:
    cleaned = re.sub(r"[«»\"'“”]", "", name.lower())
    cleaned = re.sub(r"\b(ооо|оао|зао|пао|ао|ип|llc|ltd|inc|гк|группа компаний)\b", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


async def upsert_employer(db: AsyncSession, nv: NormalizedVacancy) -> uuid.UUID | None:
    if not nv.employer_name:
        return None
    norm = normalize_employer_name(nv.employer_name)
    if nv.employer_hh_id:
        stmt = (
            insert(Employer)
            .values(
                id=uuid.uuid4(),
                hh_id=nv.employer_hh_id,
                name=nv.employer_name,
                normalized_name=norm,
                url=nv.employer_url,
            )
            .on_conflict_do_update(
                index_elements=["hh_id"],
                index_where=Employer.hh_id.isnot(None),
                set_={"name": nv.employer_name, "normalized_name": norm, "updated_at": utcnow()},
            )
            .returning(Employer.id)
        )
        return (await db.execute(stmt)).scalar_one()
    existing = (
        await db.execute(select(Employer.id).where(Employer.normalized_name == norm, Employer.hh_id.is_(None)).limit(1))
    ).scalar_one_or_none()
    if existing:
        return existing
    employer = Employer(id=uuid.uuid4(), name=nv.employer_name, normalized_name=norm)
    db.add(employer)
    await db.flush()
    return employer.id


def _apply(v: Vacancy, nv: NormalizedVacancy) -> None:
    for attr in (
        "url", "apply_url", "title", "employer_name", "employer_hh_id", "area_id", "area_name", "salary_from",
        "salary_to", "salary_currency", "salary_gross", "work_formats", "employment_type", "experience_id",
        "schedule", "description_text", "key_skills", "professional_roles", "published_at", "archived",
        "has_test", "response_letter_required",
    ):  # fmt: skip
        setattr(v, attr, getattr(nv, attr))


async def upsert_vacancy(
    db: AsyncSession,
    nv: NormalizedVacancy,
    *,
    source: VacancySource,
    owner_user_id: uuid.UUID | None = None,
) -> tuple[Vacancy, bool]:
    """Insert or update a vacancy. Returns (vacancy, content_changed). Snapshots keep content history.

    API vacancies are global (keyed by hh id). User-imported ones are private to the owner and never
    touch the shared record, so a user cannot alter what others see.
    """
    now = utcnow()
    content_hash = nv.content_hash()
    is_api = source == VacancySource.HH_API and nv.hh_id is not None
    if is_api:
        stmt = select(Vacancy).where(Vacancy.hh_id == nv.hh_id)
    elif nv.hh_id:
        stmt = select(Vacancy).where(
            Vacancy.owner_user_id == owner_user_id, Vacancy.hh_id.is_(None), Vacancy.source_ref == nv.hh_id
        )
    else:
        stmt = select(Vacancy).where(
            Vacancy.owner_user_id == owner_user_id, Vacancy.hh_id.is_(None), Vacancy.content_hash == content_hash
        )
    vacancy = (await db.execute(stmt.with_for_update())).scalar_one_or_none()
    employer_id = await upsert_employer(db, nv)
    changed = False
    if vacancy is None:
        vacancy = Vacancy(
            id=uuid.uuid4(),
            source=source.value,
            hh_id=nv.hh_id if is_api else None,
            source_ref=None if is_api else nv.hh_id,
            owner_user_id=None if is_api else owner_user_id,
            content_hash=content_hash,
            first_seen_at=now,
            last_seen_at=now,
            employer_id=employer_id,
        )
        _apply(vacancy, nv)
        db.add(vacancy)
        await db.flush()
        changed = True
    else:
        vacancy.last_seen_at = now
        # A search result carries only a snippet: never let it overwrite a full description.
        richer_existing = len(vacancy.description_text) > len(nv.description_text) and not nv.key_skills
        if vacancy.content_hash != content_hash and not richer_existing:
            _apply(vacancy, nv)
            vacancy.content_hash = content_hash
            vacancy.employer_id = employer_id
            changed = True
        elif nv.archived != vacancy.archived:
            vacancy.archived = nv.archived
            changed = True
    if changed:
        await db.execute(
            insert(VacancySnapshot)
            .values(
                id=uuid.uuid4(),
                vacancy_id=vacancy.id,
                content_hash=vacancy.content_hash,
                payload=nv.snapshot(),
                captured_at=now,
            )
            .on_conflict_do_nothing(index_elements=["vacancy_id", "content_hash"])
        )
    return vacancy, changed
