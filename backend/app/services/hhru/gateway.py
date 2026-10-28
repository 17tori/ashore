"""Per-user access to hh.ru: encrypted tokens, refresh, circuit breaker, call metrics."""

import logging
import uuid
from datetime import timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.crypto import get_box
from app.db.base import utcnow
from app.models import IntegrationEvent, OAuthConnection
from app.models.enums import ConnectionStatus
from app.services.hhru.client import CallRecord, HhClient
from app.services.hhru.errors import (
    HhApiError,
    HhAuthError,
    HhCaptchaRequired,
    HhCircuitOpen,
    HhNetworkError,
    HhNotConfigured,
    HhRateLimited,
    HhServerError,
)
from app.services.hhru.oauth import HhOAuth, TokenPair
from app.services.notifications.service import notify

log = logging.getLogger(__name__)

_TRIPPING = (HhServerError, HhNetworkError, HhRateLimited)


def _aad(user_id: uuid.UUID, kind: str) -> str:
    return f"hh:{kind}:{user_id}"


def encrypt_tokens(conn: OAuthConnection, pair: TokenPair) -> None:
    box = get_box()
    conn.access_token_enc = box.encrypt(pair.access_token, _aad(conn.user_id, "access"))
    conn.refresh_token_enc = (
        box.encrypt(pair.refresh_token, _aad(conn.user_id, "refresh")) if pair.refresh_token else None
    )
    conn.access_expires_at = pair.expires_at


class HhGateway:
    def __init__(
        self,
        db: AsyncSession,
        user_id: uuid.UUID,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
        oauth: HhOAuth | None = None,
    ):
        self.db = db
        self.user_id = user_id
        self.settings = settings or get_settings()
        self._http = http
        self._oauth = oauth or HhOAuth(self.settings, http=http)

    async def _sink(self, record: CallRecord) -> None:
        self.db.add(
            IntegrationEvent(
                id=uuid.uuid4(),
                user_id=self.user_id,
                operation=record.operation,
                status_code=record.status_code,
                error_type=record.error_type,
                duration_ms=record.duration_ms,
                created_at=utcnow(),
            )
        )

    async def connection(self, *, for_update: bool = False) -> OAuthConnection | None:
        stmt = select(OAuthConnection).where(OAuthConnection.user_id == self.user_id)
        if for_update:
            stmt = stmt.with_for_update()
        return (await self.db.execute(stmt)).scalar_one_or_none()

    def _client(self, token: str | None) -> HhClient:
        return HhClient(token, settings=self.settings, http=self._http, on_call=self._sink)

    def app_client(self) -> HhClient | None:
        token = self.settings.hh_app_access_token.get_secret_value()
        if not token or not self.settings.hh_user_agent:
            return None
        return self._client(token)

    async def user_client(self) -> HhClient:
        """Client authorized as the user. Refreshes the access token when it has expired."""
        if not self.settings.hh_user_agent:
            raise HhNotConfigured("HH_USER_AGENT не задан")
        conn = await self.connection(for_update=True)
        if conn is None:
            raise HhNotConfigured("Аккаунт hh.ru не подключён")
        if conn.status in (ConnectionStatus.REVOKED, ConnectionStatus.EXPIRED):
            raise HhAuthError("Нужно заново подключить hh.ru", error_type="oauth", error_value=conn.status)
        now = utcnow()
        if conn.circuit_open_until and conn.circuit_open_until > now:
            raise HhCircuitOpen(f"Интеграция приостановлена до {conn.circuit_open_until.isoformat()}")
        box = get_box()
        if conn.access_expires_at and conn.access_expires_at <= now + timedelta(seconds=30):
            await self._refresh(conn)
        return self._client(box.decrypt(conn.access_token_enc, _aad(conn.user_id, "access")))

    async def _refresh(self, conn: OAuthConnection) -> None:
        if not conn.refresh_token_enc:
            await self._mark_auth_failure(conn, "refresh token missing")
            raise HhAuthError("Срок действия доступа hh.ru истёк", error_type="oauth", error_value="token_expired")
        refresh = get_box().decrypt(conn.refresh_token_enc, _aad(conn.user_id, "refresh"))
        try:
            pair = await self._oauth.refresh(refresh)
        except HhApiError as exc:
            if exc.status and 400 <= exc.status < 500:
                await self._mark_auth_failure(conn, exc.tag)
            raise
        encrypt_tokens(conn, pair)
        conn.status = ConnectionStatus.ACTIVE
        conn.last_error = None
        await self.db.flush()

    async def _mark_auth_failure(self, conn: OAuthConnection, detail: str) -> None:
        conn.status = ConnectionStatus.REVOKED if "revoked" in detail else ConnectionStatus.EXPIRED
        conn.last_error = detail[:500]
        await notify(
            self.db,
            self.user_id,
            kind="oauth_expired",
            title="Нужно заново подключить hh.ru",
            body="Доступ к hh.ru истёк или был отозван. Автоматические действия приостановлены.",
            dedupe_key=f"oauth_expired:{utcnow().date()}",
        )

    async def record_success(self) -> None:
        conn = await self.connection()
        if conn is not None and (conn.consecutive_failures or conn.circuit_open_until):
            conn.consecutive_failures = 0
            conn.circuit_open_until = None

    async def record_failure(self, exc: HhApiError) -> None:
        """Update the circuit breaker. Captcha opens it immediately; transient errors after a threshold."""
        conn = await self.connection()
        if conn is None:
            return
        conn.last_error = exc.tag[:500]
        if isinstance(exc, HhAuthError):
            await self._mark_auth_failure(conn, exc.tag)
            return
        if isinstance(exc, HhCaptchaRequired):
            conn.circuit_open_until = utcnow() + timedelta(seconds=self.settings.hh_circuit_cooldown_seconds)
            await notify(
                self.db,
                self.user_id,
                kind="manual_action",
                title="hh.ru запросил проверку капчей",
                body="Автоматизация остановлена. Откройте hh.ru и выполните действие вручную.",
                dedupe_key=f"captcha:{utcnow().date()}",
            )
            return
        if isinstance(exc, _TRIPPING):
            conn.consecutive_failures += 1
            if conn.consecutive_failures >= self.settings.hh_circuit_failure_threshold:
                conn.circuit_open_until = utcnow() + timedelta(seconds=self.settings.hh_circuit_cooldown_seconds)
                log.warning("hh circuit opened", extra={"user_id": str(self.user_id)})
