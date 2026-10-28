import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import VacancySource


class Employer(UUIDPk, Timestamps, Base):
    __tablename__ = "employers"
    __table_args__ = (Index("uq_employers_hh_id", "hh_id", unique=True, postgresql_where=text("hh_id IS NOT NULL")),)

    hh_id: Mapped[str | None] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(300))
    normalized_name: Mapped[str] = mapped_column(String(300), index=True)
    url: Mapped[str | None] = mapped_column(String(500))
    trusted: Mapped[bool | None] = mapped_column(Boolean)


class Vacancy(UUIDPk, Timestamps, Base):
    """Normalized vacancy. hh.ru vacancies are public and shared; manual ones belong to one user."""

    __tablename__ = "vacancies"
    __table_args__ = (
        Index("uq_vacancies_hh_id", "hh_id", unique=True, postgresql_where=text("hh_id IS NOT NULL")),
        Index(
            "uq_vacancies_owner_hash",
            "owner_user_id",
            "content_hash",
            unique=True,
            postgresql_where=text("hh_id IS NULL"),
        ),
        Index(
            "uq_vacancies_owner_ref",
            "owner_user_id",
            "source_ref",
            unique=True,
            postgresql_where=text("hh_id IS NULL AND source_ref IS NOT NULL"),
        ),
        Index("ix_vacancies_published_at", "published_at"),
        Index("ix_vacancies_salary", "salary_from", "salary_to"),
    )

    source: Mapped[str] = mapped_column(String(16), default=VacancySource.HH_API)
    hh_id: Mapped[str | None] = mapped_column(String(32))
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    # hh.ru id of a user-imported vacancy. Kept apart from ``hh_id`` so user-supplied text never
    # overwrites the shared record that came from the API.
    source_ref: Mapped[str | None] = mapped_column(String(32))
    url: Mapped[str | None] = mapped_column(String(500))
    apply_url: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str] = mapped_column(String(300))
    employer_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("employers.id", ondelete="SET NULL"))
    employer_name: Mapped[str] = mapped_column(String(300), default="")
    employer_hh_id: Mapped[str | None] = mapped_column(String(32), index=True)
    area_id: Mapped[str | None] = mapped_column(String(16), index=True)
    area_name: Mapped[str | None] = mapped_column(String(120))
    salary_from: Mapped[int | None] = mapped_column(Integer)
    salary_to: Mapped[int | None] = mapped_column(Integer)
    salary_currency: Mapped[str | None] = mapped_column(String(8))
    salary_gross: Mapped[bool | None] = mapped_column(Boolean)
    work_formats: Mapped[list] = mapped_column(JSONB, default=list)
    employment_type: Mapped[str | None] = mapped_column(String(32))
    experience_id: Mapped[str | None] = mapped_column(String(32))
    schedule: Mapped[str | None] = mapped_column(String(32))
    description_text: Mapped[str] = mapped_column(Text, default="")
    key_skills: Mapped[list] = mapped_column(JSONB, default=list)
    professional_roles: Mapped[list] = mapped_column(JSONB, default=list)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    has_test: Mapped[bool] = mapped_column(Boolean, default=False)
    response_letter_required: Mapped[bool] = mapped_column(Boolean, default=False)
    content_hash: Mapped[str] = mapped_column(String(64))
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VacancySnapshot(UUIDPk, Base):
    """History of vacancy content. A new row only when the content hash changes."""

    __tablename__ = "vacancy_snapshots"
    __table_args__ = (UniqueConstraint("vacancy_id", "content_hash"),)

    vacancy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    content_hash: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict] = mapped_column(JSONB)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VacancyMatch(UUIDPk, Timestamps, Base):
    """The user's inbox entry for a vacancy and its analysis."""

    __tablename__ = "vacancy_matches"
    __table_args__ = (
        UniqueConstraint("user_id", "vacancy_id"),
        Index("ix_vacancy_matches_user_decision", "user_id", "decision"),
        Index("ix_vacancy_matches_user_score", "user_id", "score"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    vacancy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    search_profile_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("search_profiles.id", ondelete="SET NULL"), index=True
    )
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    analyzed_content_hash: Mapped[str | None] = mapped_column(String(64))
    score: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str | None] = mapped_column(String(24))
    user_decision: Mapped[str | None] = mapped_column(String(24))
    analysis: Mapped[dict] = mapped_column(JSONB, default=dict)
    analysis_source: Mapped[str] = mapped_column(String(16), default="local")
    hidden: Mapped[bool] = mapped_column(Boolean, default=False)
    times_seen: Mapped[int] = mapped_column(Integer, default=1)
    discovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    @property
    def effective_decision(self) -> str | None:
        return self.user_decision or self.decision
