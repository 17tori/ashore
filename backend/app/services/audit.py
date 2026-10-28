import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import redact, request_id_var
from app.db.base import utcnow
from app.models import AuditLog


async def audit(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None,
    action: str,
    actor: str = "user",
    entity_type: str | None = None,
    entity_id: Any = None,
    details: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            actor=actor,
            action=action,
            entity_type=entity_type,
            entity_id=str(entity_id) if entity_id is not None else None,
            details=redact(details or {}),
            request_id=request_id_var.get(),
            created_at=utcnow(),
        )
    )
