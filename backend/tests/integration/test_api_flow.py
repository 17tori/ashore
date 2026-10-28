"""End-to-end through the HTTP API, in the primary scenario: no hh.ru API access."""

VACANCY_TEXT = (
    "Ищем junior Python-разработчика. Задачи: сервисы на FastAPI, PostgreSQL, Docker. "
    "Опыт от 1 года. Удалённая работа. Зарплата от 100 000 до 130 000 ₽."
)


async def _setup(api, resume_text):
    await api.register()
    r = await api.post("/api/resumes/text", json={"title": "Python", "text": resume_text})
    assert r.status_code == 201, r.text
    return r.json()


async def _import(api, **kw):
    body = {"title": "Junior Python-разработчик", "employer_name": "ООО Пример", "description": VACANCY_TEXT} | kw
    r = await api.post("/api/vacancies/import", json=body)
    assert r.status_code == 201, r.text
    return r.json()


async def test_health(client):
    assert (await client.get("/api/health")).json() == {"status": "ok"}
    ready = await client.get("/api/health/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"]["hh_integration"] == "not_configured"


async def test_register_requires_pd_consent(client):
    r = await client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "x" * 12, "pd_consent": False}
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


async def test_auth_required_and_csrf(api, client):
    assert (await client.get("/api/resumes")).status_code == 401
    await api.register()
    r = await client.post("/api/resumes/text", json={"title": "x", "text": "y" * 50})  # no CSRF header
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "csrf_failed"


async def test_security_headers(client):
    r = await client.get("/api/health")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["x-request-id"]


async def test_login_rate_limited(api, client):
    await api.register(email="rl@example.com")
    codes = [
        (
            await client.post("/api/auth/login", json={"email": "rl@example.com", "password": "wrong-password"})
        ).status_code
        for _ in range(11)
    ]
    assert codes[:10] == [401] * 10
    assert codes[10] == 429


async def test_e2e_manual_apply(api, resume_text):
    resume = await _setup(api, resume_text)
    assert resume["skills_count"] >= 8

    match = await _import(api)
    assert match["vacancy"]["source"] == "manual"
    assert match["score"] >= 70
    assert match["decision"] in ("eligible", "review")

    inbox = (await api.get("/api/vacancies")).json()
    assert inbox["total"] == 1

    prepared = await api.post(f"/api/vacancies/{match['id']}/prepare")
    assert prepared.status_code == 201
    app = prepared.json()
    assert app["status"] == "awaiting_confirmation"
    assert app["letter"]["text"] and not app["letter"]["validation"]["blocking"]

    # Preparing again returns the same application: one per vacancy.
    again = (await api.post(f"/api/vacancies/{match['id']}/prepare")).json()
    assert again["id"] == app["id"]

    # Without hh.ru API access, approval hands off to hh.ru with the letter ready to paste.
    approved = (await api.post(f"/api/applications/{app['id']}/approve")).json()
    assert approved["mode"] == "manual"
    assert approved["letter_text"] == app["letter"]["text"]

    sent = (await api.post(f"/api/applications/{app['id']}/mark-sent")).json()
    assert sent["status"] == "sent"
    assert sent["confirmed_by"] == "user" and sent["channel"] == "manual"

    detail = (await api.get(f"/api/applications/{app['id']}")).json()
    assert [e["to"] for e in detail["events"]][-1] == "sent"

    dash = (await api.get("/api/dashboard")).json()
    assert dash["today"]["sent"] == 1
    assert dash["today"]["sent_platform_confirmed"] == 0

    analytics = (await api.get("/api/analytics?period=day")).json()
    assert analytics["overview"]["sent"] == 1


async def test_same_vacancy_imported_twice_is_deduplicated(api, resume_text):
    await _setup(api, resume_text)
    first = await _import(api, url="https://hh.ru/vacancy/12345")
    second = await _import(api, url="https://hh.ru/vacancy/12345?from=share")
    assert first["vacancy"]["id"] == second["vacancy"]["id"]
    assert first["id"] == second["id"]
    assert (await api.get("/api/vacancies")).json()["total"] == 1


async def test_manual_import_needs_text(api, resume_text):
    await _setup(api, resume_text)
    r = await api.post("/api/vacancies/import", json={"url": "https://hh.ru/vacancy/1", "title": "x"})
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "vacancy_text_required"


async def test_letter_with_invented_skill_blocks_approval(api, resume_text):
    await _setup(api, resume_text)
    match = await _import(api)
    app = (await api.post(f"/api/vacancies/{match['id']}/prepare")).json()
    edited = (
        await api.put(
            f"/api/applications/{app['id']}/letter", json={"text": "Пять лет работаю с Kubernetes и Scala. " * 4}
        )
    ).json()
    assert edited["letter"]["validation"]["blocking"]
    r = await api.post(f"/api/applications/{app['id']}/approve")
    assert r.status_code == 400
    assert r.json()["error"]["code"] == "letter_invalid"


async def test_idor_returns_404(api, other_api, resume_text):
    resume = await _setup(api, resume_text)
    match = await _import(api)
    app = (await api.post(f"/api/vacancies/{match['id']}/prepare")).json()

    await other_api.register()
    assert (await other_api.get(f"/api/vacancies/{match['id']}")).status_code == 404
    assert (await other_api.get(f"/api/applications/{app['id']}")).status_code == 404
    assert (await other_api.get(f"/api/resumes/{resume['id']}")).status_code == 404
    assert (await other_api.post(f"/api/applications/{app['id']}/mark-sent")).status_code == 404
    assert (await other_api.put(f"/api/applications/{app['id']}/letter", json={"text": "x" * 200})).status_code == 404
    assert (await other_api.get("/api/vacancies")).json()["total"] == 0
    # An imported vacancy is private: the other user cannot see it via their own import either.
    r = await other_api.patch("/api/automation/policy", json={"allowed_resume_ids": [resume["id"]]})
    assert r.status_code == 400


async def test_invalid_status_transition(api, resume_text):
    await _setup(api, resume_text)
    match = await _import(api)
    app = (await api.post(f"/api/vacancies/{match['id']}/prepare")).json()
    r = await api.post(f"/api/applications/{app['id']}/status", json={"status": "invitation"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "invalid_transition"


async def test_bookmarklet(api):
    await api.register()
    code = (await api.get("/api/vacancies/bookmarklet")).json()["code"]
    assert code.startswith("javascript:")
    assert "/clip#" in code


async def test_auto_apply_requires_explicit_confirmation(api, resume_text):
    resume = await _setup(api, resume_text)
    state = (await api.get("/api/automation")).json()
    assert state["mode"] == "manual" and not state["auto_active"]

    r = await api.patch("/api/automation/policy", json={"mode": "auto"})
    assert r.status_code == 400 and r.json()["error"]["code"] == "confirm_required"

    r = await api.post("/api/automation/confirm-auto", json={"rules_hash": state["rules_hash"], "acknowledged": True})
    assert r.status_code == 400 and r.json()["error"]["code"] == "auto_apply_not_confirmed"

    state = (
        await api.patch(
            "/api/automation/policy",
            json={
                "allowed_resume_ids": [resume["id"]],
                "allowed_positions": ["Python-разработчик"],
                "daily_limit": 500,
            },
        )
    ).status_code
    assert state == 422  # the hard cap cannot be exceeded
    state = (
        await api.patch(
            "/api/automation/policy",
            json={"allowed_resume_ids": [resume["id"]], "allowed_positions": ["Python-разработчик"], "daily_limit": 5},
        )
    ).json()
    assert state["auto_problems"] == []

    stale = "0" * 64
    r = await api.post("/api/automation/confirm-auto", json={"rules_hash": stale, "acknowledged": True})
    assert r.json()["error"]["code"] == "rules_changed"

    confirmed = (
        await api.post("/api/automation/confirm-auto", json={"rules_hash": state["rules_hash"], "acknowledged": True})
    ).json()
    assert confirmed["auto_active"] and confirmed["mode"] == "auto"

    # Changing any rule voids the confirmation until the user confirms again.
    changed = (await api.patch("/api/automation/policy", json={"min_score": 60})).json()
    assert changed["mode"] == "auto" and not changed["auto_active"]

    stopped = (await api.post("/api/automation/stop-all")).json()
    assert stopped["paused"]
    log = (await api.get("/api/automation/log")).json()
    assert {"automation.auto_confirmed", "automation.paused"} <= {e["action"] for e in log}


async def test_hh_connect_not_configured(api):
    await api.register()
    r = await api.post("/api/hh/connect")
    assert r.status_code == 409
    status = (await api.get("/api/hh/status")).json()
    assert status["configured"] is False
    assert all(c["status"] == "unknown" for c in status["capabilities"].values())


async def test_search_run_without_hh_is_honest(api, resume_text):
    await _setup(api, resume_text)
    profile = (await api.post("/api/search-profiles", json={"name": "Python", "positions": ["Python"]})).json()
    r = await api.post(f"/api/search-profiles/{profile['id']}/run")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "integration_unavailable"


async def test_demo_seed_marks_samples(api):
    await api.register()
    result = (await api.post("/api/demo/seed")).json()
    assert result["vacancies"] == 6
    await api.post("/api/demo/seed")  # idempotent
    inbox = (await api.get("/api/vacancies?include_hidden=true&per_page=100")).json()
    assert inbox["total"] == 6
    assert all(item["vacancy"]["is_sample"] for item in inbox["items"])
    by_title = {i["vacancy"]["title"]: i for i in inbox["items"]}
    scam = next(v for k, v in by_title.items() if "500 000" in k)
    assert scam["decision"] == "reject"


async def test_export_and_delete_account(api, client, resume_text):
    await _setup(api, resume_text)
    export = await api.get("/api/settings/export")
    assert export.status_code == 200
    data = export.json()
    assert "Иванова" in data["resumes"][0]["raw_text"]
    assert data["resumes"][0]["contacts"]["emails"] == ["anna.ivanova@example.com"]

    assert (await api.post("/api/settings/delete-account", json={"password": "wrong-password"})).status_code == 401
    assert (
        await api.post("/api/settings/delete-account", json={"password": "correct-horse-battery"})
    ).status_code == 204
    assert (await client.get("/api/auth/me")).status_code == 401


async def test_ai_consent_toggle(api):
    await api.register()
    s = (await api.patch("/api/settings", json={"ai_external_consent": True})).json()
    assert s["ai"]["consent"]
    s = (await api.patch("/api/settings", json={"ai_external_consent": False})).json()
    assert not s["ai"]["consent"]
    assert (await api.patch("/api/settings", json={"timezone": "Mars/Base"})).status_code == 400


async def test_telegram_webhook_hidden_when_not_configured(client):
    r = await client.post("/api/telegram/webhook", json={"update_id": 1})
    assert r.status_code == 404


async def test_resume_upload_rejects_fake_pdf(api):
    await api.register()
    r = await api.post("/api/resumes/upload", files={"file": ("cv.pdf", b"hello", "application/pdf")})
    assert r.status_code == 400


async def test_resume_versioning(api, resume_text):
    resume = await _setup(api, resume_text)
    full = (await api.get(f"/api/resumes/{resume['id']}")).json()
    v2 = (
        await api.put(f"/api/resumes/{resume['id']}/profile", json={"profile": full["profile"], "confirm_all": True})
    ).json()
    assert v2["version"] == 2 and v2["profile_confirmed"]
    versions = (await api.get(f"/api/resumes/{v2['id']}/versions")).json()
    assert [v["version"] for v in versions] == [2, 1]
    assert len((await api.get("/api/resumes")).json()) == 1
