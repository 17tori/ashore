from fastapi import APIRouter, Request
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import constant_time_equals
from app.core.errors import IntegrationUnavailable, NotFound
from app.models import TelegramLink
from app.security.deps import DB, CurrentUser
from app.services.audit import audit
from app.services.notifications.telegram import create_link_code, handle_update

router = APIRouter(prefix="/api/telegram", tags=["telegram"])
SECRET_HEADER = "x-telegram-bot-api-secret-token"


class TelegramPrefs(BaseModel):
    notifications_enabled: bool


@router.post("/link-code")
async def link_code(db: DB, user: CurrentUser) -> dict:
    if not get_settings().telegram_configured:
        raise IntegrationUnavailable("Telegram-бот не настроен на сервере (нужен TELEGRAM_BOT_TOKEN)")
    return await create_link_code(db, user)


@router.patch("/link")
async def update_link(body: TelegramPrefs, db: DB, user: CurrentUser) -> dict:
    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user.id))).scalar_one_or_none()
    if link is None:
        raise NotFound("Telegram не привязан")
    link.notifications_enabled = body.notifications_enabled
    return {"notifications_enabled": link.notifications_enabled}


@router.delete("/link", status_code=204)
async def unlink(db: DB, user: CurrentUser) -> None:
    link = (await db.execute(select(TelegramLink).where(TelegramLink.user_id == user.id))).scalar_one_or_none()
    if link is not None:
        await db.delete(link)
        await audit(db, user_id=user.id, action="telegram.unlinked")


@router.post("/webhook", include_in_schema=False)
async def webhook(request: Request, db: DB) -> dict:
    """Telegram calls this with the secret set via setWebhook(secret_token=...). Anything else is a 404."""
    settings = get_settings()
    expected = settings.telegram_webhook_secret.get_secret_value()
    if not settings.telegram_configured or not expected:
        raise NotFound("Не найдено")
    if not constant_time_equals(request.headers.get(SECRET_HEADER, ""), expected):
        raise NotFound("Не найдено")
    try:
        update = await request.json()
    except ValueError:
        return {"ok": True}
    if isinstance(update, dict):
        await handle_update(db, update)
    return {"ok": True}
