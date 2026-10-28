import uuid
from typing import Any

from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import Notification

NOTIFICATION_KINDS = {
    "new_matches",
    "invitation",
    "employer_reply",
    "oauth_expired",
    "manual_action",
    "awaiting_confirmation",
    "automation_paused",
    "daily_report",
    "visibility_reminder",
    "application_failed",
}


async def notify(
    db: AsyncSession,
    user_id: uuid.UUID,
    *,
    kind: str,
    title: str,
    body: str = "",
    payload: dict[str, Any] | None = None,
    dedupe_key: str | None = None,
) -> None:
    """Store an in-app notification; the Telegram dispatcher picks it up later. Duplicates are ignored."""
    stmt = (
        insert(Notification)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            kind=kind,
            title=title[:200],
            body=body,
            payload=payload or {},
            dedupe_key=dedupe_key,
            created_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["user_id", "dedupe_key"])
    )
    await db.execute(stmt)
