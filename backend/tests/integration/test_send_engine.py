"""Application sending against a mocked hh.ru: idempotency, ambiguous results, stop conditions."""

import uuid
from datetime import timedelta

import httpx
import pytest
import respx
from sqlalchemy import func, select

from app.core.config import Settings
from app.db.base import utcnow
from app.models import Application, Notification, OAuthConnection, Resume, User
from app.models.enums import ApplicationStatus as S
from app.models.enums import Capability, CapabilityStatus, ConnectionStatus, VacancySource
from app.services.applications.engine import prepare_application, process_queue, send_application
from app.services.automation.policy import confirm_auto_rules, get_policy
from app.services.hhru.capabilities import capability_map, set_capability
from app.services.hhru.gateway import HhGateway, encrypt_tokens
from app.services.hhru.normalize import normalize_hh_vacancy
from app.services.hhru.oauth import TokenPair
from app.services.matching.engine import analyze_and_store
from app.services.resume.extraction import build_profile
from app.services.vacancies.ingest import upsert_vacancy
from tests.factories import search as make_search
from tests.unit.test_normalize import PAYLOAD

API = "https://api.hh.ru"
HH_SETTINGS = Settings(hh_user_agent="AshoreTest/0.1 (test@example.com)", hh_requests_per_second=1000, hh_max_retries=0)


def gateway(db, user) -> HhGateway:
    return HhGateway(db, user.id, settings=HH_SETTINGS)


async def world(db, resume_text, *, connected: bool = True, letter_required: bool = False):
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:8]}@example.com",
        password_hash="x",
        timezone="Europe/Moscow",
        settings={},
        pd_consent_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    resume = Resume(
        id=uuid.uuid4(),
        user_id=user.id,
        title="Python",
        version=1,
        is_primary=True,
        profile=build_profile(resume_text).model_dump(),
        quality={},
        hh_resume_id="a" * 38,
    )
    db.add(resume)
    profile = make_search(user_id=user.id, resume_id=resume.id, letter_mode="always")
    db.add(profile)
    await db.flush()
    payload = {
        **PAYLOAD,
        "id": str(uuid.uuid4().int)[:9],
        "has_test": False,
        "response_letter_required": letter_required,
        "description": "<p>Python, FastAPI, PostgreSQL, Docker. Опыт от 1 года.</p>",
    }
    vacancy, _ = await upsert_vacancy(db, normalize_hh_vacancy(payload), source=VacancySource.HH_API)
    match = await analyze_and_store(db, user, vacancy, profile, [resume], force=True)
    if connected:
        conn = OAuthConnection(
            id=uuid.uuid4(),
            user_id=user.id,
            access_token_enc="",
            status=ConnectionStatus.ACTIVE.value,
            consecutive_failures=0,
        )
        encrypt_tokens(conn, TokenPair("ACCESS", "REFRESH", utcnow() + timedelta(days=10)))
        db.add(conn)
    await db.flush()
    app = await prepare_application(db, user, match, target=S.AWAITING_CONFIRMATION)
    await db.commit()
    return user, resume, vacancy, match, app


async def count_apps(db, user) -> int:
    return (await db.execute(select(func.count()).where(Application.user_id == user.id))).scalar_one()


@respx.mock
async def test_user_confirmed_send_succeeds_once(db, resume_text):
    user, resume, vacancy, match, app = await world(db, resume_text)
    route = respx.post(f"{API}/negotiations").mock(
        return_value=httpx.Response(201, headers={"Location": "/negotiations/9001"})
    )

    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    await db.commit()
    assert outcome.status == S.SENT
    app = await db.get(Application, app.id)
    await db.refresh(app)
    assert app.status == S.SENT and app.confirmed_by == "platform" and app.hh_negotiation_id == "9001"
    sent = route.calls.last.request.content.decode()
    assert f"vacancy_id={vacancy.hh_id}" in sent and f"resume_id={resume.hh_resume_id}" in sent and "message=" in sent
    assert (await capability_map(db, user.id))[Capability.APPLY]["status"] == CapabilityStatus.VERIFIED

    # A second attempt (double click, retry, Telegram + web) never reaches hh.ru again.
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    assert outcome.status == S.SENT
    assert route.call_count == 1
    again = await prepare_application(db, user, match, target=S.AWAITING_CONFIRMATION)
    assert again.id == app.id and await count_apps(db, user) == 1


@respx.mock
async def test_timeout_after_send_becomes_unknown_then_reconciled(db, resume_text):
    user, resume, vacancy, match, app = await world(db, resume_text)
    post = respx.post(f"{API}/negotiations").mock(side_effect=httpx.ReadTimeout("slow"))

    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    await db.commit()
    assert outcome.status == S.UNKNOWN
    await db.refresh(app)
    assert app.status == S.UNKNOWN

    # Without verified read access, the user is asked; nothing is re-sent.
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    await db.commit()
    assert outcome.status == S.UNKNOWN and post.call_count == 1
    note = (
        await db.execute(
            select(Notification).where(Notification.user_id == user.id, Notification.kind == "manual_action")
        )
    ).scalar_one()
    assert "Проверьте" in note.title

    # With read access, reconciliation finds the negotiation on hh.ru.
    await set_capability(db, user.id, Capability.NEGOTIATIONS_READ, CapabilityStatus.VERIFIED)
    respx.get(f"{API}/negotiations").mock(
        return_value=httpx.Response(
            200, json={"items": [{"id": "77", "vacancy": {"id": vacancy.hh_id}, "resume": {"id": resume.hh_resume_id}}]}
        )
    )
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    await db.commit()
    await db.refresh(app)
    assert app.status == S.SENT and app.hh_negotiation_id == "77"
    assert post.call_count == 1


@respx.mock
async def test_reconcile_not_found_allows_one_retry(db, resume_text):
    user, resume, vacancy, match, app = await world(db, resume_text)
    post = respx.post(f"{API}/negotiations").mock(
        side_effect=[httpx.ReadTimeout("slow"), httpx.Response(201, headers={"Location": "/negotiations/5"})]
    )
    await send_application(db, user, app.id, gateway(db, user), actor="user")
    await db.commit()
    await set_capability(db, user.id, Capability.NEGOTIATIONS_READ, CapabilityStatus.VERIFIED)
    respx.get(f"{API}/negotiations").mock(return_value=httpx.Response(200, json={"items": []}))
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    assert outcome.status == S.SENT
    assert post.call_count == 2


@respx.mock
async def test_already_applied_is_success(db, resume_text):
    user, *_, app = await world(db, resume_text)
    respx.post(f"{API}/negotiations").mock(
        return_value=httpx.Response(403, json={"errors": [{"type": "negotiations", "value": "already_applied"}]})
    )
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    assert outcome.status == S.SENT


@respx.mock
async def test_limit_exceeded_pauses_automation(db, resume_text):
    user, *_, app = await world(db, resume_text)
    respx.post(f"{API}/negotiations").mock(
        return_value=httpx.Response(403, json={"errors": [{"type": "negotiations", "value": "limit_exceeded"}]})
    )
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    assert outcome.status == S.READY
    assert (await get_policy(db, user.id)).paused


@respx.mock
async def test_captcha_stops_everything(db, resume_text):
    user, *_, app = await world(db, resume_text)
    respx.post(f"{API}/negotiations").mock(
        return_value=httpx.Response(403, json={"errors": [{"type": "captcha_required", "value": "captcha_required"}]})
    )
    await send_application(db, user, app.id, gateway(db, user), actor="user")
    policy = await get_policy(db, user.id)
    conn = (await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))).scalar_one()
    assert policy.paused
    assert conn.circuit_open_until and conn.circuit_open_until > utcnow()


@respx.mock
async def test_forbidden_falls_back_to_manual(db, resume_text):
    user, *_, app = await world(db, resume_text)
    respx.post(f"{API}/negotiations").mock(return_value=httpx.Response(403, json={"errors": [{"type": "forbidden"}]}))
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    assert outcome.status == S.AWAITING_CONFIRMATION
    assert (await capability_map(db, user.id))[Capability.APPLY]["status"] == CapabilityStatus.UNAVAILABLE

    # Once hh.ru said no, further sends are blocked locally and never hit the API.
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="user")
    assert outcome.status == "blocked"


@respx.mock
async def test_expired_token_is_refreshed(db, resume_text):
    user, *_, app = await world(db, resume_text)
    conn = (await db.execute(select(OAuthConnection).where(OAuthConnection.user_id == user.id))).scalar_one()
    conn.access_expires_at = utcnow() - timedelta(minutes=1)
    await db.commit()
    token = respx.post(f"{API}/token").mock(
        return_value=httpx.Response(200, json={"access_token": "NEW", "refresh_token": "R2", "expires_in": 1209600})
    )
    post = respx.post(f"{API}/negotiations").mock(return_value=httpx.Response(201))
    HH = Settings(hh_user_agent="AshoreTest/0.1", hh_client_id="c", hh_client_secret="s", hh_requests_per_second=1000)
    outcome = await send_application(db, user, app.id, HhGateway(db, user.id, settings=HH), actor="user")
    assert outcome.status == S.SENT
    assert token.call_count == 1
    assert post.calls.last.request.headers["Authorization"] == "Bearer NEW"


@respx.mock
async def test_auto_mode_never_sends_unverified_or_unconfirmed(db, resume_text):
    user, resume, vacancy, match, app = await world(db, resume_text)
    post = respx.post(f"{API}/negotiations").mock(return_value=httpx.Response(201))
    policy = await get_policy(db, user.id)

    # Assisted mode: nothing is sent automatically.
    policy.mode = "assisted"
    await db.commit()
    await process_queue(db, user, gateway(db, user))
    assert post.call_count == 0

    # Auto confirmed, but hh.ru has not verified the apply operation for this account yet.
    policy = await get_policy(db, user.id)
    policy.allowed_resume_ids = [str(resume.id)]
    policy.allowed_positions = ["Python"]
    policy.min_score = 50
    await confirm_auto_rules(db, user, policy)
    app.status = S.READY.value
    await db.commit()
    stats = await process_queue(db, user, gateway(db, user))
    assert post.call_count == 0 and stats["blocked"] >= 1

    # Verified + confirmed: sends, within the daily limit.
    await set_capability(db, user.id, Capability.APPLY, CapabilityStatus.VERIFIED)
    a = await db.get(Application, app.id)
    a.status = S.READY.value
    await db.commit()
    stats = await process_queue(db, user, gateway(db, user))
    assert stats["sent"] == 1 and post.call_count == 1


@respx.mock
async def test_auto_respects_daily_limit_and_pause(db, resume_text):
    user, resume, vacancy, match, app = await world(db, resume_text)
    post = respx.post(f"{API}/negotiations").mock(return_value=httpx.Response(201))
    await set_capability(db, user.id, Capability.APPLY, CapabilityStatus.VERIFIED)
    policy = await get_policy(db, user.id)
    policy.allowed_resume_ids = [str(resume.id)]
    policy.allowed_positions = ["Python"]
    policy.min_score = 50
    policy.daily_limit = 1
    await confirm_auto_rules(db, user, policy)
    # One application already sent today.
    other = Application(
        id=uuid.uuid4(),
        user_id=user.id,
        vacancy_id=(await world(db, resume_text))[2].id,
        status=S.SENT.value,
        idempotency_key=uuid.uuid4().hex,
        sent_at=utcnow(),
    )
    db.add(other)
    a = await db.get(Application, app.id)
    a.status = S.READY.value
    await db.commit()
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="system")
    assert outcome.status == "blocked" and "лимит" in outcome.detail
    assert post.call_count == 0

    policy = await get_policy(db, user.id)
    policy.daily_limit = 5
    policy.paused = True
    await db.commit()
    outcome = await send_application(db, user, app.id, gateway(db, user), actor="system")
    assert post.call_count == 0


async def test_unique_application_per_vacancy(db, resume_text):
    user, resume, vacancy, match, app = await world(db, resume_text, connected=False)
    db.add(
        Application(id=uuid.uuid4(), user_id=user.id, vacancy_id=vacancy.id, status="matched", idempotency_key="dup")
    )
    with pytest.raises(Exception, match="unique|duplicate"):
        await db.flush()
