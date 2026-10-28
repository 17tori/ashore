import uuid
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFound, Unauthorized
from app.db.base import Base
from app.db.session import get_db
from app.models import User
from app.security.sessions import SESSION_COOKIE, load_session_user, verify_csrf

DB = Annotated[AsyncSession, Depends(get_db)]


async def current_user(request: Request, db: DB) -> User:
    token = request.cookies.get(SESSION_COOKIE)
    if not token:
        raise Unauthorized("Требуется вход")
    user = await load_session_user(db, token)
    if user is None:
        raise Unauthorized("Сессия истекла")
    verify_csrf(request)
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(current_user)]


async def get_owned[T: Base](db: AsyncSession, model: type[T], obj_id: uuid.UUID, user: User) -> T:
    """Load a row owned by ``user``. Foreign rows answer 404, never 403, so ids do not leak (IDOR)."""
    obj = await db.get(model, obj_id)
    if obj is None or getattr(obj, "user_id", None) != user.id:
        raise NotFound("Объект не найден")
    return obj
