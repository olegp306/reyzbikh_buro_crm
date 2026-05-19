# CRM / Workflow-платформа архитектурного бюро — Design Spec

- **Дата:** 2026-05-19
- **Карточка:** №1 «Lead Intake → CRM → Proposal → Follow-up» (первая из серии)
- **Статус:** дизайн одобрен в чате; ожидает финальное ревью этого документа
- **Автор:** brainstorming-сессия с оператором бюро

---

## 1. Контекст и цели

### 1.1 Проблема

Архитектурное бюро ведёт работу с клиентами в перемешку: переписка в Telegram, заметки в голове, документы по папкам Google Drive. Нужен модульный инструмент, который начнёт с одной автоматизации (приём лидов → предложение → напоминание), но в будущем вырастет в полноценный workflow-движок (контракты, проекты, выставление счетов, рефералы и т.д.).

### 1.2 Принципы

1. **БД-центрированность.** Центр системы — Postgres и доменные сущности, а не Telegram-бот или конкретный скрипт.
2. **Telegram — это канал, не ядро.** Завтра можно подключить веб-форму, e-mail, дашборд — без переписывания.
3. **Модульность с первого дня.** Каждая будущая «карточка-workflow» — это отдельный пакет, который использует общие сущности.
4. **Без оверинжиниринга.** Никаких микросервисов, шин сообщений, многоуровневых очередей в v1. Только то, что реально нужно для первой карточки и не мешает росту.
5. **Реальная БД с первого дня.** Postgres, миграции Alembic, никаких SQLite-«на потом».

### 1.3 Не-цели v1

См. §8 «Out of scope».

---

## 2. Принятые решения

| Решение | Выбор | Обоснование |
|---|---|---|
| Стек | Python · FastAPI · SQLAlchemy 2.0 · Alembic · aiogram 3 | Лучшая экосистема для Telegram + Google API + AI |
| БД | PostgreSQL 16 (Docker) | Один и тот же образ в dev и prod; JSONB, FOR UPDATE SKIP LOCKED |
| Скоуп карточки | Полный цикл: intake → AI-extract → proposal → Google Doc → follow-up | По запросу оператора; этапы реализуются последовательно |
| Деплой | VPS + Docker Compose | Один `docker-compose.yml` для dev и prod |
| Пользователи | Соло-оператор, авторизация по Telegram allowlist | Простейшее, при этом таблица `users` есть для роста |
| Авторизация web-UI | Откладывается | UI в v1 нет |
| Очередь задач | Postgres-таблица `scheduled_jobs` | Без Redis/Celery; хватает на текущий объём |
| Шина событий | In-process (Python) + append-only таблица `events` | Аудит + точка расширения для будущих модулей |

---

## 3. Архитектура

### 3.1 Процессы

Три процесса в одном Docker Compose, один общий Python-пакет:

```
┌─ docker-compose ──────────────────────────────────────────┐
│   ┌──────────┐    ┌──────────┐    ┌──────────┐            │
│   │   api    │    │   bot    │    │  worker  │            │
│   │ FastAPI  │    │ aiogram  │    │ jobs +   │            │
│   │  :8000   │    │ polling  │    │ scheduler│            │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘            │
│        └───────────────┴───────────────┘                  │
│                        │                                  │
│                  ┌─────┴──────┐                          │
│                  │ PostgreSQL │                          │
│                  └────────────┘                          │
└───────────────────────────────────────────────────────────┘
                          │
        ┌─────────────────┼─────────────────┐
        ▼                 ▼                 ▼
   ┌─────────┐      ┌──────────┐     ┌───────────┐
   │Telegram │      │  OpenAI  │     │  Google   │
   │  API    │      │/Anthropic│     │ Docs/Cal  │
   └─────────┘      └──────────┘     └───────────┘
```

- **`api`** — FastAPI; в v1 только `/healthz`. Слот зарезервирован под веб-дашборд и входящие webhooks.
- **`bot`** — aiogram long-polling; переводит события Telegram в вызовы use case'ов. Никакой бизнес-логики в handler'ах.
- **`worker`** — циклически вычитывает `scheduled_jobs`, исполняет отложенные задачи (публикация в Google Doc, отправка follow-up'ов, ретраи).

Все три процесса импортируют один и тот же пакет `crm` — отличаются только entrypoint'ом.

### 3.2 Структура репозитория

```
reyzbikh_buro_crm/
├── docker-compose.yml
├── docker-compose.prod.yml          # override для прода
├── Dockerfile                       # один образ, три команды запуска
├── pyproject.toml                   # uv (или poetry)
├── alembic.ini
├── migrations/                      # Alembic
├── .env.example
├── README.md
│
├── src/
│   └── crm/
│       ├── __init__.py
│       │
│       ├── domain/                  # Чистые сущности (dataclasses / pydantic)
│       │   ├── client.py            # без IO и без ORM
│       │   ├── lead.py
│       │   ├── project.py
│       │   ├── proposal.py
│       │   ├── follow_up.py
│       │   ├── contract.py
│       │   ├── document.py
│       │   └── event.py
│       │
│       ├── db/                      # SQLAlchemy ORM, сессии, репозитории
│       │   ├── base.py
│       │   ├── session.py
│       │   ├── models/              # ORM-модели
│       │   ├── repositories/        # *_repo.py
│       │   └── unit_of_work.py
│       │
│       ├── use_cases/               # ВСЯ бизнес-логика
│       │   ├── intake_lead.py
│       │   ├── qualify_lead.py
│       │   ├── generate_proposal.py
│       │   ├── publish_proposal_to_gdoc.py
│       │   ├── mark_proposal_sent.py
│       │   ├── send_follow_up.py
│       │   └── record_follow_up_result.py
│       │
│       ├── adapters/                # Pluggable IO
│       │   ├── ai/                  # extractor, proposal_writer
│       │   ├── gdocs/               # create_doc, write_body
│       │   ├── gcal/                # (заглушка)
│       │   └── telegram/            # outbound sender
│       │
│       ├── events/                  # In-process event bus + типы
│       │   ├── bus.py
│       │   └── types.py
│       │
│       ├── scheduler/               # Postgres-backed очередь
│       │   ├── jobs.py              # enqueue / fetch_due
│       │   └── runner.py            # worker loop
│       │
│       ├── modules/                 # Будущие workflow-карточки
│       │   └── lead_intake/         # ТЕКУЩАЯ карточка
│       │       └── wiring.py        # регистрирует подписчики и handler'ы
│       │
│       ├── config.py                # pydantic-settings
│       ├── container.py             # минимальный DI
│       │
│       └── entrypoints/
│           ├── api.py               # FastAPI app
│           ├── bot.py               # aiogram dispatcher
│           └── worker.py            # scheduler runner
│
└── tests/
    ├── unit/                        # domain + use_cases с fake-адаптерами
    ├── integration/                 # testcontainers + Postgres
    └── e2e/                         # bot conversation flows
```

### 3.3 Правила зависимостей

- `domain/` **никогда** не импортирует ничего из `db/`, `adapters/`, `entrypoints/`.
- `use_cases/` зависит от `domain/` и от **интерфейсов** репозиториев/адаптеров (Protocol), а не от конкретных реализаций.
- `adapters/` и `db/` зависят от `domain/` для типов, но не друг от друга.
- `entrypoints/` собирает всё через `container.py` и вызывает use case'ы.
- `modules/<name>/` — это «клей»: регистрирует подписчиков event bus, добавляет handler'ы в бота, может определить свои use case'ы.

---

## 4. Доменная модель

### 4.1 ERD (схематично)

```
Users     Clients ─┐
                   │ 1:N
Leads ───► Proposals ───► Projects
  │  N:1     │ N:0..1        │
  │          │               │ 1:N
  └─► FollowUps (полиморфные)│
                             ▼
                        Contracts

Documents — полиморфные вложения к Lead / Client / Project / Proposal / Contract
Events    — append-only аудит-лог всех доменных изменений
ScheduledJobs — очередь отложенных задач
```

### 4.2 Жизненный цикл (бизнес-смысл)

```
Lead (new)
  └── AI извлёк поля       → Lead.extracted_data
  └── оператор подтвердил → Lead.status=qualified
                            (опционально создан Client, lead.client_id set)
  └── сгенерировано        → Proposal(lead_id) status=draft
  └── опубликовано в GDoc  → Document(owner=proposal, kind=gdoc)
  └── отправлено клиенту   → Proposal.status=sent, FollowUp(+3d), Job
  └── ответ клиента        → accepted: Project создаётся, Proposal.project_id set
                            declined: Lead.status=declined
                            → опционально Contract(project_id, proposal_id)
```

### 4.3 Таблицы

#### `users`
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| telegram_id | bigint UNIQUE NULL | allowlist auth |
| display_name | text | |
| role | enum(`owner`,`architect`,`assistant`) | в v1 только `owner` |
| is_active | bool | default true |
| created_at | timestamptz | |

#### `clients`
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| full_name | text | |
| phone | text NULL | |
| email | text NULL | |
| telegram_id | bigint NULL | |
| source | enum(`telegram`,`referral`,`website`,`walk_in`,`other`) NULL | |
| notes | text DEFAULT '' | |
| created_at / updated_at | timestamptz | |

#### `leads`
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| client_id | FK clients NULL | set при промоушене |
| channel | enum(`telegram`,`email`,`web_form`,`manual`) | в v1 только `telegram` |
| channel_message_id | text NULL | например, ID сообщения Telegram |
| raw_text | text | оригинальный текст / транскрипт |
| summary | text NULL | сгенерированное AI summary |
| extracted_data | JSONB DEFAULT '{}' | результат AI-извлечения |
| status | enum(`new`,`qualifying`,`qualified`,`proposal_sent`,`accepted`,`declined`,`archived`) | |
| assigned_to_user_id | FK users NULL | default = оператор |
| created_at / updated_at | timestamptz | |

#### `projects`
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| client_id | FK clients NOT NULL | |
| lead_id | FK leads NULL | provenance |
| title | text | |
| description | text DEFAULT '' | |
| status | enum(`proposed`,`contract_signed`,`in_progress`,`paused`,`completed`,`cancelled`) | |
| started_at / completed_at | timestamptz NULL | |
| created_at / updated_at | timestamptz | |

#### `proposals`
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| lead_id | FK leads NOT NULL | |
| project_id | FK projects NULL | set после акцепта |
| version | int DEFAULT 1 | для ревизий |
| status | enum(`draft`,`sent`,`accepted`,`declined`,`revised`) | |
| generated_text | text | AI-результат |
| scope_summary | text | |
| price_estimate | numeric(12,2) NULL | |
| currency | text DEFAULT 'RUB' | |
| sent_at / responded_at | timestamptz NULL | |
| created_at / updated_at | timestamptz | |

Google Doc proposal'а хранится не здесь, а в `documents` (`owner_type='proposal'`, `kind='gdoc'`).

#### `follow_ups` (полиморфный subject через 4 nullable FK + CHECK)
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| lead_id | FK leads NULL | exactly one of |
| proposal_id | FK proposals NULL | these four FKs |
| client_id | FK clients NULL | must be non-null |
| project_id | FK projects NULL | (CHECK constraint) |
| kind | enum(`reminder`,`status_check`,`deadline`) | |
| scheduled_for | timestamptz NOT NULL | |
| status | enum(`pending`,`sent`,`cancelled`,`failed`) | |
| channel | enum(`telegram`,`email`) | в v1 только `telegram` |
| message_template | text | для оператора или для исходящего |
| sent_at | timestamptz NULL | |
| result_notes | text NULL | заметки оператора после отработки |
| created_at / updated_at | timestamptz | |

```sql
CHECK (num_nonnulls(lead_id, proposal_id, client_id, project_id) = 1)
```

#### `contracts`
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| project_id | FK projects NOT NULL | |
| proposal_id | FK proposals NULL | |
| contract_number | text UNIQUE NULL | |
| signed_at | timestamptz NULL | null = draft |
| value | numeric(12,2) NULL | |
| currency | text DEFAULT 'RUB' | |
| created_at / updated_at | timestamptz | |

Сам файл контракта — в `documents` (`kind='pdf'` или `gdoc`).

#### `documents` (полиморфные вложения)
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| owner_type | enum(`lead`,`client`,`project`,`proposal`,`contract`) NOT NULL | |
| owner_id | bigint NOT NULL | индекс (owner_type, owner_id) |
| kind | enum(`gdoc`,`pdf`,`image`,`link`,`other`) NOT NULL | |
| title | text | |
| url | text NULL | для external |
| gdoc_id | text NULL | когда kind=`gdoc` |
| mime_type | text NULL | |
| uploaded_by_user_id | FK users NULL | |
| created_at | timestamptz | |

#### `events` (append-only аудит-лог)
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| event_type | text NOT NULL | напр. `lead.created`, `proposal.generated` |
| aggregate_type | text NOT NULL | `lead` / `proposal` / ... |
| aggregate_id | bigint NULL | |
| actor_user_id | FK users NULL | null = system |
| payload | JSONB NOT NULL DEFAULT '{}' | |
| occurred_at | timestamptz NOT NULL DEFAULT now() | |

Индексы: `(aggregate_type, aggregate_id, occurred_at)`, `(event_type, occurred_at)`.

Таблица **только для записи** из бизнес-кода. В v1 не используется как источник триггеров — внутренние реакции выполняются через явные вызовы внутри use case'ов.

#### `scheduled_jobs` (очередь воркера)
| field | type | notes |
|---|---|---|
| id | bigserial PK | |
| job_type | text NOT NULL | `send_follow_up`, `publish_proposal_to_gdoc`, … |
| payload | JSONB NOT NULL | |
| run_at | timestamptz NOT NULL | |
| status | enum(`pending`,`running`,`done`,`failed`) | |
| attempts | int DEFAULT 0 | |
| max_attempts | int DEFAULT 5 | |
| last_error | text NULL | |
| locked_at | timestamptz NULL | для `FOR UPDATE SKIP LOCKED` |
| locked_by | text NULL | id worker'а |
| idempotency_key | text NULL | UNIQUE; используется use case'ом при энкью, чтобы избежать дублей |
| created_at / updated_at | timestamptz | |

Индекс: `(status, run_at) WHERE status IN ('pending')` для быстрого picking.

### 4.4 Ключевые решения схемы

1. **Lead и Client разделены.** Лид — это входящее *событие*, клиент — это *сторона*. Cold-лиды могут навсегда остаться без клиента.
2. **Proposal привязан к Lead, не к Project.** Проект появляется только после акцепта — `proposals.project_id` устанавливается тогда.
3. **`documents.owner_type` — enum-полиморфизм без жёстких FK.** Для 5+ типов CHECK-конструкция стала бы нечитаемой; целостность вложений менее критична.
4. **`follow_ups` — полиморфизм через 4 nullable FK + CHECK.** Subject'ов мало, нужна реальная ссылочная целостность.
5. **Soft-delete отложен.** Хватает `status` enums (`archived`, `cancelled`, `declined`).
6. **`extracted_data` и `payload` — JSONB.** Схема извлечения будет мутировать; колонки появятся позже, когда стабилизируется.
7. **Multi-tenant нет.** Одно бюро. При продаже как SaaS добавим `tenant_id` + RLS.

---

## 5. Поток данных: карточка Lead Intake → Proposal → Follow-up

### 5.1 Happy path (последовательность)

```
1.  Оператор форвардит сообщение клиента в бота
2.  bot.handler вызывает use_case intake_lead(raw_text, channel, msg_id, operator_id)
3.  use_case: INSERT Lead (status=new), publish event lead.created
4.  use_case: AI-extractor.extract(raw_text) — синхронно (вне транзакции)
5.  use_case: UPDATE Lead (extracted_data, summary, status=qualifying), event lead.extracted
6.  bot отвечает: «Извлёк такое-то. [Подтвердить] [Править]»
7.  Оператор → "Подтвердить" → use_case qualify_lead → Lead.status=qualified
8.  Оператор → "Сгенерировать предложение"
9.  bot.handler вызывает use_case generate_proposal(lead_id, operator_id)
10. use_case: INSERT Proposal (status=draft), AI generate_proposal(lead) — вне транзакции
11. use_case: UPDATE Proposal (generated_text, price_estimate), event proposal.generated
12. bot показывает черновик: «[В Google Doc] [Править] [Удалить]»
13. Оператор → "В Google Doc" → use_case publish_proposal_to_gdoc
14. use_case: INSERT scheduled_job (publish_proposal_to_gdoc, run_at=now)
15. Worker подхватывает job: SELECT ... FOR UPDATE SKIP LOCKED
16. Worker вызывает adapter gdocs.create_doc(title, body)
17. Worker INSERT Document (owner=proposal, kind=gdoc, url, gdoc_id)
    Worker publish event proposal.published_to_gdoc
18. Worker уведомляет оператора в Telegram: «Документ готов: <url>»
19. Оператор отправляет ссылку клиенту (вне системы в v1)
20. Оператор → "Предложение отправлено" → use_case mark_proposal_sent
21. use_case: UPDATE Proposal (status=sent, sent_at=now)
    INSERT FollowUp (proposal_id, scheduled_for=now+3d, kind=status_check)
    INSERT scheduled_job (send_follow_up, run_at=scheduled_for)
    event proposal.sent
... 3 дня спустя ...
22. Worker подхватывает job send_follow_up → use_case send_follow_up(follow_up_id)
23. use_case: формирует напоминание, шлёт ОПЕРАТОРУ через Telegram-адаптер
    UPDATE FollowUp (status=sent, sent_at=now), event follow_up.sent
24. bot пишет оператору: «Прошло 3 дня по предложению X — напомни клиенту»
25. Оператор отвечает с результатом → use_case record_follow_up_result
26. use_case: UPDATE FollowUp (result_notes); опционально UPDATE Lead/Proposal статус
```

### 5.2 Use cases карточки

| use case | вход | действие | вызывает |
|---|---|---|---|
| `intake_lead` | `raw_text, channel, channel_message_id, operator_id` | создаёт Lead → AI extract → обновляет Lead | bot handler |
| `qualify_lead` | `lead_id, operator_id, [client_data]` | переводит Lead в qualified; опц. создаёт Client | bot handler |
| `generate_proposal` | `lead_id, operator_id` | создаёт Proposal → AI generate | bot handler |
| `publish_proposal_to_gdoc` | `proposal_id, operator_id` | ставит job; статус Proposal → publishing | bot handler |
| `mark_proposal_sent` | `proposal_id, operator_id` | Proposal=sent, FollowUp+3d, job | bot handler |
| `send_follow_up` | `follow_up_id` | формирует и шлёт напоминание оператору | worker |
| `record_follow_up_result` | `follow_up_id, result_notes, [new_lead_status]` | сохраняет результат, опц. обновляет связанные | bot handler |

Контракт каждого use case:
- получает зависимости через DI (репозитории + адаптеры);
- работает в одной транзакции (Unit of Work);
- AI/HTTP-вызовы выполняет **вне** транзакции (см. §6.3 «Транзакционные правила»);
- завершает запись в `events` той же транзакцией;
- возвращает доменный результат, не отформатированный текст.

### 5.3 Sync vs async

| Операция | Где исполняется | Почему |
|---|---|---|
| AI-извлечение полей лида | синхронно в bot handler | оператор ждёт ответ; aiogram — async, не блокирует других |
| AI-генерация текста предложения | синхронно в bot handler | интерактивно |
| Публикация в Google Doc | через `scheduled_jobs` | внешние сбои; нужны ретраи |
| Отправка follow-up | через `scheduled_jobs` | по определению — в будущем |
| Запись в `events` | синхронно, в той же транзакции | атомарность аудита |

### 5.4 Обработка ошибок

| Место | Стратегия |
|---|---|
| Bot ловит исключение use case'а | лог + ответ оператору «Не получилось: <короткое описание>» |
| AI таймаут | retry до 2 раз в адаптере, потом — exception наружу |
| GDocs API падает | worker инкрементит `attempts`, exp backoff; после `max_attempts` — `status=failed` + алёрт в Telegram |
| Воркер крашится в середине job | reclaimer-функция при старте: jobs с `locked_at < now() - 5m` разблокируются |
| Двойной запуск воркеров | `FOR UPDATE SKIP LOCKED` гарантирует one-take |
| Транзакция сломалась после AI-вызова | AI вызывается до открытия транзакции; повторный AI-запрос приемлемее, чем рассогласование БД |
| Двойное выполнение job (worker упал между job done и COMMIT) | use case проверяет идемпотентность (например, существование Document для proposal) |

### 5.5 Карта статусов

| Шаг | Lead.status | Proposal.status | FollowUp.status |
|---|---|---|---|
| Пришло сообщение | `new` | — | — |
| AI извлёк поля | `qualifying` | — | — |
| Оператор подтвердил | `qualified` | — | — |
| Сгенерирован черновик | `qualified` | `draft` | — |
| Опубликовано в GDoc | `qualified` | `draft` (+ Document) | — |
| Отправлено клиенту | `proposal_sent` | `sent` | `pending` |
| Сработал follow-up | `proposal_sent` | `sent` | `sent` |
| Клиент принял | `accepted` | `accepted` | `sent` |
| Клиент отказался | `declined` | `declined` | `sent` |

---

## 6. Сквозные вопросы

### 6.1 Шина событий vs таблица `events`

| | таблица `events` | in-process event bus |
|---|---|---|
| Где живёт | Postgres, append-only | Python-процесс, ephemeral |
| Назначение | аудит, история, фундамент будущих модулей | склейка use case'ов внутри транзакции |
| Кто пишет | каждый use case в конце транзакции | use case вызывает `bus.publish(SomeEvent(...))` |
| Кто читает | будущий UI таймлайна, отчёты | подписчики в `modules/<name>/wiring.py` |
| В v1 | используется как лог | используется минимально — нет неявной магии |

**Правило для v1:** триггеры между use case'ами пишутся **явно**. Например, `mark_proposal_sent` сам создаёт FollowUp и Job — не через подписку на событие. Шина и таблица — фундамент для будущих карточек (например, карточка «Контракт» подпишется на `ProposalAccepted`).

### 6.2 `scheduled_jobs` — внутренняя реализация

**Энкью** (синхронно из use case в той же транзакции):
```python
async def enqueue(
    session,
    job_type: str,
    payload: dict,
    run_at: datetime | None = None,
    max_attempts: int = 5,
    idempotency_key: str | None = None,
) -> int: ...
```

**Worker loop** (псевдокод):
```python
LEASE_TIMEOUT = timedelta(minutes=5)
POLL_INTERVAL = 5

async def run_worker(worker_id: str):
    while not shutdown.is_set():
        await reclaim_stuck_jobs(LEASE_TIMEOUT)
        jobs = await fetch_due_jobs(limit=10)  # FOR UPDATE SKIP LOCKED → status=running
        for job in jobs:
            await execute_job(job)  # отдельная транзакция на job
        await asyncio.sleep(POLL_INTERVAL)
```

**Бэкофф:** `run_at = now() + 60s * 2^attempts + jitter`. После `max_attempts` → `status='failed'` + Telegram-алёрт.

**Регистр handler'ов** (`job_type → use_case`) живёт в `entrypoints/worker.py`; импортируется из `modules/lead_intake/wiring.py`.

### 6.3 Адаптеры и DI

**Контейнер:**
```python
class Container:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = create_async_engine(settings.database_url)
        self.session_factory = async_sessionmaker(self.db, expire_on_commit=False)
        self.ai_extractor       = build_ai_extractor(settings)
        self.proposal_writer    = build_proposal_writer(settings)
        self.gdocs              = build_gdocs(settings)
        self.telegram_sender    = build_telegram_sender(settings)

    def uow(self): return SqlAlchemyUnitOfWork(self.session_factory)
```

Каждый entrypoint при старте создаёт один `Container`, дальше use case'ы получают зависимости через аргументы. **Никаких глобалов и сингтонов.**

`build_*(settings)` смотрит на `settings.app_env`:
- `prod` / `dev` — реальные клиенты;
- `test` — fake-реализации.

**Контракт адаптера AI-extractor** (пример):
```python
class AIExtractor(Protocol):
    async def extract(self, raw_text: str) -> ExtractedLead: ...

@dataclass(frozen=True)
class ExtractedLead:
    full_name: str | None
    contact: str | None
    project_type: str | None     # квартира / дом / коммерция / ...
    area_m2: float | None
    budget_range: str | None
    timeline: str | None
    summary: str
    confidence: float            # 0..1
    raw_response: dict           # для дебага, идёт в Lead.extracted_data
```

**Транзакционные правила:**
- AI и HTTP-вызовы (Google) — **вне** транзакции БД. Транзакция открывается только для чтения «снимка» и финальной записи.
- Запись в `events` — в той же транзакции, что и изменение домена.
- Энкью job — в той же транзакции, что и изменение, которое job обслуживает (атомарность «сделали и запланировали»).

### 6.4 Конфигурация и секреты

`.env.example` (коммитим):
```env
APP_ENV=dev                        # dev | prod | test
LOG_LEVEL=INFO

DATABASE_URL=postgresql+asyncpg://crm:crm@postgres:5432/crm

TELEGRAM_BOT_TOKEN=
TELEGRAM_OPERATOR_IDS=             # comma-separated allowlist

AI_PROVIDER=openai                 # openai | anthropic | fake
OPENAI_API_KEY=
OPENAI_MODEL=gpt-5.5-medium

GOOGLE_SERVICE_ACCOUNT_JSON=       # путь к файлу
GOOGLE_DOCS_PARENT_FOLDER_ID=

WORKER_POLL_INTERVAL_SECONDS=5
```

Загрузка — `pydantic-settings`. Падает на старте, если обязательное отсутствует.

**Секреты в prod:** `.env` на VPS с правами `chmod 600`. Файл сервис-аккаунта Google — `secrets/google-sa.json`.

### 6.5 Деплой

**`docker-compose.yml`** (см. полную версию в §3.2). Сервисы: `postgres`, `migrate` (одноразовый, гонит `alembic upgrade head`), `api`, `bot`, `worker`. Один `Dockerfile`, разные `command`.

**Production override (`docker-compose.prod.yml`):**
- managed Postgres или `pg_dump` cron-бэкапы;
- `LOG_LEVEL=INFO`, JSON-логи;
- ужесточённые healthcheck'и;
- reverse proxy (Caddy/Traefik) перед `api` для будущего HTTPS — в v1 `api` может вообще не торчать наружу.

**Миграции:** Alembic, отдельный сервис `migrate` запускается до остальных. Без авто-`create_all`.

### 6.6 Тесты

| Уровень | Где | Что покрывает |
|---|---|---|
| Unit | `tests/unit/` | `domain/`, use case'ы с fake-адаптерами и fake-репозиториями |
| Integration | `tests/integration/` | use case'ы поверх настоящего Postgres (через `testcontainers-python`); репозитории; миграции |
| E2E | `tests/e2e/` | сценарии «оператор → бот → use case → БД» с fake AI/GDocs |

**Обязательное покрытие v1:**
- `intake_lead` — happy + AI ошибки;
- `generate_proposal` — happy + AI ошибки;
- `publish_proposal_to_gdoc` — happy + ретрай при сбое GDocs (тест воркера);
- `mark_proposal_sent` создаёт FollowUp с корректным `scheduled_for`;
- worker идемпотентен: дёрнули job дважды → Document создаётся один раз;
- CHECK на `follow_ups`: попытка вставить две non-null subject FK падает.

**CI:** GitHub Actions — `pytest -q`, `ruff`, опц. `mypy`, `alembic upgrade head` на пустой БД.

### 6.7 Наблюдаемость

- **Логи:** `structlog`, JSON в prod, плоский в dev; контекст `lead_id` / `proposal_id` / `job_id` в каждой записи.
- **Алёрты:** при `scheduled_jobs.status='failed'` worker отправляет сообщение оператору в Telegram.
- **Маскировка секретов:** structlog-processor вырезает значения ключей `*_token`, `*_key`, `api_key`.
- **Метрики / трейсы:** отложено до появления реальной нагрузки.

---

## 7. Точки расширения для будущих карточек

| Будущая карточка | Что добавляет | Что НЕ трогает |
|---|---|---|
| Подписание контракта | use case `create_contract(proposal_id)`, новый event `contract.signed`, handler'ы в боте | базовые таблицы |
| Запуск проекта | подписчик на `contract.signed`, события в Google Calendar через `adapters/gcal/`, статусы Project | базовые таблицы |
| Выставление счетов | новая таблица `invoices` (FK на project), новый адаптер платёжной системы | существующие сущности |
| Архив лидов / отчёты | read-only use case'ы, индексы по `events` | базовые таблицы |
| Рефералы | новый модуль `modules/referrals/`, поле `Client.referred_by_client_id` (миграция) | основные потоки |
| Web-дашборд | роуты в `entrypoints/api.py`, frontend-проект отдельно; use case'ы переиспользуются | бизнес-логику |
| Двусторонний канал с клиентом | новый адаптер `telegram/client_chat.py`, новые статусы FollowUp | домен |

---

## 8. Out of scope для v1

| Фича | Причина откладывания |
|---|---|
| Web-дашборд (UI) | FastAPI готов принять, но UI — отдельная карточка |
| Soft-delete через `deleted_at` | хватает `status` enums |
| Полнотекстовый поиск | добавим когда лидов будет >100 |
| Multi-tenant | не нужно для одного бюро |
| Web-логин / OAuth для оператора | Telegram allowlist решает |
| Celery / Redis / RabbitMQ | Postgres-очередь покрывает текущие нужды |
| Двусторонний канал с клиентом через Telegram | в v1 оператор общается с клиентом вне системы |
| E-mail / web-форма как канал лидов | следующие карточки |
| Метрики Prometheus, трейсы OTel | нет нагрузки |
| Голосовая транскрибация лидов | отдельная мини-карточка при необходимости |

---

## 9. Карта рисков

| Риск | Вероятность | Митигатор |
|---|---|---|
| Google Docs API OAuth — больно настроить | высокая | сервис-аккаунт + shared folder вместо OAuth-flow; отложить, пока остальное не работает на fake-адаптере |
| AI-извлечение выдаёт мусор на нестандартных лидах | средняя | хранить `raw_response`; «подтвердить/править» — обязательный шаг; не автоматизировать переход в `qualified` |
| Дрейф схемы `extracted_data` ломает старые лиды | средняя | `extracted_data.schema_version`; default'ы при чтении |
| Worker отстаёт от расписания follow-up'ов | низкая | один воркер обрабатывает десятки тысяч лёгких задач/мин; алёрт если `oldest_pending > 1h` |
| Транзакция с AI-вызовом — долгая блокировка | средняя | AI строго вне транзакции |
| Утечка токенов в логи | средняя | structlog-маскировщик `*_token`, `*_key` |
| Двойная отправка follow-up'а из-за реткрая | средняя | идемпотентность: use case проверяет `FollowUp.status` перед отправкой |

---

## 10. Глоссарий

- **Лид (Lead)** — входящий запрос (сообщение из Telegram, e-mail, web-форма).
- **Клиент (Client)** — сторона, с которой бюро вступило в отношения.
- **Предложение (Proposal)** — коммерческое предложение в ответ на лид.
- **Проект (Project)** — рабочая единица, появляется после акцепта предложения.
- **Контракт (Contract)** — формальное соглашение по проекту.
- **Документ (Document)** — внешний файл/ссылка (Google Doc, PDF, изображение), привязанный к одной из сущностей.
- **Событие (Event)** — append-only запись о доменном изменении.
- **Job (ScheduledJob)** — отложенная задача в Postgres-очереди.
- **Use case** — функция, реализующая один пользовательский сценарий; единственное место бизнес-логики.
- **Adapter** — обёртка над внешним сервисом (AI, Google, Telegram) с фиксированным Protocol-контрактом.
- **Карточка (workflow card)** — один автоматизированный сценарий бизнес-процесса (текущая v1 — Lead Intake → Proposal → Follow-up).

---

## 11. Решения, которые принимаются на этапе плана реализации

Эти вопросы не блокируют дизайн, но должны быть отвечены при написании implementation plan:

- Конкретный package manager — `uv` vs `poetry`.
- Pre-commit hooks — `pre-commit` + `ruff format` + `ruff check`.
- Точная модель OpenAI/Anthropic и prompt-шаблоны для extractor и proposal-writer (вынести в `prompts/` как `.j2`).
- Стратегия миграций при изменении JSONB-схемы (`extracted_data.schema_version`).
- Конкретный layout `docker-compose.prod.yml` (managed Postgres vs in-compose).
- Структура шаблонов сообщений бота (i18n / dataclass / Jinja).
