import uuid
from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    display_name: Mapped[str] = mapped_column(String(120), default="")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    # 152-ФЗ: explicit consent to process personal data, and a separate consent to send it to an external AI.
    pd_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ai_external_consent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    settings: Mapped[dict] = mapped_column(JSONB, default=dict)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UserSession(UUIDPk, Base):
    __tablename__ = "user_sessions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    user_agent: Mapped[str] = mapped_column(String(200), default="")


class TelegramLink(UUIDPk, Timestamps, Base):
    __tablename__ = "telegram_links"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    username: Mapped[str] = mapped_column(String(64), default="")
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class TelegramLinkCode(UUIDPk, Base):
    __tablename__ = "telegram_link_codes"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
