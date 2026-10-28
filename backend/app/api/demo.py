from fastapi import APIRouter

from app.core.config import get_settings
from app.core.errors import NotFound
from app.security.deps import DB, CurrentUser
from app.services.audit import audit
from app.services.demo import seed_demo

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.post("/seed")
async def seed(db: DB, user: CurrentUser) -> dict:
    """Loads sample vacancies (marked «Пример») so the whole flow can be tried without hh.ru access."""
    if not get_settings().demo_mode:
        raise NotFound("Демо-режим выключен")
    result = await seed_demo(db, user)
    await audit(db, user_id=user.id, action="demo.seeded", details={"vacancies": result["vacancies"]})
    return result
