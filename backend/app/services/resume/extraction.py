"""Deterministic resume understanding. Works without any AI provider and never invents facts:
everything comes from the text, everything is marked ``confirmed=False`` until the user confirms it."""

import re
from dataclasses import dataclass
from datetime import date

from app.schemas.profile import (
    Assumption,
    CandidateProfile,
    CertificateItem,
    EducationItem,
    ExperienceItem,
    LanguageItem,
    ProfileSkill,
    ProjectItem,
)
from app.services.hhru.normalize import parse_salary_text
from app.services.matching.skills import extract_skills, normalize_skill_list

SECTION_ALIASES: dict[str, tuple[str, ...]] = {
    "experience": ("опыт работы", "опыт", "work experience", "experience", "профессиональный опыт", "места работы"),
    "education": ("образование", "education", "высшее образование", "среднее специальное образование"),
    "skills": ("ключевые навыки", "навыки", "skills", "технические навыки", "технологии", "стек", "hard skills"),
    "projects": ("проекты", "projects", "портфолио", "pet-проекты", "pet проекты", "личные проекты"),
    "about": ("о себе", "about", "about me", "summary", "дополнительная информация", "обо мне"),
    "languages": ("знание языков", "языки", "languages", "иностранные языки"),
    "certificates": (
        "повышение квалификации, курсы",
        "курсы",
        "сертификаты",
        "certificates",
        "certifications",
        "повышение квалификации",
        "тесты, экзамены",
    ),
    "desired": ("желаемая должность и зарплата", "желаемая должность", "цель", "objective"),
}

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7, "август": 8,
    "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "oct": 10, "nov": 11, "dec": 12,
}  # fmt: skip

_MONTH_WORD = r"(?:январ\w*|феврал\w*|март\w*|апрел\w*|ма[йя]\w*|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*|jan\w*|feb\w*|mar\w*|apr\w*|may|jun\w*|jul\w*|aug\w*|sep\w*|oct\w*|nov\w*|dec\w*)"
_POINT = rf"(?:{_MONTH_WORD}\s+\d{{4}}|\d{{1,2}}[./]\d{{4}}|\d{{4}})"
_NOW = r"(?:настоящее\s+время|по\s+н\.?\s*в\.?|н\.?\s*в\.?|сейчас|present|now|current|по\s+настоящее\s+время)"
DATE_RANGE = re.compile(rf"(?P<start>{_POINT})\s*(?:—|–|-|по|to)\s*(?P<end>{_POINT}|{_NOW})", re.IGNORECASE)
HH_TOTAL_EXP = re.compile(r"опыт работы\s*[—–-]\s*(?:(\d+)\s*(?:год|года|лет))?\s*(?:(\d+)\s*месяц\w*)?", re.IGNORECASE)
DURATION_LINE = re.compile(r"^\s*(\d+\s*(год|года|лет|месяц\w*|year\w*|month\w*)\s*)+$", re.IGNORECASE)
EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?:\+7|8)[\s\-(]*\d{3}[\s\-)]*\d{3}[\s\-]*\d{2}[\s\-]*\d{2}")
EDU_HINT = re.compile(
    r"(университет|институт|колледж|академи|техникум|училищ|школа|university|college|institute)", re.I
)
LANG_LINE = re.compile(
    r"(английский|немецкий|французский|китайский|испанский|русский|english|german|french|chinese|spanish)"
    r"\s*[—–:-]?\s*(родной|[abc][12]|базовые знания|читаю профессиональную литературу|"
    r"могу проходить интервью|свободно владею|native|fluent|intermediate|upper[- ]intermediate|advanced|beginner|elementary)?",
    re.IGNORECASE,
)
ACHIEVEMENT_HINT = re.compile(
    r"(\d+\s*%|в\s+\d+\s+раз|сократил|увеличил|ускорил|снизил|автоматизировал|внедрил|"
    r"reduced|increased|improved|automated|launched)",
    re.IGNORECASE,
)
NON_COMMERCIAL = re.compile(r"(pet[- ]?проект|учебн|стажир|internship|волонт|фриланс|freelance|курсов\w* проект)", re.I)


@dataclass(slots=True)
class Contacts:
    emails: list[str]
    phones: list[str]


def _norm_heading(line: str) -> str:
    return re.sub(r"[:\s]+$", "", line.strip().lower())


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"header": []}
    current = "header"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        heading = _norm_heading(line)
        matched = None
        if len(heading) <= 45:
            for key, aliases in SECTION_ALIASES.items():
                if heading in aliases or any(
                    heading.startswith(a + " —") or heading.startswith(a + " -") for a in aliases
                ):
                    matched = key
                    break
        if matched:
            current = matched
            sections.setdefault(current, [])
            # hh.ru puts total experience on the heading line itself: "Опыт работы — 3 года 2 месяца"
            if matched == "experience" and HH_TOTAL_EXP.search(line):
                sections[current].append(line)
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _parse_point(value: str, *, is_end: bool) -> tuple[int, int] | None:
    v = value.strip().lower()
    if re.fullmatch(_NOW, v, re.IGNORECASE):
        today = date.today()
        return today.year, today.month
    m = re.fullmatch(r"(\d{1,2})[./](\d{4})", v)
    if m:
        return int(m.group(2)), max(1, min(12, int(m.group(1))))
    m = re.fullmatch(r"(\d{4})", v)
    if m:
        return int(m.group(1)), 12 if is_end else 1
    m = re.fullmatch(rf"({_MONTH_WORD})\s+(\d{{4}})", v, re.IGNORECASE)
    if m:
        word = m.group(1).lower()
        month = next(
            (n for prefix, n in sorted(MONTHS.items(), key=lambda x: -len(x[0])) if word.startswith(prefix)), 1
        )
        return int(m.group(2)), month
    return None


def _months_between(start: tuple[int, int], end: tuple[int, int]) -> int:
    return max(0, (end[0] - start[0]) * 12 + (end[1] - start[1]) + 1)


def _merge_months(ranges: list[tuple[tuple[int, int], tuple[int, int]]]) -> int:
    """Total months covered by possibly overlapping ranges."""
    if not ranges:
        return 0
    as_idx = sorted((s[0] * 12 + s[1], e[0] * 12 + e[1]) for s, e in ranges)
    total, cur_s, cur_e = 0, as_idx[0][0], as_idx[0][1]
    for s, e in as_idx[1:]:
        if s <= cur_e + 1:
            cur_e = max(cur_e, e)
        else:
            total += cur_e - cur_s + 1
            cur_s, cur_e = s, e
    return total + cur_e - cur_s + 1


def parse_experience(lines: list[str]) -> tuple[list[ExperienceItem], int | None]:
    hh_total: int | None = None
    items: list[ExperienceItem] = []
    current: ExperienceItem | None = None
    pending_header: list[str] = []
    for line in lines:
        total = HH_TOTAL_EXP.search(line)
        if total and (total.group(1) or total.group(2)) and hh_total is None and line.lower().startswith("опыт"):
            hh_total = int(total.group(1) or 0) * 12 + int(total.group(2) or 0)
            continue
        match = DATE_RANGE.search(line)
        if match:
            start = _parse_point(match.group("start"), is_end=False)
            end_raw = match.group("end")
            is_current = bool(re.fullmatch(_NOW, end_raw.strip(), re.IGNORECASE))
            end = _parse_point(end_raw, is_end=True)
            current = ExperienceItem(
                start=f"{start[0]:04d}-{start[1]:02d}" if start else None,
                end=None if is_current or not end else f"{end[0]:04d}-{end[1]:02d}",
                current=is_current,
            )
            rest = (line[: match.start()] + " " + line[match.end() :]).strip(" ,|—–-")
            pending_header = [rest] if rest else []
            items.append(current)
            continue
        if current is None:
            continue
        if DURATION_LINE.match(line):
            continue
        if len(pending_header) < 3 and not current.description:
            pending_header.append(line)
            # hh.ru layout: company, (city / site), position. Generic CVs: "Position, Company".
            if len(pending_header) == 1:
                current.company = line[:200]
            elif len(pending_header) == 2:
                current.title = line[:200]
            elif len(pending_header) == 3:
                if (
                    re.search(r"(www\.|https?://|\.ru\b|\.com\b)", current.title, re.I)
                    or len(current.title) < 25
                    and "," in current.title
                ):
                    current.title = line[:200]
                else:
                    current.description = line
            continue
        current.description = (current.description + "\n" + line).strip()
    for item in items:
        if item.company and not item.title and "," in item.company:
            title, company = item.company.split(",", 1)
            item.title, item.company = title.strip(), company.strip()
        item.technologies = extract_skills(f"{item.title}\n{item.description}")
        item.commercial = not NON_COMMERCIAL.search(f"{item.company} {item.title} {item.description}")
    return items, hh_total


def parse_education(lines: list[str]) -> list[EducationItem]:
    items: list[EducationItem] = []
    pending_year: int | None = None
    for line in lines:
        year = re.fullmatch(r"(19|20)\d{2}", line.strip())
        if year:
            pending_year = int(line.strip())
            continue
        if EDU_HINT.search(line):
            y = re.search(r"\b(19|20)\d{2}\b", line)
            items.append(
                EducationItem(
                    institution=re.sub(r"\b(19|20)\d{2}\b", "", line).strip(" ,—–-")[:250],
                    year=int(y.group(0)) if y else pending_year,
                )
            )
            pending_year = None
        elif items and not items[-1].field:
            items[-1].field = line[:250]
    return items


def parse_projects(lines: list[str]) -> list[ProjectItem]:
    projects: list[ProjectItem] = []
    for line in lines:
        is_title = line.startswith(("•", "-", "–", "*")) or (len(line) < 80 and not line.endswith("."))
        clean = line.lstrip("•-–* ").strip()
        if is_title or not projects:
            name, _, desc = clean.partition(" — ")
            if not desc:
                name, _, desc = clean.partition(": ")
            projects.append(ProjectItem(name=name[:200], description=desc))
        else:
            projects[-1].description = (projects[-1].description + " " + clean).strip()
    for p in projects:
        url = re.search(r"https?://\S+", f"{p.name} {p.description}")
        p.url = url.group(0).rstrip(").,") if url else None
        p.technologies = extract_skills(f"{p.name} {p.description}")
    return [p for p in projects if p.name]


def parse_skill_section(lines: list[str]) -> list[str]:
    raw: list[str] = []
    for line in lines:
        for part in re.split(r"[,;•|·\t]| {2,}", line):
            part = part.strip(" .-–—")
            if 1 < len(part) <= 40:
                raw.append(part)
    return raw


def extract_contacts(text: str) -> Contacts:
    return Contacts(
        emails=sorted(set(EMAIL.findall(text))),
        phones=sorted({re.sub(r"[^\d+]", "", p) for p in PHONE.findall(text)}),
    )


def infer_level(months: int, has_commercial: bool) -> str:
    if not has_commercial or months == 0:
        return "intern" if months == 0 else "junior"
    if months < 18:
        return "junior"
    if months < 48:
        return "middle"
    if months < 96:
        return "senior"
    return "lead"


def build_profile(text: str) -> CandidateProfile:
    sections = split_sections(text)
    profile = CandidateProfile()
    header = sections.get("header", [])

    desired = sections.get("desired", [])
    if desired:
        profile.desired_positions = [desired[0][:120]]
        for line in desired[1:]:
            sal_from, _, currency = parse_salary_text(line)
            if sal_from:
                profile.min_salary = sal_from
                profile.currency = currency or "RUR"
                break
        joined = " ".join(desired).lower()
        if "удален" in joined or "удалён" in joined:
            profile.work_formats.append("remote")
        if "частичная" in joined:
            profile.part_time_ok = True
        if "стажировка" in joined:
            profile.internship_ok = True
    elif header:
        profile.headline = header[0][:200]

    experience, hh_total = parse_experience(sections.get("experience", []))
    profile.experience = experience
    commercial_ranges = []
    for item in experience:
        if not item.start or not item.commercial:
            continue
        s = tuple(int(x) for x in item.start.split("-"))
        e = tuple(int(x) for x in item.end.split("-")) if item.end else (date.today().year, date.today().month)
        commercial_ranges.append((s, e))
    computed = _merge_months(commercial_ranges)  # type: ignore[arg-type]
    profile.total_experience_months = hh_total if hh_total is not None else computed
    profile.has_commercial_experience = any(i.commercial for i in experience) and profile.total_experience_months > 0
    if hh_total is not None and computed and abs(hh_total - computed) > 6:
        profile.assumptions.append(
            Assumption(
                field="total_experience_months",
                value=str(hh_total),
                reason=f"Указанный в резюме стаж расходится с суммой периодов ({computed} мес.)",
            )
        )

    profile.education = parse_education(sections.get("education", []))
    profile.projects = parse_projects(sections.get("projects", []))
    for line in sections.get("certificates", []):
        y = re.search(r"\b(19|20)\d{2}\b", line)
        profile.certificates.append(CertificateItem(name=line[:200], year=int(y.group(0)) if y else None))
    seen_langs = set()
    for line in sections.get("languages", []) + sections.get("about", []):
        for m in LANG_LINE.finditer(line):
            name = m.group(1).capitalize()
            if name.lower() not in seen_langs:
                seen_langs.add(name.lower())
                profile.languages.append(LanguageItem(name=name, level=(m.group(2) or "").strip()))

    profile.summary = " ".join(sections.get("about", []))[:2000]
    section_skills = normalize_skill_list(parse_skill_section(sections.get("skills", [])))
    text_skills = extract_skills(text)
    names = normalize_skill_list(section_skills + text_skills)
    profile.skills = [ProfileSkill(name=n) for n in names]

    profile.achievements = [
        line.lstrip("•-–* ")[:300]
        for item in experience
        for line in item.description.splitlines()
        if ACHIEVEMENT_HINT.search(line)
    ][:15]
    profile.level = infer_level(profile.total_experience_months, profile.has_commercial_experience)  # type: ignore[assignment]
    profile.assumptions.append(
        Assumption(field="level", value=profile.level, reason="Уровень рассчитан по стажу, подтвердите или измените")
    )
    keywords = list(dict.fromkeys(profile.desired_positions + [i.title for i in experience if i.title] + names[:15]))
    profile.keywords = [k for k in keywords if k][:25]
    return profile


QUALITY_CHECKS = (
    ("desired_positions", 10, "Укажите желаемую должность: по ней строится поиск"),
    ("skills", 20, "Добавьте не меньше 8 ключевых навыков"),
    ("experience", 20, "Опишите опыт или учебные проекты с датами"),
    ("descriptions", 15, "Добавьте описание задач в каждое место работы"),
    ("achievements", 15, "Добавьте измеримые результаты: цифры, проценты, сроки"),
    ("summary", 10, "Заполните раздел «О себе» (2–4 предложения)"),
    ("projects", 10, "Добавьте проекты со ссылками, особенно если коммерческого опыта мало"),
)


def assess_quality(profile: CandidateProfile) -> dict:
    passed = {
        "desired_positions": bool(profile.desired_positions),
        "skills": len(profile.skills) >= 8,
        "experience": bool(profile.experience),
        "descriptions": bool(profile.experience) and all(len(e.description) >= 80 for e in profile.experience),
        "achievements": len(profile.achievements) >= 2,
        "summary": 80 <= len(profile.summary) <= 1500,
        "projects": bool(profile.projects) or profile.total_experience_months >= 24,
    }
    score = sum(weight for key, weight, _ in QUALITY_CHECKS if passed[key])
    tips = [tip for key, _, tip in QUALITY_CHECKS if not passed[key]]
    return {"score": score, "recommendations": tips, "checks": passed}
