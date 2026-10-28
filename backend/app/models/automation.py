import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk
from app.models.enums import AutomationMode


class AutomationPolicy(UUIDPk, Timestamps, Base):
    """User-confirmed automation rules. Auto-Apply works only while ``confirmed_rules_hash`` matches."""

    __tablename__ = "automation_policies"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    mode: Mapped[str] = mapped_column(String(16), default=AutomationMode.MANUAL)
    paused: Mapped[bool] = mapped_column(Boolean, default=False)
    paused_reason: Mapped[str | None] = mapped_column(String(300))
    paused_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    allowed_resume_ids: Mapped[list] = mapped_column(JSONB, default=list)
    allowed_positions: Mapped[list] = mapped_column(JSONB, default=list)
    min_score: Mapped[int] = mapped_column(Integer, default=75)
    salary_min: Mapped[int | None] = mapped_column(Integer)
    employment_types: Mapped[list] = mapped_column(JSONB, default=list)
    excluded_employers: Mapped[list] = mapped_column(JSONB, default=list)
    daily_limit: Mapped[int] = mapped_column(Integer, default=10)
    letter_rules: Mapped[dict] = mapped_column(JSONB, default=dict)
    stop_conditions: Mapped[dict] = mapped_column(JSONB, default=dict)
    apply_windows: Mapped[list] = mapped_column(JSONB, default=list)

    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_rules_hash: Mapped[str | None] = mapped_column(String(64))

    ai_monthly_budget: Mapped[float] = mapped_column(Numeric(10, 2), default=0)


class ScheduledJob(UUIDPk, Timestamps, Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = (UniqueConstraint("user_id", "kind", "search_profile_id"),)

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    search_profile_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("search_profiles.id", ondelete="CASCADE"))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    interval_minutes: Mapped[int] = mapped_column(Integer, default=60)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(16))
    last_error: Mapped[str | None] = mapped_column(String(500))
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)


class ResumeVisibilityAction(UUIDPk, Base):
    __tablename__ = "resume_visibility_actions"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    resume_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resumes.id", ondelete="CASCADE"), index=True)
    action: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    scheduled_for: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cost_amount: Mapped[float] = mapped_column(Numeric(10, 2), default=0)
    cost_currency: Mapped[str] = mapped_column(String(8), default="RUR")
    detail: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class Notification(UUIDPk, Base):
    __tablename__ = "notifications"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text, default="")
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    dedupe_key: Mapped[str | None] = mapped_column(String(128))
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    telegram_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)

    __table_args__ = (UniqueConstraint("user_id", "dedupe_key"),)


class AuditLog(UUIDPk, Base):
    __tablename__ = "audit_logs"

    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    actor: Mapped[str] = mapped_column(String(16))  # user / system / telegram / ai
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity_type: Mapped[str | None] = mapped_column(String(32))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


class AIUsageRecord(UUIDPk, Base):
    __tablename__ = "ai_usage_records"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    purpose: Mapped[str] = mapped_column(String(32))
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost: Mapped[float] = mapped_column(Numeric(12, 6), default=0)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
