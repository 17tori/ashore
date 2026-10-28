import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import ResumeSource


class Resume(UUIDPk, Timestamps, Base):
    """A resume version. Editing creates a new row with ``parent_id`` pointing at the previous version."""

    __tablename__ = "resumes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("resumes.id", ondelete="SET NULL"))
    version: Mapped[int] = mapped_column(Integer, default=1)
    title: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(16), default=ResumeSource.UPLOAD)
    file_name: Mapped[str | None] = mapped_column(String(255))
    # Raw text and contact details are personal data: stored encrypted.
    raw_text_enc: Mapped[str | None] = mapped_column(Text)
    contacts_enc: Mapped[str | None] = mapped_column(Text)
    profile: Mapped[dict] = mapped_column(JSONB, default=dict)
    profile_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    quality: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    hh_resume_id: Mapped[str | None] = mapped_column(String(64), index=True)
    hh_status: Mapped[str | None] = mapped_column(String(32))
    hh_can_publish: Mapped[bool | None] = mapped_column(Boolean)
    hh_next_publish_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hh_last_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hh_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
