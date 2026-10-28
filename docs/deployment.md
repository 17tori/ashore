# Развёртывание

## Требования

Сервер с Docker и Docker Compose, домен, направленный на сервер (для HTTPS через Caddy).
Для соблюдения 152-ФЗ сервер с базой данных должен находиться в РФ.

## Запуск

```bash
cp .env.example .env
# заполнить: SITE_ADDRESS (домен), PUBLIC_BASE_URL (https://домен), POSTGRES_PASSWORD, ENCRYPTION_KEYS
docker compose up -d --build
```

Caddy сам получит сертификат. Миграции применяются при старте backend. Проверка:

```bash
curl https://домен/api/health/ready
```

## Переменные

Все переменные перечислены в `.env.example`. Обязательные: `PUBLIC_BASE_URL`, `POSTGRES_PASSWORD`,
`ENCRYPTION_KEYS`, `COOKIE_SECURE=true` в продакшене. Интеграции hh.ru, AI и Telegram необязательны.

## Telegram

1. Создать бота у @BotFather, записать `TELEGRAM_BOT_TOKEN` и `TELEGRAM_BOT_USERNAME`.
2. Придумать `TELEGRAM_WEBHOOK_SECRET` и зарегистрировать webhook:

```bash
curl "https://api.telegram.org/bot$TELEGRAM_BOT_TOKEN/setWebhook" \
  -d url=https://домен/api/telegram/webhook -d secret_token=$TELEGRAM_WEBHOOK_SECRET
```

## Ротация ключа шифрования

Добавить новый ключ первым: `ENCRYPTION_KEYS=new,old`, перезапустить. Новые записи шифруются новым
ключом, старые читаются старым. Старый ключ удалять только после перешифрования данных.

## Резервные копии

```bash
docker compose exec postgres pg_dump -U ashore ashore | gzip > backup-$(date +%F).sql.gz
```

Резервная копия содержит зашифрованные данные; без `ENCRYPTION_KEYS` она бесполезна, храните ключи отдельно.

## Разработка

```bash
# backend
cd backend && uv sync && cp ../.env.example .env  # заполнить DATABASE_URL, ENCRYPTION_KEYS
uv run alembic upgrade head && uv run uvicorn app.main:app --reload
uv run pytest            # нужна база ashore_test и Redis
# frontend
cd frontend && npm install && npm run dev   # /api проксируется на localhost:8000
```

`DEMO_MODE=true` включает кнопку загрузки примеров вакансий (помечены «Пример»).
