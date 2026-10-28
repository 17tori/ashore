import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.schemas.profile import CandidateProfile


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=10, max_length=200)
    display_name: str = Field(default="", max_length=120)
    pd_consent: bool = Field(description="Согласие на обработку персональных данных (152-ФЗ)")
    timezone: str = "Europe/Moscow"

    @field_validator("pd_consent")
    @classmethod
    def consent_required(cls, v: bool) -> bool:
        if not v:
            raise ValueError("Нужно согласие на обработку персональных данных")
        return v


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(max_length=200)


class SettingsPatch(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    timezone: str | None = None
    ai_external_consent: bool | None = None
    notifications: dict | None = None
    visibility: dict | None = None


class DeleteAccountIn(BaseModel):
    password: str


class ResumeTextIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=20, max_length=200_000)


class ResumeProfilePatch(BaseModel):
    title: str | None = Field(default=None, max_length=200)
    profile: CandidateProfile
    confirm_all: bool = False


class ResumeLinkHh(BaseModel):
    hh_resume_id: str = Field(pattern=r"^[0-9a-f]{20,64}$")


class AreaIn(BaseModel):
    id: str | None = None
    name: str


class EmployerRef(BaseModel):
    id: str | None = None
    name: str = ""


WorkFormat = Literal["remote", "on_site", "hybrid", "field_work"]
Employment = Literal["full", "part", "project", "internship", "fly_in_fly_out", "volunteer"]
Experience = Literal["noExperience", "between1And3", "between3And6", "moreThan6"]


class SearchProfileIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool = True
    resume_id: uuid.UUID | None = None
    positions: list[str] = Field(default_factory=list, max_length=10)
    skills: list[str] = Field(default_factory=list, max_length=50)
    areas: list[AreaIn] = Field(default_factory=list)
    work_formats: list[WorkFormat] = Field(default_factory=list)
    employment_types: list[Employment] = Field(default_factory=list)
    experience: list[Experience] = Field(default_factory=list)
    salary_min: int | None = Field(default=None, ge=0, le=10_000_000)
    currency: str = "RUR"
    only_with_salary: bool = False
    industries: list[str] = Field(default_factory=list)
    excluded_employers: list[EmployerRef] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list, max_length=50)
    period_days: int = Field(default=7, ge=1, le=30)
    eligible_threshold: int = Field(default=70, ge=0, le=100)
    review_threshold: int = Field(default=50, ge=0, le=100)
    daily_apply_limit: int = Field(default=10, ge=0, le=50)
    weights: dict[str, float] = Field(default_factory=dict)
    letter_template: Literal[
        "junior_developer", "ai_automation", "sysadmin", "uxui_designer", "intern", "no_experience"
    ] = "junior_developer"
    letter_tone: Literal["formal", "neutral", "friendly"] = "neutral"
    letter_length: Literal["short", "medium"] = "short"
    letter_mode: Literal["always", "when_required", "never"] = "always"
    search_interval_minutes: int = Field(default=120, ge=30, le=24 * 60)


class VacancyImportIn(BaseModel):
    url: str | None = Field(default=None, max_length=500)
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=60_000)
    employer_name: str = Field(default="", max_length=300)
    salary_text: str = Field(default="", max_length=200)
    area_name: str | None = Field(default=None, max_length=120)
    search_profile_id: uuid.UUID | None = None
    source: Literal["manual", "bookmarklet"] = "manual"


class DecisionIn(BaseModel):
    decision: Literal["reject", "review", "eligible"] | None


class LetterPatch(BaseModel):
    text: str = Field(min_length=1, max_length=4000)


class ApplicationStatusIn(BaseModel):
    status: Literal["viewed", "invitation", "rejected", "archived"]
    note: str = Field(default="", max_length=1000)


class NotesIn(BaseModel):
    notes: str = Field(max_length=5000)


class ApplyWindow(BaseModel):
    days: list[int] = Field(default_factory=lambda: list(range(5)))
    start: str = Field(default="09:00", pattern=r"^\d{2}:\d{2}$")
    end: str = Field(default="19:00", pattern=r"^\d{2}:\d{2}$")


class PolicyPatch(BaseModel):
    mode: Literal["manual", "assisted", "auto"] | None = None
    allowed_resume_ids: list[uuid.UUID] | None = None
    allowed_positions: list[str] | None = None
    min_score: int | None = Field(default=None, ge=0, le=100)
    salary_min: int | None = Field(default=None, ge=0)
    employment_types: list[Employment] | None = None
    excluded_employers: list[EmployerRef] | None = None
    daily_limit: int | None = Field(default=None, ge=0, le=50)
    letter_rules: dict | None = None
    stop_conditions: dict | None = None
    apply_windows: list[ApplyWindow] | None = None
    ai_monthly_budget: float | None = Field(default=None, ge=0, le=10_000)
