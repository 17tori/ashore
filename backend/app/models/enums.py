from enum import StrEnum


class AutomationMode(StrEnum):
    MANUAL = "manual"
    ASSISTED = "assisted"
    AUTO = "auto"


class MatchDecision(StrEnum):
    REJECT = "reject"
    REVIEW = "review"
    ELIGIBLE = "eligible"
    READY_TO_APPLY = "ready_to_apply"
    APPLIED = "applied"


class ApplicationStatus(StrEnum):
    FOUND = "found"
    ANALYZING = "analyzing"
    MATCHED = "matched"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    READY = "ready"
    SENDING = "sending"
    SENT = "sent"
    VIEWED = "viewed"
    INVITATION = "invitation"
    REJECTED = "rejected"
    ARCHIVED = "archived"
    FAILED = "failed"
    UNKNOWN = "unknown"


class CapabilityStatus(StrEnum):
    VERIFIED = "verified"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"


class Capability(StrEnum):
    VACANCY_SEARCH = "vacancy_search"
    RESUMES_READ = "resumes_read"
    NEGOTIATIONS_READ = "negotiations_read"
    APPLY = "apply"
    RESUME_PUBLISH = "resume_publish"


class ConnectionStatus(StrEnum):
    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class VacancySource(StrEnum):
    HH_API = "hh_api"
    MANUAL = "manual"
    BOOKMARKLET = "bookmarklet"
    DEMO = "demo"


class ResumeSource(StrEnum):
    UPLOAD = "upload"
    HH = "hh"
    MANUAL = "manual"
    DEMO = "demo"


class VisibilityActionKind(StrEnum):
    PUBLISH = "publish"
    REMINDER = "reminder"
    MANUAL_MARK = "manual_mark"


class VisibilityActionStatus(StrEnum):
    SCHEDULED = "scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    REMINDED = "reminded"
    CONFIRMED_BY_USER = "confirmed_by_user"


class JobKind(StrEnum):
    DISCOVER = "discover"
    PROCESS_QUEUE = "process_queue"
    SYNC_NEGOTIATIONS = "sync_negotiations"
    CHECK_OAUTH = "check_oauth"
    VISIBILITY = "visibility"
    DAILY_REPORT = "daily_report"
