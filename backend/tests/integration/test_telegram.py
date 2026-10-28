import uuid

from sqlalchemy import select

from app.core.config import Settings
from app.db.base import utcnow
from app.models import Application, TelegramLink, User
from app.services.automation.policy import get_policy
from app.services.notifications.service import notify
from app.services.notifications.telegram import TelegramBot, create_link_code, dispatch_pending, handle_update


class FakeBot(TelegramBot):
    def __init__(self):
        super().__init__(Settings(telegram_bot_token="123:abc", telegram_bot_username="ashore_bot"))
        self.sent: list[tuple[int, str]] = []
        self.answers: list[str] = []

    async def call(self, method, payload):
        if method == "sendMessage":
            self.sent.append((payload["chat_id"], payload["text"]))
        elif method == "answerCallbackQuery":
            self.answers.append(payload["text"])
        return {"ok": True}


async def _user(db) -> User:
    user = User(
        id=uuid.uuid4(),
        email=f"{uuid.uuid4().hex[:6]}@example.com",
        password_hash="x",
        timezone="Europe/Moscow",
        settings={},
        pd_consent_at=utcnow(),
    )
    db.add(user)
    await db.flush()
    return user


def msg(chat_id: int, text: str) -> dict:
    return {"message": {"chat": {"id": chat_id}, "from": {"username": "tester"}, "text": text}}


async def test_link_flow_and_commands(db):
    user = await _user(db)
    bot = FakeBot()
    code = (await create_link_code(db, user))["code"]
    await handle_update(db, msg(555, f"/start {code}"), bot)
    assert "Готово" in bot.sent[-1][1]
    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user.id))).scalar_one()
    assert link.chat_id == 555

    # A code works once.
    await handle_update(db, msg(556, f"/start {code}"), bot)
    assert "недействителен" in bot.sent[-1][1]

    await handle_update(db, msg(555, "/pause"), bot)
    assert (await get_policy(db, user.id)).paused
    await handle_update(db, msg(555, "/resume"), bot)
    assert not (await get_policy(db, user.id)).paused
    await handle_update(db, msg(555, "/stats"), bot)
    assert "Сегодня" in bot.sent[-1][1]


async def test_unlinked_chat_has_no_access(db):
    bot = FakeBot()
    await handle_update(db, msg(999, "/stats"), bot)
    assert "не привязан" in bot.sent[-1][1]


async def test_callback_cannot_touch_other_users_application(db, resume_text):
    owner = await _user(db)
    attacker = await _user(db)
    bot = FakeBot()
    db.add(TelegramLink(id=uuid.uuid4(), user_id=attacker.id, chat_id=777, username="a"))
    from tests.integration.test_send_engine import world

    _, _, _, _, app = await world(db, resume_text, connected=False)
    await handle_update(
        db, {"callback_query": {"id": "1", "data": f"skip:{app.id}", "message": {"chat": {"id": 777}}}}, bot
    )
    assert bot.answers[-1] == "Отклик не найден"
    assert (await db.get(Application, app.id)).status == "awaiting_confirmation"
    assert owner


async def test_dispatch_sends_once(db):
    user = await _user(db)
    db.add(TelegramLink(id=uuid.uuid4(), user_id=user.id, chat_id=42, username="u"))
    await notify(db, user.id, kind="invitation", title="Приглашение <b>", body="Компания пригласила", dedupe_key="i1")
    bot = FakeBot()
    assert await dispatch_pending(db, bot) == 1
    assert await dispatch_pending(db, bot) == 0
    assert "&lt;b&gt;" in bot.sent[0][1]  # user-controlled text is escaped
