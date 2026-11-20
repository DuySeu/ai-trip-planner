# Lựa chọn khách sạn trong chat: kế hoạch triển khai

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** câu hỏi về giá hoặc lựa chọn khách sạn trong chat trả về một câu trả lời ngắn và một slider thẻ khách sạn lấy từ các trang đặt phòng.

**Architecture:** agent mới `hotel_options` trong `CATALOG`; `run_hotel_turn` tìm với task `"accommodation"`, lưu nguồn, gọi model một lần qua `call_json`, stream câu trả lời, gửi event `hotels` và lưu thẻ vào `messages.suggestions` với intent `hotel_options`. Frontend vẽ slider bằng CSS scroll-snap.

**Tech Stack:** FastAPI, psycopg 3, pydantic, Tavily; React + Tailwind v4, Vitest, MSW.

**Spec:** `docs/2026-11-20-chat-hotel-options-design.md`

## Global Constraints

- Model không bao giờ viết URL; `url` của thẻ lấy từ nguồn theo `source_id`.
- Tối đa 6 thẻ (`MAX_HOTEL_CARDS = 6`), tối đa 3 điểm nổi bật mỗi thẻ.
- Không thêm cột, không thêm dependency. Migration mới là `0003_hotel_options_intent.sql`.
- Mọi chuỗi giao diện nằm trong `en.json` và `vi.json`; màu, bo góc, bóng lấy từ token (`frontend/CLAUDE.md`).
- Không dùng em dash, en dash, ngoặc kép cong trong code và tài liệu.

## Review Focus

- Tavily không trả gì: chỉ có câu trả lời chữ, không có event `hotels`, message lưu `suggestions = null`.
- Model trả thẻ với `source_id` không có trong nguồn: thẻ bị bỏ; không còn thẻ nào thì không có slider.
- Model trả JSON hỏng hai lần: lượt chat kết thúc bằng lỗi `invalid_output` như các luồng khác.
- Tải lại trang: slider hiện lại từ `suggestions` của message `hotel_options`.
- Thẻ không có giá: hiện "Chưa có giá" thay cho số 0.

### Task 1: Thẻ khách sạn trong domain và intent mới

**Files:**
- Create: `src/domain/hotels.py`, `sql/migrations/0003_hotel_options_intent.sql`, `tests/unit/test_hotels.py`
- Modify: `tests/integration/test_schema.py`

**Interfaces:**
- Produces: `HotelCard` (name, area, stars: int 1-5 | None, price_per_night: Decimal | None, price_currency: str = "VND", highlights: tuple[str, ...] tối đa 3, source_id: int), `HotelOptionsReply` (reply: str, cards: tuple[HotelCard, ...]), `MAX_HOTEL_CARDS = 6`, `hotel_cards_out(cards, sources: Mapping[int, str]) -> list[dict[str, Any]]` trả các thẻ có `source_id` trong `sources` (tối đa 6, thẻ có giá đứng trước), mỗi thẻ dạng JSON thêm `url`.

- [ ] Test `test_hotel_cards_out_drops_unknown_sources_and_adds_url`, `test_hotel_cards_out_puts_priced_cards_first_and_keeps_six`, `test_hotel_card_rejects_six_stars`.
- [ ] Test `test_message_accepts_hotel_options_intent` trong `test_schema.py`.
- [ ] Viết `src/domain/hotels.py` và migration (thêm `hotel_options` vào `messages_intent_check`), chạy test.

### Task 2: Luồng hotel trong chat

**Files:**
- Create: `src/agents/hotel_options_agent.py`, `src/chat/hotel_turn.py`, `tests/integration/test_hotel_turn.py`
- Modify: `src/core/prompts.py` (`hotel_options_prompt`), `src/chat/events.py` (`"hotels"`), `src/chat/chat_service.py` (CATALOG, `_dispatch`), `tests/integration/test_chat_service.py`, `docs/api.md`

**Interfaces:**
- Consumes: Task 1.
- Produces: `HotelOptionsAgent(router).run(content: str, ctx) -> HotelOptionsReply` (purpose `answer`); `run_hotel_turn(turn, deps, query: str | None) -> Iterator[ChatEvent]` lưu message assistant của chính nó.

- [ ] Test `test_hotel_turn_searches_accommodation_and_streams_cards` (search task là `accommodation`, event cuối là `hotels`, thẻ có `url` của nguồn, message lưu intent `hotel_options` với `suggestions`).
- [ ] Test `test_hotel_turn_without_hits_answers_in_text_only` và `test_hotel_turn_drops_cards_with_unknown_source`.
- [ ] Test `test_hotel_question_routes_to_hotel_options` trong `test_chat_service.py`.
- [ ] Viết prompt, agent, turn, event và định tuyến; chạy test, ruff, mypy trên file đã đổi.

### Task 3: Slider trong frontend

**Files:**
- Create: `frontend/src/components/HotelCard.tsx`, `frontend/src/components/HotelSlider.tsx`
- Modify: `frontend/src/api/api.types.ts`, `frontend/src/chat/useChatStream.ts`, `frontend/src/components/ChatPanel.tsx`, `frontend/src/i18n/en.json`, `frontend/src/i18n/vi.json`, `frontend/src/mocks/chatScript.ts`, `frontend/src/mocks/fixtures.ts`, `frontend/src/components/ChatPanel.test.tsx`

**Interfaces:**
- Consumes: event `{ type: "hotels", data: { cards: HotelCard[] } }`, message intent `hotel_options` với `suggestions: HotelCard[]`.

- [ ] Test `hotel_question_shows_slider_with_source_links_after_reload` (thẻ có tên, link "View on booking.com" mở tab mới, slider còn sau khi tải lại) và `hotel_card_without_price_says_no_price`.
- [ ] Viết types, stream state `hotels`, `HotelCard`, `HotelSlider`, render trong `ChatPanel`, chuỗi i18n, kịch bản mock.
- [ ] Chạy `npm test && npm run lint && npm run typecheck && npm run build`.
