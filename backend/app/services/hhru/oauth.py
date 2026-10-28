from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import urlencode

import httpx

from app.core.config import Settings, get_settings
from app.db.base import utcnow
from app.services.hhru.client import parse_error
from app.services.hhru.errors import HhNetworkError, HhNotConfigured


@dataclass(slots=True)
class TokenPair:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None


class HhOAuth:
    def __init__(self, settings: Settings | None = None, http: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._http = http

    def _require_config(self) -> None:
        if not self.settings.hh_configured:
            raise HhNotConfigured("HH_CLIENT_ID, HH_CLIENT_SECRET и HH_USER_AGENT не заданы")

    def authorize_url(self, state: str) -> str:
        self._require_config()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self.settings.hh_client_id,
                "state": state,
                "redirect_uri": self.settings.hh_redirect_uri,
            }
        )
        return f"{self.settings.hh_authorize_url}?{query}"

    async def _token_request(self, data: dict[str, str]) -> dict:
        self._require_config()
        http = self._http or httpx.AsyncClient(timeout=self.settings.hh_timeout_seconds)
        try:
            response = await http.post(
                self.settings.hh_token_url,
                data=data,
                headers={"HH-User-Agent": self.settings.hh_user_agent, "Accept": "application/json"},
            )
        except httpx.TransportError as exc:
            raise HhNetworkError(f"hh.ru token endpoint unreachable: {exc.__class__.__name__}") from exc
        finally:
            if self._http is None:
                await http.aclose()
        if response.status_code >= 400:
            raise parse_error(response)
        return response.json()

    @staticmethod
    def _pair(payload: dict) -> TokenPair:
        expires_in = payload.get("expires_in")
        return TokenPair(
            access_token=payload["access_token"],
            refresh_token=payload.get("refresh_token"),
            expires_at=utcnow() + timedelta(seconds=int(expires_in)) if expires_in else None,
        )

    async def exchange_code(self, code: str) -> TokenPair:
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": self.settings.hh_client_id,
                "client_secret": self.settings.hh_client_secret.get_secret_value(),
                "code": code,
                "redirect_uri": self.settings.hh_redirect_uri,
            }
        )
        return self._pair(payload)

    async def refresh(self, refresh_token: str) -> TokenPair:
        """hh.ru refresh tokens are single-use and only accepted after the access token expired."""
        payload = await self._token_request({"grant_type": "refresh_token", "refresh_token": refresh_token})
        return self._pair(payload)

    async def application_token(self) -> TokenPair:
        """Client-credentials token. hh.ru allows a new one at most every 5 minutes; it revokes the old one."""
        payload = await self._token_request(
            {
                "grant_type": "client_credentials",
                "client_id": self.settings.hh_client_id,
                "client_secret": self.settings.hh_client_secret.get_secret_value(),
            }
        )
        return self._pair(payload)
