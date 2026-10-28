"""Runtime detection of what hh.ru actually allows this user's token to do.

Only safe GET requests are used for probing. ``apply`` and ``resume_publish`` are irreversible, so they
are never probed: they become ``verified`` only after a user-confirmed real call succeeded.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.base import utcnow
from app.models import IntegrationCapability
from app.models.enums import Capability, CapabilityStatus
from app.services.hhru.errors import (
    HhApiError,
    HhAuthError,
    HhForbidden,
    HhNotConfigured,
    HhNotFound,
)
from app.services.hhru.gateway import HhGateway


async def set_capability(
    db: AsyncSession, user_id: uuid.UUID, capability: Capability, status: CapabilityStatus, detail: str = ""
) -> None:
    stmt = (
        insert(IntegrationCapability)
        .values(
            id=uuid.uuid4(),
            user_id=user_id,
            capability=capability.value,
            status=status.value,
            detail=detail[:500],
            checked_at=utcnow(),
        )
        .on_conflict_do_update(
            index_elements=["user_id", "capability"],
            set_={"status": status.value, "detail": detail[:500], "checked_at": utcnow()},
        )
    )
    await db.execute(stmt)


async def capability_map(db: AsyncSession, user_id: uuid.UUID) -> dict[str, dict]:
    rows = (
        (await db.execute(select(IntegrationCapability).where(IntegrationCapability.user_id == user_id)))
        .scalars()
        .all()
    )
    result = {c.value: {"status": CapabilityStatus.UNKNOWN.value, "detail": "", "checked_at": None} for c in Capability}
    for row in rows:
        result[row.capability] = {"status": row.status, "detail": row.detail, "checked_at": row.checked_at}
    return result


async def is_verified(db: AsyncSession, user_id: uuid.UUID, capability: Capability) -> bool:
    row = (
        await db.execute(
            select(IntegrationCapability.status).where(
                IntegrationCapability.user_id == user_id, IntegrationCapability.capability == capability.value
            )
        )
    ).scalar_one_or_none()
    return row == CapabilityStatus.VERIFIED


def _classify(exc: HhApiError) -> tuple[CapabilityStatus, str]:
    if isinstance(exc, HhForbidden | HhNotFound):
        return CapabilityStatus.UNAVAILABLE, f"hh.ru ответил {exc.status} {exc.tag}"
    if isinstance(exc, HhAuthError):
        return CapabilityStatus.UNAVAILABLE, "токен не принят hh.ru"
    return CapabilityStatus.UNKNOWN, f"временная ошибка: {exc.tag}"


async def probe_capabilities(db: AsyncSession, user_id: uuid.UUID, gateway: HhGateway) -> dict[str, dict]:
    # Vacancy search: user token first, then the application token.
    search_status, search_detail = CapabilityStatus.UNAVAILABLE, "нет токена с доступом к поиску"
    clients = []
    try:
        clients.append(("user", await gateway.user_client()))
    except (HhNotConfigured, HhApiError):
        pass
    app_client = gateway.app_client()
    if app_client is not None:
        clients.append(("app", app_client))
    for label, client in clients:
        try:
            await client.search_vacancies([("per_page", 1)])
            search_status, search_detail = CapabilityStatus.VERIFIED, f"доступен через токен {label}"
            break
        except HhApiError as exc:
            search_status, search_detail = _classify(exc)
    await set_capability(db, user_id, Capability.VACANCY_SEARCH, search_status, search_detail)

    user_client = next((c for label, c in clients if label == "user"), None)
    if user_client is None:
        for cap in (Capability.RESUMES_READ, Capability.NEGOTIATIONS_READ):
            await set_capability(db, user_id, cap, CapabilityStatus.UNAVAILABLE, "аккаунт hh.ru не подключён")
        return await capability_map(db, user_id)

    for cap, call in (
        (Capability.RESUMES_READ, user_client.my_resumes),
        (Capability.NEGOTIATIONS_READ, lambda: user_client.negotiations(per_page=1)),
    ):
        try:
            await call()
            await set_capability(db, user_id, cap, CapabilityStatus.VERIFIED, "проверено запросом")
        except HhApiError as exc:
            status, detail = _classify(exc)
            await set_capability(db, user_id, cap, status, detail)

    current = await capability_map(db, user_id)
    if current[Capability.RESUMES_READ]["status"] != CapabilityStatus.VERIFIED:
        # Without access to own resumes an application cannot name a resume_id.
        for cap in (Capability.APPLY, Capability.RESUME_PUBLISH):
            await set_capability(
                db, user_id, cap, CapabilityStatus.UNAVAILABLE, "нет доступа к резюме соискателя через API"
            )
    else:
        for cap in (Capability.APPLY, Capability.RESUME_PUBLISH):
            if current[cap]["status"] != CapabilityStatus.VERIFIED:
                await set_capability(
                    db,
                    user_id,
                    cap,
                    CapabilityStatus.UNKNOWN,
                    "проверяется только первым действием, подтверждённым пользователем",
                )
    return await capability_map(db, user_id)
