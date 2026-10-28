from app.services.hhru.normalize import (
    extract_hh_vacancy_id,
    html_to_text,
    normalize_hh_vacancy,
    normalize_manual,
    parse_salary_text,
)

PAYLOAD = {
    "id": "123456",
    "name": "Junior Python Developer",
    "alternate_url": "https://hh.ru/vacancy/123456",
    "apply_alternate_url": "https://hh.ru/applicant/vacancy_response?vacancyId=123456",
    "employer": {"id": "42", "name": "Пример", "alternate_url": "https://hh.ru/employer/42"},
    "area": {"id": "1", "name": "Москва"},
    "salary_range": {"from": 100000, "to": None, "currency": "RUR", "gross": False},
    "work_format": [{"id": "REMOTE", "name": "Удалённо"}],
    "employment_form": {"id": "FULL"},
    "experience": {"id": "between1And3"},
    "description": "<p>Пишем на <strong>Python</strong></p><ul><li>FastAPI</li></ul>",
    "key_skills": [{"name": "Python"}, {"name": "FastAPI"}],
    "published_at": "2026-10-20T10:00:00+0300",
    "archived": False,
    "has_test": True,
    "response_letter_required": True,
}


def test_new_format_fields():
    nv = normalize_hh_vacancy(PAYLOAD)
    assert nv.hh_id == "123456"
    assert nv.salary_from == 100000 and nv.salary_to is None and nv.salary_currency == "RUR"
    assert nv.work_formats == ["remote"]
    assert nv.employment_type == "full"
    assert nv.has_test and nv.response_letter_required
    assert "Python" in nv.description_text and "<" not in nv.description_text
    assert nv.published_at is not None and nv.published_at.utcoffset() is not None


def test_legacy_fields_and_missing_salary():
    legacy = dict(PAYLOAD)
    for key in ("salary_range", "work_format", "employment_form"):
        legacy.pop(key)
    legacy["salary"] = None
    legacy["schedule"] = {"id": "remote"}
    legacy["employment"] = {"id": "full"}
    nv = normalize_hh_vacancy(legacy)
    assert nv.salary_from is None and nv.salary_to is None
    assert "remote" in nv.work_formats
    assert nv.employment_type == "full"


def test_content_hash_ignores_volatile_fields():
    a = normalize_hh_vacancy(PAYLOAD)
    b = normalize_hh_vacancy({**PAYLOAD, "published_at": "2026-10-21T10:00:00+0300"})
    c = normalize_hh_vacancy({**PAYLOAD, "name": "Middle Python Developer"})
    assert a.content_hash() == b.content_hash() != c.content_hash()


def test_extract_id():
    assert extract_hh_vacancy_id("https://hh.ru/vacancy/987654?from=x") == "987654"
    assert extract_hh_vacancy_id("https://spb.hh.ru/vacancy/55") == "55"
    assert extract_hh_vacancy_id("987") == "987"
    assert extract_hh_vacancy_id("https://example.com/vacancy/1") is None


def test_salary_text():
    assert parse_salary_text("от 80 000 до 120 000 ₽ на руки") == (80000, 120000, "RUR")
    assert parse_salary_text("до 150 000 руб.")[1] == 150000
    assert parse_salary_text("з/п не указана") == (None, None, None)


def test_manual_import_keeps_unknowns_unknown():
    nv = normalize_manual(title="Python-разработчик", description="Удалённая работа. Без опыта. Python, SQL." * 3)
    assert nv.hh_id is None and nv.apply_url is None
    assert "remote" in nv.work_formats
    assert nv.experience_id == "noExperience"
    assert nv.salary_from is None


def test_html_to_text_strips_scripts():
    assert "alert" not in html_to_text("<p>ok</p><script>alert(1)</script>")
