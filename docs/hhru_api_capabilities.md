# Возможности API hh.ru для AI Job Agent

Дата исследования: 28.10.2026.

## Источники и уровень проверки

| Источник | Что проверено |
| --- | --- |
| [github.com/hhru/api](https://github.com/hhru/api), коммит `906d7b6` от 19.12.2025 | Официальное оглавление API, OAuth, ошибки, кеширование |
| История коммитов того же репозитория (`238d17b`, 17.12.2025) | Какие методы соискателя были убраны из официальной документации |
| [api.hh.ru/openapi/redoc](https://api.hh.ru/openapi/redoc), [openapi.yml](https://api.hh.ru/openapi/specification/public) | **Не удалось загрузить**: сетевая политика среды разработки блокирует `api.hh.ru` (HTTP 403 на CONNECT) |
| [Хабр, 11.08.2026](https://habr.com/ru/news/1069286/), [sys-admin.by, 12.08.2026](https://sys-admin.by/info/it-news/headhunter-zakryl-publichnyi-api-vakansii-chto-izmenitsia-dlia-razrabotchikov-i-analitikov/) | С апреля 2026 `GET /vacancies` без авторизации отвечает `403 Forbidden` |
| [TenChat, 18.12.2025](https://tenchat.ru/media/4294976-otklyucheniye-soiskatelskogo-api-headhunter) | С 15.12.2025 hh.ru отключил «соискательский API» для большинства соискателей |

Реальные ответы API **не проверены**: в среде разработки нет учётных данных и доступа к `api.hh.ru`.
Поэтому приложение определяет доступность каждой операции на лету (см. «Проверка возможностей»), а не полагается на эту таблицу.

## Ключевые выводы

1. **Соискательский API закрыт для сторонних приложений с 15.12.2025.** 17.12.2025 из официального README удалены разделы:
   «Работа с резюме для соискателя» (`/resumes/mine`, создание, редактирование, публикация и продление резюме, статус резюме, списки видимости),
   «Переписка для соискателя» (список откликов, **отклик на вакансию**, сообщения),
   «Поиск по вакансиям, похожим на резюме», отобранные и скрытые вакансии, сохранённые поиски, соискательские статусы.
   Файл `docs/negotiations.md` в репозитории остался, но ссылки на него из оглавления удалены.
2. **Анонимный поиск вакансий закрыт с апреля 2026.** В текущем оглавлении поиск вакансий помечен только бейджами `client` (токен приложения) и `employer`, бейджа `anonymous` нет.
3. **Токен приложения требует регистрации и модерации** на [dev.hh.ru](https://dev.hh.ru). По FAQ модерация длится до 15 рабочих дней. По отраслевым публикациям, ключи выдаются в основном работодателям и рекрутинговым сервисам.
4. Сторонние инструменты, у которых автоотклики продолжают работать (например, `hh-applicant-tool`), используют `client_id` официального Android-приложения hh.ru и проходят вход через страницу логина с паролем пользователя и решением капчи. **Это обход ограничений платформы, в проекте не используется.**

## Таблица операций

Статусы:

- **Verified (docs)**: метод есть в действующей официальной документации.
- **Conditional**: метод существует, но доступность для соискателя через стороннее приложение не гарантирована; приложение включает его только после проверки на лету.
- **Unavailable**: метода нет в официальном API, либо он удалён из документации для соискателей.

| Операция | Endpoint | Метод | Авторизация | Ограничения | Статус |
| --- | --- | --- | --- | --- | --- |
| OAuth: запрос кода | `https://hh.ru/oauth/authorize?response_type=code&client_id&state&redirect_uri` | GET (браузер) | — | `redirect_uri` должен совпадать с зарегистрированным; домен `m.hh.ru` больше не поддерживается | Verified (docs) |
| OAuth: обмен кода на токен | `https://api.hh.ru/token` (`grant_type=authorization_code`) | POST form | client_id + client_secret | `code` одноразовый; ошибки `invalid_grant: code expired / code has already been used` | Verified (docs), URL настраивается `HH_TOKEN_URL` |
| OAuth: обновление токена | `https://api.hh.ru/token` (`grant_type=refresh_token`) | POST form | refresh_token | refresh-токен одноразовый; обновлять можно только **после** истечения access-токена (`token not expired`) | Verified (docs) |
| Токен приложения | `https://api.hh.ru/token` (`grant_type=client_credentials`) | POST form | client_id + client_secret | не чаще раза в 5 минут (`app token refresh too early`); новый токен отзывает старый | Verified (docs) |
| Проверка токена | `/me` | GET | любой токен | — | Verified (docs) |
| Поиск вакансий | `/vacancies` | GET | токен приложения или работодателя | анонимно 403 с 04.2026; глубина выдачи `page × per_page ≤ 2000`, `per_page ≤ 100` | Conditional |
| Детали вакансии | `/vacancies/{id}` | GET | токен приложения или работодателя | 404 для удалённых | Conditional |
| Похожие вакансии | `/vacancies/{id}/similar_vacancies` | GET | токен приложения | — | Conditional |
| Справочники, регионы, навыки | `/dictionaries`, `/areas`, `/skills`, `/professional_roles` | GET | анонимно | кешировать (см. `docs/cache.md`) | Verified (docs) |
| Работодатель | `/employers/{id}` | GET | токен приложения | — | Verified (docs) |
| Получение своих резюме | `/resumes/mine` | GET | токен соискателя | удалено из документации 17.12.2025 | Conditional (probe) |
| Статус резюме | `/resumes/{id}` (`can_publish_or_update`, `next_publish_at`) | GET | токен соискателя | удалено из документации | Conditional (probe) |
| Отклик на вакансию | `/negotiations` (`vacancy_id`, `resume_id`, `message`) | POST | токен соискателя | удалено из документации; `already_applied`, `test_required` (тестовые вакансии через API недоступны), `limit_exceeded`, `resume_visibility_conflict` | Conditional, без probe |
| Список откликов и статусы | `/negotiations` | GET | токен соискателя | удалено из документации | Conditional (probe) |
| Сопроводительное письмо | поле `message` в `POST /negotiations` | — | токен соискателя | `empty_message`, `too_long_message`; если `response_letter_required=true`, письмо обязательно | Conditional |
| Выбор конкретного резюме | `resume_id` в `POST /negotiations`; `/vacancies/{id}/suitable_resumes` | — | токен соискателя | удалено из документации | Conditional |
| Поднятие (публикация) резюме | `/resumes/{id}/publish` | POST | токен соискателя | удалено из документации; доступность по `can_publish_or_update` | Conditional |
| Списки видимости резюме | `/resumes/{id}/{list_type}` | GET/POST/DELETE | токен соискателя | удалено из документации | Unavailable для автоматизации |
| Платное продвижение резюме | — | — | — | в API соискателя никогда не было методов покупки услуг | Unavailable |
| Webhook-уведомления | `/webhook/subscriptions` | GET/POST/PUT/DELETE | работодатель | только для работодателей | Unavailable для соискателя |
| Решение капчи | — | — | — | API отвечает `403 captcha_required`; приложение останавливает автоматизацию и просит пользователя пройти действие на hh.ru | Не обходится |

## Требования к запросам

- Заголовок `HH-User-Agent` (или `User-Agent`) обязателен, формат `AppName/Version (contact@email)`. Без него `400 bad_user_agent`. Значение задаётся `HH_USER_AGENT`.
- Авторизация: `Authorization: Bearer <access_token>`.
- Формат ошибок: `{"errors": [{"type": "...", "value": "..."}]}`. Тело 5xx может быть не JSON.
- Ошибки OAuth: `403 oauth/token_expired`, `token_revoked`, `bad_authorization`, `user_auth_expected`, `application_not_found`.
- Лимиты частоты официально не опубликованы. Клиент ограничивает себя сам (token bucket, по умолчанию 2 запроса/с), уважает `429` и `Retry-After`, а при `captcha_required` открывает circuit breaker.

## Проверка возможностей

`app/services/hhru/capabilities.py` выполняет только безопасные GET-запросы:

| Возможность | Проверка | Verified, если |
| --- | --- | --- |
| `vacancy_search` | `GET /vacancies?per_page=1` | 200 |
| `resumes_read` | `GET /resumes/mine` | 200 |
| `negotiations_read` | `GET /negotiations?per_page=1` | 200 |
| `apply` | не проверяется запросом: отклик необратим | первый отклик, подтверждённый пользователем, вернул 201/204 |
| `resume_publish` | наличие `can_publish_or_update` в резюме | первое подтверждённое поднятие вернуло 204 |

Auto-Apply включается только при `apply = verified`. До этого работает режим Assisted.

## Легальные запасные сценарии

| Функция | Если API недоступен |
| --- | --- |
| Поиск вакансий | Ручное добавление (ссылка, ID, текст) и букмарклет «Добавить в Ashore»: пользователь сам открывает вакансию на hh.ru, букмарклет отправляет видимый текст страницы в приложение. Без фонового обхода сайта |
| Импорт резюме | Загрузка PDF, DOCX или TXT (hh.ru умеет скачивать резюме в PDF и DOCX) |
| Отклик | Режим Assisted: письмо готовится, копируется одним нажатием, открывается `apply_alternate_url` (`https://hh.ru/applicant/vacancy_response?vacancyId=…`), пользователь отмечает отправку. Статус `sent` ставится с пометкой «подтверждено пользователем» |
| Статусы откликов | Ручное обновление в CRM и из Telegram |
| Поднятие резюме | Напоминания по расписанию с учётом 4-часового интервала, ссылка на `https://hh.ru/applicant/resumes`, журнал действий |

## Что нужно для реальной интеграции

1. Зарегистрировать приложение на [dev.hh.ru](https://dev.hh.ru) и пройти модерацию.
2. Указать `redirect_uri` = `${PUBLIC_BASE_URL}/api/hh/oauth/callback`.
3. Заполнить `HH_CLIENT_ID`, `HH_CLIENT_SECRET`, `HH_USER_AGENT`, при наличии `HH_APP_ACCESS_TOKEN`.
4. Подключить аккаунт в «Настройках» и нажать «Проверить возможности».
