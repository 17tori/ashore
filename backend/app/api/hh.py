import uuid
from datetime import timedelta

from fastapi import APIRouter
from fastapi.responses import RedirectResponse
from sqlalchemy import delete, select

from app.core.config import get_settings
from app.core.crypto import random_token, token_hash
from app.core.errors import AppError, IntegrationUnavailable
from app.db.base import utcnow
from app.models import IntegrationCapability, OAuthConnection, OAuthState
from app.models.enums import ConnectionStatus
from app.security.deps import DB, CurrentUser
from app.services.audit import audit
from app.services.hhru.capabilities import capability_map, probe_capabilities
from app.services.hhru.errors import HhApiError, HhNotConfigured
from app.services.hhru.gateway import HhGateway, encrypt_tokens
from app.services.hhru.oauth import HhOAuth
from app.services.visibility.manager import import_hh_resumes

router = APIRouter(prefix="/api/hh", tags=["hh.ru"])
STATE_TTL = timedelta(minutes=10)


@router.get("/status")
async def status(db: DB, user: CurrentUser) -> dict:
    settings = get_settings()
    conn = (await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))).scalar_one_or_none()
    return {
        "configured": settings.hh_configured,
        "app_token_configured": bool(settings.hh_app_access_token.get_secret_value()),
        "connection": None
        if conn is None
        else {
            "status": conn.status,
            "account_label": conn.account_label,
            "is_applicant": conn.is_applicant,
            "access_expires_at": conn.access_expires_at,
            "last_checked_at": conn.last_checked_at,
            "circuit_open_until": conn.circuit_open_until,
            "last_error": conn.last_error,
            "connected_at": conn.created_at,
        },
        "capabilities": await capability_map(db, user.id),
        "redirect_uri": settings.hh_redirect_uri,
    }


@router.post("/connect")
async def connect(db: DB, user: CurrentUser) -> dict:
    oauth = HhOAuth()
    state = random_token()
    try:
        url = oauth.authorize_url(state)
    except HhNotConfigured as exc:
        raise IntegrationUnavailable(
            "Интеграция с hh.ru не настроена: нужно зарегистрированное приложение на dev.hh.ru"
        ) from exc
    now = utcnow()
    db.add(
        OAuthState(
            id=uuid.uuid4(), user_id=user.id, state_hash=token_hash(state), created_at=now, expires_at=now + STATE_TTL
        )
    )
    return {"authorize_url": url}


@router.get("/oauth/callback")
async def callback(
    db: DB, user: CurrentUser, code: str | None = None, state: str | None = None, error: str | None = None
) -> RedirectResponse:
    base = get_settings().public_base_url
    if error or not code or not state:
        return RedirectResponse(f"{base}/settings?hh=denied", status_code=303)
    row = (
        await db.execute(select(OAuthState).where(OAuthState.state_hash == token_hash(state)).with_for_update())
    ).scalar_one_or_none()
    # The state must exist, be fresh, unused, and belong to the user whose browser completes the flow.
    if row is None or row.used_at is not None or row.expires_at < utcnow() or row.user_id != user.id:
        await audit(db, user_id=user.id, action="hh.oauth_state_rejected")
        return RedirectResponse(f"{base}/settings?hh=invalid_state", status_code=303)
    row.used_at = utcnow()
    try:
        pair = await HhOAuth().exchange_code(code)
    except HhApiError as exc:
        await audit(db, user_id=user.id, action="hh.oauth_exchange_failed", details={"error": exc.tag})
        return RedirectResponse(f"{base}/settings?hh=exchange_failed", status_code=303)
    conn = (await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))).scalar_one_or_none()
    if conn is None:
        conn = OAuthConnection(id=uuid.uuid4(), user_id=user.id, access_token_enc="")
        db.add(conn)
    encrypt_tokens(conn, pair)
    conn.status = ConnectionStatus.ACTIVE
    conn.consecutive_failures = 0
    conn.circuit_open_until = None
    conn.last_error = None
    await db.flush()
    gateway = HhGateway(db, user.id)
    try:
        client = await gateway.user_client()
        async with client:
            me = await client.me()
        conn.hh_user_id = str(me.get("id")) if me.get("id") else None
        conn.is_applicant = me.get("is_applicant")
        conn.account_label = " ".join(filter(None, [me.get("first_name"), (me.get("last_name") or "")[:1] + "."]))[:200]
        conn.last_checked_at = utcnow()
        await probe_capabilities(db, user.id, gateway)
    except HhApiError as exc:
        conn.last_error = exc.tag
    await audit(db, user_id=user.id, action="hh.connected")
    return RedirectResponse(f"{base}/settings?hh=connected", status_code=303)


@router.post("/probe")
async def probe(db: DB, user: CurrentUser) -> dict:
    return await probe_capabilities(db, user.id, HhGateway(db, user.id))


@router.delete("/connection", status_code=204)
async def disconnect(db: DB, user: CurrentUser) -> None:
    await db.execute(delete(OAuthConnection).where(OAuthConnection.user_id == user.id))
    await db.execute(delete(IntegrationCapability).where(IntegrationCapability.user_id == user.id))
    await audit(db, user_id=user.id, action="hh.disconnected")


@router.post("/import-resumes")
async def import_resumes(db: DB, user: CurrentUser) -> dict:
    try:
        count = await import_hh_resumes(db, user, HhGateway(db, user.id))
    except HhApiError as exc:
        raise AppError(f"hh.ru вернул ошибку: {exc.tag}", code="hh_error") from exc
    if count == 0:
        raise IntegrationUnavailable("Импорт резюме через API недоступен: загрузите резюме файлом (PDF/DOCX с hh.ru)")
    return {"imported": count}
