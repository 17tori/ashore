import httpx
import pytest
import respx

from app.core.config import Settings
from app.services.hhru.client import HhClient, TokenBucket, backoff_delay
from app.services.hhru.errors import (
    HhAmbiguousResult,
    HhAuthError,
    HhCaptchaRequired,
    HhForbidden,
    HhNotConfigured,
    HhRateLimited,
)
from app.services.hhru.oauth import HhOAuth
from app.services.hhru.query import build_search_params, max_pages
from tests.factories import search

BASE = "https://api.hh.ru"


def settings(**kw) -> Settings:
    data = {
        "hh_user_agent": "AshoreTest/0.1 (test@example.com)",
        "hh_client_id": "cid",
        "hh_client_secret": "csecret",
        "hh_requests_per_second": 1000,
        "encryption_keys": "a2tra2tra2tra2tra2tra2tra2tra2tra2tra2tra2s=",
    } | kw
    return Settings(**data)


async def _no_sleep(_: float) -> None:
    return None


def client(token: str | None = "tok", **kw) -> HhClient:
    return HhClient(token, settings=settings(**kw), sleep=_no_sleep)


@respx.mock
async def test_sends_required_headers():
    route = respx.get(f"{BASE}/me").mock(return_value=httpx.Response(200, json={"id": "1"}))
    async with client() as c:
        assert (await c.me())["id"] == "1"
    request = route.calls.last.request
    assert request.headers["HH-User-Agent"].startswith("AshoreTest")
    assert request.headers["Authorization"] == "Bearer tok"


@respx.mock
async def test_retries_get_on_5xx_and_429():
    route = respx.get(f"{BASE}/vacancies/1").mock(
        side_effect=[
            httpx.Response(503),
            httpx.Response(429, headers={"Retry-After": "0"}),
            httpx.Response(200, json={"id": "1"}),
        ]
    )
    async with client() as c:
        assert (await c.get_vacancy("1"))["id"] == "1"
    assert route.call_count == 3


@respx.mock
async def test_gives_up_after_max_retries():
    respx.get(f"{BASE}/vacancies/1").mock(return_value=httpx.Response(429))
    async with client(hh_max_retries=2) as c:
        with pytest.raises(HhRateLimited):
            await c.get_vacancy("1")


@respx.mock
async def test_error_parsing():
    respx.get(f"{BASE}/me").mock(
        return_value=httpx.Response(403, json={"errors": [{"type": "oauth", "value": "token_expired"}]})
    )
    async with client() as c:
        with pytest.raises(HhAuthError) as exc:
            await c.me()
    assert exc.value.tag == "oauth:token_expired"


@respx.mock
async def test_captcha_detected():
    respx.post(f"{BASE}/negotiations").mock(
        return_value=httpx.Response(403, json={"errors": [{"type": "captcha_required", "value": "captcha_required"}]})
    )
    async with client() as c:
        with pytest.raises(HhCaptchaRequired):
            await c.apply(vacancy_id="1", resume_id="r", message=None)


@respx.mock
async def test_apply_is_never_retried_after_timeout():
    route = respx.post(f"{BASE}/negotiations").mock(side_effect=httpx.ReadTimeout("slow"))
    async with client() as c:
        with pytest.raises(HhAmbiguousResult):
            await c.apply(vacancy_id="1", resume_id="r", message="Здравствуйте")
    assert route.call_count == 1


@respx.mock
async def test_apply_5xx_is_ambiguous():
    route = respx.post(f"{BASE}/negotiations").mock(return_value=httpx.Response(502))
    async with client() as c:
        with pytest.raises(HhAmbiguousResult):
            await c.apply(vacancy_id="1", resume_id="r", message=None)
    assert route.call_count == 1


@respx.mock
async def test_apply_connect_error_retried_once():
    route = respx.post(f"{BASE}/negotiations").mock(
        side_effect=[httpx.ConnectError("down"), httpx.Response(201, headers={"Location": "/negotiations/77"})]
    )
    async with client() as c:
        result = await c.apply(vacancy_id="1", resume_id="r", message=None)
    assert route.call_count == 2
    assert result["_location"] == "/negotiations/77"


@respx.mock
async def test_forbidden_is_not_retried():
    route = respx.post(f"{BASE}/negotiations").mock(
        return_value=httpx.Response(403, json={"errors": [{"type": "forbidden"}]})
    )
    async with client() as c:
        with pytest.raises(HhForbidden):
            await c.apply(vacancy_id="1", resume_id="r", message=None)
    assert route.call_count == 1


def test_backoff_bounded():
    assert all(0 <= backoff_delay(a) <= 30 for a in range(20))


async def test_token_bucket_limits_rate():
    import time

    bucket = TokenBucket(rate=20, capacity=1)
    start = time.monotonic()
    for _ in range(4):
        await bucket.acquire()
    assert time.monotonic() - start >= 0.14


def test_oauth_authorize_url_and_config():
    oauth = HhOAuth(settings())
    url = oauth.authorize_url("STATE123")
    assert url.startswith("https://hh.ru/oauth/authorize?")
    assert "state=STATE123" in url and "client_id=cid" in url and "response_type=code" in url
    with pytest.raises(HhNotConfigured):
        HhOAuth(settings(hh_client_id="")).authorize_url("x")


@respx.mock
async def test_oauth_exchange():
    respx.post("https://api.hh.ru/token").mock(
        return_value=httpx.Response(200, json={"access_token": "A", "refresh_token": "R", "expires_in": 1209600})
    )
    pair = await HhOAuth(settings()).exchange_code("code")
    assert pair.access_token == "A" and pair.refresh_token == "R" and pair.expires_at is not None


def test_search_params():
    profile = search(positions=["Python-разработчик"], experience=["noExperience"], work_formats=["remote"])
    params = build_search_params(profile, page=0, since=None)
    keys = [k for k, _ in params]
    assert ("text", '"Python-разработчик"') in params
    assert "area" in keys and "experience" in keys
    assert ("work_format", "REMOTE") in params
    legacy = build_search_params(profile, page=0, since=None, legacy=True)
    assert ("schedule", "remote") in legacy
    assert max_pages(10_000) * 100 <= 2000
