# Tạo trip trong chat: kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Chat nhận ra ý định tạo trip, trả về một tin nhắn chứa form điền sẵn từ lịch sử chat, cho người dùng tạo hoặc hủy, rồi hiện tiến độ tạo plan ngay tại tin nhắn đó, còn nguyên khi tải lại trang.

**Architecture:** Một agent `create_trip` mới trong bộ phân loại chạy 1 lần gọi LLM để rút `RequestDraft` từ lịch sử, code tìm tọa độ điểm đến, rồi lưu một tin nhắn assistant `intent='trip_form'` với `content` là JSON của draft. `POST /trips` nhận thêm `message_id` và chuyển tin nhắn sang `created_trip` trong cùng transaction; `PATCH` tin nhắn chuyển sang `canceled_trip`. Frontend render tin nhắn theo `intent` và poll trip như trang trip.

**Tech Stack:** Python 3.12, FastAPI, psycopg 3 (không ORM), pytest; React + TypeScript, TanStack Query, MSW, Vitest, Tailwind v4.

**Spec:** `docs/2026-11-20-chat-create-trip-design.md`

## Global Constraints

- Không thêm cột vào `messages`; dữ liệu form ở `messages.content` dạng chuỗi JSON, trạng thái ở `messages.intent`.
- Ba intent mới, đúng chính tả: `trip_form`, `created_trip`, `canceled_trip`.
- Schema đổi bằng file mới `sql/migrations/0002_trip_form_intents.sql`, không sửa `0001_init.sql`.
- Query mới viết trong `sql/queries/<area>.sql` dạng `-- name: <query_name>`.
- Tọa độ điểm đến do code đặt (`search_places`), không do model.
- Chỉ chuyển được từ `trip_form`; chuyển lần hai trả 409 `conflict`.
- Hết quota AI (`QuotaExhausted`, `LLMBudgetExceeded`) thì trả sự kiện `error`, không lưu tin nhắn; lỗi model khác vẫn hiện form từ draft cũ và mặc định.
- Sau khi tạo trip từ form, `conversations.request_draft` về `NULL` trong cùng transaction.
- Lệnh chạy: `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest ...`; ruff và mypy chỉ chạy trên file đã sửa. Frontend: `npm test`, `npm run lint`, `npm run typecheck` trong `frontend/`.
- UI theo `frontend/CLAUDE.md`: chỉ dùng token và recipe trong `src/styles/recipes.ts`, có cả dark mode, chuỗi mới ở cả `en.json` và `vi.json`.
- Không dùng em dash hay dấu ngoặc cong trong code, copy và docs.

## Review Focus

- Hai tab cùng bấm "Tạo kế hoạch" trên một form: chỉ một trip được tạo, request thứ hai trả 409 và không để lại trip hay job (Task 6).
- Trip đã tạo rồi bị xóa: tin nhắn hiện "Chuyến đi này đã bị xóa" thay vì lỗi hoặc spinner mãi (Task 8).
- `content` của tin nhắn form không phải JSON hợp lệ (dữ liệu cũ, sửa tay): thread vẫn hiện, tin nhắn đó hiện dòng lỗi chung (Task 8).
- Model trả tên điểm đến không tìm được hoặc ở nước không hỗ trợ: form vẫn hiện, ô điểm đến trống (Task 5).
- Mô hình bịa ngày khi người dùng chỉ nói "3 ngày 2 đêm": ngày trong quá khứ không được giữ trong draft (Task 4).

---

### Task 1: Migration cho 3 intent mới

**Files:**
- Create: `sql/migrations/0002_trip_form_intents.sql`
- Test: `tests/integration/test_schema.py`

**Interfaces:**
- Produces: `messages.intent` chấp nhận `trip_form`, `created_trip`, `canceled_trip`.

- [x] **Step 1: Viết test lỗi**

```python
@pytest.mark.parametrize("intent", ["trip_form", "created_trip", "canceled_trip"])
def test_message_accepts_trip_form_intents(db_conn, intent):
    user = users.claim_user(db_conn, "Duy")
    conv = conversations.create_conversation(db_conn, user.id, None)
    row = messages.add_message(db_conn, conv.id, "assistant", "{}", intent)
    assert row.intent == intent

def test_message_still_rejects_unknown_intent(db_conn):
    # add_message with intent "nope" raises psycopg.errors.CheckViolation
```

- [x] **Step 2: Chạy, thấy fail** - `UV_PROJECT_ENVIRONMENT=../.venv uv run pytest tests/integration/test_schema.py -k intent -v`, expected: CheckViolation ở 3 case đầu.
- [x] **Step 3: Viết migration**: `ALTER TABLE messages DROP CONSTRAINT messages_intent_check, ADD CONSTRAINT messages_intent_check CHECK (intent IN (<8 giá trị cũ>, 'trip_form', 'created_trip', 'canceled_trip'));`. Kiểm tra tên constraint thật bằng `\d messages` trước khi viết.
- [x] **Step 4: Chạy lại, thấy pass**; chạy thêm `test_migrate_is_idempotent`.

### Task 2: Repository cho tin nhắn form và draft

**Files:**
- Modify: `sql/queries/messages.sql`, `src/db/repositories/messages.py`
- Modify: `sql/queries/conversations.sql`, `src/db/repositories/conversations.py`
- Test: `tests/integration/test_repositories.py`

**Interfaces:**
- Consumes: Task 1.
- Produces:
  - `messages.get_message(conn, message_id: UUID) -> MessageRow` (raise `NotFound`).
  - `messages.close_trip_form(conn, message_id: UUID, intent: Literal["created_trip", "canceled_trip"], content: str | None) -> MessageRow | None`: `UPDATE ... SET intent = %(intent)s, content = COALESCE(%(content)s, content) WHERE id = %(id)s AND intent = 'trip_form' RETURNING *`; trả `None` khi không còn là `trip_form`.
  - `conversations.clear_draft(conn, conversation_id: UUID) -> None`.

- [x] **Step 1: Viết test lỗi**: `test_close_trip_form_moves_open_form_to_created`, `test_close_trip_form_returns_none_when_already_closed` (gọi hai lần, lần hai là `None`, intent vẫn là giá trị đầu), `test_close_trip_form_keeps_content_when_none_given`, `test_get_unknown_message_raises_not_found`, `test_clear_draft_sets_request_draft_to_null`.
- [x] **Step 2: Chạy, thấy fail** vì hàm chưa có.
- [x] **Step 3: Viết query và hàm** theo mẫu `add_message` / `save_draft`.
- [x] **Step 4: Chạy, thấy pass.**

### Task 3: Dòng ngắn thay JSON trong lịch sử gửi cho LLM

**Files:**
- Create: `src/chat/history.py` (file riêng vì `chat.handlers` đã import `planning.plan_editor`, đặt ở đó sẽ tạo vòng import)
- Modify: `src/chat/handlers.py:151` (`conversation_text`), `src/chat/chat_service.py:198` (`_classify`), `src/planning/plan_editor.py:102`
- Test: `tests/unit/test_trip_form_history.py`

**Interfaces:**
- Produces: `TRIP_FORM_INTENTS: frozenset[str]` và `message_for_model(message: MessageRow) -> str` trong `src/chat/history.py`. Tin nhắn thường trả `content`; tin nhắn form trả `[trip form: <destination.name hoặc ?>, <start_date to end_date | length_days days | no dates>, <open | created | canceled>]`; JSON hỏng trả `[trip form]`.

- [x] **Step 1: Viết test lỗi**

```python
def test_plain_message_is_its_content(): ...
def test_open_form_names_place_and_length():
    m = row(intent="trip_form", content=json.dumps({"destination": {"name": "Hải Phòng", ...}, "length_days": 3}))
    assert message_for_model(m) == "[trip form: Hải Phòng, 3 days, open]"
def test_created_form_with_dates():
    assert message_for_model(m) == "[trip form: Hải Phòng, 2026-12-01 to 2026-12-03, created]"
def test_form_without_destination_uses_question_mark(): ...  # "[trip form: ?, no dates, canceled]"
def test_broken_json_gives_bare_marker(): ...  # "[trip form]"
```

- [x] **Step 2: Chạy, thấy fail.**
- [x] **Step 3: Viết `message_for_model`**, dùng nó trong `conversation_text`, `_classify` và `plan_editor`.
- [x] **Step 4: Chạy test này và `tests/unit/test_plan_editor.py`, `tests/integration/test_chat_service.py`, thấy pass.**

### Task 4: Agent rút thông tin cho form

**Files:**
- Modify: `src/domain/discovery.py` (model mới), `src/core/prompts.py` (`create_trip_prompt`)
- Create: `src/agents/create_trip_agent.py`
- Test: `tests/unit/test_discover_agents.py`

**Interfaces:**
- Produces:
  - `class TripFormExtract(RequestDraft)` với thêm `destination_name: PlaceText | None = None`; `HIDDEN_FIELDS` thêm `"TripFormExtract": {"destination"}`.
  - `CreateTripAgent(router).run(draft: Mapping[str, Any], today: date, conversation: str, message: str, ctx: CallContext) -> TripFormExtract`, purpose `"discover"`, dùng `discovery_content` và `call_json` như `DiscoverAskAgent`.
  - `drop_past_dates(extract: TripFormExtract, today: date) -> TripFormExtract`: bỏ `start_date`/`end_date` khi `start_date < today`.
- `create_trip_prompt` nói rõ: chỉ ghi những gì người dùng đã nói; không đoán ngày; "N ngày M đêm" thành `length_days = N`; `destination_name` là một thành phố hoặc vùng, không phải quốc gia khi người dùng đã nêu thành phố; trả JSON theo `{schema}`.

- [x] **Step 1: Viết test lỗi**: `test_create_trip_agent_makes_one_discover_call_and_returns_the_extract` (FakeProvider trả `{"destination_name": "Hải Phòng", "length_days": 3, "origin": "Hà Nội"}`), `test_create_trip_prompt_hides_destination_and_shows_destination_name`, `test_drop_past_dates_removes_dates_before_today`, `test_drop_past_dates_keeps_future_dates`.
- [x] **Step 2: Chạy, thấy fail.**
- [x] **Step 3: Viết model, prompt, agent.**
- [x] **Step 4: Chạy, thấy pass**; ruff + mypy trên 3 file đã sửa.

### Task 5: Lượt chat `create_trip`

**Files:**
- Create: `src/chat/create_trip_turn.py`
- Modify: `src/chat/chat_service.py` (CATALOG, `ChatDeps`, `_dispatch`), `src/chat/events.py` (`EventType` thêm `"trip_form"`), `src/api/routes/chat.py` (`get_chat_deps`)
- Modify: `tests/integration/test_chat_service.py:99`, `tests/integration/test_discovery_turn.py:83` (tham số mới của `ChatDeps`)
- Test: `tests/integration/test_create_trip_turn.py`

**Interfaces:**
- Consumes: Task 2, 3, 4.
- Produces:
  - `ChatDeps` thêm trường cuối `places: Callable[[str, Language], list[Place]]`; `get_chat_deps` truyền `lambda q, lang: search_places(deps.http, DbCache(deps.pool), q, lang)`.
  - `AgentSpec(name="create_trip", description=...)`: người dùng muốn lập kế hoạch hoặc lịch trình cho một chuyến mới ngay bây giờ; không dùng khi người dùng còn đang chọn điểm đến hoặc muốn sửa trip đang mở.
  - `run_create_trip_turn(turn: ChatTurn, deps: ChatDeps) -> Iterator[ChatEvent]`: phát đúng một `ChatEvent("trip_form", {"message_id": str, "draft": dict})`, không có token.

Luồng: đọc conversation và lịch sử như `run_discovery_turn`; gọi agent; `QuotaExhausted`/`LLMBudgetExceeded` để rơi lên (thành `error`), `InvalidLLMOutput`/`LLMUnavailable` thì dùng extract rỗng. Bỏ ngày quá khứ. Nếu có `destination_name`, gọi `deps.places(name, "vi" nếu tin nhắn có dấu tiếng Việt, ngược lại "en")`, lấy kết quả đầu thành `Destination`; `ResearchFailed` hoặc rỗng thì không có destination. `draft = merge_draft(known, extract_không_có_destination_name)` cộng destination. Lưu draft, lưu tin nhắn `("assistant", json.dumps(draft, ensure_ascii=False), "trip_form")`, rồi phát sự kiện.

- [x] **Step 1: Viết test lỗi**

```python
def test_create_trip_turn_saves_form_message_and_emits_trip_form_event(...):
    # script: classifier routes to create_trip, agent returns destination_name "Hải Phòng", length_days 3
    # places double returns one VN place
    # events == [("trip_form", {"message_id": <id>, "draft": {...destination with lat/lon..., "length_days": 3}}), ("done", {})]
    # last message: intent "trip_form", json.loads(content) == event draft
    # conversation.request_draft == event draft
def test_unknown_destination_leaves_destination_out(...)      # places returns []
def test_geocoder_failure_leaves_destination_out(...)          # places raises ResearchFailed
def test_invalid_model_output_still_gives_form_from_old_draft(...)  # saved draft {"travelers": 4} -> event draft travelers 4
def test_quota_exhausted_sends_error_and_saves_no_message(...)
def test_vietnamese_message_searches_places_in_vietnamese(...)
```

- [x] **Step 2: Chạy, thấy fail.**
- [x] **Step 3: Viết `create_trip_turn.py`, nối vào `_dispatch` (`if agent == "create_trip": yield from run_create_trip_turn(turn, deps); return`, trước `reply.intent = agent`).**
- [x] **Step 4: Chạy file test mới và toàn bộ `tests/integration/test_chat_service.py`, `test_discovery_turn.py`, `test_api_chat.py`, thấy pass.**

### Task 6: API tạo và hủy từ form

**Files:**
- Modify: `src/api/schemas/trips.py` (`CreateTripBody.message_id: UUID | None = None`), `src/api/routes/trips.py`
- Modify: `src/api/schemas/chat.py` (`CloseTripFormBody`), `src/api/routes/chat.py`
- Modify: `docs/api.md`
- Test: `tests/integration/test_api_trips.py`, `tests/integration/test_api_chat.py`

**Interfaces:**
- Consumes: Task 2.
- Produces:
  - `POST /trips` với `message_id`: request của trip là `body.model_dump(mode="json", exclude={"user_id", "message_id"})`. Sau khi tạo trip và job: `get_message`, rồi `get_conversation(message.conversation_id).user_id != body.user_id` thì `NotFound`; `close_trip_form(conn, message_id, "created_trip", json.dumps({**request, "trip_id": str(trip.id)}, ensure_ascii=False))` trả `None` thì `Conflict("This form was already used")`; `clear_draft`. Một `conn.commit()` ở cuối; lỗi giữa chừng thì không commit gì.
  - `PATCH /conversations/{conversation_id}/messages/{message_id}` body `CloseTripFormBody(intent: Literal["canceled_trip"])`, trả `ApiResponse[MessageOut]` 200. Tin nhắn không thuộc conversation thì 404; không còn là `trip_form` thì 409.

- [x] **Step 1: Viết test lỗi**: `test_create_trip_from_form_marks_message_created_with_trip_id`, `test_create_trip_from_form_clears_conversation_draft`, `test_create_trip_twice_from_one_form_returns_409_and_keeps_one_trip` (đếm `trips.count_trips(user)` = 1 sau lần hai), `test_create_trip_from_other_users_form_returns_404_and_creates_nothing`, `test_create_trip_message_id_is_not_stored_in_the_request`, `test_cancel_trip_form_returns_canceled_message`, `test_cancel_after_create_returns_409`, `test_cancel_message_of_other_conversation_returns_404`, `test_cancel_with_other_intent_returns_422`.
- [x] **Step 2: Chạy, thấy fail.**
- [x] **Step 3: Viết schema và route.**
- [x] **Step 4: Chạy, thấy pass**; ruff + mypy trên file đã sửa.
- [x] **Step 5: Cập nhật `docs/api.md`**: trường `message_id` của `POST /trips`, endpoint PATCH mới, sự kiện SSE `trip_form`, 3 intent mới.

### Task 7: Frontend, lớp API và mock

**Files:**
- Modify: `frontend/src/api/api.types.ts`, `frontend/src/api/conversations.ts`, `frontend/src/api/trips.ts`, `frontend/src/chat/useChatStream.ts`
- Modify: `frontend/src/mocks/handlers.ts`, `frontend/src/mocks/chatScript.ts`, `frontend/src/mocks/mockDb.ts` nếu cần
- Test: `frontend/src/chat/useChatStream.test.tsx`

**Interfaces:**
- Produces:
  - `MessageIntent` thêm 3 giá trị; `CHAT_EVENT_TYPES` thêm `"trip_form"`; `ChatEvent` thêm `{ type: "trip_form"; data: { message_id: string; draft: RequestDraft } }`; `CreateTripBody.message_id?: string`.
  - `type TripFormContent = RequestDraft & { trip_id?: string }` và `parseTripForm(content: string): TripFormContent | null` (JSON hỏng hoặc không phải object trả `null`).
  - `useCloseTripForm()` mutation gọi PATCH rồi invalidate `conversationKeys.detail(conversationId)`.
  - `ChatState` streaming thêm `hasTripForm: boolean`; sự kiện `trip_form` đặt nó `true` (tin nhắn thật đến từ refetch sau `done`).
  - Mock: `/chat` trả sự kiện `trip_form` khi nội dung chứa "plan trip" hoặc "tạo plan", lưu tin nhắn `trip_form`; `POST /trips` với `message_id` chuyển tin nhắn sang `created_trip`, lần hai trả 409; PATCH mới.

- [x] **Step 1: Viết test lỗi**: `trip_form_event_sets_has_trip_form`, `parseTripForm_returns_null_for_broken_json`, `parseTripForm_reads_trip_id`.
- [x] **Step 2: Chạy `npm test -- useChatStream`, thấy fail.**
- [x] **Step 3: Viết type, parser, hook, mock.**
- [x] **Step 4: Chạy, thấy pass**; `npm run typecheck`.

### Task 8: Frontend, form và tiến độ trong chat

**Files:**
- Create: `frontend/src/components/ChatTripForm.tsx`, `frontend/src/components/ChatTripProgress.tsx`
- Modify: `frontend/src/components/TripForm.tsx` (`onGetIdeas?`, thêm `onCancel?`), `frontend/src/components/ChatPanel.tsx`, `frontend/src/i18n/en.json`, `frontend/src/i18n/vi.json`
- Modify: `frontend/ui-component-principles.md` nếu thay đổi đụng vào chat input
- Test: `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: Task 7.
- Produces:
  - `ChatTripForm({ conversationId, message }: { conversationId: string; message: Message })`: lời dẫn i18n `chat.tripForm.intro`, rồi `TripForm` với `initialValues={fromDraft(parsed, null)}`, `isBare`, không có `onGetIdeas`, có `onCancel`. Gửi thì `useCreateTrip` với `toCreateTripBody(...)` cộng `message_id`, `onSuccess` invalidate conversation; không chuyển trang.
  - `ChatTripProgress({ tripId }: { tripId: string })`: `useTrip(tripId)`; đang chạy thì `JobProgress`; `ready` thì điểm đến, ngày và link `/trips/{id}` ("Mở chuyến đi"); `failed` thì `JobProgress` với retry qua `useRetryTrip`; lỗi `not_found` thì `chat.tripForm.deleted`.
  - `ChatPanel` chọn theo `intent`: `trip_form` thì `ChatTripForm`; `created_trip` thì `ChatTripProgress` (thiếu `trip_id` thì `deleted`); `canceled_trip` thì một dòng `text-sm text-muted-foreground` `chat.tripForm.canceled`; `parseTripForm` trả `null` thì `chat.tripForm.broken`.
  - Chuỗi i18n mới: `chat.tripForm.intro`, `create`, `cancel`, `canceled`, `deleted`, `broken`, `openTrip`, cả `en` và `vi`.

- [x] **Step 1: Viết test lỗi**: `asking_to_plan_shows_prefilled_form_in_chat` (Destination = "Hải Phòng"), `form_cancel_shows_canceled_line_after_reload` (render lại route, vẫn thấy dòng hủy), `form_create_shows_progress_then_open_trip_link`, `created_form_for_deleted_trip_says_deleted`, `broken_form_content_shows_error_line_and_keeps_thread`, `form_in_chat_has_no_get_ideas_button`.
- [x] **Step 2: Chạy `npm test -- ChatPanel`, thấy fail.**
- [x] **Step 3: Viết component, nối vào ChatPanel, thêm chuỗi.**
- [x] **Step 4: Chạy `npm test`, `npm run lint`, `npm run typecheck`, thấy pass.**
- [ ] **Step 5: Chạy app thật** (`docker compose up -d db`, migrate, uvicorn, worker, `npm run dev`), lặp lại luồng ở screenshot: hỏi Hà Nội - Hải Phòng 3 ngày 2 đêm, rồi "tạo plan trip cho tôi"; xem form điền sẵn, tạo, tiến độ, tải lại trang; kiểm tra cả light và dark.
