# Целевая продуктовая модель VILTARA SHOP и границы текущего этапа

- **Статус:** продуктовые решения утверждены в рамках Issue #54 и PR #55.
- **Последняя сверка реализации:** 2026-11-13.
- **Проверенная база:** main, commit 9593f1a003a4f976cf3e6b3b20cb1d3830d83018.
- **Назначение документа:** фиксирует продуктовые ограничения и фактический статус кода на main. Открытые PR не считаются реализованными, пока не смёржены.

---

## 1. Главные продуктовые решения

**D1. VILTARA — маркетплейс, и цена обязательна.**

Объявление содержит NFT и цену продавца (price_amount, price_currency). Отсутствие платёжной интеграции не означает, что объявления бесплатны и не является основанием удалять цены или денежные снимки из заказов.

**D2. Резервирование — не оплата.**

Покупатель может зарезервировать объявление без фактического списания средств. Заказ фиксирует цену и валюту на момент резерва. Резервирование не переводит деньги, не удерживает NFT в блокчейне и не доказывает передачу NFT. Не использовать тексты «оплачено» или «покупка завершена» без соответствующего доверенного механизма.

**D3. Платёж и escrow — отдельные будущие продукты.**

Payment provider, checkout, Stars settlement, ledger, escrow, custody, refunds, disputes, commissions и seller payouts не входят в текущий MVP. ADR-0001/0002 и design-документы описывают предложения/будущие архитектурные варианты, а не запущенные платёжные рельсы. Любая реализация требует отдельного решения владельца, продуктовой и технической проверки.

**D4. TON NFT (TEP-62) и Telegram Gifts — разные домены.**

Сейчас поддерживаются стандартные TON NFT items, реализующие TEP-62. Telegram Gifts не интегрированы как передаваемые маркетплейс-активы; для них нужен отдельный адаптер и проверка ограничений Telegram Business API.

**D5. Никаких ключей и никаких клиентских доказательств.**

Seed-фразы и приватные ключи никогда не запрашиваются и не хранятся. TON Connect инициирует операции в кошельке пользователя. Подключённый адрес не доказывает владение кошельком до backend-проверки TON Connect Proof.

Хеш/ссылка, скриншот, callback кошелька, текст из UI или клиентский статус сами по себе не являются доказательством передачи NFT. Подтверждение доставки выполняет серверный observer по сохранённому намерению перевода и независимым on-chain/provider данным.

### Два разных механизма проверки

| Механизм | Что делает | Статус на main |
|---|---|---|
| Проверка владения NFT (ownership verification) | TEP-62 verifier проверяет item, сеть и текущего владельца относительно верифицированного кошелька пользователя; используется при синхронизации инвентаря, публикации и резервировании | Реализовано; ошибки/неопределённость провайдера не трактуются как успех |
| Подтверждение передачи NFT (delivery confirmation) | После резерва сервер проверяет, что именно сохранённый NFT item перешёл с ожидаемого кошелька продавца на сохранённый адрес покупателя в нужной сети | B1–B6 реализованы на main; независимое подтверждение observer есть в коде. Live testnet/Tonkeeper acceptance остаётся отдельным ручным gate по Issue #46 |

Поэтому текущая сделка включает два этапа: резерв фиксирует заказ и снимок цены; отдельный seller-initiated transfer доставляет NFT, а backend подтверждает его независимо. Эти этапы не являются оплатой.

---

## 2. Разделение доменов

| Домен | Что содержит | Статус |
|---|---|---|
| **Listing** | TEP-62 NFT, обязательная цена продавца, валюта и состояния объявления | Реализован |
| **Reservation / Order** | Покупатель, продавец, объявление, снимок цены/валюты, срок, idempotency key и история событий | Реализован; резерв не является оплатой |
| **Delivery** | Снимок item/network/source/destination/query/deadline, попытки, submission hints, observer и подтверждение доставки | B1–B6 реализованы на main; live acceptance не завершён |
| **Notification outbox** | Транзакционные уведомления buyer/seller по событиям заказа и доставки, worker с retry/dedupe | Реализован; worker запускается отдельно через bot profile |
| **Admin moderation** | Очередь модерации, обязательный `pending_review`, approve/reject/suspend/restore, append-only аудит | Реализован; публичная публикация только после одобрения; доступ закрыт по умолчанию |
| **Seller profile and reviews** | Публичный профиль, доступные объявления, отзывы и безопасная репутация | Реализован; отзывы доступны только по заказам с независимо подтверждённой передачей NFT |
| **Seller overview** | Личные счётчики объявлений/заказов, последняя активность и снимки цен по валютам | Реализован; доступ только для аутентифицированного пользователя; `pending_review` учитывается отдельно |
| **Payment** | Приём, списание и подтверждение средств | Не реализован |
| **Escrow / guarantee** | Удержание средств/актива, возвраты, споры и выплаты | Не реализован |
| **Telegram Gifts** | Отдельный тип актива и transfer adapter | Не реализован |
| **Deal chat** | Коммуникация участников сделки | Не реализован |

Правило: Reservation не меняет денежный смысл заказа. Если появится платёж, это отдельный модуль с собственным жизненным циклом и доказательствами, а не фиктивный статус внутри текущего Order.

---

## 3. Фактическое состояние реализации на main (2026-11-13)

### Реализовано

| Компонент | Состояние |
|---|---|
| Цена в Listing | Обязательная положительная цена и валюта; сохраняется в API и UI |
| Снимок цены/валюты в Order | Переносится из listing при создании резерва; исторический снимок не должен подменяться текущей ценой |
| Каталог | Публичное чтение, существующие фильтры/сортировка/пагинация |
| Telegram auth | Проверка raw Telegram Mini App initData backend-ом и bearer session |
| TON Connect Proof | Challenge → TON Proof → криптографическая backend-проверка; UI и proof fail-closed до настройки public manifest и exact domain allowlist |
| NFT inventory | Backend-верифицированный инвентарь, paginated sync, multi-wallet ownership recheck, безопасная обработка потери владения |
| My NFT UI | Отдельный экран инвентаря со статусами, pagination, sync и loading/error/empty состояниями |
| Listings | Создание draft из eligible verified asset, отправка на обязательную модерацию после свежей проверки владения, edit/unpublish flows |
| Order lifecycle | Резервирование с idempotency/concurrency защитой, cancellation и expiry; не оплата |
| Stage B B1–B6 | Read-only transfer evidence adapter, миграции и immutable snapshots, leased observer, prepare/submit/read API, атомарное completion после независимой финальной проверки, seller TON Connect flow и notifications |
| Telegram notifications | Durable outbox; сообщения buyer/seller создаются в той же транзакции, что и соответствующие lifecycle changes; отправка — отдельным worker |
| Admin moderation | Отдельный /admin workspace; публикация через `pending_review`; bounded queue; approve/reject/suspend/restore; обязательная причина и Idempotency-Key; append-only audit history; PostgreSQL блокирует UPDATE/DELETE/TRUNCATE журнала |
| Public seller profile | Безопасные публичные сведения о продавце, доступные объявления и отзывы только по завершённым заказам с подтверждённой передачей NFT |
| Private seller overview | User-scoped счётчики объявлений/заказов, последняя активность и отдельные суммы по TON/XTR; резервные суммы не являются платежами |

### Важные детали TON Connect

- Frontend остаётся выключенным/fail-closed, пока не задан публичный VITE_TONCONNECT_MANIFEST_URL.
- Backend proof challenges доступны только при корректном непустом TON_CONNECT_ALLOWED_DOMAINS.
- Домен в allowlist проверяется точно; подключённый адрес без свежего proof не является verified wallet.
- Настройки должны относиться к реальному публичному HTTPS hostname Mini App. Не включать wallet flow с произвольным локальным или временным URL.

### Важные детали доставки NFT (Stage B)

1. Покупатель резервирует активное объявление. В заказе фиксируется цена и валюта; деньги не списываются.
2. При подготовке доставки backend повторно проверяет владение NFT продавцом и сохраняет точные item, network, seller source, buyer destination, query ID и deadline.
3. Продавец формирует и подписывает TEP-62 transfer в своём TON Connect wallet. Сервер не хранит ключи, не подписывает и не отправляет транзакцию от имени пользователя.
4. Возвращённый кошельком reference/BOC digest используется только как lookup hint. Он не принимается за tx hash или доказательство передачи.
5. Leased observer независимо сопоставляет transfer evidence с persisted intent и политикой финальности. Только эта серверная проверка может атомарно завершить Order и перевести Listing в соответствующее конечное состояние.
6. Неопределённость, лаг провайдера или конфликт доказательств не означают success; попытка остаётся в состоянии наблюдения/manual review согласно state machine.

Подробный контракт, переходы, отказоустойчивость и ограничения: [docs/STAGE_B_ORDER_LIFECYCLE.md](STAGE_B_ORDER_LIFECYCLE.md).

### Важные детали admin moderation

- API находится под /api/admin; отдельная Mini App workspace открывается по /admin.
- ADMIN_TELEGRAM_IDS — server-side JSON allowlist числовых Telegram IDs; по умолчанию пуст, поэтому доступ закрыт.
- Actor берётся только из проверенной bearer session; клиент не может сам назначить себе admin.
- Публикация создаёт `pending_review`, а не публичное объявление. Approve/restore требуют свежей проверки TON NFT ownership. Reject/suspend/restore/approve следуют строгим переходам Listing state. Редактирование ожидающего объявления возвращает его в draft, после чего требуется повторная отправка.
- Каждое решение требует причины и Idempotency-Key; изменение Listing и audit record коммитятся атомарно.
- PostgreSQL append-only защита запрещает изменение и удаление audit rows, включая TRUNCATE. Downgrade не должен удалять непустой audit log.

Операционная настройка и точные endpoint-контракты: [docs/ADMIN_MODERATION_AUDIT.md](ADMIN_MODERATION_AUDIT.md).

---

## 4. Ручная приёмка и незакрытые gates

Слитый код и успешный CI доказывают автоматизированное поведение на тестовой инфраструктуре, но не заменяют реальные действия в Telegram, Tonkeeper или TON testnet.

| Issue | Что реализовано | Что остаётся проверить вручную |
|---|---|---|
| [#43 TON Connect Proof](https://github.com/AzizIo/Vstore/issues/43) | Backend криптографическая проверка и frontend lifecycle находятся в main | Реальный connect/sign в Telegram Mini App на целевом HTTPS host; verified wallet в backend; reopen/restore; account/network switch; публичные manifest/icon, content types и CORS |
| [#44 NFT inventory](https://github.com/AzizIo/Vstore/issues/44) | Backend sync/reconciliation, multi-wallet checks и My NFT UI находятся в main | Testnet/provider сценарии с несколькими страницами и вторым verified wallet; ownership loss после резерва; outage/malformed response; owner review/screenshots |
| [#46 NFT delivery Stage B](https://github.com/AzizIo/Vstore/issues/46) | B1–B6 находятся в main, включая observer и seller wallet UX | Реальный testnet/Tonkeeper seller transfer; проверка indexed finality на успешных и негативных transfer; задержки провайдера и manual-review cases |
| [#47 full Mini App journey](https://github.com/AzizIo/Vstore/issues/47) | Основные frontend/backend workflows, durable notifications и API-backed Playwright coverage существуют | Полный проход в настоящем Telegram mobile WebView от двух пользователей, реальные уведомления и wallet return/UX на целевом публичном host |

Issues #43, #44, #46 и #47 должны оставаться открытыми до документирования их соответствующих ручных acceptance criteria. Исторические чек-листы issue могут не отражать последние merged PR; перед изменением статуса сначала сопоставить пункты с кодом и последними комментариями.

### Что доказывают автоматические E2E

API-backed Playwright тесты запускают реальный FastAPI backend против временных PostgreSQL/Redis сервисов и loopback TON provider fixture. Они проверяют persistence и серверные переходы состояния, но Tonkeeper/Telegram wallet boundary и TON provider заменены тестовыми fixture. Это не live blockchain acceptance.

---

## 5. Что не входит в текущий MVP

Не реализовывать и не изображать реализованными без отдельного решения:

- Payment provider, checkout, payment webhook/ledger и settlement;
- Telegram Stars как фактический платёжный rail за NFT;
- escrow, custody, refunds, dispute resolution, buyer guarantee;
- marketplace commissions и seller payouts;
- хранение seed phrases/private keys или server-side wallet signing;
- Telegram Gifts transfers;
- deal chat.

Архитектурные документы ADR-0001/0002 и PAYMENTS_ESCROW_DESIGN — предложения для отдельного этапа. Они не разрешают добавлять платёжное поведение в текущий order lifecycle.

---

## 6. Правила для будущих миграций и изменений

- Не удалять денежные поля price_amount и price_currency: они описывают условия объявления и снимок заказа, а не наличие payment provider.
- Любая destructive-миграция (drop column/table или удаление истории) требует отдельного issue с обоснованием, планом сохранения данных и явного согласования владельца.
- Новые статусы заказа, связанные с оплатой, допустимы только вместе с реальным платёжным модулем и утверждённым контрактом.
- Изменения Delivery должны сохранять persisted intent, idempotency, observer fencing, независимую проверку и правила финальности.
- Изменения moderation должны сохранять fail-closed allowlist, verified actor, атомарность решения и append-only audit.

