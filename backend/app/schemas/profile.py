"""Normalized candidate profile. Every fact carries its source and whether the user confirmed it."""

from typing import Literal

from pydantic import BaseModel, Field

Source = Literal["extracted", "llm", "user", "hh"]
Level = Literal["intern", "junior", "middle", "senior", "lead", "unknown"]


class Fact(BaseModel):
    source: Source = "extracted"
    confirmed: bool = False


class ProfileSkill(Fact):
    name: str
    years: float | None = None


class ExperienceItem(Fact):
    company: str = ""
    title: str = ""
    start: str | None = None  # YYYY-MM
    end: str | None = None  # YYYY-MM, None = current
    current: bool = False
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    commercial: bool = True


class EducationItem(Fact):
    institution: str = ""
    degree: str = ""
    field: str = ""
    year: int | None = None


class ProjectItem(Fact):
    name: str = ""
    description: str = ""
    technologies: list[str] = Field(default_factory=list)
    url: str | None = None


class CertificateItem(Fact):
    name: str
    year: int | None = None


class LanguageItem(BaseModel):
    name: str
    level: str = ""


class Assumption(BaseModel):
    field: str
    value: str
    reason: str


class AreaRef(BaseModel):
    id: str | None = None
    name: str


class CandidateProfile(BaseModel):
    headline: str = ""
    summary: str = ""
    desired_positions: list[str] = Field(default_factory=list)
    skills: list[ProfileSkill] = Field(default_factory=list)
    experience: list[ExperienceItem] = Field(default_factory=list)
    education: list[EducationItem] = Field(default_factory=list)
    projects: list[ProjectItem] = Field(default_factory=list)
    certificates: list[CertificateItem] = Field(default_factory=list)
    languages: list[LanguageItem] = Field(default_factory=list)
    industries: list[str] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
    level: Level = "unknown"
    total_experience_months: int = 0
    has_commercial_experience: bool = False

    # Preferences
    min_salary: int | None = None
    currency: str = "RUR"
    areas: list[AreaRef] = Field(default_factory=list)
    work_formats: list[str] = Field(default_factory=list)
    employment_types: list[str] = Field(default_factory=list)
    internship_ok: bool = False
    part_time_ok: bool = False
    relocation: bool = False

    assumptions: list[Assumption] = Field(default_factory=list)

    def skill_names(self) -> list[str]:
        return [s.name for s in self.skills]

    def is_empty(self) -> bool:
        return not (self.skills or self.experience or self.projects or self.summary or self.desired_positions)
