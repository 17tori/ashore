"""Test setup: a dedicated Postgres database and Redis db 15. External services are never called."""

import base64
import os
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://ashore:ashore@localhost:5432/ashore_test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ["ENVIRONMENT"] = "test"
os.environ["ENCRYPTION_KEYS"] = base64.urlsafe_b64encode(b"k" * 32).decode()
os.environ["AI_PROVIDER"] = "local"
os.environ["DEMO_MODE"] = "true"
for name in ("HH_CLIENT_ID", "HH_CLIENT_SECRET", "HH_APP_ACCESS_TOKEN", "HH_USER_AGENT", "TELEGRAM_BOT_TOKEN"):
    os.environ[name] = ""

import httpx  # noqa: E402
import pytest  # noqa: E402
from sqlalchemy import text  # noqa: E402

import app.models  # noqa: E402,F401
from app.core.config import get_settings  # noqa: E402
from app.core.crypto import reset_box  # noqa: E402
from app.core.redis import close_redis, get_redis  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import dispose_engine, get_engine, get_sessionmaker  # noqa: E402
from app.security.sessions import CSRF_COOKIE, CSRF_HEADER  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(scope="session", autouse=True)
async def _schema() -> AsyncIterator[None]:
    get_settings.cache_clear()
    reset_box()
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    yield
    await close_redis()
    await dispose_engine()


@pytest.fixture(autouse=True)
async def _clean() -> AsyncIterator[None]:
    yield
    tables = ", ".join(f'"{t.name}"' for t in Base.metadata.sorted_tables)
    async with get_engine().begin() as conn:
        await conn.execute(text(f"TRUNCATE {tables} CASCADE"))
    try:
        await get_redis().flushdb()
    except Exception:  # noqa: BLE001 - redis-less test runs are allowed
        pass


@pytest.fixture
async def db():
    async with get_sessionmaker()() as session:
        yield session
        await session.rollback()


@pytest.fixture
async def client() -> AsyncIterator[httpx.AsyncClient]:
    from app.main import create_app

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield c


class Api:
    """Thin wrapper that echoes the CSRF cookie like the frontend does."""

    def __init__(self, client: httpx.AsyncClient):
        self.c = client

    def _headers(self) -> dict[str, str]:
        token = self.c.cookies.get(CSRF_COOKIE)
        return {CSRF_HEADER: token} if token else {}

    async def get(self, url: str, **kw) -> httpx.Response:
        return await self.c.get(url, **kw)

    async def post(self, url: str, **kw) -> httpx.Response:
        return await self.c.post(url, headers=self._headers(), **kw)

    async def put(self, url: str, **kw) -> httpx.Response:
        return await self.c.put(url, headers=self._headers(), **kw)

    async def patch(self, url: str, **kw) -> httpx.Response:
        return await self.c.patch(url, headers=self._headers(), **kw)

    async def delete(self, url: str, **kw) -> httpx.Response:
        return await self.c.delete(url, headers=self._headers(), **kw)

    async def register(self, email: str | None = None, password: str = "correct-horse-battery") -> dict:
        r = await self.c.post(
            "/api/auth/register",
            json={"email": email or f"u{uuid.uuid4().hex[:8]}@example.com", "password": password, "pd_consent": True},
        )
        assert r.status_code == 201, r.text
        return r.json()


@pytest.fixture
async def api(client) -> Api:
    return Api(client)


@pytest.fixture
async def other_api() -> AsyncIterator[Api]:
    from app.main import create_app

    transport = httpx.ASGITransport(app=create_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as c:
        yield Api(c)


@pytest.fixture
def resume_text() -> str:
    return (FIXTURES / "resume_hh.txt").read_text(encoding="utf-8")
