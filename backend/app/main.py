import logging
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api import (
    analytics,
    applications,
    auth,
    automation,
    demo,
    health,
    hh,
    notifications,
    resumes,
    search_profiles,
    settings,
    telegram,
    vacancies,
)
from app.core.config import get_settings
from app.core.errors import AppError
from app.core.logging import configure_logging, request_id_var
from app.core.redis import close_redis, rate_limit_hit
from app.db.session import dispose_engine
from app.services.hhru.errors import HhApiError, HhCircuitOpen, HhNotConfigured

log = logging.getLogger("app")

API_RATE_LIMIT = 300  # requests per minute per client, on top of the per-endpoint limits
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
    "Cache-Control": "no-store",
}


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    configure_logging(get_settings().log_level)
    yield
    await close_redis()
    await dispose_engine()


def _error(status: int, code: str, message: str, details: dict | None = None) -> JSONResponse:
    return JSONResponse(
        {"error": {"code": code, "message": message, "details": details or {}, "request_id": request_id_var.get()}},
        status_code=status,
    )


def create_app() -> FastAPI:
    config = get_settings()
    app = FastAPI(
        title=config.app_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs" if config.environment != "production" else None,
        openapi_url="/api/openapi.json" if config.environment != "production" else None,
        redoc_url=None,
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        rid = request.headers.get("x-request-id", "")
        rid = rid if rid and len(rid) <= 64 and rid.replace("-", "").isalnum() else uuid.uuid4().hex
        token = request_id_var.set(rid)
        try:
            path = request.url.path
            if path.startswith("/api/") and not path.startswith("/api/health") and path != "/api/telegram/webhook":
                client = request.headers.get("x-forwarded-for", "").split(",")[0].strip() or (
                    request.client.host if request.client else "?"
                )
                if not await rate_limit_hit(f"api:{client}", API_RATE_LIMIT, 60):
                    response = _error(429, "rate_limited", "Слишком много запросов, подождите минуту")
                    response.headers["X-Request-ID"] = rid
                    return response
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            for key, value in SECURITY_HEADERS.items():
                response.headers.setdefault(key, value)
            return response
        finally:
            request_id_var.reset(token)

    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, exc.details)

    @app.exception_handler(HhApiError)
    async def hh_error(_: Request, exc: HhApiError) -> JSONResponse:
        if isinstance(exc, HhNotConfigured):
            return _error(409, "integration_unavailable", "Интеграция с hh.ru не настроена")
        if isinstance(exc, HhCircuitOpen):
            return _error(503, "hh_paused", "Запросы к hh.ru временно приостановлены после серии ошибок")
        log.warning("hh.ru error", extra={"tag": exc.tag, "status": exc.status})
        return _error(502, "hh_error", "hh.ru вернул ошибку", {"tag": exc.tag})

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError) -> JSONResponse:
        fields = [
            {
                "field": ".".join(str(p) for p in e.get("loc", ())[1:]),
                "message": e.get("msg", ""),
                "type": e.get("type", ""),
            }
            for e in exc.errors()
        ]
        return _error(422, "validation_error", "Проверьте введённые данные", {"fields": fields})

    @app.exception_handler(Exception)
    async def unhandled(_: Request, exc: Exception) -> JSONResponse:
        log.exception("unhandled error")
        return _error(500, "internal_error", "Внутренняя ошибка. Мы уже записали её в журнал.")

    for module in (
        health,
        auth,
        hh,
        resumes,
        search_profiles,
        vacancies,
        applications,
        automation,
        analytics,
        notifications,
        settings,
        telegram,
        demo,
    ):
        app.include_router(module.router)
    return app


app = create_app()
