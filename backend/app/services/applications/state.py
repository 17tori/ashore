import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import Conflict
from app.db.base import utcnow
from app.models import Application, ApplicationEvent
from app.models.enums import ApplicationStatus as S

TRANSITIONS: dict[S, set[S]] = {
    S.FOUND: {S.ANALYZING, S.MATCHED, S.ARCHIVED},
    S.ANALYZING: {S.MATCHED, S.ARCHIVED},
    S.MATCHED: {S.AWAITING_CONFIRMATION, S.READY, S.SENT, S.ARCHIVED},
    S.AWAITING_CONFIRMATION: {S.READY, S.SENT, S.ARCHIVED},
    S.READY: {S.SENDING, S.AWAITING_CONFIRMATION, S.SENT, S.ARCHIVED},
    S.SENDING: {S.SENT, S.UNKNOWN, S.FAILED, S.READY, S.AWAITING_CONFIRMATION},
    S.UNKNOWN: {S.SENT, S.FAILED, S.READY, S.AWAITING_CONFIRMATION, S.ARCHIVED},
    S.FAILED: {S.READY, S.AWAITING_CONFIRMATION, S.SENT, S.ARCHIVED},
    S.SENT: {S.VIEWED, S.INVITATION, S.REJECTED, S.ARCHIVED},
    S.VIEWED: {S.INVITATION, S.REJECTED, S.ARCHIVED},
    S.INVITATION: {S.REJECTED, S.ARCHIVED},
    S.REJECTED: {S.ARCHIVED},
    S.ARCHIVED: set(),
}


def can_transition(current: str, target: str) -> bool:
    return S(target) in TRANSITIONS[S(current)]


async def transition(db: AsyncSession, app: Application, target: S, *, actor: str, note: str = "") -> None:
    if app.status == target:
        return
    if not can_transition(app.status, target):
        raise Conflict(f"Нельзя перевести отклик из «{app.status}» в «{target}»", code="invalid_transition")
    now = utcnow()
    db.add(
        ApplicationEvent(
            id=uuid.uuid4(),
            application_id=app.id,
            user_id=app.user_id,
            from_status=app.status,
            to_status=target.value,
            actor=actor,
            note=note[:1000],
            created_at=now,
        )
    )
    app.status = target.value
    app.status_changed_at = now
    if target == S.SENT and app.sent_at is None:
        app.sent_at = now
