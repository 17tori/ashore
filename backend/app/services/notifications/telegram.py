"""Optional Telegram bot: notifications and a few safe controls. Never sends tokens or resume contents."""

import html
import logging
import uuid
from datetime import timedelta
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.crypto import random_token, token_hash
from app.db.base import utcnow
from app.models import Application, Notification, TelegramLink, TelegramLinkCode, User, Vacancy
from app.models.enums import ApplicationStatus as S
from app.services.analytics.metrics import overview
from app.services.applications.engine import mark_sent_manually, send_application
from app.services.applications.state import transition
from app.services.audit import audit
from app.services.automation.policy import local_day_start, pause_automation, resume_automation
from app.services.hhru.gateway import HhGateway

log = logging.getLogger(__name__)
LINK_CODE_TTL = timedelta(minutes=15)


class TelegramBot:
    def __init__(self, settings: Settings | None = None, http: httpx.AsyncClient | None = None):
        self.settings = settings or get_settings()
        self._http = http

    @property
    def enabled(self) -> bool:
        return self.settings.telegram_configured

    async def call(self, method: str, payload: dict[str, Any]) -> dict:
        token = self.settings.telegram_bot_token.get_secret_value()
        http = self._http or httpx.AsyncClient(timeout=15)
        try:
            response = await http.post(f"https://api.telegram.org/bot{token}/{method}", json=payload)
            return response.json()
        except (httpx.TransportError, ValueError) as exc:
            log.warning("telegram call failed: %s", exc.__class__.__name__)
            return {"ok": False}
        finally:
            if self._http is None:
                await http.aclose()

    async def send(self, chat_id: int, text: str, buttons: list[list[dict]] | None = None) -> bool:
        payload: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text[:4000],
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        if buttons:
            payload["reply_markup"] = {"inline_keyboard": buttons}
        return bool((await self.call("sendMessage", payload)).get("ok"))


async def create_link_code(db: AsyncSession, user: User) -> dict:
    code = random_token(12)
    db.add(
        TelegramLinkCode(
            id=uuid.uuid4(), user_id=user.id, code_hash=token_hash(code), expires_at=utcnow() + LINK_CODE_TTL
        )
    )
    username = get_settings().telegram_bot_username
    return {
        "code": code,
        "deep_link": f"https://t.me/{username}?start={code}" if username else None,
        "expires_in_seconds": int(LINK_CODE_TTL.total_seconds()),
    }


async def _link(db: AsyncSession, chat_id: int, username: str, code: str) -> str:
    row = (
        await db.execute(
            select(TelegramLinkCode).where(TelegramLinkCode.code_hash == token_hash(code)).with_for_update()
        )
    ).scalar_one_or_none()
    if row is None or row.used_at is not None or row.expires_at < utcnow():
        return "Код недействителен или истёк. Получите новый в настройках Ashore."
    row.used_at = utcnow()
    existing = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
    if existing is not None and existing.user_id != row.user_id:
        return "Этот чат уже привязан к другому аккаунту."
    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == row.user_id))).scalar_one_or_none()
    if link is None:
        db.add(TelegramLink(id=uuid.uuid4(), user_id=row.user_id, chat_id=chat_id, username=username[:64]))
    else:
        link.chat_id = chat_id
        link.username = username[:64]
    await audit(db, user_id=row.user_id, action="telegram.linked", actor="telegram")
    return "Готово: Telegram привязан. Команды: /stats, /queue, /pause, /resume."


async def _user_for_chat(db: AsyncSession, chat_id: int) -> User | None:
    link = (await db.execute(select(TelegramLink).where(TelegramLink.chat_id == chat_id))).scalar_one_or_none()
    if link is None:
        return None
    user = await db.get(User, link.user_id)
    return user if user and user.deleted_at is None else None


async def _stats_text(db: AsyncSession, user: User) -> str:
    today = await overview(db, user.id, since=local_day_start(user.timezone))
    week = await overview(db, user.id, since=utcnow() - timedelta(days=7))
    return (
        "<b>Сегодня</b>\n"
        f"Найдено: {today['found']} · подходит: {today['suitable']} · отправлено: {today['sent']}\n"
        f"<b>За 7 дней</b>\nОтклики: {week['sent']} · приглашения: {week['invitations']}"
    )


async def _queue(db: AsyncSession, user: User, bot: TelegramBot, chat_id: int) -> None:
    rows = (
        await db.execute(
            select(Application, Vacancy)
            .join(Vacancy, Vacancy.id == Application.vacancy_id)
            .where(Application.user_id == user.id, Application.status == S.AWAITING_CONFIRMATION.value)
            .order_by(Application.created_at)
            .limit(5)
        )
    ).all()
    if not rows:
        await bot.send(chat_id, "Очередь подтверждения пуста.")
        return
    for app, vacancy in rows:
        text = f"<b>{html.escape(vacancy.title)}</b>\n{html.escape(vacancy.employer_name)}"
        buttons = [
            [
                {"text": "Отправить", "callback_data": f"approve:{app.id}"},
                {"text": "Пропустить", "callback_data": f"skip:{app.id}"},
            ]
        ]
        if vacancy.url:
            buttons.append([{"text": "Открыть на hh.ru", "url": vacancy.url}])
        await bot.send(chat_id, text, buttons)


async def _callback(db: AsyncSession, user: User, data: str, bot: TelegramBot, chat_id: int) -> str:
    action, _, raw_id = data.partition(":")
    try:
        app_id = uuid.UUID(raw_id)
    except ValueError:
        return "Неизвестное действие"
    app = await db.get(Application, app_id)
    if app is None or app.user_id != user.id:  # IDOR guard: callbacks are client-controlled strings
        return "Отклик не найден"
    if action == "skip":
        await transition(db, app, S.ARCHIVED, actor="telegram", note="пропущено в Telegram")
        return "Пропущено"
    if action == "sent":
        await mark_sent_manually(db, user, app, actor="telegram")
        return "Отмечено как отправленное"
    if action == "approve":
        outcome = await send_application(db, user, app.id, HhGateway(db, user.id), actor="telegram")
        if outcome.status == S.SENT:
            return "Отклик отправлен через hh.ru"
        vacancy = await db.get(Vacancy, app.vacancy_id)
        if vacancy.apply_url:
            await bot.send(
                chat_id,
                f"Через API не получилось: {html.escape(outcome.detail)}. Откликнитесь на сайте и отметьте:",
                [
                    [{"text": "Открыть форму отклика", "url": vacancy.apply_url}],
                    [{"text": "Я отправил(а)", "callback_data": f"sent:{app.id}"}],
                ],
            )
        return "Нужен отклик на сайте"
    return "Неизвестное действие"


async def handle_update(db: AsyncSession, update: dict, bot: TelegramBot | None = None) -> None:
    bot = bot or TelegramBot()
    if "callback_query" in update:
        cq = update["callback_query"]
        chat_id = (cq.get("message") or {}).get("chat", {}).get("id")
        user = await _user_for_chat(db, chat_id) if chat_id else None
        answer = await _callback(db, user, cq.get("data") or "", bot, chat_id) if user else "Чат не привязан"
        await bot.call("answerCallbackQuery", {"callback_query_id": cq.get("id"), "text": answer[:190]})
        return
    message = update.get("message") or {}
    chat_id = (message.get("chat") or {}).get("id")
    text = (message.get("text") or "").strip()
    if not chat_id or not text:
        return
    if text.startswith("/start"):
        code = text.partition(" ")[2].strip()
        reply = (
            await _link(db, chat_id, (message.get("from") or {}).get("username") or "", code)
            if code
            else ("Откройте Ashore → Настройки → Telegram и нажмите «Привязать».")
        )
        await bot.send(chat_id, reply)
        return
    user = await _user_for_chat(db, chat_id)
    if user is None:
        await bot.send(chat_id, "Чат не привязан. Откройте Ashore → Настройки → Telegram.")
        return
    command = text.split()[0].lower()
    if command == "/stats":
        await bot.send(chat_id, await _stats_text(db, user))
    elif command == "/pause":
        await pause_automation(db, user.id, "Пауза из Telegram", actor="telegram")
        await bot.send(chat_id, "Автоматизация на паузе.")
    elif command == "/resume":
        await resume_automation(db, user.id, actor="telegram")
        await bot.send(chat_id, "Автоматизация возобновлена.")
    elif command == "/queue":
        await _queue(db, user, bot, chat_id)
    elif command == "/unlink":
        link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user.id))).scalar_one()
        await db.delete(link)
        await bot.send(chat_id, "Telegram отвязан.")
    else:
        await bot.send(chat_id, "Команды: /stats, /queue, /pause, /resume, /unlink")


async def dispatch_pending(db: AsyncSession, bot: TelegramBot | None = None, limit: int = 200) -> int:
    bot = bot or TelegramBot()
    if not bot.enabled:
        return 0
    rows = (
        await db.execute(
            select(Notification, TelegramLink)
            .join(TelegramLink, TelegramLink.user_id == Notification.user_id)
            .where(
                Notification.telegram_sent_at.is_(None),
                Notification.created_at >= utcnow() - timedelta(hours=24),
                TelegramLink.notifications_enabled.is_(True),
            )
            .order_by(Notification.created_at)
            .limit(limit)
            .with_for_update(of=Notification, skip_locked=True)
        )
    ).all()
    sent = 0
    for notification, link in rows:
        text = f"<b>{html.escape(notification.title)}</b>"
        if notification.body:
            text += f"\n{html.escape(notification.body)}"
        url = (notification.payload or {}).get("url")
        buttons = [[{"text": "Открыть", "url": url}]] if url else None
        if await bot.send(link.chat_id, text, buttons):
            sent += 1
        notification.telegram_sent_at = utcnow()
    return sent
