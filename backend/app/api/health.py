from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import get_settings
from app.core.redis import redis_healthy
from app.db.session import get_sessionmaker

router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("")
async def liveness() -> dict:
    return {"status": "ok"}


@router.get("/ready")
async def readiness() -> JSONResponse:
    checks: dict[str, str] = {}
    try:
        async with get_sessionmaker()() as db:
            await db.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception:
        checks["database"] = "unavailable"
    checks["redis"] = "ok" if await redis_healthy() else "unavailable"
    settings = get_settings()
    checks["hh_integration"] = "configured" if settings.hh_configured else "not_configured"
    checks["ai_provider"] = settings.ai_provider
    if checks["database"] != "ok":
        status, code = "unavailable", 503
    elif checks["redis"] != "ok":
        status, code = "degraded", 200
    else:
        status, code = "ok", 200
    return JSONResponse({"status": status, "checks": checks}, status_code=code)
