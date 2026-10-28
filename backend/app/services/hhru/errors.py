from typing import Any


class HhApiError(Exception):
    """Error answered by hh.ru (or the network path to it)."""

    retryable = False

    def __init__(
        self,
        message: str,
        *,
        status: int | None = None,
        error_type: str | None = None,
        error_value: str | None = None,
        body: Any = None,
    ):
        super().__init__(message)
        self.status = status
        self.error_type = error_type
        self.error_value = error_value
        self.body = body

    @property
    def tag(self) -> str:
        return ":".join(x for x in (self.error_type, self.error_value) if x) or f"http_{self.status}"


class HhAuthError(HhApiError):
    """Token expired, revoked or invalid. Requires refresh or a new OAuth consent."""


class HhForbidden(HhApiError):
    """The operation is not allowed for this token (e.g. applicant methods closed for the app)."""


class HhNotFound(HhApiError):
    pass


class HhCaptchaRequired(HhApiError):
    """hh.ru asks for a captcha. Automation stops; the user must act on hh.ru. Never solved by us."""


class HhRateLimited(HhApiError):
    retryable = True

    def __init__(self, *args: Any, retry_after: float | None = None, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.retry_after = retry_after


class HhServerError(HhApiError):
    retryable = True


class HhNetworkError(HhApiError):
    retryable = True


class HhAmbiguousResult(HhApiError):
    """A non-idempotent request may or may not have been executed (timeout after sending)."""


class HhCircuitOpen(HhApiError):
    pass


class HhNotConfigured(HhApiError):
    pass
