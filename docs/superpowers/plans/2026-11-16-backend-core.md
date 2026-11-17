# Backend core implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend of the AI trip planner: Postgres schema, pure domain rules, research clients, LLM planning with fallback, background plan jobs, Excel export, chat (trip questions, plan edits and destination discovery in one conversation), and the HTTP API.

**Architecture:** A fixed pipeline in code (spec approach 1). Pure `domain` models and rules sit at the center; `research`, `planning`, `export` depend on `domain`; `chat`, `discovery`, `jobs` add the database; `api` calls services only. Plan generation runs in a separate worker process that leases jobs from a Postgres table.

**Tech Stack:** Python 3.12+, FastAPI, pydantic 2, psycopg 3 (pool), httpx, openpyxl, tavily-python, the existing `openrouter` provider, pytest, uv, ruff, mypy. Postgres 17 (`postgres:17-alpine`).

**Spec:** `docs/superpowers/specs/2026-11-16-ai-trip-planner-design.md` (read it first; this plan cites its sections instead of repeating them). Requirements: `REQUIREMENTS.md`.

**Out of scope for this plan:** the `web/` frontend (separate plan), login.

## Global constraints

- Python `>=3.12`; `from __future__ import annotations` at the top of every new module; type hints on every public signature; absolute imports with `src/` on the path (`from domain.plan import Plan`), as the existing code does.
- Follow the user's coding-style skill (`~/.claude/skills/coding-style/SKILL.md` and `references/python.md`): one-line header comment above every function, `# METHOD /path - Purpose` above every route, no bare `except`, no mutable defaults, return new values instead of mutating arguments, `Sequence`/`Mapping` for read-only parameters, `pathlib.Path`, f-strings, `logging` not `print`.
- New code takes its dependencies as arguments. Existing singletons (`core.config.config`, `tools.tool_registry.registry`) stay as they are.
- Leave the template leftovers alone (`otp_tool`, `chart_tool`, `src/knowledge/`, `src/memory/`, the Vietnamobile prompts).
- Pydantic models in `domain` are `frozen=True`. Money is `Decimal`; in SQL it is `numeric(14,2)`.
- Every structured LLM output goes through `planning.llm_json.call_json`. Code never trusts an id, URL, date or price the model invents (spec "Plan document").
- No test calls OpenRouter, Tavily, Open-Meteo or ExchangeRate-API. Integration tests need Postgres (`docker compose up -d db`, or any server in `DB_*`); they run in `<DB_NAME>_test`, created on first run.
- Ruff line length 100, double quotes; mypy strict on `src/`.
- No commit steps: the folder is not a git repo, and the user commits only when they ask. Each task ends at "tests pass".
- Plain punctuation in all text and prompts: `-`, straight quotes, `...`; no em or en dashes.

## Review focus

1. A Vietnamese name typed in a different Unicode form or case ("Đức" in NFD from a Mac, "ĐỨC") must hit the same user. Tests in Task 2 (database collation) and Task 4 (NFC normalization).
2. A free model wraps JSON in ```` ```json ```` fences, adds prose before it, or truncates it. `call_json` must extract or repair, never crash. Test in Task 9.
3. A trip that starts 10 days out and lasts 10 days is half inside the 16-day forecast window: each date gets its own `basis`. Test in Task 11.
4. At 00:30 in Vietnam, a UTC server still sees yesterday's date; "start today" must be accepted. Test in Task 4.
5. A visitor closes the tab while a chat reply streams: an edit that was applied stays saved, and the assistant message is stored with the text sent so far. Test in Task 18.

---

### Task 1: Project setup and config

**Files:**

- Create: `pyproject.toml`, `.env.example`, `docker-compose.yml`, `tests/conftest.py`, `tests/unit/test_settings.py`
- Create: `src/core/settings.py`
- Modify: `scripts/sync_models.sh:16` (pass `src/core/constants.py`)
- Modify: `src/api/main.py` (stop importing the broken `api.routes.chat`; Task 22 replaces that route)

**Interfaces:**

- Produces: `core.settings.Settings` (frozen dataclass) and `load_settings(env: Mapping[str, str]) -> Settings`.

Settings fields (env name in caps, default after `=`; no default means required):

| Field | Env | Default |
|---|---|---|
| db (`DbSettings`) | DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME, DB_SSLMODE | user, password, name required; host `localhost`, port 5432, sslmode `prefer`; `db.conninfo(dbname=None)` builds the libpq string |
| openrouter_api_key | OPENROUTER_API_KEY | required |
| tavily_api_key | TAVILY_API_KEY | required |
| planner_models, chat_models, classifier_models | PLANNER_MODELS, CHAT_MODELS, CLASSIFIER_MODELS | required, comma-separated model ids |
| llm_calls_per_job | LLM_CALLS_PER_JOB | 6 |
| planner_timeout_s, chat_timeout_s | PLANNER_TIMEOUT_S, CHAT_TIMEOUT_S | 90, 30 |
| daily_llm_ceiling_new_trips | DAILY_LLM_CEILING_NEW_TRIPS | required (set from the account's real quota) |
| daily_llm_ceiling_chat | DAILY_LLM_CEILING_CHAT | required, must be greater than the trips ceiling |
| daily_tavily_ceiling | DAILY_TAVILY_CEILING | required |
| quota_reset_hour_utc | QUOTA_RESET_HOUR_UTC | 0 (OpenRouter reset time unverified) |
| openrouter_daily_cap_pattern | OPENROUTER_DAILY_CAP_PATTERN | `free-models-per-day` (unverified, regex) |
| tavily_quota_pattern | TAVILY_QUOTA_PATTERN | `usage limit` (unverified, regex) |
| retention_days, user_inactive_days | RETENTION_DAYS, USER_INACTIVE_DAYS | 30, 90 |
| trust_proxy_headers | TRUST_PROXY_HEADERS | false |
| cors_origins | CORS_ORIGINS | `http://localhost:5173` |
| ip_requests_per_minute, ip_chat_per_minute | ... | 30, 10 |
| ip_trips_per_day, ip_chat_per_day | ... | 10, 200 |
| user_trips_per_day, user_chat_per_day | ... | 5, 100 |
| template_path | TEMPLATE_PATH | `data/trip-template.xlsx` |

- [x] **Step 1: Write `pyproject.toml`**

Dependencies: `fastapi`, `uvicorn[standard]`, `pydantic>=2.9`, `python-dotenv`, `openai`, `openrouter`, `boto3`, `tavily-python`, `httpx`, `psycopg[binary,pool]`, `openpyxl`. Dev group: `pytest`, `ruff`, `mypy`. Ruff and mypy config exactly as in the coding-style Python reference. Pytest: `pythonpath = ["src"]`, `testpaths = ["tests"]`, marker `integration`.

- [x] **Step 2: Write `docker-compose.yml` with the `db` service only**

`postgres:17-alpine`, user/password/db `trip`, port 5432, `POSTGRES_INITDB_ARGS: "--locale-provider=builtin --builtin-locale=C.UTF-8"` (Postgres 17's builtin provider gives Unicode case mapping on Alpine; Review focus 1), credentials and port from `DB_*` in `.env`. Task 23 adds `api` and `worker`.

- [x] **Step 3: Write the failing tests**

```python
def test_load_settings_reads_required_and_defaults():
    s = load_settings(MIN_ENV)
    assert s.planner_models == ("a/b:free", "c/d:free")
    assert s.llm_calls_per_job == 6
    assert s.trust_proxy_headers is False

def test_load_settings_names_every_missing_variable():
    with pytest.raises(ValueError) as e:
        load_settings({})
    assert "DB_PASSWORD" in str(e.value) and "TAVILY_API_KEY" in str(e.value)

def test_load_settings_rejects_chat_ceiling_below_trip_ceiling():
    with pytest.raises(ValueError):
        load_settings({**MIN_ENV, "DAILY_LLM_CEILING_CHAT": "10", "DAILY_LLM_CEILING_NEW_TRIPS": "20"})
```

`MIN_ENV` is a module constant in the test with every required variable set.

- [x] **Step 4: Run, expect FAIL** - `uv run pytest tests/unit/test_settings.py -v` -> `ModuleNotFoundError: core.settings`
- [x] **Step 5: Implement `load_settings` in `src/core/settings.py`**, collecting all missing names before raising. Write `.env.example` listing every variable with a one-line comment and no values. Fix `scripts/sync_models.sh:16`. Remove `chat` from the imports and routers in `src/api/main.py`.
- [x] **Step 6: Run, expect PASS** - same command. Also `bash -n scripts/sync_models.sh` exits 0 and `PYTHONPATH=src uv run python -c "import api.main"` exits 0.

---

### Task 2: Schema, migrations, database access

**Files:**

- Create: `sql/migrations/0001_init.sql`, `scripts/migrate.py`, `src/db/pool.py`, `src/db/queries.py`
- Test: `tests/integration/conftest.py`, `tests/integration/test_schema.py`

**Interfaces:**

- Produces: `db.pool.open_pool(database_url: str, max_size: int = 10) -> ConnectionPool`. A unit of work is `with pool.connection() as conn:`, which already commits on exit and rolls back on exception, so there is no separate transaction helper.
- Produces: `db.queries.load_queries(path: Path) -> Mapping[str, str]` (blocks headed `-- name: <query_name>`; raises `ValueError` on a duplicate or empty name).
- Produces: `scripts/migrate.py` with `apply_migrations(conn, migrations_dir: Path) -> list[str]` returning versions applied; CLI `PYTHONPATH=src uv run python scripts/migrate.py` reads `DB_*`.
- Produces: fixture `db` in `tests/integration/conftest.py`: drops and recreates schema `public` once per session, migrates, and truncates all tables (except `schema_migrations`) before each test.

- [x] **Step 1: Write `0001_init.sql`** with every table, column, check, foreign key and index in spec "Database": `users`, `trips`, `conversations`, `messages`, `jobs`, `search_cache`, `research_results`, `llm_calls`, `quota_blocks`. The plan lives on `trips` (`plan`, totals, `plan_revision`). Partial unique index `jobs_one_active_per_trip ON jobs(trip_id) WHERE status IN ('queued','running')`.
- [x] **Step 2: Write the failing tests**

```python
def test_migrate_applies_once_and_is_idempotent(db_conn):
    assert apply_migrations(db_conn, MIGRATIONS) == []      # session fixture already applied 0001

def test_user_names_unique_ignoring_case_and_spaces(db_conn):
    insert_user(db_conn, "Đức")
    with pytest.raises(psycopg.errors.UniqueViolation):
        insert_user(db_conn, "  đỨC ")

def test_trip_rejects_end_before_start_and_over_30_days(db_conn): ...   # two CheckViolation asserts

def test_trip_local_currency_null_exactly_when_country_vn(db_conn): ...  # VN+THB fails, TH+null fails

def test_only_one_active_job_per_trip(db_conn): ...                     # second queued job -> UniqueViolation

def test_deleting_trip_cascades_to_jobs_research(db_conn): ...

def test_load_queries_rejects_duplicate_name(tmp_path): ...
```

`insert_user` here is a raw `INSERT` helper in the test file, not the Task 3 repository.

- [x] **Step 3: Run, expect FAIL** - `uv run pytest tests/integration/test_schema.py -v -m integration`
- [x] **Step 4: Implement `migrate.py`, `pool.py`, `queries.py`.** Each migration runs in its own transaction and inserts its version into `schema_migrations`.
- [x] **Step 5: Run, expect PASS** - same command.

---

### Task 3: Repositories

**Files:**

- Create: `sql/queries/{users,conversations,trips,messages,jobs,research,llm_calls,quota}.sql`
- Create: `src/db/repositories/{users,conversations,trips,messages,jobs,research,llm_calls,quota}.py`
- Create: `src/core/exceptions.py` (replace the stub)
- Test: `tests/integration/test_repositories.py`

**Interfaces:**

- Produces in `core.exceptions`: `NotFound`, `Conflict`, `PlanConflict(Conflict)`, `LimitExceeded`, `QuotaExhausted(blocked_until: datetime)`, `LLMUnavailable`, `LLMBudgetExceeded`, `InvalidLLMOutput(errors: list[str])`, `EditRejected(errors: list[str])`, `ResearchFailed`.
- Every repository function takes `conn: psycopg.Connection` first and returns frozen dataclass rows (`UserRow`, `TripRow`, `ConversationRow`, `MessageRow`, `JobRow`, `SourceRow`) built with `psycopg.rows.class_row`. JSONB columns come back as `dict`; the caller validates them into domain models.
- `users`: `claim_user(conn, name: str) -> UserRow` (insert, or return the existing row on `name_key` conflict; touches `last_seen_at`), `get_user(conn, user_id) -> UserRow` (raises `NotFound`).
- `trips`: `create_trip(conn, user_id, request: dict, local_currency: str | None, retention_days: int) -> TripRow`, `get_trip`, `list_trips(conn, user_id, limit, offset) -> list[TripRow]`, `set_status(conn, trip_id, status, failure_reason=None)`, `touch(conn, trip_id, retention_days)`, `delete_trip`, `count_trips_today(conn, user_id) -> int`.
- `trips` also has `save_plan(conn, trip_id, base_revision: int, plan: dict, total_cost_vnd: Decimal, over_budget: bool, model_id: str | None, request: dict | None = None) -> TripRow`: one `UPDATE` that writes the plan, totals and, when given, the request columns, with `plan_revision = plan_revision + 1 WHERE id = %s AND plan_revision = %s`; zero rows updated raises `PlanConflict`.
- `conversations`: `create_conversation(conn, user_id, draft: dict | None) -> ConversationRow`, `get_conversation`, `list_conversations(conn, user_id) -> list[ConversationRow]` (newest first), `save_draft(conn, conversation_id, draft: dict)`, `touch_conversation(conn, conversation_id)` (sets `updated_at`).
- `messages`: `add_message(conn, conversation_id, role, content, intent=None, suggestions=None) -> MessageRow`, `recent_messages(conn, conversation_id, limit: int) -> list[MessageRow]` (oldest first), `count_user_messages_today(conn, user_id) -> int`, `count_intent(conn, conversation_id, intent) -> int`.
- `jobs`: `enqueue(conn, trip_id, kind="generate_plan", request: dict | None = None) -> JobRow` (raises `Conflict` on the active-job index), `lease_next(conn, worker_id: str, lease_seconds: int) -> JobRow | None`, `set_stage`, `add_llm_calls(conn, job_id, n: int)`, `finish(conn, job_id, status, last_error=None)`, `requeue(conn, job_id, run_after: datetime, last_error: str)`, `active_job(conn, trip_id) -> JobRow | None`.
- `research`: `cache_get(conn, key) -> dict | None` (ignores expired), `cache_put(conn, key, provider, query, payload, ttl: timedelta)`, `save_sources(conn, *, trip_id=None, conversation_id=None, kind, items: Sequence[SourceInput]) -> list[SourceRow]`, `sources_for_trip(conn, trip_id) -> list[SourceRow]`.
- `llm_calls`: `log_call(conn, LlmCallRecord)`, `count_today(conn, purpose_in: Sequence[str] | None = None) -> int`.
- `quota`: `block(conn, service, until, reason)`, `active_block(conn, service) -> datetime | None`, `count_tavily_today(conn) -> int` (from `search_cache` writes with provider `tavily` today).

`lease_next` SQL (the one algorithm the signature does not fix):

```sql
-- name: lease_next
UPDATE jobs SET status = 'running', attempts = attempts + 1,
       leased_until = now() + make_interval(secs => %(lease_seconds)s)
WHERE id = (
  SELECT id FROM jobs
  WHERE (status = 'queued' AND run_after <= now())
     OR (status = 'running' AND leased_until < now())
  ORDER BY run_after
  FOR UPDATE SKIP LOCKED
  LIMIT 1)
RETURNING *;
```

- [x] **Step 1: Write the failing tests**

```python
def test_claim_user_returns_same_row_for_same_name_any_case(db_conn):
    a = claim_user(db_conn, "Duy"); b = claim_user(db_conn, " duy ")
    assert a.id == b.id and b.name == "Duy"

def test_save_plan_overwrites_plan_and_bumps_revision(db_conn, trip):
    first = save_plan(db_conn, trip.id, 0, PLAN, Decimal("100"), False, "m")
    second = save_plan(db_conn, trip.id, 1, PLAN, Decimal("90"), False, "m")
    assert (first.plan_revision, second.plan_revision) == (1, 2)
    assert get_trip(db_conn, trip.id).total_cost_vnd == Decimal("90")

def test_save_plan_with_stale_revision_raises_plan_conflict(db_conn, trip): ...

def test_two_connections_never_lease_the_same_job(db_pool, trip):
    enqueue(...)
    with db_pool.connection() as c1, db_pool.connection() as c2:
        j1 = lease_next(c1, "w1", 60); j2 = lease_next(c2, "w2", 60)
    assert j1 is not None and j2 is None

def test_expired_lease_is_leased_again(db_conn, trip): ...

def test_cache_get_ignores_expired_rows(db_conn): ...

def test_list_conversations_newest_first(db_conn, user): ...
```

- [x] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_repositories.py -v -m integration`
- [x] **Step 3: Implement the SQL files and repository modules.**
- [x] **Step 4: Run, expect PASS.**

---

### Task 4: Currency, trip request

**Files:**

- Create: `src/domain/currency.py`, `src/domain/trip_request.py`
- Modify: `src/core/constants.py` (add `COUNTRY_CURRENCY: Mapping[str, str]`, ISO 3166 alpha-2 to ISO 4217, covering at least every country in Asia, Europe, North America and Oceania plus `VN: VND`)
- Test: `tests/unit/test_currency.py`, `tests/unit/test_trip_request.py`

**Interfaces:**

- Produces in `domain.currency`: `HOME_CURRENCY = "VND"`, `local_currency_for(country_code: str) -> str | None` (None for `VN`; raises `ValueError` for an unknown country), `Currencies` model (`home: Literal["VND"]`, `local: str | None`, `local_to_home_rate: Decimal | None`, `rate_date: date | None`; validator: local and rate both set or both None), `to_vnd(amount: Decimal, currency: str, currencies: Currencies) -> Decimal` (raises `ValueError` for a currency that is neither home nor local).
- Produces in `domain.trip_request`: `Destination` (`name`, `country_code`, `lat`, `lon`), `TripRequest` (fields of spec "Validation rules" plus `notes: str | None`), enums as `Literal` types `GroupType`, `TravelStyle`, `TransportMode`, `Language`, `BudgetScope`; `validate_request(request: TripRequest, today: date) -> list[str]` for cross-field rules; `today_in_vietnam(now: datetime) -> date` (Asia/Ho_Chi_Minh via `zoneinfo`); `budget_total_vnd(request) -> Decimal`; `clean_text(value: str, max_len: int) -> str` (NFC-normalize, strip, remove control characters, raise on over-length); `normalize_name(name: str) -> str` (NFC + strip; 1 to 50 chars).

- [ ] **Step 1: Write the failing tests**

```python
def test_local_currency_none_for_vietnam_and_thb_for_thailand():
    assert local_currency_for("VN") is None and local_currency_for("TH") == "THB"

def test_to_vnd_converts_local_with_stored_rate():
    c = Currencies(home="VND", local="THB", local_to_home_rate=Decimal("720.5"), rate_date=date(2026, 11, 16))
    assert to_vnd(Decimal("10"), "THB", c) == Decimal("7205.0")
    assert to_vnd(Decimal("10"), "VND", c) == Decimal("10")

def test_to_vnd_rejects_third_currency(): ...

def test_today_in_vietnam_is_next_day_at_0030_local_when_utc_is_previous_day():
    assert today_in_vietnam(datetime(2026, 11, 16, 17, 30, tzinfo=UTC)) == date(2026, 11, 17)

def test_validate_request_accepts_start_today_and_rejects_yesterday(): ...
def test_validate_request_rejects_trip_longer_than_30_days(): ...
def test_validate_request_rejects_unknown_country(): ...
def test_transport_modes_may_be_empty_but_styles_may_not(): ...
def test_budget_total_vnd_multiplies_per_person_by_travelers(): ...

def test_normalize_name_turns_nfd_into_nfc():
    assert normalize_name(unicodedata.normalize("NFD", " Đức ")) == unicodedata.normalize("NFC", "Đức")
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_currency.py tests/unit/test_trip_request.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 5: Plan model and budget

**Files:**

- Create: `src/domain/plan.py`, `src/domain/budget.py`
- Test: `tests/unit/test_plan.py`, `tests/unit/test_budget.py`, `tests/fixtures/plan_domestic.json`, `tests/fixtures/plan_abroad.json`

**Interfaces:**

- Produces in `domain.plan` (all frozen pydantic, field names exactly as spec "Plan document"): `Category`, `PriceBasis`, `ItemStatus`, `Weather`, `PlanItem` (adds `option_id: str | None`), `Day`, `TransportOption` (`leg: Literal["outbound", "return", "local"]`), `Accommodation`, `ChecklistItem`, `PlanWarning`, `Plan`. `id` fields default to `""` (empty until assigned).
- Produces: `assign_ids(plan: Plan) -> Plan` (fills every empty id with the next free `it_N`, `tr_N`, `ac_N`, `ck_N`, never changing an existing id), `transport_item(option: TransportOption, day: date) -> PlanItem` (category `transport`, `option_id` set, price fields copied), `CATEGORY_LABELS_VI: Mapping[Category, str]` (`transport` to `Đi lại` and so on per spec).
- Produces in `domain.budget`: `CostLine(category: Category, currency: str, per_person: Decimal)`, `cost_lines(plan: Plan, travelers: int) -> list[CostLine]` (per person, grouped by category and currency; accommodation = `price_per_night x nights x rooms / travelers` for the chosen one; transport options counted only through their items), `total_cost_vnd(plan: Plan, travelers: int) -> Decimal`, `over_budget_vnd(plan: Plan, request: TripRequest) -> Decimal` (0 when within budget).

- [ ] **Step 1: Write the failing tests**

```python
def test_plan_fixture_round_trips_through_json():
    plan = Plan.model_validate_json(FIXTURE_ABROAD)
    assert Plan.model_validate(plan.model_dump(mode="json")) == plan

def test_assign_ids_keeps_existing_ids_and_fills_empty_ones(): ...

def test_total_cost_counts_chosen_accommodation_only_and_converts_local():
    # abroad fixture: 2 travelers, items 350 THB pp, chosen hotel 1800 THB x 4 nights x 1 room, rate 720.5
    assert total_cost_vnd(plan, 2) == Decimal(...)   # computed by hand in the test

def test_chosen_transport_option_is_not_counted_twice(): ...

def test_over_budget_is_zero_when_within_budget_and_positive_when_over(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_plan.py tests/unit/test_budget.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 6: Plan rules

**Files:**

- Create: `src/domain/plan_rules.py`
- Test: `tests/unit/test_plan_rules.py`

**Interfaces:**

- Consumes: `Plan`, `TripRequest`, `Currencies`.
- Produces: `RuleResult(plan: Plan, errors: list[str])` and `check_plan(plan: Plan, request: TripRequest, known_source_ids: AbstractSet[int]) -> RuleResult`. `errors` are short sentences addressed to the model ("days: missing 2026-12-21"), used as repair input. The returned `plan` is the sanitized copy: unknown `source_id` set to None and `price_basis` set to `estimate`.

Rules (each one error message per violation): one day per trip date and no others; items' dates inside the trip; `start_time <= end_time` and items ordered by `start_time` within a day; every price currency is `VND` or `currencies.local`; outbound and return legs each have 2 to 3 options with exactly one `chosen`; when `request.transport_modes` is non-empty, chosen options use one of those modes; every chosen outbound and return option has a linked `transport` item (`option_id`) on the first and last day respectively; at most one chosen accommodation; `source` basis requires a `source_id`.

- [ ] **Step 1: Write the failing tests**, one per rule, named after it, for example:

```python
def test_missing_trip_date_is_an_error(): ...
def test_items_out_of_time_order_is_an_error(): ...
def test_third_currency_is_an_error(): ...
def test_two_chosen_outbound_options_is_an_error(): ...
def test_chosen_mode_outside_requested_modes_is_an_error(): ...
def test_empty_requested_modes_allows_any_mode(): ...
def test_unknown_source_id_is_removed_and_price_becomes_estimate():
    result = check_plan(plan_with_source(99), request, known_source_ids={1, 2})
    item = result.plan.days[0].items[0]
    assert (item.source_id, item.price_basis, result.errors) == (None, "estimate", [])
def test_valid_fixture_has_no_errors(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_plan_rules.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 7: Plan edits

**Files:**

- Create: `src/domain/plan_edit.py`
- Test: `tests/unit/test_plan_edit.py`

**Interfaces:**

- Produces: `PlanEdit(ops: tuple[EditOp, ...] (1 to 20), explanation: str)`, where `EditOp` is a discriminated union on `op`: `AddItem(date, item)`, `UpdateItem(item_id, changes: ItemChanges)` (`ItemChanges` = every `PlanItem` field except `id` and `option_id`, all optional), `RemoveItem(item_id)`, `MoveItem(item_id, date, start_time | None, end_time | None)`, `SetAccommodation(accommodation_id | None, accommodation: Accommodation | None)` (exactly one set), `ChooseTransportOption(option_id)`, `AddTransportOption(option, choose: bool)`, `ReplaceDay(date, items)`, `UpdateChecklist(items)`, `UpdateRequest(changes: RequestChanges)` (`start_date`, `end_date`, `travelers`, `origin`, `language`, all optional).
- Produces: `EditResult(plan: Plan, request_changes: RequestChanges | None, changed: list[str])` and `apply_edit(plan: Plan, edit: PlanEdit, request: TripRequest) -> EditResult`. Raises `EditRejected(errors)` for an unknown id, a date outside the trip, `RemoveItem` on an item with `option_id` (switch the option instead), or `UpdateRequest` combined with other ops. New items and options get ids via `assign_ids`. `ChooseTransportOption` unchooses the leg's other options and replaces the linked item with `transport_item(option, day)` in the same position. `changed` lists one human-readable line per op ("Removed it_4 Ba Na Hills", "Chose tr_2 for outbound").

- [ ] **Step 1: Write the failing tests**

```python
def test_remove_item_leaves_every_other_item_unchanged():
    result = apply_edit(PLAN, PlanEdit(ops=(RemoveItem(op="remove_item", item_id="it_4"),), explanation="x"), REQ)
    before = [i for d in PLAN.days for i in d.items if i.id != "it_4"]
    assert [i for d in result.plan.days for i in d.items] == before

def test_unknown_item_id_is_rejected(): ...
def test_choose_transport_option_swaps_linked_item_and_flags(): ...
def test_add_transport_option_with_choose_true_becomes_the_chosen_one(): ...
def test_removing_a_transport_option_item_is_rejected(): ...
def test_update_request_alone_returns_request_changes_and_same_plan(): ...
def test_update_request_mixed_with_other_ops_is_rejected(): ...
def test_new_items_get_fresh_ids_that_do_not_collide(): ...
def test_apply_edit_does_not_mutate_input_plan(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_plan_edit.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 8: Model router

**Files:**

- Create: `src/models/model_router.py` (replace the stub)
- Test: `tests/fakes.py`, `tests/unit/test_model_router.py`

**Interfaces:**

- Consumes: `models.base.LLMProvider`, `LLMResponse`; `core.exceptions`.
- Produces in `tests/fakes.py`: `FakeProvider(LLMProvider)` built from a list of scripted results (a string answer, or an exception to raise), recording the messages it received; `FakeSearch` (query to results, records calls).
- Produces in `models.model_router`:
  - `Purpose = Literal["generate", "repair", "classify", "edit", "answer", "discover", "suggest"]`
  - `CallContext(trip_id: UUID | None, conversation_id: UUID | None, message_id: UUID | None, budget: CallBudget | None)`
  - `CallBudget(limit: int, used: int)` with `take() -> None` (raises `LLMBudgetExceeded` when `used == limit`, else increments); the only mutable object here, owned by one job attempt.
  - `CallSink` protocol: `log(record: LlmCallRecord) -> None`, `block(service: str, until: datetime, reason: str) -> None`, `blocked_until(service: str) -> datetime | None`.
  - `ModelRouter(provider_for: Callable[[str], LLMProvider], models: Mapping[Purpose, Sequence[str]], sink: CallSink, daily_cap_pattern: str, reset_hour_utc: int, now: Callable[[], datetime])`
  - `models_for(purpose) -> list[str]` (config order, ids missing from `ModelId` dropped, see `src/core/constants.py`)
  - `invoke_model(model_id, purpose, messages, system_prompt, ctx) -> LLMResponse`: checks the block, takes the budget, calls, logs the outcome, maps errors: HTTP 429 matching the daily-cap pattern -> `block("openrouter", next_reset, msg)` then `QuotaExhausted`; other 429, 5xx, timeout -> `LLMUnavailable`.
  - `invoke(purpose, messages, system_prompt, ctx) -> LLMResponse`: tries `models_for(purpose)` in order, skipping on `LLMUnavailable`; raises `LLMUnavailable` when all fail.
  - `stream(purpose, messages, system_prompt, ctx) -> Iterator[str]`: falls back to the next model only before the first token.
  - `classify_error(exc: Exception, daily_cap_pattern: str) -> Outcome`, exercised by a test with the exception types the `openrouter` SDK raises (read them from the installed package before writing the test).
  - `RouterProvider(router: ModelRouter, purpose: Purpose, ctx: CallContext)`, an `LLMProvider` adapter that exposes `router.invoke(purpose, ...)` as an `LLMProvider` so `OrchestratorAgent(llm=RouterProvider(...))` goes through fallback and logging without changing `src/agents/orchestrator_agent.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_invoke_falls_back_to_next_model_on_rate_limit(): ...       # second model's answer returned, two log records
def test_daily_cap_blocks_service_until_next_reset_and_raises():
    # now = 2026-11-16 15:00 UTC, reset hour 0 -> blocked_until 2026-11-17 00:00 UTC
def test_active_block_raises_quota_exhausted_without_calling_provider(): ...
def test_budget_take_raises_after_limit_and_counts_failed_calls(): ...
def test_models_for_drops_ids_not_in_model_id(): ...
def test_stream_falls_back_before_first_token_only(): ...
def test_every_call_is_logged_with_outcome_and_tokens(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_model_router.py -v`
- [ ] **Step 3: Implement.** `next_reset` is the next `reset_hour_utc:00` strictly after `now`.
- [ ] **Step 4: Run, expect PASS.**

---

### Task 9: Structured LLM output

**Files:**

- Create: `src/planning/llm_json.py`
- Test: `tests/unit/test_llm_json.py`

**Interfaces:**

- Consumes: `ModelRouter.models_for`, `ModelRouter.invoke_model`, `orchestrator_repair_prompt` pattern from `src/core/prompts.py`.
- Produces: `JsonResult[T](value: T, model_id: str)` and `call_json(router: ModelRouter, purpose: Purpose, system_prompt: str, messages: Sequence[Mapping[str, Any]], schema: type[T], check: Callable[[T], list[str]] | None, ctx: CallContext) -> JsonResult[T]`. Per model: call, extract the first JSON object (strip ```` ``` ```` fences, skip leading prose, `json.JSONDecoder().raw_decode` as in `src/orchestration/routing_parser.py`), validate, run `check`; on errors, one repair call that shows the model its answer and the error list; still failing -> next model. All models failing -> `InvalidLLMOutput(errors of the last attempt)`. `QuotaExhausted` and `LLMBudgetExceeded` propagate immediately.
- Produces: `extract_json_object(text: str | None) -> tuple[dict | None, list[str]]` (pure, reused by tests).

- [ ] **Step 1: Write the failing tests**

```python
def test_extracts_json_inside_fences_and_after_prose():
    assert extract_json_object('Sure!\n```json\n{"a": 1}\n```')[0] == {"a": 1}
def test_truncated_json_reports_error_and_repair_succeeds(): ...   # FakeProvider: broken, then valid; 2 calls
def test_semantic_check_errors_trigger_repair_with_those_errors(): ...  # repair prompt contains the error text
def test_second_failure_moves_to_next_model(): ...
def test_all_models_failing_raises_invalid_llm_output(): ...
def test_quota_exhausted_is_not_swallowed(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_llm_json.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 10: Cached HTTP clients: places, exchange rates

**Files:**

- Create: `src/research/cache.py`, `src/research/places.py`, `src/research/exchange_rates.py`
- Test: `tests/unit/test_places.py`, `tests/unit/test_exchange_rates.py`, `tests/fixtures/geocoding_da_lat.json`, `tests/fixtures/er_api_vnd.json`

**Interfaces:**

- Produces in `research.cache`: `Cache` protocol (`get(key) -> dict | None`, `put(key, provider, query, payload, ttl)`) with a DB-backed implementation `DbCache(pool)` over the Task 3 `research` repository; `cache_key(provider: str, query: str, params: Mapping[str, Any]) -> str` (sha256 of provider, casefolded and whitespace-collapsed query, sorted params).
- Produces in `research.places`: `Place(name, admin1, country_code, lat, lon)`, `search_places(client: httpx.Client, cache: Cache, q: str, language: Language) -> list[Place]` calling `https://geocoding-api.open-meteo.com/v1/search` with `name`, `count=10`, `language`; results with a country not in `COUNTRY_CURRENCY` dropped; TTL 30 days.
- Produces in `research.exchange_rates`: `vnd_rate(client, cache, currency: str, today: date) -> tuple[Decimal, date]` calling `https://open.er-api.com/v6/latest/VND`; the response lists units of each currency per 1 VND, so the result is `1 / rates[currency]` VND per unit, with the response's update date. TTL 24 h. Raises `ResearchFailed` when the call fails, `result != "success"`, or the currency is missing.

Before writing fixtures, fetch each endpoint once by hand and save the real response shape (response formats unverified in the spec).

- [ ] **Step 1: Write the failing tests** using `httpx.MockTransport` and an in-memory `Cache` fake:

```python
def test_search_places_maps_results_and_drops_unknown_countries(): ...
def test_search_places_uses_cache_on_second_call(): ...          # transport hit once
def test_vnd_rate_inverts_per_vnd_rate(): ...                    # rates["THB"] = 0.001388 -> ~720.46
def test_vnd_rate_raises_research_failed_for_missing_currency(): ...
def test_cache_key_ignores_case_and_extra_spaces(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_places.py tests/unit/test_exchange_rates.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 11: Weather

**Files:**

- Create: `src/research/weather.py`
- Test: `tests/unit/test_weather.py`, `tests/fixtures/open_meteo_forecast.json`, `tests/fixtures/open_meteo_archive.json`

**Interfaces:**

- Produces: `FORECAST_DAYS = 16`; `weather_for_trip(client, cache, lat: float, lon: float, start: date, end: date, today: date) -> dict[date, Weather]`. Dates up to `today + 15 days` use `https://api.open-meteo.com/v1/forecast` (`basis="forecast"`, TTL 6 h); later dates use `https://archive-api.open-meteo.com/v1/archive` for the same month and day one year earlier (`basis="typical"`, TTL 30 days). Daily fields `temperature_2m_max`, `temperature_2m_min`, `precipitation_sum`, `weather_code`, `timezone=auto`. `summary` is built in code from `weather_code` (a fixed WMO code to text table). A failed call returns `{}` for those dates; it is not an error.

- [ ] **Step 1: Write the failing tests**

```python
def test_trip_crossing_forecast_window_gets_both_bases():
    w = weather_for_trip(..., start=today + timedelta(days=10), end=today + timedelta(days=19), today=today)
    assert {w[d].basis for d in w} == {"forecast", "typical"}
    assert w[today + timedelta(days=15)].basis == "forecast"
    assert w[today + timedelta(days=16)].basis == "typical"
def test_feb_29_falls_back_to_feb_28_last_year(): ...
def test_failed_call_returns_empty_for_those_dates(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_weather.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 12: Web research and the research service

**Files:**

- Create: `src/research/web_research.py`, `src/research/research_service.py`
- Modify: `src/tools/implementations/web_search_tool.py` (description becomes travel search; behavior unchanged)
- Test: `tests/unit/test_web_research.py`, `tests/unit/test_research_service.py`

**Interfaces:**

- Produces in `research.web_research`: `ResearchKind = Literal["accommodation", "transport", "local_transport", "activities", "food"]`; `build_queries(request: TripRequest) -> dict[ResearchKind, str]` (exactly 5; Vietnamese wording when `country_code == "VN"`, English otherwise; `transport` names the requested modes, or none when empty); `tavily_search(client: TavilyClient, cache: Cache, sink: CallSink, query: str, max_results: int, quota_pattern: str, now) -> list[SearchHit]` (cached 24 h; a quota error writes a `tavily` block and raises `QuotaExhausted`); `SearchHit(title, url, content)` with `content` trimmed to `MAX_SNIPPET_CHARS` (builder picks the value).
- Produces in `research.research_service`: `ResearchBundle(currencies: Currencies, weather: Mapping[date, Weather], sources: tuple[SourceRow, ...], failed_kinds: tuple[ResearchKind, ...])`; `run_research(request: TripRequest, trip_id: UUID, deps: ResearchDeps, today: date) -> ResearchBundle`. `ResearchDeps` is a frozen dataclass of callables: `search(query) -> list[SearchHit]`, `weather(lat, lon, start, end, today) -> dict[date, Weather]`, `rate(currency, today) -> tuple[Decimal, date]`, `save_sources(trip_id, kind, hits) -> list[SourceRow]`. Runs the 5 searches, weather and the rate in a `ThreadPoolExecutor`. A failed search goes in `failed_kinds`; all 5 failing raises `ResearchFailed`; a failed rate for a trip abroad raises `ResearchFailed`; `QuotaExhausted` propagates.

- [ ] **Step 1: Write the failing tests**

```python
def test_build_queries_returns_five_kinds_in_vietnamese_for_vn(): ...
def test_build_queries_mentions_only_requested_modes(): ...
def test_partial_search_failure_is_reported_not_raised(): ...
def test_all_searches_failing_raises_research_failed(): ...
def test_missing_rate_abroad_raises_research_failed(): ...
def test_domestic_trip_skips_rate_and_has_no_local_currency(): ...
def test_quota_exhausted_during_search_propagates(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_web_research.py tests/unit/test_research_service.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 13: Plan generator

**Files:**

- Create: `src/planning/plan_generator.py`
- Modify: `src/core/prompts.py` (add `planner_prompt`, `plan_repair_prompt`, `budget_cut_prompt`)
- Test: `tests/unit/test_plan_generator.py`

**Interfaces:**

- Consumes: `call_json`, `check_plan`, `assign_ids`, `over_budget_vnd`, `total_cost_vnd`, `ResearchBundle`.
- Produces: `GeneratedPlan(plan: Plan, model_id: str, total_cost_vnd: Decimal, over_budget: bool)` and `generate_plan(router: ModelRouter, request: TripRequest, research: ResearchBundle, previous: Plan | None, ctx: CallContext) -> GeneratedPlan`.

Behavior: the prompt holds the request, the research sources in `<sources>` tags as numbered data (each `id`, kind, title, url, snippet) with the data-not-instructions rule, the trip language, `previous` when re-planning, and the JSON schema of `Plan` without ids. After `call_json` (check = `check_plan(...).errors`), code overwrites `currencies` and each day's `weather` from `research` (the model never sets them), adds a `missing_research` warning per failed kind, and if `over_budget_vnd > 0` makes one `budget_cut_prompt` call; still over -> keep it and add an `over_budget` warning with the amount. Then `assign_ids`.

- [ ] **Step 1: Write the failing tests** with `FakeProvider` returning fixture JSON:

```python
def test_weather_and_currencies_come_from_research_not_model(): ...
def test_over_budget_triggers_one_cut_call_then_warns(): ...     # 2 LLM calls, warning code "over_budget"
def test_within_budget_makes_a_single_call(): ...
def test_failed_research_kind_adds_missing_research_warning(): ...
def test_sources_are_wrapped_as_data_in_the_prompt(): ...        # recorded message contains "<sources>"
def test_previous_plan_is_included_when_replanning(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_plan_generator.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 14: Generate-plan job and worker

**Files:**

- Create: `src/jobs/generate_plan.py`, `src/jobs/worker.py`, `src/core/logger.py` (replace the stub), `src/db/call_sink.py`
- Test: `tests/integration/test_generate_plan_job.py`, `tests/integration/test_call_sink.py`, `tests/unit/test_logger.py`

**Interfaces:**

- Produces in `core.logger`: `configure_logging(level: str) -> None` (JSON lines: time, level, logger, message, plus `request_id`, `trip_id`, `job_id`, `model_id` from `contextvars`), `log_context(**fields) -> ContextManager[None]`.
- Produces in `db.call_sink`: `DbCallSink(pool)` implementing Task 8's `CallSink` with the `llm_calls` and `quota` repositories, each write in its own short transaction so a failed job does not roll back its call log. Tests: `test_log_call_persists_outcome`, `test_block_then_blocked_until_returns_time`, `test_expired_block_returns_none`.
- Produces in `jobs.generate_plan`: `run_generate_plan(job: JobRow, deps: JobDeps) -> None`. Stages: set trip `researching` and job stage, `run_research`, set `planning`, `generate_plan` with `CallBudget(limit=settings.llm_calls_per_job, used=job.llm_calls_used)`, `save_plan` with the trip's current `plan_revision` and `request=job.request` (null for a first plan or a retry), set trip `ready`, finish job `succeeded`. Always writes the budget's new calls back with `add_llm_calls`.
- Failure handling: `QuotaExhausted` -> trip `failed` with reason `quota_exhausted`, job `failed`, no retry. `LLMBudgetExceeded` -> reason `llm_budget_exceeded`, no retry. `ResearchFailed`, `InvalidLLMOutput`, `LLMUnavailable` -> `requeue` with backoff `30 s x 2^(attempts-1)` while `attempts < max_attempts`, else trip `failed` with reason `generation_failed`. On a re-plan that fails, the trip goes back to `ready` (the current plan still stands) and the failure reason is kept for the UI.
- Produces in `jobs.worker`: `run_worker(deps, worker_id: str, poll_seconds: float, stop: threading.Event) -> None` (lease, run, heartbeat log each minute, runs `cleanup` every 24 h and once at start), entry point `uv run python -m jobs.worker` with SIGTERM setting `stop`.

- [ ] **Step 1: Write the failing tests** (Postgres, fake LLM and fake research deps):

```python
def test_job_turns_queued_trip_into_ready_with_plan_at_revision_1(db_pool, queued_trip): ...
def test_quota_exhausted_fails_trip_without_retry(db_pool, queued_trip): ...
def test_transient_failure_requeues_with_backoff_then_fails_after_max_attempts(db_pool, queued_trip): ...
def test_llm_calls_used_accumulates_across_attempts_and_stops_at_cap(db_pool, queued_trip): ...
def test_failed_replan_keeps_trip_ready_with_old_plan_and_request(db_pool, ready_trip): ...
def test_worker_stops_cleanly_when_stop_event_set(db_pool): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_generate_plan_job.py tests/unit/test_logger.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 15: Cleanup

**Files:**

- Create: `src/jobs/cleanup.py`, add queries to `sql/queries/trips.sql` and `conversations.sql`
- Test: `tests/integration/test_cleanup.py`

**Interfaces:**

- Produces: `run_cleanup(conn, now: datetime, user_inactive_days: int) -> CleanupCounts(trips, conversations, users, cache_rows)`. Deletes trips with `expires_at < now`, users with no trips and `last_seen_at < now - user_inactive_days` (their conversations cascade), and `search_cache` rows past `expires_at`.

- [ ] **Step 1: Write the failing tests:** `test_expired_trip_and_its_rows_are_deleted`, `test_trip_touched_yesterday_is_kept`, `test_inactive_user_without_trips_is_deleted_and_name_freed`, `test_inactive_user_with_a_trip_is_kept`, `test_expired_cache_rows_are_deleted`.
- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_cleanup.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 16: Excel export

**Files:**

- Create: `src/export/xlsx_exporter.py`
- Test: `tests/unit/test_xlsx_exporter.py`

**Interfaces:**

- Consumes: `Plan`, `TripRequest`, `cost_lines`, `CATEGORY_LABELS_VI`, `data/trip-template.xlsx`.
- Produces: `export_plan(template: Path, plan: Plan, request: TripRequest) -> bytes`. Cell mapping exactly as spec "Excel export". Status text by trip language: en `planned`/`booked`/`paid`, vi `Dự kiến`/`Đã đặt`/`Đã thanh toán`. Estimate marker appended to the note: en `(estimate)`, vi `(ước tính)`. Rows past 82: write the column F formula `=IF(E{r}="","",E{r}*$K$8)` and rewrite `Checklist!C2` to `=SUM(Itinerary!E3:E{last})`.

- [ ] **Step 1: Write the failing tests** (open the returned bytes with openpyxl):

```python
def test_domestic_trip_fills_title_currency_headcount():
    ws = load(export_plan(TEMPLATE, DOMESTIC, REQ_VN))["Itinerary"]
    assert (ws["A1"].value, ws["J3"].value, ws["K3"].value, ws["K8"].value) == ("Da Lat TRIP", "VND", 1, 4)
    assert ws["J4"].value is None

def test_abroad_trip_sets_local_currency_and_rate_in_j4_k4(): ...
def test_only_transport_prices_go_in_itinerary_column_e(): ...
def test_vnd_priced_transport_abroad_goes_to_checklist_row_with_vnd_unit(): ...

def test_written_costs_add_up_to_plan_total():
    # sum(Itinerary E x K8 x rate of its currency) + sum(Checklist C x K8 x rate of E) == total_cost_vnd(plan, travelers)

def test_more_than_80_items_extends_formulas_and_checklist_sum(): ...
def test_template_validations_and_currencies_name_survive(): ...
def test_summary_sheet_left_empty(): ...
def test_checklist_overflow_merges_into_khac_row(): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_xlsx_exporter.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 17: Plan editor

**Files:**

- Create: `src/planning/plan_editor.py`
- Modify: `src/core/prompts.py` (add `plan_editor_prompt`)
- Test: `tests/unit/test_plan_editor.py`

**Interfaces:**

- Produces: `compact_plan(plan: Plan) -> str` (one line per item and option with its id; builder picks the format, ids must be visible), `propose_edit(router, request: TripRequest, plan: Plan, history: Sequence[MessageRow], message: str, ctx) -> JsonResult[PlanEdit]`. The `check` passed to `call_json` runs `apply_edit` then `check_plan` and returns `EditRejected.errors` plus rule errors, so a bad edit gets one repair round.

- [ ] **Step 1: Write the failing tests:** `test_valid_edit_is_returned_after_one_call`, `test_edit_with_unknown_id_is_repaired_once`, `test_edit_that_breaks_plan_rules_is_repaired_once`, `test_compact_plan_shows_every_item_and_option_id`.
- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_plan_editor.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 18: Chat service

**Files:**

- Create: `src/chat/events.py`, `src/chat/chat_service.py`, `src/chat/handlers.py`
- Modify: `src/core/prompts.py` (add `plan_answer_prompt`, `travel_advice_prompt`, `trip_research_answer_prompt`)
- Test: `tests/integration/test_chat_service.py`

**Interfaces:**

- Produces in `chat.events`: `ChatEvent(type: Literal["token", "plan", "suggestions", "error", "done"], data: dict)` and `to_sse(event) -> str` (`event: <type>\ndata: <json>\n\n`).
- Produces in `chat.chat_service`: `CATALOG: tuple[AgentSpec, ...]` (`plan_answer`, `plan_editor`, `trip_research`, `travel_advice`, `discover` with the descriptions from spec "Chatting"); `prepare_message(conn, conversation_id, content, trip_id: UUID | None, plan_revision: int | None) -> ChatTurn` (validates before streaming starts: conversation exists; `trip_id`, when given, is a trip of the conversation's user else `NotFound`; `plan_revision`, when given, equals the trip's else `PlanConflict`; saves the user message; touches the conversation and the trip); `stream_reply(turn: ChatTurn, deps: ChatDeps) -> Iterator[ChatEvent]`. Every LLM call of the turn passes `CallContext(trip_id=turn.trip_id, conversation_id=..., message_id=<the user message>)`.
- `stream_reply`: the LLM context holds a summary of every trip of the user plus the request, compact plan and sources of the trip in `trip_id`; classify with `OrchestratorAgent(model_id=..., inference_config=..., llm=RouterProvider(router, "classify", ctx))`; `needs_clarification` -> stream the clarification; `fallback` -> `plan_answer` when `trip_id` is set, else `travel_advice`. `plan_editor` without `trip_id` and `plan_revision` -> a reply asking the visitor to open the trip to change, no LLM edit call; if a job is active -> `error` event code `conflict` ("plan is being regenerated"); else `propose_edit`, `apply_edit`, `save_plan` **before** streaming, then `plan` event (new `plan_revision`), then the explanation and `changed` lines as tokens; `UpdateRequest` -> `enqueue` with the new request in `jobs.request` (the trip columns stay until the new plan lands), `plan` event omitted, reply says re-planning started. `trip_research`: the router step's `task` is the query, 1 search (a second only when the first returns nothing), answer streamed from the hits, hits saved with kind `chat`. `discover` -> yields the events of `run_discovery_turn` (Task 19). Assistant message saved in a `finally` block with the text streamed so far and intent. `QuotaExhausted` -> `error` event code `quota_exhausted` with `blocked_until`.

- [ ] **Step 1: Write the failing tests** (Postgres, FakeProvider scripts the classifier JSON then the answer):

```python
def test_question_streams_answer_and_saves_both_messages(...): ...
def test_trip_of_another_user_raises_not_found_before_streaming(...): ...
def test_edit_without_open_trip_asks_to_open_it(...): ...
def test_discover_intent_runs_discovery_turn(...): ...
def test_llm_calls_carry_the_user_message_id(...): ...
def test_edit_overwrites_plan_before_any_token(...): ...      # first event is "plan"
def test_stale_plan_revision_raises_before_streaming(...): ...
def test_edit_while_job_active_yields_conflict_error_event(...): ...
def test_update_request_queues_replan_job(...): ...
def test_research_searches_once_with_router_task_text(...): ...  # FakeSearch got the step's task string
def test_closing_stream_after_first_token_still_saves_assistant_message(...):
    events = stream_reply(turn, deps); next(events); events.close()
    assert recent_messages(conn, conv_id, 2)[-1].content == FIRST_TOKEN
def test_quota_exhausted_yields_error_event(...): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_chat_service.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 19: Discovery service

**Files:**

- Create: `src/discovery/discovery_service.py`
- Modify: `src/core/prompts.py` (add `discovery_turn_prompt`, `discovery_cards_prompt`)
- Test: `tests/integration/test_discovery_service.py`

**Interfaces:**

- Produces: `RequestDraft` (every `TripRequest` field optional, plus `month: str | None` and `length_days: int | None`), `DiscoveryTurn(action: Literal["ask", "suggest", "answer"], reply: str, request_draft: RequestDraft, queries: tuple[str, ...] (max 3))`, `SuggestionCard(name, country_code, why, length_days, est_cost_per_person_vnd: Decimal, best_months: tuple[str, ...], highlights: tuple[str, ...], source_ids: tuple[int, ...])` (cost always an estimate), `run_discovery_turn(turn: ChatTurn, deps: ChatDeps) -> Iterator[ChatEvent]`, called by `stream_reply` for the `discover` intent (the user message is already saved).
- Behavior per spec "Discovery turn". When the conversation already has 2 `ask` replies and the model asks again, code switches to `suggest` and builds queries from the draft (`discovery_queries(draft: RequestDraft, language) -> tuple[str, ...]`). Cards: `call_json` with a check that drops cards whose country is not in `COUNTRY_CURRENCY` and whose `source_ids` are unknown (removed, not an error), and errors when fewer than 1 card remains. Events: reply tokens, then one `suggestions` event with the cards. Search hits are saved with `save_sources(conversation_id=...)` so card `source_ids` resolve. Draft saved with `save_draft`; message saved with `intent` and `suggestions` in `finally`.

- [ ] **Step 1: Write the failing tests:** `test_ask_turn_makes_one_call_and_saves_draft`, `test_suggest_turn_searches_then_streams_cards`, `test_third_ask_is_turned_into_suggest`, `test_card_with_unknown_country_is_dropped`, `test_answer_turn_makes_no_search`.
- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_discovery_service.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 20: API foundation

**Files:**

- Modify: `src/api/main.py` (becomes `create_app(settings: Settings, deps: AppDeps | None = None) -> FastAPI`)
- Modify: `src/api/routes/health.py` (add `/ready`)
- Create: `src/api/deps.py`, `src/api/errors.py`, `src/api/envelope.py`, `src/api/limits.py`
- Test: `tests/unit/test_limits.py`, `tests/integration/test_api_foundation.py`

**Interfaces:**

- Produces in `api.envelope`: `ErrorBody(code: str, message: str)`, `PageMeta(total, limit, offset)`, `ApiResponse[T](success: bool, data: T | None, error: ErrorBody | None, meta: PageMeta | None)`. This is the coding-style envelope; its `error` carries the spec's `{code, message}` shape.
- Produces in `api.errors`: handlers mapping `NotFound` -> 404 `not_found`, `Conflict`/`PlanConflict` -> 409 `conflict`, `LimitExceeded` -> 429 `rate_limited`, `QuotaExhausted` -> 429 `quota_exhausted` (message includes `blocked_until` ISO time), `RequestValidationError` -> 422 `invalid_request`, anything else -> 500 `internal_error` with a fixed message (logged with the request id, never echoed).
- Produces in `api.limits`: `RateLimiter(per_minute: int, per_day: int, now: Callable[[], datetime])` with `hit(key: str) -> None` raising `LimitExceeded` (token bucket per minute, counter per UTC day); `client_ip(request, trust_proxy_headers: bool) -> str` (first `X-Forwarded-For` entry only when trusted).
- Produces in `api.deps`: `AppDeps` (pool, router, http client, tavily client, limiters, settings) built once in `create_app`; FastAPI dependencies `get_conn`, `limit_api`, `limit_trip_create`, `limit_chat`, `require_quota(kind: Literal["trip", "chat"])` (checks `quota_blocks` and the daily ceilings from settings).
- Middleware: request id (`X-Request-ID` in and out), body size cap 64 KB (413 `payload_too_large`), CORS from `settings.cors_origins`.

- [ ] **Step 1: Write the failing tests:** `test_limiter_allows_burst_then_blocks_within_minute`, `test_limiter_daily_counter_resets_next_utc_day`, `test_client_ip_ignores_forwarded_header_unless_trusted`, `test_unknown_error_returns_500_envelope_without_exception_text`, `test_body_over_64kb_is_rejected_with_413`, `test_ready_returns_503_when_db_unreachable`, `test_active_quota_block_returns_429_quota_exhausted`, `test_new_trip_ceiling_blocks_trips_but_not_chat`.
- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/unit/test_limits.py tests/integration/test_api_foundation.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 21: Users, places, trips, export routes

**Files:**

- Create: `src/api/routes/{users,places,trips,exports}.py`, `src/api/schemas/{users,places,trips}.py`
- Test: `tests/integration/test_api_trips.py`

**Interfaces:**

- Routes and errors exactly as spec "API" for: `POST /users`, `GET /users/{id}`, `GET /users/{id}/trips`, `GET /places`, `POST /trips` (202), `GET /trips/{id}` (includes `status`, job `stage`, `failure_reason`, `plan_revision` and plan), `POST /trips/{id}/retry`, `DELETE /trips/{id}` (204), `GET /trips/{id}/export.xlsx` (`Content-Disposition: attachment; filename="<destination>.xlsx"`, filename ASCII-folded).
- `POST /trips` body: `TripRequest` fields plus `user_id` and optional `conversation_id`; checks per-name and per-IP trip caps and `require_quota("trip")`; creates trip and job in one transaction.

- [ ] **Step 1: Write the failing tests** (TestClient with fake LLM and fake research; the worker function from Task 14 is called directly to finish the job):

```python
def test_create_trip_returns_202_and_trip_becomes_ready_after_job(...): ...
def test_sixth_trip_same_day_same_name_returns_429(...): ...
def test_retry_when_job_active_returns_409(...): ...
def test_export_downloads_xlsx_of_current_plan(...): ...
def test_export_before_ready_returns_409(...): ...
def test_places_requires_two_characters(...): ...
def test_claim_user_twice_returns_same_id(...): ...
```

- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_api_trips.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 22: Conversation routes

**Files:**

- Modify: `src/api/routes/chat.py` (replace its contents: the generic LLM chat goes, conversation routes come in)
- Create: `src/api/schemas/chat.py`
- Test: `tests/integration/test_api_chat.py`

**Interfaces:**

- `POST /conversations` (`{user_id, draft?}`), `GET /users/{id}/conversations`, `GET /conversations/{id}` (messages paged), `POST /conversations/{id}/messages` (`{content, trip_id?, plan_revision?}`). The POST message route runs `limit_chat`, the per-name message cap and `require_quota("chat")`, then `prepare_message` (so 404, 409 and 429 are normal JSON responses), then returns `StreamingResponse(map(to_sse, stream_reply(...)), media_type="text/event-stream")`. `content` 1 to 4000 characters after `clean_text`.

- [ ] **Step 1: Write the failing tests:** `test_chat_post_streams_sse_events_ending_with_done`, `test_chat_with_stale_plan_revision_returns_409_json_not_stream`, `test_chat_over_daily_name_cap_returns_429`, `test_discovery_flow_returns_cards_event`, `test_chat_with_other_users_trip_returns_404`, `test_message_over_4000_chars_returns_422`.
- [ ] **Step 2: Run, expect FAIL** - `uv run pytest tests/integration/test_api_chat.py -v`
- [ ] **Step 3: Implement.**
- [ ] **Step 4: Run, expect PASS.**

---

### Task 23: Run it all together

**Files:**

- Modify: `docker-compose.yml` (add `api`: `uvicorn api.main:app` via a `create_app` factory flag, port 8000; `worker`: `python -m jobs.worker`; both `env_file: .env`, `PYTHONPATH=src`, run `scripts/migrate.py` before start)
- Create: `Dockerfile` (python 3.12 slim, uv sync, no dev deps), `scripts/smoke.py`

**Interfaces:**

- `scripts/smoke.py` (manual, real services, not in the suite): claims a test name, searches a place, creates a 3-day domestic trip, polls until `ready` or `failed` (timeout 5 min), sends one question and one edit, downloads the export, prints each step's result and the LLM and Tavily call counts from `llm_calls` and `search_cache`.

- [ ] **Step 1: Run the full suite** - `uv run pytest -v` -> all pass. `uv run ruff check src tests` -> no errors. `uv run mypy src` -> no errors (or list each remaining error to the user, do not suppress).
- [ ] **Step 2: Start the stack** - `docker compose up -d --build` then `curl -s localhost:8000/ready` -> `{"success":true,...}`.
- [ ] **Step 3: Run the smoke script** with a real `.env` - `uv run python scripts/smoke.py`. Expected: trip reaches `ready`, 1 to 3 LLM calls and at most 5 Tavily calls for creation, the export opens in Excel or LibreOffice with totals matching the API's `total_cost_vnd`. Report the output to the user, including any failure.
