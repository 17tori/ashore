import uuid

from app.models import Resume
from app.models.enums import MatchDecision
from app.services.matching.engine import analyze, decide
from app.services.matching.fraud import fraud_signals
from app.services.matching.scoring import hard_filters, normalize_weights, score_vacancy
from app.services.matching.skills import canonical_skill, extract_skills
from app.services.resume.extraction import build_profile
from tests.factories import search, vacancy


def _resume(text: str) -> Resume:
    return Resume(id=uuid.uuid4(), user_id=uuid.uuid4(), title="r", version=1, profile=build_profile(text).model_dump())


def test_skill_aliases():
    assert canonical_skill("postgres") == canonical_skill("PostgreSQL")
    assert "Python" in extract_skills("Опыт с python3 и FastAPI")
    assert "Go" not in extract_skills("Let's go to the office")


def test_weights_normalized():
    w = normalize_weights(
        {"skills": 3, "experience": 1, "title": 0, "salary": 0, "format_region": 0, "education_other": 0}
    )
    assert round(sum(w.values())) == 100
    assert w["skills"] == 75


def test_good_match_scores_high(resume_text):
    profile = build_profile(resume_text)
    result = score_vacancy(vacancy(), search(), profile)
    assert result["score"] >= 70
    assert set(result["matched_skills"]) >= {"Python", "FastAPI"}
    assert hard_filters(vacancy(), search(), profile).failures == []


def test_hard_filters(resume_text):
    profile = build_profile(resume_text)
    assert hard_filters(vacancy(archived=True), search(), profile).failures
    low = hard_filters(vacancy(salary_from=40_000, salary_to=50_000), search(), profile)
    assert any("ниже минимума" in f for f in low.failures)
    office = hard_filters(vacancy(work_formats=["on_site"], area_id="2", area_name="Казань"), search(), profile)
    assert office.failures
    senior = hard_filters(vacancy(experience_id="moreThan6"), search(), profile)
    assert any("опыт" in f for f in senior.failures)
    stop = hard_filters(vacancy(), search(excluded_employers=[{"id": "1", "name": "ООО Тест"}]), profile)
    assert any("стоп-лист" in f for f in stop.failures)


def test_missing_salary_is_a_risk_not_a_rejection(resume_text):
    profile = build_profile(resume_text)
    result = hard_filters(vacancy(salary_from=None, salary_to=None), search(), profile)
    assert not result.failures
    assert "зарплата не указана" in result.risks
    strict = hard_filters(vacancy(salary_from=None, salary_to=None), search(only_with_salary=True), profile)
    assert strict.failures


def test_contradictory_requirements_go_to_review(resume_text):
    profile = build_profile(resume_text)
    v = vacancy(experience_id="noExperience", description_text="Стажёр без опыта. Требуется опыт от 5 лет на Python.")
    result = hard_filters(v, search(), profile)
    assert "противоречивые требования к опыту" in result.review_reasons


def test_fraud_signals():
    strong, weak = fraud_signals(
        "Оператор", "Оплата обучения 5000 рублей перед стартом", salary_from=300_000, experience_id="noExperience"
    )
    assert strong
    assert weak


def test_decide_thresholds():
    s = search()
    assert decide(85, [], [], s) == MatchDecision.ELIGIBLE
    assert decide(85, [], ["тест"], s) == MatchDecision.REVIEW
    assert decide(60, [], [], s) == MatchDecision.REVIEW
    assert decide(30, [], [], s) == MatchDecision.REJECT
    assert decide(99, ["регион"], [], s) == MatchDecision.REJECT


def test_analyze_picks_best_resume(resume_text):
    python = _resume(resume_text)
    designer = _resume("Ключевые навыки\nFigma, Photoshop\n\nОпыт работы\nДизайнер")
    result = analyze(vacancy(), search(), [designer, python])
    assert result["recommended_resume_id"] == str(python.id)


def test_analyze_without_resume():
    result = analyze(vacancy(), search(), [])
    assert result["hard_filter_failures"]
