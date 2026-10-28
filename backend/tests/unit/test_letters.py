import pytest

from app.services.cover_letters.generator import TEMPLATES, generate_local, validate_letter
from app.services.resume.extraction import build_profile
from tests.factories import vacancy


@pytest.mark.parametrize("template", list(TEMPLATES))
@pytest.mark.parametrize("tone", ["formal", "neutral", "friendly"])
def test_templates_produce_valid_letters(resume_text, template, tone):
    profile = build_profile(resume_text)
    result = generate_local(vacancy(), profile, template=template, tone=tone, length="short")
    assert 120 <= len(result.text) <= 2000
    assert not result.blocking, result.issues
    assert "Python" in result.text or "FastAPI" in result.text


def test_letter_never_claims_missing_skills(resume_text):
    profile = build_profile(resume_text)
    v = vacancy(key_skills=["Kubernetes", "Python"], description_text="Нужен Kubernetes и Python")
    result = generate_local(v, profile, template="junior_developer", tone="neutral", length="medium")
    assert "Kubernetes" not in result.text


def test_validator_catches_fabrication(resume_text):
    profile = build_profile(resume_text)
    codes = {i.code for i in validate_letter("У меня 5 лет опыта с Kubernetes. Гарантирую результат!", profile)}
    assert {"unverified_skill", "experience_overstated", "overpromise"} <= codes


def test_validator_catches_model_residue(resume_text):
    profile = build_profile(resume_text)
    codes = {i.code for i in validate_letter("Как языковая модель, я не могу... " * 5, profile)}
    assert "ai_residue" in codes


def test_validator_length(resume_text):
    profile = build_profile(resume_text)
    assert any(i.code == "too_long" for i in validate_letter("а" * 2100, profile))
