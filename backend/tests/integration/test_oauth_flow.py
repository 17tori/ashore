from urllib.parse import parse_qs, urlparse

from sqlalchemy import select

import app.api.hh as hh_api
from app.core.config import Settings
from app.core.crypto import get_box
from app.db.base import utcnow
from app.db.session import get_sessionmaker
from app.models import OAuthConnection
from app.services.hhru.oauth import TokenPair

CONFIGURED = Settings(hh_client_id="cid", hh_client_secret="secret", hh_user_agent="AshoreTest/0.1 (t@example.com)")


class FakeOAuth:
    exchanged: list[str] = []

    def __init__(self, *a, **kw):
        pass

    def authorize_url(self, state: str) -> str:
        return f"https://hh.ru/oauth/authorize?response_type=code&client_id=cid&state={state}"

    async def exchange_code(self, code: str) -> TokenPair:
        FakeOAuth.exchanged.append(code)
        return TokenPair("ACCESS-SECRET", "REFRESH-SECRET", utcnow())


def _patch(monkeypatch):
    monkeypatch.setattr(hh_api, "get_settings", lambda: CONFIGURED)
    monkeypatch.setattr(hh_api, "HhOAuth", FakeOAuth)
    FakeOAuth.exchanged = []


async def _state(api) -> str:
    url = (await api.post("/api/hh/connect")).json()["authorize_url"]
    return parse_qs(urlparse(url).query)["state"][0]


async def test_callback_stores_encrypted_tokens(monkeypatch, api):
    _patch(monkeypatch)
    user = await api.register()
    state = await _state(api)
    r = await api.get(f"/api/hh/oauth/callback?code=abc&state={state}")
    assert r.status_code == 303 and r.headers["location"].endswith("hh=connected")
    async with get_sessionmaker()() as db:
        conn = (await db.execute(select(OAuthConnection))).scalar_one()
    assert str(conn.user_id) == user["id"]
    assert "ACCESS-SECRET" not in conn.access_token_enc
    assert get_box().decrypt(conn.access_token_enc, f"hh:access:{conn.user_id}") == "ACCESS-SECRET"

    # The state is single-use.
    r = await api.get(f"/api/hh/oauth/callback?code=abc&state={state}")
    assert r.headers["location"].endswith("hh=invalid_state")
    assert FakeOAuth.exchanged == ["abc"]


async def test_state_bound_to_user(monkeypatch, api, other_api):
    _patch(monkeypatch)
    await api.register()
    state = await _state(api)
    await other_api.register()
    r = await other_api.get(f"/api/hh/oauth/callback?code=abc&state={state}")
    assert r.headers["location"].endswith("hh=invalid_state")
    assert FakeOAuth.exchanged == []


async def test_unknown_state_and_denial(monkeypatch, api):
    _patch(monkeypatch)
    await api.register()
    assert (await api.get("/api/hh/oauth/callback?code=abc&state=forged")).headers["location"].endswith("invalid_state")
    assert (await api.get("/api/hh/oauth/callback?error=access_denied")).headers["location"].endswith("hh=denied")
