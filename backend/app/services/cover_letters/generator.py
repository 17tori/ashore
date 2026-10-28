"""Cover letters built only from confirmed profile facts, adapted to each vacancy, then validated."""

import hashlib
import logging
import re
from dataclasses import asdict, dataclass, field

from app.models import User, Vacancy
from app.schemas.profile import CandidateProfile, ProjectItem
from app.services.ai.provider import AIError, AINotAvailable
from app.services.ai.service import AIService, wrap_untrusted
from app.services.matching.scoring import vacancy_skills
from app.services.matching.skills import extract_skills, skill_key

log = logging.getLogger(__name__)

TEMPLATES = {
    "junior_developer": "Junior-разработчик",
    "ai_automation": "Специалист по AI-автоматизации",
    "sysadmin": "Системный администратор",
    "uxui_designer": "UX/UI-дизайнер",
    "intern": "Стажёр",
    "no_experience": "Без коммерческого опыта",
}
TONES = ("formal", "neutral", "friendly")
LENGTHS = ("short", "medium")
MAX_LETTER_CHARS = 2000

# Phrasing is deliberately gender-neutral in Russian (no "готов/готова", "рад/рада").
_OPENINGS = {
    "junior_developer": [
        "Меня заинтересовала вакансия «{title}»{company}: задачи совпадают с тем, чем я занимаюсь в разработке.",
        "Откликаюсь на вакансию «{title}»{company}. Мне близок ваш стек и хочется расти именно в такой команде.",
    ],
    "ai_automation": [
        "Откликаюсь на вакансию «{title}»{company}. Автоматизация процессов и работа с AI-инструментами для меня основная специализация.",
        "Вакансия «{title}»{company} совпадает с тем, что я делаю: автоматизирую рутину и связываю сервисы между собой.",
    ],
    "sysadmin": [
        "Откликаюсь на вакансию «{title}»{company}. Сопровождение инфраструктуры и поддержка пользователей мне хорошо знакомы.",
        "Меня заинтересовала вакансия «{title}»{company}: описанные задачи по администрированию совпадают с моим опытом.",
    ],
    "uxui_designer": [
        "Откликаюсь на вакансию «{title}»{company}. Мне интересно делать продукты понятнее и удобнее для людей.",
        "Вакансия «{title}»{company} привлекла задачами: мне близка работа, где решения проверяются на реальных пользователях.",
    ],
    "intern": [
        "Хочу пройти стажировку «{title}»{company}: это хороший способ применить знания на реальных задачах.",
        "Откликаюсь на стажировку «{title}»{company}. Мне важно учиться у сильной команды и приносить пользу.",
    ],
    "no_experience": [
        "Откликаюсь на вакансию «{title}»{company}. Коммерческого опыта у меня пока нет, но есть проекты, которые показывают мои навыки.",
        "Меня заинтересовала вакансия «{title}»{company}. Опыт у меня пока проектный, ниже коротко о том, что уже умею.",
    ],
}
_GREETINGS = {"formal": "Добрый день!", "neutral": "Здравствуйте!", "friendly": "Здравствуйте!"}
_CLOSINGS = {
    "formal": "Спасибо за внимание к отклику. Удобно обсудить детали в любое время.",
    "neutral": "Спасибо, что рассмотрели отклик. Можно обсудить детали в удобное для вас время.",
    "friendly": "Спасибо! Будет здорово пообщаться и обсудить задачи подробнее.",
}


@dataclass(slots=True)
class LetterIssue:
    code: str
    severity: str  # error | warning
    message: str


def issues_payload(issues: list[LetterIssue]) -> dict:
    return {"issues": [asdict(i) for i in issues], "blocking": any(i.severity == "error" for i in issues)}


@dataclass(slots=True)
class LetterResult:
    text: str
    generator: str
    issues: list[LetterIssue] = field(default_factory=list)

    @property
    def blocking(self) -> bool:
        return any(i.severity == "error" for i in self.issues)


def _variant(options: list[str], key: str) -> str:
    idx = int(hashlib.sha256(key.encode()).hexdigest(), 16) % len(options)
    return options[idx]


def _best_project(profile: CandidateProfile, wanted: set[str]) -> ProjectItem | None:
    best, best_overlap = None, 0
    for project in profile.projects:
        overlap = len({skill_key(t) for t in project.technologies} & wanted)
        if overlap > best_overlap:
            best, best_overlap = project, overlap
    return best


def _experience_sentence(profile: CandidateProfile) -> str | None:
    commercial = [e for e in profile.experience if e.commercial and (e.company or e.title)]
    if not commercial:
        return None
    latest = commercial[0]
    months = profile.total_experience_months
    span = f"{months // 12} г. {months % 12} мес." if months >= 12 else f"{months} мес."
    where = f" в {latest.company}" if latest.company else ""
    role = latest.title or "специалист"
    prefix = "Сейчас работаю" if latest.current else "Последнее место работы"
    return (
        f"{prefix}{where} ({role}), общий опыт {span}."
        if latest.current
        else f"{prefix}{where}: {role}, общий опыт {span}."
    )


def generate_local(
    vacancy: Vacancy, profile: CandidateProfile, *, template: str, tone: str, length: str
) -> LetterResult:
    template = (
        template
        if template in _OPENINGS
        else ("no_experience" if not profile.has_commercial_experience else "junior_developer")
    )
    tone = tone if tone in TONES else "neutral"
    company = f" в {vacancy.employer_name}" if vacancy.employer_name else ""
    key = f"{vacancy.id}:{template}:{tone}"

    wanted = {skill_key(s) for s in vacancy_skills(vacancy)}
    own = profile.skill_names()
    matched = [s for s in own if skill_key(s) in wanted]
    lines = [_GREETINGS[tone], "", _variant(_OPENINGS[template], key).format(title=vacancy.title, company=company)]

    body: list[str] = []
    if matched:
        body.append(f"Из того, что важно для вас, у меня есть опыт работы с {', '.join(matched[:5])}.")
    elif own:
        body.append(f"Мои основные инструменты: {', '.join(own[:5])}.")
    exp = _experience_sentence(profile)
    if exp:
        body.append(exp)
    project = _best_project(profile, wanted)
    if project and (length == "medium" or not exp):
        techs = f" ({', '.join(project.technologies[:4])})" if project.technologies else ""
        link = f" {project.url}" if project.url else ""
        body.append(f"Из проектов: {project.name}{techs}.{link}")
    if length == "medium" and profile.achievements:
        body.append(f"Результат, которым горжусь: {profile.achievements[0].rstrip('.')}.")
    lines.append(" ".join(body))
    lines += ["", _CLOSINGS[tone]]
    text = "\n".join(line for line in lines if line is not None).strip()
    return LetterResult(text=text, generator="local", issues=validate_letter(text, profile, vacancy))


_CANCELLARESE = [
    "являюсь", "в рамках", "данной вакансии", "осуществлять", "осуществление", "вышеуказанн",
    "в целях", "имею честь", "прошу рассмотреть мою кандидатуру", "стрессоустойчив", "коммуникабелен",
]  # fmt: skip
_OVERPROMISE = re.compile(
    r"(гарантирую|100\s*%|лучший\s+кандидат|идеальн\w+\s+кандидат|в\s+кратчайшие\s+сроки|любые\s+задачи)", re.I
)
_AI_RESIDUE = re.compile(r"(как\s+(языковая\s+)?модель|as an ai|ignore (all )?previous|я\s+—?\s*ии\b|chatgpt)", re.I)
_YEARS = re.compile(r"(\d+)\s*(?:\+\s*)?(?:год|года|лет)\s+(?:коммерческого\s+)?опыт", re.I)


def validate_letter(text: str, profile: CandidateProfile, vacancy: Vacancy | None = None) -> list[LetterIssue]:
    issues: list[LetterIssue] = []
    own = {skill_key(s) for s in profile.skill_names()}
    for project in profile.projects:
        own |= {skill_key(t) for t in project.technologies}
    for exp in profile.experience:
        own |= {skill_key(t) for t in exp.technologies}
    for skill in extract_skills(text):
        if skill_key(skill) not in own:
            issues.append(
                LetterIssue("unverified_skill", "error", f"В письме упомянут навык «{skill}», которого нет в профиле")
            )
    years = profile.total_experience_months / 12
    for m in _YEARS.finditer(text):
        if int(m.group(1)) > years + 0.5:
            issues.append(
                LetterIssue("experience_overstated", "error", f"Заявлено {m.group(1)} лет опыта, в профиле {years:.1f}")
            )
    if _OVERPROMISE.search(text):
        issues.append(LetterIssue("overpromise", "error", "Чрезмерные обещания"))
    if _AI_RESIDUE.search(text):
        issues.append(LetterIssue("ai_residue", "error", "Служебный текст модели в письме"))
    lowered = text.lower()
    for phrase in _CANCELLARESE:
        if phrase in lowered:
            issues.append(LetterIssue("cancellarese", "warning", f"Канцелярит: «{phrase}»"))
    if len(text) > MAX_LETTER_CHARS:
        issues.append(LetterIssue("too_long", "error", f"Письмо длиннее {MAX_LETTER_CHARS} символов"))
    if len(text) < 120:
        issues.append(LetterIssue("too_short", "warning", "Письмо слишком короткое"))
    return issues


LLM_SYSTEM = """Ты пишешь сопроводительные письма для откликов на hh.ru от первого лица соискателя.
Требования: естественный русский язык, деловой и живой тон без канцелярита, без шаблонных фраз,
без обещаний «гарантирую», без выдуманного опыта. Используй ТОЛЬКО факты из блока FACTS.
Не упоминай навыки, работодателей и цифры, которых нет в FACTS. Пиши гендерно-нейтрально
(избегай форм «готов/готова», «рад/рада»). Не добавляй подпись и контакты.
Верни JSON: {"letter": string}"""


async def generate_letter(
    vacancy: Vacancy,
    profile: CandidateProfile,
    *,
    template: str,
    tone: str,
    length: str,
    ai: AIService | None = None,
    user: User | None = None,
) -> LetterResult:
    local = generate_local(vacancy, profile, template=template, tone=tone, length=length)
    if ai is None or user is None:
        return local
    wanted = {skill_key(s) for s in vacancy_skills(vacancy)}
    facts = {
        "skills": profile.skill_names()[:30],
        "matching_skills": [s for s in profile.skill_names() if skill_key(s) in wanted],
        "experience": [
            {"company": e.company, "title": e.title, "current": e.current, "summary": e.description[:400]}
            for e in profile.experience[:3]
        ],
        "total_experience_months": profile.total_experience_months,
        "projects": [{"name": p.name, "technologies": p.technologies, "url": p.url} for p in profile.projects[:4]],
        "achievements": profile.achievements[:3],
        "education": [e.institution for e in profile.education[:2]],
    }
    prompt = (
        f"Шаблон: {TEMPLATES.get(template, template)}. Тон: {tone}. Длина: "
        f"{'3–4 предложения' if length == 'short' else '5–7 предложений'}.\n"
        f"FACTS: {facts}\n\n"
        + wrap_untrusted("vacancy", f"{vacancy.title}\n{vacancy.employer_name}\n{vacancy.description_text}", 6000)
    )
    try:
        data = await ai.complete_json(user, purpose="cover_letter", system=LLM_SYSTEM, prompt=prompt)
    except (AINotAvailable, AIError) as exc:
        log.info("llm letter skipped: %s", exc)
        return local
    text = str(data.get("letter") or "").strip()
    if not text:
        return local
    result = LetterResult(text=text, generator="ai", issues=validate_letter(text, profile, vacancy))
    if result.blocking:
        log.info("llm letter rejected by validator: %s", [i.code for i in result.issues])
        local.issues.append(
            LetterIssue("ai_rejected", "warning", "AI-вариант не прошёл проверку фактов, использован шаблон")
        )
        return local
    return result
