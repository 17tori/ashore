import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import CapabilityStatus, ConnectionStatus


class OAuthState(UUIDPk, Base):
    __tablename__ = "oauth_states"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class OAuthConnection(UUIDPk, Timestamps, Base):
    """hh.ru account link. Tokens are encrypted with AES-GCM bound to the user id."""

    __tablename__ = "oauth_connections"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    provider: Mapped[str] = mapped_column(String(16), default="hh")
    hh_user_id: Mapped[str | None] = mapped_column(String(64))
    account_label: Mapped[str] = mapped_column(String(200), default="")
    is_applicant: Mapped[bool | None] = mapped_column()
    access_token_enc: Mapped[str] = mapped_column(Text)
    refresh_token_enc: Mapped[str | None] = mapped_column(Text)
    access_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16), default=ConnectionStatus.ACTIVE)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    circuit_open_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(String(500))


class IntegrationCapability(UUIDPk, Base):
    __tablename__ = "integration_capabilities"
    __table_args__ = (UniqueConstraint("user_id", "capability"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    capability: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), default=CapabilityStatus.UNKNOWN)
    detail: Mapped[str] = mapped_column(String(500), default="")
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class IntegrationEvent(UUIDPk, Base):
    """One row per outbound hh.ru call: feeds API error analytics and incident investigation."""

    __tablename__ = "integration_events"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    operation: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    error_type: Mapped[str | None] = mapped_column(String(64))
    duration_ms: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
