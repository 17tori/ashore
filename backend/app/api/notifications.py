import uuid

from fastapi import APIRouter, Query
from sqlalchemy import func, select, update

from app.api.serializers import notification_out
from app.db.base import utcnow
from app.models import Notification
from app.security.deps import DB, CurrentUser, get_owned

router = APIRouter(prefix="/api/notifications", tags=["notifications"])


@router.get("")
async def list_notifications(
    db: DB, user: CurrentUser, unread_only: bool = False, limit: int = Query(default=50, ge=1, le=200)
) -> dict:
    stmt = select(Notification).where(Notification.user_id == user.id)
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    rows = (await db.execute(stmt.order_by(Notification.created_at.desc()).limit(limit))).scalars()
    unread = (
        await db.execute(select(func.count()).where(Notification.user_id == user.id, Notification.read_at.is_(None)))
    ).scalar_one()
    return {"items": [notification_out(n) for n in rows], "unread": unread}


@router.post("/{notification_id}/read")
async def mark_read(notification_id: uuid.UUID, db: DB, user: CurrentUser) -> dict:
    n = await get_owned(db, Notification, notification_id, user)
    n.read_at = n.read_at or utcnow()
    return notification_out(n)


@router.post("/read-all")
async def read_all(db: DB, user: CurrentUser) -> dict:
    result = await db.execute(
        update(Notification)
        .where(Notification.user_id == user.id, Notification.read_at.is_(None))
        .values(read_at=utcnow())
    )
    return {"updated": result.rowcount}
