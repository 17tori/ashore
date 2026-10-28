import uuid

from fastapi import APIRouter, Request, Response
from sqlalchemy import select

from app.api.serializers import user_out
from app.core.errors import Conflict, TooManyRequests, Unauthorized
from app.core.redis import rate_limit_hit
from app.db.base import utcnow
from app.models import User
from app.schemas.api import LoginIn, RegisterIn
from app.security.deps import DB, CurrentUser
from app.security.passwords import hash_password, needs_rehash, verify_password
from app.security.sessions import create_session, destroy_session
from app.services.audit import audit
from app.services.automation.policy import get_policy

router = APIRouter(prefix="/api/auth", tags=["auth"])

# Equalizes timing between unknown emails and wrong passwords.
_DUMMY_HASH = hash_password("timing-equalizer-not-a-real-password")


def _client_ip(request: Request) -> str:
    return request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
        request.client.host if request.client else "?"
    )


@router.post("/register", status_code=201)
async def register(body: RegisterIn, request: Request, response: Response, db: DB) -> dict:
    if not await rate_limit_hit(f"register:{_client_ip(request)}", 10, 3600):
        raise TooManyRequests("Слишком много регистраций, попробуйте позже")
    email = body.email.lower()
    if (await db.execute(select(User.id).where(User.email == email))).scalar_one_or_none():
        raise Conflict("Пользователь с таким email уже существует", code="email_taken")
    now = utcnow()
    user = User(
        id=uuid.uuid4(),
        email=email,
        password_hash=hash_password(body.password),
        display_name=body.display_name,
        timezone=body.timezone,
        pd_consent_at=now,
        settings={"notifications": {"telegram": True}, "visibility": {"enabled": True, "auto_publish": False}},
    )
    db.add(user)
    await db.flush()
    await get_policy(db, user.id)
    await audit(db, user_id=user.id, action="auth.registered", details={"pd_consent_at": now.isoformat()})
    await create_session(db, user, response, request.headers.get("user-agent", ""))
    return user_out(user)


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response, db: DB) -> dict:
    email = body.email.lower()
    if not await rate_limit_hit(f"login:{_client_ip(request)}:{email}", 10, 900):
        raise TooManyRequests("Слишком много попыток входа, подождите 15 минут")
    user = (await db.execute(select(User).where(User.email == email, User.deleted_at.is_(None)))).scalar_one_or_none()
    if user is None:
        verify_password(_DUMMY_HASH, body.password)
        raise Unauthorized("Неверный email или пароль", code="bad_credentials")
    if not verify_password(user.password_hash, body.password):
        await audit(db, user_id=user.id, action="auth.login_failed")
        raise Unauthorized("Неверный email или пароль", code="bad_credentials")
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(body.password)
    await create_session(db, user, response, request.headers.get("user-agent", ""))
    await audit(db, user_id=user.id, action="auth.login")
    return user_out(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: DB, user: CurrentUser) -> Response:
    await destroy_session(db, request, response)
    response.status_code = 204
    return response


@router.get("/me")
async def me(user: CurrentUser) -> dict:
    return user_out(user)
