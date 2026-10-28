"""Normalization of hh.ru vacancy payloads (current and legacy field shapes) and manual imports."""

import hashlib
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from html.parser import HTMLParser
from typing import Any

WORK_FORMATS = ("remote", "on_site", "hybrid", "field_work")
EMPLOYMENT_TYPES = ("full", "part", "project", "internship", "fly_in_fly_out", "volunteer")
EXPERIENCE_LEVELS = ("noExperience", "between1And3", "between3And6", "moreThan6")
# Experience buckets as (min_years, max_years).
EXPERIENCE_RANGES: dict[str, tuple[float, float]] = {
    "noExperience": (0, 1),
    "between1And3": (1, 3),
    "between3And6": (3, 6),
    "moreThan6": (6, 50),
}

_NEW_WORK_FORMAT = {"REMOTE": "remote", "ON_SITE": "on_site", "HYBRID": "hybrid", "FIELD_WORK": "field_work"}
_LEGACY_SCHEDULE = {"remote": "remote", "fullDay": "on_site", "shift": "on_site", "flyInFlyOut": "field_work"}
_NEW_EMPLOYMENT = {"FULL": "full", "PART": "part", "PROJECT": "project", "FLY_IN_FLY_OUT": "fly_in_fly_out"}
_LEGACY_EMPLOYMENT = {
    "full": "full",
    "part": "part",
    "project": "project",
    "probation": "internship",
    "volunteer": "volunteer",
}

HH_VACANCY_URL = re.compile(r"(?:https?://)?(?:[\w-]+\.)?hh\.(?:ru|kz|uz|by)/vacancy/(\d+)", re.IGNORECASE)


class _TextExtractor(HTMLParser):
    _BLOCK = {"p", "br", "li", "div", "ul", "ol", "h1", "h2", "h3", "h4", "tr"}

    _SKIP = {"script", "style", "template", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self._skipping = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in self._SKIP:
            self._skipping += 1
        elif tag == "li":
            self.parts.append("\n• ")
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skipping:
            self._skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self._skipping:
            self.parts.append(data)


def html_to_text(html: str | None) -> str:
    if not html:
        return ""
    parser = _TextExtractor()
    parser.feed(html)
    text = "".join(parser.parts)
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def parse_hh_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    for candidate in (value, re.sub(r"([+-]\d{2})(\d{2})$", r"\1:\2", value)):
        try:
            return datetime.fromisoformat(candidate)
        except ValueError:
            continue
    return None


def extract_hh_vacancy_id(url_or_id: str) -> str | None:
    value = url_or_id.strip()
    if value.isdigit():
        return value
    match = HH_VACANCY_URL.search(value)
    return match.group(1) if match else None


@dataclass(slots=True)
class NormalizedVacancy:
    title: str
    hh_id: str | None = None
    url: str | None = None
    apply_url: str | None = None
    employer_name: str = ""
    employer_hh_id: str | None = None
    employer_url: str | None = None
    area_id: str | None = None
    area_name: str | None = None
    salary_from: int | None = None
    salary_to: int | None = None
    salary_currency: str | None = None
    salary_gross: bool | None = None
    work_formats: list[str] = field(default_factory=list)
    employment_type: str | None = None
    experience_id: str | None = None
    schedule: str | None = None
    description_text: str = ""
    key_skills: list[str] = field(default_factory=list)
    professional_roles: list[str] = field(default_factory=list)
    published_at: datetime | None = None
    archived: bool = False
    has_test: bool = False
    response_letter_required: bool = False

    def content_hash(self) -> str:
        material = {
            "title": self.title.strip().lower(),
            "employer": self.employer_name.strip().lower(),
            "salary": [self.salary_from, self.salary_to, self.salary_currency],
            "formats": sorted(self.work_formats),
            "employment": self.employment_type,
            "experience": self.experience_id,
            "skills": sorted(s.lower() for s in self.key_skills),
            "description": re.sub(r"\s+", " ", self.description_text).strip().lower(),
            "archived": self.archived,
        }
        return hashlib.sha256(json.dumps(material, ensure_ascii=False, sort_keys=True).encode()).hexdigest()

    def snapshot(self) -> dict[str, Any]:
        data = asdict(self)
        data["published_at"] = self.published_at.isoformat() if self.published_at else None
        return data


def _salary(payload: dict[str, Any]) -> tuple[int | None, int | None, str | None, bool | None]:
    salary = payload.get("salary_range") or payload.get("salary")
    if not isinstance(salary, dict):
        return None, None, None, None
    return salary.get("from"), salary.get("to"), salary.get("currency"), salary.get("gross")


def _work_formats(payload: dict[str, Any]) -> list[str]:
    formats: list[str] = []
    for item in payload.get("work_format") or []:
        mapped = _NEW_WORK_FORMAT.get(str(item.get("id", "")).upper())
        if mapped and mapped not in formats:
            formats.append(mapped)
    if not formats:
        schedule = (payload.get("schedule") or {}).get("id")
        mapped = _LEGACY_SCHEDULE.get(schedule or "")
        if mapped:
            formats.append(mapped)
    return formats


def _employment(payload: dict[str, Any]) -> str | None:
    if payload.get("internship") is True:
        return "internship"
    form = (payload.get("employment_form") or {}).get("id")
    if form:
        return _NEW_EMPLOYMENT.get(str(form).upper())
    legacy = (payload.get("employment") or {}).get("id")
    return _LEGACY_EMPLOYMENT.get(legacy or "")


def normalize_hh_vacancy(payload: dict[str, Any]) -> NormalizedVacancy:
    """Accepts both search items (short form) and full ``GET /vacancies/{id}`` payloads."""
    sal_from, sal_to, currency, gross = _salary(payload)
    employer = payload.get("employer") or {}
    area = payload.get("area") or {}
    description = payload.get("description")
    if not description:
        snippet = payload.get("snippet") or {}
        description = "\n".join(filter(None, [snippet.get("requirement"), snippet.get("responsibility")]))
    archived = payload.get("archived")
    return NormalizedVacancy(
        hh_id=str(payload["id"]) if payload.get("id") is not None else None,
        title=(payload.get("name") or "").strip(),
        url=payload.get("alternate_url"),
        apply_url=payload.get("apply_alternate_url"),
        employer_name=(employer.get("name") or "").strip(),
        employer_hh_id=str(employer["id"]) if employer.get("id") is not None else None,
        employer_url=employer.get("alternate_url"),
        area_id=str(area["id"]) if area.get("id") is not None else None,
        area_name=area.get("name"),
        salary_from=sal_from,
        salary_to=sal_to,
        salary_currency=currency,
        salary_gross=gross,
        work_formats=_work_formats(payload),
        employment_type=_employment(payload),
        experience_id=(payload.get("experience") or {}).get("id"),
        schedule=(payload.get("schedule") or {}).get("id"),
        description_text=html_to_text(description),
        key_skills=[s["name"] for s in payload.get("key_skills") or [] if s.get("name")],
        professional_roles=[r["name"] for r in payload.get("professional_roles") or [] if r.get("name")],
        published_at=parse_hh_datetime(payload.get("published_at")),
        archived=str(archived).lower() == "true" if archived is not None else False,
        has_test=bool(payload.get("has_test")),
        response_letter_required=bool(payload.get("response_letter_required")),
    )


_SALARY_RE = re.compile(
    r"(?:от\s*(?P<from>[\d\s\xa0]{3,}))?\s*(?:до\s*(?P<to>[\d\s\xa0]{3,}))?\s*(?P<cur>₽|руб|RUR|RUB|\$|USD|€|EUR)",
    re.IGNORECASE,
)
_CURRENCY = {"₽": "RUR", "руб": "RUR", "rur": "RUR", "rub": "RUR", "$": "USD", "usd": "USD", "€": "EUR", "eur": "EUR"}


def parse_salary_text(text: str) -> tuple[int | None, int | None, str | None]:
    for match in _SALARY_RE.finditer(text or ""):
        raw_from, raw_to = match.group("from"), match.group("to")
        if not raw_from and not raw_to:
            continue

        def num(v: str | None) -> int | None:
            digits = re.sub(r"\D", "", v or "")
            return int(digits) if digits else None

        return num(raw_from), num(raw_to), _CURRENCY.get(match.group("cur").lower(), "RUR")
    return None, None, None


_REMOTE_HINTS = re.compile(r"удал[её]нн|remote|из дома", re.IGNORECASE)
_HYBRID_HINTS = re.compile(r"гибрид|hybrid", re.IGNORECASE)
_NO_EXP_HINTS = re.compile(r"(опыт\s+(работы\s+)?не\s+(требуется|обязателен))|без\s+опыта", re.IGNORECASE)
_EXP_YEARS = re.compile(r"опыт\w*\s+(?:работы\s+)?(?:от\s+)?(\d+)(?:[–\-]\d+)?\s*(?:год|лет)", re.IGNORECASE)


def normalize_manual(
    *,
    title: str,
    description: str,
    url: str | None = None,
    employer_name: str = "",
    salary_text: str = "",
    area_name: str | None = None,
) -> NormalizedVacancy:
    """Best-effort normalization of a vacancy the user pasted or clipped. Unknown fields stay unknown."""
    hh_id = extract_hh_vacancy_id(url) if url else None
    sal_from, sal_to, currency = parse_salary_text(salary_text or description[:2000])
    formats: list[str] = []
    if _REMOTE_HINTS.search(description):
        formats.append("remote")
    if _HYBRID_HINTS.search(description):
        formats.append("hybrid")
    experience: str | None = None
    if _NO_EXP_HINTS.search(description):
        experience = "noExperience"
    elif m := _EXP_YEARS.search(description):
        years = int(m.group(1))
        experience = "between1And3" if years <= 1 else "between3And6" if years <= 3 else "moreThan6"
    return NormalizedVacancy(
        hh_id=hh_id,
        title=title.strip()[:300],
        url=f"https://hh.ru/vacancy/{hh_id}" if hh_id else url,
        apply_url=f"https://hh.ru/applicant/vacancy_response?vacancyId={hh_id}" if hh_id else None,
        employer_name=employer_name.strip()[:300],
        area_name=area_name,
        salary_from=sal_from,
        salary_to=sal_to,
        salary_currency=currency,
        work_formats=formats,
        experience_id=experience,
        description_text=description.strip()[:50_000],
    )
