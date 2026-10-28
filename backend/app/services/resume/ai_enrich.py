"""Optional LLM enrichment of a rule-based profile, with hallucination guards.

The model may only *add* facts that are literally supported by the resume text. Anything it claims that
cannot be found in the text goes to ``assumptions`` for the user to confirm, never into the profile."""

import logging
import re

from app.models import User
from app.schemas.profile import Assumption, CandidateProfile, ProfileSkill
from app.services.ai.provider import AIError, AINotAvailable
from app.services.ai.service import AIService, wrap_untrusted
from app.services.matching.skills import SKILLS, canonical_skill

log = logging.getLogger(__name__)

SYSTEM = """Ты извлекаешь факты из резюме соискателя на российском рынке труда.
Верни только JSON-объект со схемой:
{"skills": [string], "desired_positions": [string], "industries": [string],
 "achievements": [string], "level": "intern|junior|middle|senior|lead|unknown", "summary": string}
Правила: используй только то, что явно написано в резюме. Не придумывай навыки, работодателей, дипломы,
сертификаты и достижения. Если сведений нет, верни пустой список или "unknown"."""


def _supported(term: str, text_lower: str) -> bool:
    term_l = term.lower().strip()
    if not term_l:
        return False
    if term_l in text_lower:
        return True
    canonical = canonical_skill(term)
    aliases = [canonical.lower(), *SKILLS.get(canonical, [])]
    return any(re.search(rf"(?<![\w]){re.escape(a)}(?![\w])", text_lower) for a in aliases if len(a) > 1)


async def enrich_profile(
    ai: AIService, user: User, profile: CandidateProfile, text: str
) -> tuple[CandidateProfile, bool]:
    """Returns (profile, used_ai). Falls back silently to the rule-based profile."""
    try:
        data = await ai.complete_json(
            user, purpose="resume_extraction", system=SYSTEM, prompt=wrap_untrusted("resume", text, 20_000)
        )
    except (AINotAvailable, AIError) as exc:
        log.info("resume enrichment skipped: %s", exc)
        return profile, False

    text_lower = text.lower()
    known = {s.name.lower() for s in profile.skills}
    for raw in data.get("skills") or []:
        if not isinstance(raw, str):
            continue
        name = canonical_skill(raw)
        if name.lower() in known:
            continue
        if _supported(raw, text_lower):
            profile.skills.append(ProfileSkill(name=name, source="llm"))
            known.add(name.lower())
        else:
            profile.assumptions.append(
                Assumption(field="skills", value=name, reason="AI предположил навык, которого нет в тексте резюме")
            )
    for raw in data.get("desired_positions") or []:
        if isinstance(raw, str) and raw and raw not in profile.desired_positions and _supported(raw, text_lower):
            profile.desired_positions.append(raw[:120])
    for raw in data.get("achievements") or []:
        if isinstance(raw, str) and raw not in profile.achievements:
            digits_ok = all(d in text for d in re.findall(r"\d+", raw))
            if digits_ok and len(raw) < 300:
                profile.achievements.append(raw)
    for raw in data.get("industries") or []:
        if isinstance(raw, str) and raw not in profile.industries:
            profile.industries.append(raw[:80])
    level = data.get("level")
    if level in {"intern", "junior", "middle", "senior", "lead"} and level != profile.level:
        profile.assumptions.append(
            Assumption(field="level", value=level, reason="AI оценивает уровень иначе, чем расчёт по стажу")
        )
    if not profile.summary and isinstance(data.get("summary"), str):
        profile.assumptions.append(
            Assumption(field="summary", value=data["summary"][:600], reason="Черновик раздела «О себе» от AI")
        )
    return profile, True
