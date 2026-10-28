import uuid
from datetime import timedelta

from fastapi import Request, Response
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import constant_time_equals, random_token, token_hash
from app.core.errors import Forbidden
from app.db.base import utcnow
from app.models import User, UserSession

SESSION_COOKIE = "ashore_session"
CSRF_COOKIE = "ashore_csrf"
CSRF_HEADER = "x-csrf-token"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


async def create_session(db: AsyncSession, user: User, response: Response, user_agent: str = "") -> None:
    settings = get_settings()
    token = random_token()
    now = utcnow()
    db.add(
        UserSession(
            id=uuid.uuid4(),
            user_id=user.id,
            token_hash=token_hash(token),
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(hours=settings.session_ttl_hours),
            user_agent=user_agent[:200],
        )
    )
    max_age = settings.session_ttl_hours * 3600
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=max_age,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/",
    )
    response.set_cookie(
        CSRF_COOKIE,
        random_token(16),
        max_age=max_age,
        httponly=False,
        secure=settings.cookie_secure,
        samesite="strict",
        path="/",
    )


async def destroy_session(db: AsyncSession, request: Request, response: Response) -> None:
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        await db.execute(delete(UserSession).where(UserSession.token_hash == token_hash(token)))
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


async def load_session_user(db: AsyncSession, token: str) -> User | None:
    now = utcnow()
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, User.id == UserSession.user_id)
            .where(UserSession.token_hash == token_hash(token), UserSession.expires_at > now)
        )
    ).first()
    if row is None:
        return None
    session, user = row
    if user.deleted_at is not None:
        return None
    if (now - session.last_seen_at) > timedelta(minutes=5):
        session.last_seen_at = now
    return user


def verify_csrf(request: Request) -> None:
    """Double-submit check: the header must echo the CSRF cookie on every state-changing request."""
    if request.method not in UNSAFE_METHODS:
        return
    cookie = request.cookies.get(CSRF_COOKIE)
    header = request.headers.get(CSRF_HEADER)
    if not cookie or not header or not constant_time_equals(cookie, header):
        raise Forbidden("CSRF-токен отсутствует или неверен", code="csrf_failed")
