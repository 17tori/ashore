import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import ApplicationStatus


class CoverLetter(UUIDPk, Timestamps, Base):
    __tablename__ = "cover_letters"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    vacancy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    template_kind: Mapped[str] = mapped_column(String(32))
    tone: Mapped[str] = mapped_column(String(16))
    length: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    generator: Mapped[str] = mapped_column(String(16), default="local")
    validation: Mapped[dict] = mapped_column(JSONB, default=dict)
    edited_by_user: Mapped[bool] = mapped_column(Boolean, default=False)


class Application(UUIDPk, Timestamps, Base):
    """At most one application per user and vacancy. ``idempotency_key`` guards the platform call."""

    __tablename__ = "applications"
    __table_args__ = (
        UniqueConstraint("user_id", "vacancy_id"),
        Index("ix_applications_user_status", "user_id", "status"),
        Index("ix_applications_user_sent_at", "user_id", "sent_at"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    vacancy_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("vacancies.id", ondelete="CASCADE"))
    match_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("vacancy_matches.id", ondelete="SET NULL"))
    search_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("search_profiles.id", ondelete="SET NULL"))
    resume_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    cover_letter_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("cover_letters.id", ondelete="SET NULL"))
    status: Mapped[str] = mapped_column(String(32), default=ApplicationStatus.FOUND)
    channel: Mapped[str | None] = mapped_column(String(16))  # api / manual
    confirmed_by: Mapped[str | None] = mapped_column(String(16))  # platform / user
    idempotency_key: Mapped[str] = mapped_column(String(64), unique=True)
    hh_negotiation_id: Mapped[str | None] = mapped_column(String(64))
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))
    platform_response: Mapped[dict] = mapped_column(JSONB, default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")


class ApplicationEvent(UUIDPk, Base):
    __tablename__ = "application_events"

    application_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(32))
    to_status: Mapped[str] = mapped_column(String(32))
    actor: Mapped[str] = mapped_column(String(16))  # system / user / platform / telegram
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
