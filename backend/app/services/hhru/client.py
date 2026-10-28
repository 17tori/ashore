"""Thin, strict client for the official hh.ru API.

* Sends ``HH-User-Agent`` on every call (required by hh.ru).
* Rate limits itself with a token bucket and honours ``429`` / ``Retry-After``.
* Retries only idempotent requests, with exponential backoff and full jitter.
* A non-idempotent request (``POST /negotiations``) is never retried after it may have reached hh.ru:
  a timeout raises ``HhAmbiguousResult`` so the caller can reconcile instead of re-sending.
"""

import asyncio
import logging
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import Settings, get_settings
from app.services.hhru.errors import (
    HhAmbiguousResult,
    HhApiError,
    HhAuthError,
    HhCaptchaRequired,
    HhForbidden,
    HhNetworkError,
    HhNotFound,
    HhRateLimited,
    HhServerError,
)

log = logging.getLogger(__name__)


@dataclass(slots=True)
class CallRecord:
    operation: str
    status_code: int | None
    error_type: str | None
    duration_ms: int


EventSink = Callable[[CallRecord], Awaitable[None]]


class TokenBucket:
    def __init__(self, rate: float, capacity: float | None = None):
        self.rate = max(rate, 0.01)
        self.capacity = capacity or max(1.0, rate)
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:
            while True:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= 1:
                    self._tokens -= 1
                    return
                await asyncio.sleep((1 - self._tokens) / self.rate)


_bucket: TokenBucket | None = None


def shared_bucket(settings: Settings) -> TokenBucket:
    global _bucket
    if _bucket is None or _bucket.rate != settings.hh_requests_per_second:
        _bucket = TokenBucket(settings.hh_requests_per_second)
    return _bucket


def backoff_delay(attempt: int, base: float = 0.5, cap: float = 30.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * (2**attempt)))  # noqa: S311 - jitter, not crypto


def parse_error(response: httpx.Response) -> HhApiError:
    status = response.status_code
    body: Any
    try:
        body = response.json()
    except ValueError:
        body = None
    err_type = err_value = None
    if isinstance(body, dict):
        errors = body.get("errors") or []
        if errors and isinstance(errors[0], dict):
            err_type = errors[0].get("type")
            err_value = errors[0].get("value")
        elif "error" in body:  # OAuth token endpoint (RFC 6749 format)
            err_type = str(body.get("error"))
            err_value = str(body.get("error_description") or "")
    msg = f"hh.ru {status} {err_type or ''} {err_value or ''}".strip()
    kwargs = {"status": status, "error_type": err_type, "error_value": err_value, "body": body}
    if err_type == "captcha_required" or (err_value or "") == "captcha_required":
        return HhCaptchaRequired(msg, **kwargs)
    if status == 429:
        retry_after = response.headers.get("Retry-After")
        return HhRateLimited(msg, retry_after=float(retry_after) if retry_after else None, **kwargs)
    if status >= 500:
        return HhServerError(msg, **kwargs)
    if err_type == "oauth" or status == 401:
        return HhAuthError(msg, **kwargs)
    if status == 404:
        return HhNotFound(msg, **kwargs)
    if status == 403:
        return HhForbidden(msg, **kwargs)
    return HhApiError(msg, **kwargs)


class HhClient:
    def __init__(
        self,
        access_token: str | None = None,
        *,
        settings: Settings | None = None,
        http: httpx.AsyncClient | None = None,
        on_call: EventSink | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        self.settings = settings or get_settings()
        self.access_token = access_token
        self._http = http
        self._owns_http = http is None
        self._on_call = on_call
        self._sleep = sleep

    async def __aenter__(self) -> "HhClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    @property
    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=self.settings.hh_api_base_url, timeout=self.settings.hh_timeout_seconds
            )
        return self._http

    async def aclose(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
            self._http = None

    def _headers(self) -> dict[str, str]:
        headers = {"HH-User-Agent": self.settings.hh_user_agent, "Accept": "application/json"}
        if self.access_token:
            headers["Authorization"] = f"Bearer {self.access_token}"
        return headers

    async def _record(self, operation: str, status: int | None, err: str | None, started: float) -> None:
        if self._on_call is not None:
            try:
                await self._on_call(CallRecord(operation, status, err, int((time.monotonic() - started) * 1000)))
            except Exception:  # metrics must never break the call path
                log.exception("failed to record hh call")

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: dict[str, Any] | list[tuple[str, Any]] | None = None,
        data: dict[str, Any] | None = None,
        idempotent: bool = True,
    ) -> Any:
        attempts = self.settings.hh_max_retries + 1 if idempotent else 1
        last_error: HhApiError | None = None
        attempt = -1
        while attempt + 1 < attempts:
            attempt += 1
            await shared_bucket(self.settings).acquire()
            started = time.monotonic()
            try:
                response = await self.http.request(method, path, params=params, data=data, headers=self._headers())
            except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
                # The request never reached hh.ru: safe to retry even for non-idempotent calls.
                await self._record(operation, None, "connect_error", started)
                last_error = HhNetworkError(f"hh.ru unreachable: {exc.__class__.__name__}")
                if not idempotent and attempt == 0:
                    attempts = max(attempts, 2)
            except httpx.TransportError as exc:
                await self._record(operation, None, "transport_error", started)
                if not idempotent:
                    raise HhAmbiguousResult(
                        f"no response from hh.ru after sending {operation}: {exc.__class__.__name__}"
                    ) from exc
                last_error = HhNetworkError(f"hh.ru transport error: {exc.__class__.__name__}")
            else:
                if response.status_code < 400:
                    await self._record(operation, response.status_code, None, started)
                    if response.status_code == 204 or not response.content:
                        return {"_status": response.status_code, "_location": response.headers.get("Location")}
                    try:
                        return response.json()
                    except ValueError:
                        return {"_status": response.status_code}
                error = parse_error(response)
                await self._record(operation, response.status_code, error.tag, started)
                if not error.retryable:
                    raise error
                if not idempotent and isinstance(error, HhServerError):
                    # 5xx on a write: hh.ru may have applied it. Do not guess.
                    raise HhAmbiguousResult(str(error), status=error.status, body=error.body) from error
                last_error = error
            if attempt + 1 < attempts:
                delay = backoff_delay(attempt)
                if isinstance(last_error, HhRateLimited) and last_error.retry_after:
                    delay = max(delay, last_error.retry_after)
                await self._sleep(delay)
        assert last_error is not None
        raise last_error

    # --- Read operations -------------------------------------------------------------------------

    async def me(self) -> dict[str, Any]:
        return await self.request("GET", "/me", operation="me")

    async def search_vacancies(self, params: list[tuple[str, Any]]) -> dict[str, Any]:
        return await self.request("GET", "/vacancies", params=params, operation="vacancies.search")

    async def get_vacancy(self, vacancy_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/vacancies/{vacancy_id}", operation="vacancies.get")

    async def similar_vacancies(self, vacancy_id: str, page: int = 0) -> dict[str, Any]:
        return await self.request(
            "GET",
            f"/vacancies/{vacancy_id}/similar_vacancies",
            params={"page": page, "per_page": 50},
            operation="vacancies.similar",
        )

    async def my_resumes(self) -> dict[str, Any]:
        return await self.request("GET", "/resumes/mine", operation="resumes.mine")

    async def get_resume(self, resume_id: str) -> dict[str, Any]:
        return await self.request("GET", f"/resumes/{resume_id}", operation="resumes.get")

    async def negotiations(self, *, page: int = 0, per_page: int = 50, vacancy_id: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "per_page": per_page}
        if vacancy_id:
            params["vacancy_id"] = vacancy_id
        return await self.request("GET", "/negotiations", params=params, operation="negotiations.list")

    async def areas(self) -> list[dict[str, Any]]:
        return await self.request("GET", "/areas", operation="dictionaries.areas")

    # --- Write operations (never retried after they may have reached hh.ru) ---------------------

    async def apply(self, *, vacancy_id: str, resume_id: str, message: str | None) -> dict[str, Any]:
        data = {"vacancy_id": vacancy_id, "resume_id": resume_id}
        if message:
            data["message"] = message
        return await self.request("POST", "/negotiations", data=data, operation="negotiations.apply", idempotent=False)

    async def publish_resume(self, resume_id: str) -> dict[str, Any]:
        return await self.request(
            "POST", f"/resumes/{resume_id}/publish", operation="resumes.publish", idempotent=False
        )
