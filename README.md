# VILTARA SHOP

Telegram-бот с интегрированным Telegram Mini App — маркетплейс для покупки и продажи NFT-подарков Telegram.

> **Текущий этап: маркетплейс-foundation без оплаты.** Реализованы каталог, объявления с ценой,
> резервирование и проверка владения NFT. Платежи, escrow/гарант, чат сделки и админ-панель
> **не реализованы** и не имитируются. Подробная модель и дорожная карта — в
> [`docs/PRODUCT_MODEL.md`](docs/PRODUCT_MODEL.md).

## Техническое задание

> Раздел ниже — исходное ТЗ, целиком. Не всё из него реализовано: см. статус реализации
> в конце файла и границу этапа в `docs/PRODUCT_MODEL.md`.

### 1. Формат проектаа

Telegram-бот с интегрированным Telegram Mini App — маркетплейсом для покупки и продажи настоящих NFT-подарков Telegram.

### 2. Основной функционал

- **Каталог NFT:** просмотр объявлений, изображений подарков, характеристик и цен.
- **Продажа NFT:** создание объявления, указание цены и данных подарка.
- **Покупка NFT:** просмотр объявления и создание сделки с уникальным ID.
- **Проверка NFT:** проверка доступных данных о подарке, его идентификатора и владельца через поддерживаемые API или TON-инструменты.
- **Сделки через гаранта** *(не реализовано; этап C)*: покупатель оплачивает заказ, продавец передаёт NFT, система проверяет получение, после чего продавцу перечисляются деньги за вычетом комиссии.
- **Чат сделки** *(не реализован)*: общение покупателя и продавца в рамках конкретного заказа.
- **Профиль пользователя:** информация о пользователе, его объявлениях и истории сделок.
- **Платежи** *(не реализованы; этап B)*: интеграция платёжного механизма для приёма оплаты и выплат продавцам.
- **Админ-панель** *(не реализована)*: управление пользователями, объявлениями, сделками, комиссиями и спорными ситуациями.

### 3. Дизайн

Современный премиальный интерфейс Mini App с удобной навигацией, адаптацией под мобильные устройства и визуальным стилем NFT-маркетплейса.

### 4. Результат

Рабочая демоверсия маркетплейса с реальными NFT, основными пользовательскими сценариями и административной панелью.

### 5. Важные технические ограничения

Конкретные способы проверки и передачи NFT, приёма и удержания средств определяются после проверки доступных API и платёжных решений. Гарантированная автоматизация всей сделки зависит от технической возможности реализации выбранного механизма.

---

## Технический стек

Стек выбран с учётом Telegram Mini Apps, асинхронной нагрузки, работы с TON и возможности развивать проект без преждевременного разделения на микросервисы.

### Backend

| Технология | Назначение |
|---|---|
| Python 3.13+ | Основной язык backend |
| FastAPI | REST API и webhook endpoints |
| aiogram 3 | Telegram Bot API и обработка обновлений |
| Pydantic v2 / pydantic-settings | Валидация данных и конфигурация |
| SQLAlchemy 2.x Async | Асинхронная работа с БД |
| Alembic | Миграции схемы БД |

### Telegram Mini App

| Технология | Назначение |
|---|---|
| React | UI |
| TypeScript | Типизация frontend |
| Vite | Сборка и dev server |
| Tailwind CSS | Стилизация и адаптивная вёрстка |
| TanStack Query | Серверное состояние, запросы и кеш |
| Zustand | Локальное состояние интерфейса |
| @tonconnect/ui-react | Подключение TON-кошельков |

### Данные и инфраструктура

| Технология | Назначение |
|---|---|
| PostgreSQL | Основная реляционная БД |
| Redis | Кеш, временные данные, распределённые блокировки |
| Docker / Docker Compose | Контейнеризация и локальная среда |
| S3-compatible storage | Хранение изображений и медиа |
| GitHub Actions | CI: проверки и тесты |

### TON и NFT

- **TON Connect** — подключение кошелька пользователя и запрос подтверждения транзакций. Приватные ключи пользователей не хранятся на сервере.
- **TON Center API v3** — индексированные данные о NFT, владельцах и транзакциях.
- **Проверка NFT** — проверять адрес item-контракта, принадлежность коллекции и актуального владельца; не доверять только переданным пользователем ссылкам, изображениям или metadata.
- **Blockchain watcher** — отдельный backend-модуль для отслеживания транзакций и подтверждения состоявшихся переводов.
- **Asset adapters** — изолировать интеграцию с TON NFT и Telegram Gifts, поскольку это разные механизмы владения и передачи активов.

### Тестирование и качество

| Инструмент | Назначение |
|---|---|
| pytest / pytest-asyncio / pytest-cov | Backend tests и coverage report |
| Ruff | Python lint и format |
| mypy | Статическая проверка типов Python |
| Vitest / @vitest/coverage-v8 | Frontend unit tests и coverage report |
| Playwright | E2E-тестирование Mini App |
| GitHub Actions | Автоматический запуск проверок |

## Запуск тестов

Backend:

```bash
cd backend
python -m pip install -e ".[dev]"
ruff check app tests migrations
pytest --cov=app --cov-report=term-missing -q
```

Frontend:

```bash
cd frontend
npm install
npm run test:coverage
npm run build
```

Обе проверки запускаются автоматически через GitHub Actions: Backend CI и Frontend CI. Coverage выводится в логах соответствующего workflow.

## Архитектурные решения

На первом этапе используется **модульный монолит**: один backend-проект с чёткими границами модулей. Это проще развивать и тестировать, чем набор микросервисов, и при необходимости позволяет позже выделить отдельные компоненты.

Предварительные backend-модули:

- `auth` — Telegram initData validation, пользовательские сессии и роли.
- `users` — профили и настройки.
- `assets` — NFT/Gift адаптеры, metadata и проверка владения.
- `listings` — объявления, фильтры и каталог.
- `orders` — заказы и жизненный цикл сделок.
- `escrow` — состояния гаранта, комиссии, ledger и обработка споров.
- `payments` — приём платежей, подтверждения, возвраты и выплаты.
- `blockchain` — TON Connect-related verification, индексатор и watcher.
- `chat` — сообщения и события сделки.
- `admin` — административные операции и аудит.
- `notifications` — Telegram-уведомления.

## Критически важные ограничения Telegram и TON

1. **Оплата цифровых товаров внутри Telegram.** По правилам Telegram Bot Platform цифровые товары и услуги, продаваемые внутри ботов и Mini Apps, должны оплачиваться Telegram Stars (`XTR`). TON Connect не следует использовать как обход этого требования для встроенного checkout.
2. **TON Connect — не кастодиальный кошелёк.** Он позволяет приложению подключиться к кошельку и запросить подпись/транзакцию, но не передаёт приложению приватные ключи.
3. **Telegram Gifts API имеет ограничения.** Методы просмотра, upgrade и transfer подарков бизнес-аккаунта требуют подключённого business bot и соответствующих прав. Нельзя считать, что обычный бот может забрать или передать любой подарок любого пользователя.
4. **Не смешивать Telegram Gifts и стандартные TON NFT.** Для каждого типа актива нужен отдельный адаптер и подтверждённый сценарий проверки/передачи.
5. **Гарант не считается реализованным только по факту оплаты.** Перед запуском реальных сделок необходимо отдельно подтвердить юридически и технически допустимую схему удержания средств, передачи актива, возврата и выплаты продавцу. Нельзя обещать автоматический escrow, пока этот механизм не реализован и не протестирован.

## Результат технического аудита

Подробный аудит ограничений Telegram Gifts, стандарта TON NFT, проверки владельца, передачи активов и платежей находится в [`docs/ASSET_INTEGRATION_AUDIT.md`](docs/ASSET_INTEGRATION_AUDIT.md).

Ключевое решение: первый реальный сценарий строить вокруг проверяемых TON NFT стандарта TEP-62. Telegram Gifts поддерживать отдельным адаптером; автоматическую передачу разрешать только в сценариях, подтверждённых возможностями Telegram Business API. Escrow оставить выключенным до разработки и проверки отдельного механизма.

Архитектурное решение по платежам и escrow (ADR) и технический дизайн описаны в
[`docs/adr/0001-compliant-payments-and-escrow.md`](docs/adr/0001-compliant-payments-and-escrow.md)
и [`docs/PAYMENTS_ESCROW_DESIGN.md`](docs/PAYMENTS_ESCROW_DESIGN.md).

## Предлагаемый порядок разработки

1. Аудит Telegram Gifts / TON NFT и фиксация поддерживаемых сценариев.
2. Каркас проекта, Docker Compose, PostgreSQL, Redis, миграции и CI.
3. Telegram-бот, Mini App и безопасная авторизация через проверку `initData`.
4. Каталог, карточка актива, профиль и объявления.
5. Проверка NFT и мониторинг транзакций.
6. Заказы, состояния сделок, журнал операций и админ-панель.
7. Платёжная интеграция и escrow только после подтверждения реализуемой схемы.
8. Тестирование, аудит безопасности и production deployment.


## Локальный запуск каркаса

Требования: Docker Desktop / Docker Engine с Docker Compose.

1. Скопировать пример переменных окружения и указать токен бота из BotFather в `BOT_TOKEN` (он нужен для проверки Mini App `initData`):

   ```bash
   cp .env.example .env
   ```

2. Сгенерировать секрет API (вставить результат в `AUTH_SECRET_KEY` в `.env`):

   ```bash
   openssl rand -hex 32
   ```

3. Запустить API, Mini App, PostgreSQL и Redis:

   ```bash
   docker compose up --build
   ```

4. Применить миграции базы данных:

   ```bash
   docker compose exec api alembic upgrade head
   ```

5. Проверить сервисы:
   - Mini App: http://localhost:5173
   - API: http://localhost:8000
   - Swagger: http://localhost:8000/docs
   - Readiness: http://localhost:8000/api/health/ready
   - Telegram login: `POST /api/auth/telegram` с JSON body `{"init_data":"<Telegram.WebApp.initData>"}`. Передавать нужно именно `Telegram.WebApp.initData`, не `initDataUnsafe`.
   - Current user: `GET /api/users/me` с заголовком `Authorization: Bearer <access_token>`.
   - Public catalog: `GET /api/listings?limit=24&offset=0&sort=newest`; filters: `asset_type`, `currency`, `search`, `sort=price_asc|price_desc|newest`. Видимы только `active` объявления, у которых актив `verified` и принадлежит продавцу; `reserved`, `stale`, `pending` и `failed` скрыты.
   - Listing details: `GET /api/listings/{listing_id}` (действует то же правило видимости, иначе 404).
   - My listings: `GET /api/listings/me` (требуется Bearer token).
   - Create listing draft: `POST /api/listings` (требуется Bearer token; только для уже подтверждённого актива, принадлежащего пользователю).

6. Для запуска Telegram-бота указать `BOT_TOKEN` в `.env` и выполнить:

   ```bash
   docker compose --profile bot up --build
   ```

### Текущий статус (аудит 2026-11-10)

**Этап A — маркетплейс-foundation (в работе):**

- [x] Backend FastAPI и конфигурация через environment; readiness-проверки PostgreSQL и Redis.
- [x] Асинхронное подключение SQLAlchemy к PostgreSQL; Alembic-миграции (0001–0004).
- [x] Docker Compose для локальной среды; базовый aiogram polling entrypoint.
- [x] React + TypeScript + Vite Mini App: каталог, карточка объявления, создание/редактирование, мои объявления, заказы.
- [x] HMAC-проверка Telegram Mini App initData, JWT-аутентификация, `GET /api/users/me`.
- [x] TON Connect wallet proof: серверная проверка proof и привязка кошелька (`/api/wallets/*`).
- [x] TEP-62 NFT verification adapter (TON Center v3) + инвентарь `/api/assets/me`.
- [x] Черновики объявлений из верифицированных активов; публикация после live ownership re-check.
- [x] Управление объявлениями: публикация, редактирование цены/заголовка/описания, снятие, срок публикации.
- [x] **Цена и валюта — полноценная часть объявления:** Decimal `Numeric(24,9)`, check > 0, сортировка `price_asc/price_desc`, фильтр по валюте; цена во всех UI.
- [x] Заказы: создание с **снимком цены/валюты на момент резерва**, идемпотентность, конкурентная защита, свежая проверка владения перед резервом (fail-closed 503 при недоступности провайдера).
- [x] Скрытие непокупаемых листингов (stale/unverified/reserved) из каталога и карточки.
- [x] Telegram order notifications через durable outbox.

**Не реализовано и не имитируется:**

- [ ] Платежи: приём/подтверждение средств (этап B; `PaymentAdapter` — только контракт).
- [ ] Escrow/гарант, споры, комиссии, выплаты (этап C; ADR-0001/0002).
- [ ] Подтверждение передачи NFT в сделке (серверная on-chain проверка после резерва — этап B).
- [ ] Чат сделки, админ-панель.
- [ ] E2E-тесты, production hardening, deployment runbook.

**Важно:** резервирование заказа не означает оплату — платёжного механизма нет, статусов «оплачено» не существует. Текущие пароли PostgreSQL в Compose предназначены только для локальной разработки. Каркас не принимает реальные платежи и не передаёт NFT.

---

*Проект находится в разработке. Описание будет дополняться по мере реализации функциональности.*


### Telegram order notifications

Order creation, buyer cancellation, and automatic expiry enqueue recipient notifications in the
same transaction as the order state change. Delivery is handled by the separate optional bot
container using a PostgreSQL-backed outbox. Configure `BOT_TOKEN` and
`TELEGRAM_MINI_APP_URL` in `.env`, then start the bot profile:

```bash
docker compose --profile bot up --build
```

See [docs/TELEGRAM_NOTIFICATIONS.md](docs/TELEGRAM_NOTIFICATIONS.md) for retry, monitoring,
and delivery-guarantee details.
