# Gom intent của chat và thẻ hỏi nhu cầu: kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gom 12 giá trị `messages.intent` còn 5 (`advice`, `discover`, `booking_search`, `create_trip`, `edit_plan`), chuyển dữ liệu có cấu trúc sang `messages.metadata`, thay phần hỏi nhu cầu bằng thẻ 6 bước, thêm tìm vé và thẻ hỏi ngày cho tìm khách sạn hoặc vé.

**Architecture:** Router chọn 1 trong 7 agent; code đổi agent thành 1 trong 5 intent và ghi `metadata`. Thẻ hỏi nhu cầu và thẻ hỏi ngày lưu trạng thái trong `metadata`, được cập nhật qua `PATCH` hoặc `POST /chat` với id của thẻ, không đi qua router. Một event SSE `metadata` thay cho `suggestions`, `hotels`, `trip_form`.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3, Postgres 17, pytest; React, TypeScript, TanStack Query, MSW, Vitest.

**Spec:** `docs/2026-11-20-chat-intent-redesign-design.md`

## Global Constraints

- Intent chỉ nhận: `advice`, `discover`, `booking_search`, `create_trip`, `edit_plan` (null cho tin nhắn của khách).
- `messages.suggestions` đổi tên thành `messages.metadata` (jsonb); không thêm cột nào khác vào `messages`.
- Migration mới là `sql/migrations/0004_chat_intent_redesign.sql`; không sửa `0001`-`0003`.
- CHECK trên jsonb dùng `coalesce(..., '')` để `metadata` null không lọt qua.
- ID và URL do code đặt; model không viết URL.
- Lệnh Python chạy với `UV_PROJECT_ENVIRONMENT=../.venv uv run ...`; không tạo `./.venv`. Lint và mypy chỉ chạy trên file đã sửa (`mypy --explicit-package-bases`).
- Frontend: màu chỉ từ token, mọi chuỗi trong `en.json` và `vi.json`, icon Lucide (16px trong chip, 20px trong hàng), không chạy prettier.
- `docs/api.md` cập nhật trong cùng task đổi API.
- Không commit; người dùng tự review và commit.
- Test cũ của hành vi bị bỏ (`ask`, `answer`, `MAX_ASKS`, event `hotels`...) được thay bằng test của hành vi mới, không xóa mà không có thay thế; khi xóa một test, ghi tên nó vào báo cáo của task.

## Review Focus

- Tin nhắn cũ trong DB dev (form đã tạo, gợi ý, khách sạn) phải hiện đúng sau migration: Task 1 có test chuyển dữ liệu từng intent cũ.
- Hai tab cùng trả lời một thẻ hoặc cùng bấm Tìm: lần thứ hai nhận 409, không tạo tin nhắn kết quả thứ hai (Task 4, Task 5).
- Khách bấm Gợi ý luôn ngay bước 1 (draft gần như rỗng): luồng gợi ý vẫn chạy với draft thiếu, không lỗi (Task 4).
- Ngày trong quá khứ, trả phòng trước nhận phòng, hơn 30 đêm: 422 và không tìm (Task 5).
- Router trả agent cũ đã bỏ (`discover_ask`, `hotel_options`...) do model nhớ prompt cũ: rơi về `advice`, không lỗi (Task 3).

---

### Task 1: Migration 0004 và repository tin nhắn

**Files:**
- Create: `sql/migrations/0004_chat_intent_redesign.sql`
- Modify: `sql/queries/messages.sql`, `src/db/repositories/messages.py`
- Test: `tests/integration/test_schema.py`, `tests/integration/test_migration_0004.py` (mới), `tests/integration/test_repositories.py`

**Interfaces:**
- Produces:
  - `MessageRow.metadata: dict[str, Any] | None` (thay `suggestions`).
  - `add_message(conn, conversation_id, role, content, intent=None, metadata: Mapping[str, Any] | None = None) -> MessageRow`.
  - `update_open_metadata(conn, message_id: UUID, expect: Mapping[str, str], metadata: Mapping[str, Any]) -> MessageRow | None`: ghi đè `metadata` chỉ khi mọi cặp `metadata->>key = value` trong `expect` đúng; không khớp trả None. Dùng cho mọi chuyển trạng thái (form `open` sang `created`/`canceled`, thẻ hỏi `open` sang `done`, thẻ ngày `need_dates` sang `done`).
  - `find_open_questionnaire(conn, conversation_id: UUID) -> MessageRow | None`.
  - Bỏ `close_trip_form`, `count_intent`.

- [ ] **Step 1: Viết test schema (thất bại)** trong `tests/integration/test_schema.py`, thay `test_message_accepts_trip_form_intents`, `test_message_accepts_hotel_options_intent`, `test_message_still_rejects_unknown_intent`:

```python
@pytest.mark.parametrize("intent", ["advice", "edit_plan"])
def test_message_accepts_new_intent_without_metadata(db_conn, intent): ...  # insert ok

def test_message_rejects_old_intent(db_conn):  # 'travel_advice' -> CheckViolation

def test_create_trip_message_needs_a_known_status(db_conn):
    # metadata None -> CheckViolation; {"status": "sent"} -> CheckViolation; {"status": "open", "draft": {}, "trip_id": None} -> ok

def test_booking_search_message_needs_kind_and_status(db_conn):
    # {"kind": "train", "status": "results"} -> CheckViolation; {"kind": "flight", "status": "need_dates", "query": "q"} -> ok

def test_discover_message_needs_questionnaire_or_suggestions_kind(db_conn):
    # None -> CheckViolation; {"kind": "questionnaire", ...} -> ok
```

- [ ] **Step 2: Viết test chuyển dữ liệu (thất bại)** `tests/integration/test_migration_0004.py`: tạo schema riêng `mig0004` trên kết nối test, `SET search_path TO mig0004`, chép `0001`-`0003` vào `tmp_path` và chạy `apply_migrations` từ `scripts/migrate.py`, chèn tin nhắn cũ, chép thêm `0004` và chạy lại, rồi kiểm tra; cuối test `DROP SCHEMA mig0004 CASCADE`.

```python
def test_old_intents_map_to_new_intents_and_metadata(db_conn, tmp_path):
    # travel_advice, answer, plan_answer -> ("advice", None)
    # trip_research -> ("advice", {"searched": True})
    # clarification -> ("advice", {"clarify": True})
    # plan_editor -> ("edit_plan", None)
    # ask (content "Bạn đi khi nào?") -> ("discover", {"kind": "questionnaire", "status": "done", "step": 0, "answers": {}, "choices": {}}), content giữ nguyên
    # suggest với suggestions [card] -> ("discover", {"kind": "suggestions", "cards": [card]})
    # hotel_options với suggestions None -> ("booking_search", {"kind": "hotel", "status": "results", "query": "", "dates": None, "cards": []})
    # trip_form content '{"origin": "Hà Nội"}' -> ("create_trip", {"status": "open", "draft": {"origin": "Hà Nội"}, "trip_id": None}), content ""
    # created_trip content '{"origin": "Hà Nội", "trip_id": "<uuid>"}' -> status "created", draft không có trip_id, trip_id "<uuid>"
    # canceled_trip -> status "canceled"
```

- [ ] **Step 3: Chạy để thấy thất bại**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/integration/test_schema.py tests/integration/test_migration_0004.py -v`
Expected: FAIL (CHECK cũ, cột `metadata` chưa có).

- [ ] **Step 4: Viết `0004_chat_intent_redesign.sql`**: bỏ `messages_intent_check` và CHECK mảng của `suggestions`, `RENAME COLUMN suggestions TO metadata`, các `UPDATE` theo bảng ánh xạ trong spec (mục "Migration"), rồi thêm 4 CHECK của spec (mục "Cột metadata").

- [ ] **Step 5: Sửa `messages.sql` và `messages.py`** theo Interfaces: `add_message` ghi `metadata` (dùng `Jsonb`), thêm query `update_open_metadata` (`UPDATE ... WHERE id = %(id)s AND metadata @> %(expect)s RETURNING *`) và `find_open_questionnaire` (`intent = 'discover' AND metadata @> '{"kind": "questionnaire", "status": "open"}'`, mới nhất trước, `LIMIT 1`).

- [ ] **Step 6: Test repository** trong `tests/integration/test_repositories.py`:

```python
def test_update_open_metadata_changes_only_a_matching_row(db_conn, conversation):
    # form {"status": "open"}; update với expect {"status": "open"} -> trả row mới
    # lần hai cùng expect -> None, metadata giữ bản đầu

def test_find_open_questionnaire_returns_the_open_card_only(db_conn, conversation):
    # một thẻ done, một thẻ open -> trả thẻ open; không thẻ open -> None
```

- [ ] **Step 7: Chạy lại, áp migration lên DB dev**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/integration/test_schema.py tests/integration/test_migration_0004.py tests/integration/test_repositories.py -v`
Expected: PASS. Sau đó `PYTHONPATH=src UV_PROJECT_ENVIRONMENT=../.venv uv run python scripts/migrate.py` in `0004_chat_intent_redesign.sql`.

### Task 2: Domain: bộ câu hỏi, ngày đặt chỗ, thẻ vé

**Files:**
- Create: `src/domain/questionnaire.py`, `src/domain/booking.py`, `src/domain/flights.py`
- Test: `tests/unit/test_questionnaire.py`, `tests/unit/test_booking.py`, `tests/unit/test_flights.py`

**Interfaces:**
- Produces (`src/domain/questionnaire.py`):
  - `STEPS: tuple[str, ...] = ("styles", "travelers", "budget", "origin", "when", "length")` (bước n là `STEPS[n - 1]`).
  - `OPTIONS: Mapping[str, tuple[str, ...]]`: id nút của mỗi bước.
  - `answer_for(step: int, choice: str | list[str] | None, typed: Mapping[str, Any], today: date) -> dict[str, Any]`: đổi id nút (hoặc giá trị khách nhập khi `choice` là None) thành các trường của `RequestDraft`; id lạ hoặc giá trị sai kiểu raise `ValueError`.
  - `first_missing_step(draft: Mapping[str, Any]) -> int | None`: bước đầu tiên draft còn thiếu (1-6), None khi đủ.
  - `questionnaire_metadata(draft: Mapping[str, Any]) -> dict[str, Any]`: `{"kind": "questionnaire", "status": "open", "step": first_missing_step - 1, "answers": <các trường của draft thuộc 6 bước>, "choices": {}}`.
- Produces (`src/domain/booking.py`):
  - `class BookingDates(_Frozen)`: `check_in: date | None`, `check_out: date | None`, `depart: date | None`, `return_: date | None` (alias `"return"`).
  - `dates_errors(kind: Literal["hotel", "flight"], dates: BookingDates, today: date) -> list[str]`: thiếu ngày bắt buộc, ngày trong quá khứ, `check_out <= check_in`, quá 30 đêm, `return < depart`.
  - `dates_from(kind, request_draft: Mapping[str, Any] | None, trip: TripRequest | None) -> BookingDates | None`: lấy từ trip trước, rồi draft (`start_date`/`end_date`); thiếu thì None.
- Produces (`src/domain/flights.py`): `FlightCard`, `FlightOptionsReply`, `flight_cards_out(cards, sources) -> list[dict]`, cùng khuôn `src/domain/hotels.py` (trường theo spec mục "Tìm khách sạn và vé máy bay"; `price_from` thay `price_per_night`).

Giá trị của nút (đề xuất, người dùng sẽ sửa; để trong `OPTIONS`/`answer_for`, một chỗ duy nhất):

| Bước | Id nút | Giá trị |
|---|---|---|
| styles | `relax`, `adventure`, `culture`, `food`, `nature`, `nightlife`, `shopping` (chọn nhiều) | `travel_styles` |
| travelers | `1`, `2`, `3_4`, `5_plus` | 1, 2, 4, 5; nhập số thì `typed["travelers"]` |
| budget | `saver`, `moderate`, `comfort`, `premium` | 3.000.000, 6.000.000, 12.000.000, 25.000.000 VND, `budget_scope = per_person`; `saver` thêm style `budget`, `premium` thêm `luxury` |
| origin | `hanoi`, `hcmc`, `danang` | "Hà Nội", "TP. Hồ Chí Minh", "Đà Nẵng"; nơi khác thì `typed["origin"]` |
| when | `this_month`, `next_month`, `holiday_30_4`, `holiday_2_9`, `holiday_new_year`, `christmas` | `month` (tên tháng tiếng Anh từ `today`, hoặc April, September, January, December); chọn ngày thì `typed["start_date"]` |
| length | `2_3`, `4_5`, `week`, `longer` | `length_days` 3, 5, 7, 10 |

- [ ] **Step 1: Viết test (thất bại)**

```python
def test_budget_choice_sets_amount_scope_and_style():
    assert answer_for(3, "premium", {}, TODAY) == {"budget_amount": Decimal("25000000"), "budget_scope": "per_person", "travel_styles": ["luxury"]}

def test_next_month_in_december_is_january():
    assert answer_for(5, "next_month", {}, date(2026, 12, 3)) == {"month": "January"}

def test_typed_travelers_out_of_range_is_rejected():
    with pytest.raises(ValueError): answer_for(2, None, {"travelers": 0}, TODAY)

def test_unknown_choice_is_rejected():
    with pytest.raises(ValueError): answer_for(4, "paris", {}, TODAY)

def test_first_missing_step_skips_what_the_draft_has():
    assert first_missing_step({"travel_styles": ["food"], "travelers": 2}) == 3
    assert first_missing_step(FULL_DRAFT) is None

def test_hotel_dates_need_check_out_after_check_in():
    assert dates_errors("hotel", BookingDates(check_in=D(10), check_out=D(10)), TODAY) != []

def test_hotel_stay_longer_than_30_nights_is_rejected(): ...
def test_flight_needs_only_a_future_depart_date(): ...
def test_dates_from_prefers_the_open_trip_over_the_draft(): ...
def test_flight_cards_with_unknown_sources_are_dropped_and_priced_first(): ...
```

- [ ] **Step 2: Chạy để thấy thất bại**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/unit/test_questionnaire.py tests/unit/test_booking.py tests/unit/test_flights.py -v`
Expected: FAIL (module chưa có).

- [ ] **Step 3: Viết ba module** theo Interfaces. Gộp style: `answer_for` bước 3 trả style thêm vào; người gọi gộp `travel_styles` bằng `merge_draft` sẵn có.

- [ ] **Step 4: Chạy lại**, Expected: PASS. Lint và mypy ba file.

### Task 3: Router 7 agent, 5 intent, event `metadata`

**Files:**
- Modify: `src/chat/chat_service.py`, `src/chat/events.py`, `src/chat/hotel_turn.py`, `src/chat/create_trip_turn.py`, `src/chat/handlers.py`
- Delete: `src/agents/discover_ask_agent.py`, `src/agents/discover_answer_agent.py` (sau Task 4, khi không còn ai import; hỏi người dùng trước khi xóa)
- Test: `tests/integration/test_chat_service.py`

**Interfaces:**
- Consumes: `add_message(..., metadata=...)` (Task 1).
- Produces:
  - `EventType = Literal["token", "plan", "metadata", "error", "done"]`.
  - `metadata_event(message_id: UUID | None, metadata: Mapping[str, Any]) -> ChatEvent` với `data = {"message_id": str | None, "metadata": {...}}`. `message_id` có giá trị khi tin nhắn được lưu trước event (thẻ hỏi, thẻ ngày, form), null khi lưu sau stream (kết quả tìm, gợi ý).
  - `CATALOG` có đúng 7 agent: `advice`, `web_lookup`, `discover`, `hotel_search`, `flight_search`, `create_trip`, `edit_plan`.
  - `AGENT_INTENT: Mapping[str, str]`: agent sang intent; agent lạ rơi về `advice`.
  - `_Reply` có thêm `metadata: dict[str, Any] | None`, lưu cùng tin nhắn trong `stream_reply`.

- [ ] **Step 1: Sửa test (thất bại)** trong `test_chat_service.py`. Đổi tên và kỳ vọng của test cũ theo intent mới, thêm:

```python
def test_plan_question_is_advice_without_metadata(...):  # route("advice") trong trip -> intent "advice", metadata None
def test_web_lookup_searches_and_marks_metadata_searched(...):  # route("web_lookup", "lễ hội Đà Nẵng tháng 7") -> search gọi với task text, intent "advice", metadata {"searched": True}
def test_router_clarification_is_advice_with_clarify_flag(...):  # needs_clarification -> intent "advice", metadata {"clarify": True}
def test_unknown_agent_from_router_falls_back_to_advice(...):  # route("discover_ask") -> intent "advice"
def test_edit_plan_without_open_trip_asks_to_open_it(...):  # intent "edit_plan"
def test_create_trip_saves_form_metadata_and_sends_metadata_event(...):
    # intent "create_trip", content "", metadata {"status": "open", "draft": {...}, "trip_id": None}
    # event metadata có message_id của form
def test_hotel_question_with_dates_streams_cards_in_a_metadata_event(...):
    # trip đang mở có ngày; intent "booking_search", metadata kind "hotel", status "results", dates check_in/check_out của trip, cards có url
```

Test `hotel_question...` cũ (event `hotels`) và `test_classifier_chooses_discover_ask...`, `test_discover_answer...` được thay bằng các test trên và test ở Task 4; ghi tên vào báo cáo.

- [ ] **Step 2: Chạy để thấy thất bại**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/integration/test_chat_service.py -v`

- [ ] **Step 3: Sửa code**: `CATALOG` mô tả 7 agent (mô tả `web_lookup` nói rõ không dùng cho khách sạn, vé, hay câu hỏi về plan đang mở); `_dispatch` ghi `reply.intent = AGENT_INTENT[agent]` và `reply.metadata`; `create_trip_turn` lưu `content = ""`, metadata form, gửi `metadata_event(form.id, ...)`; `hotel_turn` nhận `dates: BookingDates`, đưa ngày vào câu tìm kiếm và prompt, lưu intent `booking_search` với metadata `results`, gửi `metadata_event(None, ...)`. `discover`, `flight_search` và nhánh hỏi ngày tạm gọi stub để Task 4 và Task 5 điền.

- [ ] **Step 4: Chạy lại**, Expected: PASS. Lint và mypy các file đã sửa.

### Task 4: Thẻ hỏi nhu cầu và gợi ý

**Files:**
- Modify: `src/chat/discovery_turn.py`, `src/chat/chat_service.py` (`ChatTurn`, `prepare_message`)
- Create: `src/chat/questionnaire_service.py`
- Test: `tests/integration/test_discovery_turn.py`

**Interfaces:**
- Consumes: `questionnaire_metadata`, `answer_for`, `first_missing_step` (Task 2); `find_open_questionnaire`, `update_open_metadata` (Task 1); `metadata_event` (Task 3).
- Produces:
  - `@dataclass(frozen=True) class FollowUp: message_id: UUID; kind: Literal["discover", "booking"]; dates: BookingDates | None = None; origin: str | None = None`.
  - `ChatTurn.follow_up: FollowUp | None = None`.
  - `class InvalidInput(Exception)` trong `src/core/exceptions.py`, đăng ký handler trong `src/api/errors.py` trả 422 `invalid_request` với thông điệp của exception.
  - `prepare_message(conn, conversation_id, content, trip_id, plan_revision, retention_days=30, follow_up: FollowUp | None = None, today: date | None = None) -> ChatTurn`: tin nhắn đích phải thuộc conversation (không thì `NotFound`), thẻ hỏi phải `open` hoặc thẻ ngày phải `need_dates` (không thì `Conflict`), và với thẻ ngày, `dates_errors(kind, dates, today)` khác rỗng thì `InvalidInput`. Mọi kiểm tra chạy trước khi stream mở, nên lỗi là HTTP 404/409/422, không phải event `error`.
  - `run_discover_turn(turn, deps, call_ctx) -> Iterator[ChatEvent]`: luồng router chọn `discover` (spec bước 1, 2 và mục "Router chọn discover lần nữa").
  - `run_suggest_turn(turn, deps, call_ctx) -> Iterator[ChatEvent]`: khi `turn.follow_up.kind == "discover"`, đóng thẻ (`update_open_metadata` với expect `{"status": "open"}`; None thì `Conflict`), rồi nhánh gợi ý cũ, lưu intent `discover` với `{"kind": "suggestions", "cards": [...]}`.
  - `answer_questionnaire(conn, conversation_id: UUID, message_id: UUID, step: int, choice: str | list[str] | None, typed: Mapping[str, Any], today: date) -> MessageRow` (`questionnaire_service.py`): như spec bước 3; `ValueError` từ `answer_for` thành `InvalidInput` (422), thẻ không `open` thành `Conflict`.

- [ ] **Step 1: Viết test (thất bại)**

```python
def test_discover_opens_a_card_at_the_first_missing_step(...):
    # extract trả {"travelers": 2}; tin nhắn intent "discover", metadata step 0, answers {"travelers": 2}; một event metadata có message_id; không gọi search
def test_discover_with_a_full_draft_suggests_without_a_card(...):
    # draft đủ 6 mục -> search được gọi, tin nhắn {"kind": "suggestions"}, không có thẻ questionnaire
def test_discover_with_an_open_card_closes_it_and_suggests(...):
    # thẻ open có sẵn -> thẻ thành done, một tin nhắn suggestions mới, không thẻ mới
def test_discover_survives_a_failing_extract(...):  # extract raise InvalidLLMOutput -> vẫn mở thẻ
def test_answer_questionnaire_saves_choice_answer_and_draft(...):
    # step 3, choice "saver" -> answers budget_amount 3000000, choices {"3": "saver"}, step 3, request_draft có budget_amount
def test_answer_questionnaire_never_moves_step_back(...):  # trả lời step 4 rồi step 2 -> step vẫn 4
def test_answer_questionnaire_on_a_done_card_conflicts(...)
def test_suggest_follow_up_closes_the_card_and_saves_suggestions(...)
def test_second_suggest_on_the_same_card_conflicts(...)  # prepare_message lần hai -> Conflict
def test_suggest_with_almost_empty_draft_still_suggests(...)  # thẻ step 1 chỉ có styles
```

Test cũ về `ask`, `MAX_ASKS` trong file này được thay bằng các test trên; ghi tên vào báo cáo.

- [ ] **Step 2: Chạy để thấy thất bại**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/integration/test_discovery_turn.py -v`

- [ ] **Step 3: Viết code** theo Interfaces. Bước tách thông tin dùng `CreateTripAgent` (như `create_trip_turn`), bỏ `destination`/`destination_name`. Bỏ `MAX_ASKS`, nhánh `ask`/`answer`; xóa `discover_ask_agent.py`, `discover_answer_agent.py` và prompt của chúng sau khi hỏi người dùng.

- [ ] **Step 4: Chạy lại** cùng lệnh và `tests/integration/test_chat_service.py`, Expected: PASS. Lint và mypy.

### Task 5: Hỏi ngày và tìm vé

**Files:**
- Create: `src/chat/booking_turn.py`, `src/agents/flight_options_agent.py`
- Modify: `src/chat/hotel_turn.py` (gom vào `booking_turn.py` nếu gọn hơn), `src/core/prompts.py` (`flight_options_prompt`), `src/chat/chat_service.py`
- Test: `tests/integration/test_chat_service.py`

**Interfaces:**
- Consumes: `BookingDates`, `dates_from`, `dates_errors`, `flight_cards_out` (Task 2); `FollowUp` (Task 4).
- Produces:
  - `run_booking_turn(data, turn, deps, call_ctx, kind: Literal["hotel", "flight"], query: str) -> Iterator[ChatEvent]`: `dates_from(...)` có thì tìm; thiếu thì lưu thẻ `{"kind", "status": "need_dates", "query"}` với `content` cố định theo ngôn ngữ, gửi `metadata_event(id, ...)`. Vé còn cần `origin` (trip, draft); thiếu thì cũng hỏi.
  - `run_booking_follow_up(data, turn, deps, call_ctx) -> Iterator[ChatEvent]`: ngày đã được `prepare_message` kiểm tra; đóng thẻ (`expect {"status": "need_dates"}`, None thì `Conflict`), ghi ngày (và `origin`) vào draft khi draft chưa có, rồi tìm với `query` của thẻ.
  - `FlightOptionsAgent(router).run(content, call_ctx) -> FlightOptionsReply`, purpose `"answer"`, khuôn `HotelOptionsAgent`.

- [ ] **Step 1: Viết test (thất bại)**

```python
def test_hotel_question_without_dates_saves_a_need_dates_card(...):
    # không trip, draft rỗng -> không search, tin nhắn metadata {"kind": "hotel", "status": "need_dates", "query": <router task>}, event metadata có message_id
def test_hotel_question_reads_dates_from_the_draft(...)
def test_booking_follow_up_searches_with_the_chosen_dates_and_closes_the_card(...):
    # search query chứa ngày; thẻ cũ done; tin nhắn mới status "results", dates đúng; draft có start_date
def test_booking_follow_up_with_past_dates_is_rejected_before_search(...)  # prepare_message raise InvalidInput, search không được gọi, thẻ vẫn need_dates
def test_second_booking_follow_up_on_the_same_card_conflicts(...)
def test_flight_question_searches_transport_sites_and_streams_flight_cards(...):
    # search task "transport", sources kind "transport", metadata kind "flight", cards có url, có giá xếp trước
def test_flight_question_without_origin_asks_for_it(...)
```

- [ ] **Step 2: Chạy để thấy thất bại**, lệnh như Task 3.
- [ ] **Step 3: Viết code** theo Interfaces.
- [ ] **Step 4: Chạy lại**, Expected: PASS. Lint và mypy.

### Task 6: API và `docs/api.md`

**Files:**
- Modify: `src/api/schemas/chat.py`, `src/api/routes/chat.py`, `src/api/routes/trips.py`, `docs/api.md`, `docs/chat-intents.md`
- Test: `tests/integration/test_api_chat.py`, `tests/integration/test_api_trips.py`

**Interfaces:**
- Consumes: `answer_questionnaire` (Task 4), `FollowUp`, `prepare_message(..., follow_up=)` (Task 4), `update_open_metadata` (Task 1).
- Produces:
  - `MessageOut.metadata: dict[str, Any] | None` (bỏ `suggestions`).
  - `CancelFormBody(status: Literal["canceled"])`, `AnswerQuestionBody(step: int = Field(ge=1, le=6), choice: str | list[str] | None = None, answers: dict[str, Any] = {})`; route `PATCH` nhận `CancelFormBody | AnswerQuestionBody`.
  - `SendMessageBody` thêm `discover_message_id: UUID | None`, `booking_message_id: UUID | None`, `dates: BookingDates | None`, `origin: PlaceText | None`; validator: hai id không cùng lúc, `booking_message_id` cần `dates`.
  - `POST /trips` với `message_id`: `update_open_metadata(expect {"status": "open"}, {"status": "created", "draft": request, "trip_id": str(trip.id)})`.

- [ ] **Step 1: Viết test (thất bại)**

```python
def test_get_conversation_returns_metadata_not_suggestions(...)
def test_patch_cancels_an_open_form(...)  # 200, metadata.status "canceled"
def test_patch_cancel_on_a_created_form_conflicts(...)  # 409
def test_patch_answers_a_questionnaire_step(...)  # 200, metadata.choices["2"] == "2"
def test_patch_with_an_unknown_choice_is_422(...)
def test_patch_answer_on_a_form_message_conflicts(...)  # sai loại -> 409
def test_chat_with_both_follow_up_ids_is_422(...)
def test_chat_booking_follow_up_without_dates_is_422(...)
def test_chat_follow_up_on_another_conversation_is_404(...)
def test_create_trip_from_form_sets_created_and_trip_id(...)  # test_api_trips.py
```

- [ ] **Step 2: Chạy để thấy thất bại**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/integration/test_api_chat.py tests/integration/test_api_trips.py -v`

- [ ] **Step 3: Viết code**, rồi cập nhật `docs/api.md` (intent, `metadata` theo bảng của spec, hai dạng body `PATCH`, trường mới của `POST /chat`, event `metadata` thay ba event cũ) và `docs/chat-intents.md` (5 intent, 7 agent).
- [ ] **Step 4: Chạy toàn bộ backend**

Run: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest`
Expected: tất cả PASS. Lint và mypy các file đã sửa trong Task 1-6.

### Task 7: Frontend: kiểu dữ liệu, stream, hiển thị theo metadata

**Files:**
- Modify: `frontend/src/api/api.types.ts`, `frontend/src/api/conversations.ts`, `frontend/src/chat/useChatStream.ts`, `frontend/src/components/ChatPanel.tsx`, `frontend/src/components/ChatTripForm.tsx`, `frontend/src/components/ChatTripProgress.tsx`, `frontend/src/components/ChatTripCanceled.tsx`, `frontend/src/mocks/handlers.ts`, `frontend/src/mocks/chatScript.ts`, `frontend/src/mocks/fixtures.ts`
- Test: `frontend/src/components/ChatPanel.test.tsx`, `frontend/src/chat/useChatStream.test.tsx`, `frontend/src/mocks/handlers.test.ts`

**Interfaces:**
- Consumes: API của Task 6.
- Produces:
  - `MessageIntent = "advice" | "discover" | "booking_search" | "create_trip" | "edit_plan"`.
  - `MessageMetadata` union: `AdviceMeta`, `QuestionnaireMeta`, `SuggestionsMeta`, `BookingMeta` (`need_dates` | `done` | `results`), `TripFormMeta`; `Message.metadata: MessageMetadata | null`.
  - `ChatEvent` có `{ type: "metadata"; data: { message_id: string | null; metadata: MessageMetadata } }`, bỏ `suggestions`, `hotels`, `trip_form`.
  - Trạng thái stream: `metadata: { messageId: string | null; value: MessageMetadata } | null`.
  - `cancelTripForm(conversationId, messageId)` gửi `{ status: "canceled" }`; thêm `answerQuestion(conversationId, messageId, body)`.
  - Trong `ChatPanel`, một hàm `renderMetadata(message)` dùng cho cả tin nhắn đã lưu và đang stream.

- [ ] **Step 1: Sửa test (thất bại)**: các test ChatPanel hiện có (form tạo trip, thẻ đã hủy, thẻ gợi ý, slider khách sạn) đổi fixture sang `metadata` và vẫn kỳ vọng cùng hiển thị; thêm `old_hotel_message_from_the_migration_shows_the_slider` (metadata `results`, `query ""`, `dates null`).
- [ ] **Step 2: Chạy để thấy thất bại**: `cd frontend && npm test -- src/components/ChatPanel.test.tsx src/chat/useChatStream.test.tsx src/mocks/handlers.test.ts`
- [ ] **Step 3: Sửa code** theo Interfaces; `ChatTripForm` đọc `metadata.draft`, thẻ đã tạo đọc `metadata.trip_id`.
- [ ] **Step 4: Chạy lại**, Expected: PASS; `npm run lint && npm run typecheck`.

### Task 8: Frontend: thẻ hỏi nhu cầu, thẻ ngày, thẻ vé

**Files:**
- Create: `frontend/src/components/DiscoverQuestionnaire.tsx`, `frontend/src/components/BookingDates.tsx`, `frontend/src/components/FlightCard.tsx`
- Modify: `frontend/src/components/HotelSlider.tsx` (thành `CardSlider` nhận `children` hoặc danh sách thẻ, đổi tên file nếu đổi tên component), `frontend/src/components/ChatPanel.tsx`, `frontend/src/i18n/en.json`, `frontend/src/i18n/vi.json`, mocks
- Test: `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: `answerQuestion`, `MessageMetadata`, `sendMessage` với `discover_message_id` hoặc `booking_message_id` (Task 7).
- Produces: `DiscoverQuestionnaire({ conversationId, message })`, `BookingDates({ conversationId, message })`, `FlightCard({ flight })`.

- [ ] **Step 1: Viết test (thất bại)**

```ts
it("questionnaire_shows_the_first_missing_step_and_saves_a_choice")  // bấm "2" ở bước 2 -> PATCH {step: 2, choice: "2"}, hiện bước 3
it("questionnaire_back_shows_the_previous_answer_selected")
it("questionnaire_suggest_now_sends_the_card_id_and_shows_destination_cards")
it("done_questionnaire_after_reload_shows_the_chosen_labels")  // "Tiết kiệm", "3-4 người"
it("hotel_question_without_dates_shows_date_inputs_then_hotel_cards")  // nhập ngày, bấm Tìm -> POST /chat có booking_message_id và dates, slider hiện
it("booking_dates_with_check_out_before_check_in_shows_an_error_and_sends_nothing")
it("flight_cards_show_route_carrier_price_and_source_link")
```

- [ ] **Step 2: Chạy để thấy thất bại**: `cd frontend && npm test -- src/components/ChatPanel.test.tsx`
- [ ] **Step 3: Viết component**: chip theo recipe choice chip của `frontend/CLAUDE.md`, ngày bằng `<input type="date">` như `TripForm`, nơi xuất phát bằng `PlaceSearch`; mọi chuỗi vào `en.json`/`vi.json`.
- [ ] **Step 4: Chạy toàn bộ frontend**

Run: `cd frontend && npm test && npm run lint && npm run typecheck && npm run build`
Expected: tất cả PASS. Grep `frontend/src` không có `#` màu hoặc `rgb(`.
