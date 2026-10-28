import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class SearchProfile(UUIDPk, Timestamps, Base):
    """One career direction: its own filters, resume, thresholds, limits and letter settings."""

    __tablename__ = "search_profiles"
    __table_args__ = (UniqueConstraint("user_id", "name"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(120))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))

    positions: Mapped[list] = mapped_column(JSONB, default=list)
    skills: Mapped[list] = mapped_column(JSONB, default=list)
    areas: Mapped[list] = mapped_column(JSONB, default=list)  # [{"id": "1", "name": "Москва"}]
    work_formats: Mapped[list] = mapped_column(JSONB, default=list)  # remote / on_site / hybrid / field_work
    employment_types: Mapped[list] = mapped_column(JSONB, default=list)  # full / part / project / internship
    experience: Mapped[list] = mapped_column(JSONB, default=list)  # hh ids: noExperience, between1And3, ...
    salary_min: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(8), default="RUR")
    only_with_salary: Mapped[bool] = mapped_column(Boolean, default=False)
    industries: Mapped[list] = mapped_column(JSONB, default=list)
    excluded_employers: Mapped[list] = mapped_column(JSONB, default=list)  # [{"id": "...", "name": "..."}]
    excluded_keywords: Mapped[list] = mapped_column(JSONB, default=list)
    period_days: Mapped[int] = mapped_column(Integer, default=7)

    eligible_threshold: Mapped[int] = mapped_column(Integer, default=70)
    review_threshold: Mapped[int] = mapped_column(Integer, default=50)
    daily_apply_limit: Mapped[int] = mapped_column(Integer, default=10)
    weights: Mapped[dict] = mapped_column(JSONB, default=dict)

    letter_template: Mapped[str] = mapped_column(String(32), default="junior_developer")
    letter_tone: Mapped[str] = mapped_column(String(16), default="neutral")
    letter_length: Mapped[str] = mapped_column(String(16), default="short")
    letter_mode: Mapped[str] = mapped_column(String(16), default="always")  # always / when_required / never

    search_interval_minutes: Mapped[int] = mapped_column(Integer, default=120)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
