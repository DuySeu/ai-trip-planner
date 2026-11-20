# Gom intent của chat và thẻ hỏi nhu cầu: thiết kế

## Mục đích

Chat hiện có 10 agent để router chọn và 12 giá trị `messages.intent`. Mô tả các agent chồng lên nhau nên router chọn sai: trong lần thử ngày 2026-11-20, "Tôi muốn đi du lịch biển" ra `clarification` thay vì `ask`, "Đi Phú Quốc tháng 7 có bị mưa nhiều không?" ra `travel_advice` thay vì `answer` (xem `docs/chat-intents.md`). Cột `intent` vừa ghi lựa chọn của router vừa ghi trạng thái form (`trip_form`, `created_trip`, `canceled_trip`), nên đếm mỗi intent được chọn bao nhiêu lần không ra con số đúng.

Thiết kế này gom còn 5 intent, tách trạng thái ra cột `metadata`, và thay phần hỏi nhu cầu do LLM tự nghĩ bằng một bộ câu hỏi mẫu trong một thẻ, để khơi gợi nhu cầu của khách và gom đủ thông tin tạo trip plan.

## Mục tiêu

- 5 intent, mỗi lần trả lời của assistant mang đúng một intent là lựa chọn của router (hoặc của code khi router bị bỏ qua).
- Chat vẫn làm được: tư vấn du lịch, lên ý tưởng chuyến đi, tìm khách sạn, tìm vé máy bay, mở form tạo trip, sửa plan.
- Thống kê bằng SQL đơn giản: số lần mỗi intent, tỉ lệ form được tạo hoặc hủy, khách dừng ở câu hỏi nào.
- Ý tưởng chuyến đi bắt đầu bằng bộ câu hỏi mẫu có nút chọn nhanh.

## Không làm

- Giá vé máy bay hoặc giá phòng live theo ngày, đặt vé, đặt phòng.
- Chạy nhiều bước trong một lượt (router chia nhiều bước thì vẫn chỉ chạy bước đầu, như hiện nay).
- Trang thống kê; chỉ cần dữ liệu query được.
- Sửa lỗi `**` markdown và trích dẫn `【26†...】` trong câu trả lời (lỗi riêng).

## Không được xảy ra

- Câu trả lời cho bộ câu hỏi đi qua router và bị chọn sai intent.
- Gọi LLM trong lúc khách đang trả lời bộ câu hỏi.
- Hội thoại cũ tải lại bị mất thẻ, mất form hoặc hiện sai sau migration.
- Một form tạo trip mang trạng thái không hợp lệ.

## Ràng buộc

- Pipeline cố định trong code, không agent loop (CLAUDE.md, "Approaches" option 1). Model miễn phí trên OpenRouter.
- Thay đổi schema là migration mới đánh số tiếp (`0004_...`), không sửa migration đã chạy. Giá trị kiểu enum là `text` + `CHECK`.
- ID, URL do code đặt, không bao giờ do model viết.
- Frontend: màu chỉ từ token, mọi chuỗi trong `en.json`/`vi.json`, icon Lucide (`frontend/CLAUDE.md`). Không chạy prettier.
- Đây là thay đổi API công khai: `GET /conversations/{id}`, `PATCH /conversations/{id}/messages/{id}`, các event SSE của `POST /chat`. `docs/api.md` cập nhật cùng lúc.

## Cách làm đã chọn

Hai cách cho phần hỏi nhu cầu, cùng dựa trên 5 intent và cột `metadata`:

- **A, mỗi câu hỏi một lượt chat:** tự nhiên hơn, nhưng mỗi câu trả lời là một `POST /chat`, cần luật bỏ qua router khi đang chờ câu trả lời, và khách gõ câu khác giữa chừng thì code phải đoán: lại có chỗ chọn sai. Thread dài thêm khoảng 12 tin nhắn.
- **B, một thẻ hỏi nhu cầu (đã chọn):** router chọn `discover` một lần, thẻ có 6 bước, câu trả lời lưu qua `PATCH` vào `metadata` của tin nhắn đó như form tạo trip hiện nay. Không qua router, không gọi LLM cho tới bước gợi ý. Đổi lại ít tự nhiên hơn; mong muốn tự do chỉ gõ được ở ô ghi chú.

Đã loại: cho LLM tự gọi tool (agent loop), vì trái với pipeline cố định đã chọn và model miễn phí gọi tool không ổn định.

## Thiết kế

### Năm intent

| Intent | Thay cho | Agent trong `CATALOG` | Việc làm |
|---|---|---|---|
| `advice` | `travel_advice`, `answer`, `plan_answer`, `clarification`, `trip_research` | `advice`, `web_lookup` | Hỏi đáp chung. `advice` không tìm web: có trip đang mở với plan thì dùng prompt trả lời về plan (`answer_about_plan`), không thì prompt tư vấn (`give_travel_advice`). `web_lookup` cần thông tin mới mà plan và kiến thức chung không có (ví dụ "Đà Nẵng tháng 7 có lễ hội gì?"): chạy `answer_from_research` hiện có, step task là câu tìm kiếm |
| `discover` | `ask`, `suggest` | `discover` | Thẻ hỏi nhu cầu, rồi gợi ý 3 điểm đến |
| `booking_search` | `hotel_options` | `hotel_search`, `flight_search` | Tìm khách sạn hoặc vé trên trang đặt chỗ, trả slider thẻ |
| `create_trip` | `trip_form`, `created_trip`, `canceled_trip` | `create_trip` | Form tạo trip điền sẵn từ draft |
| `edit_plan` | `plan_editor` | `edit_plan` | Sửa plan của trip đang mở |

Tên agent và tên intent tách nhau: router chọn giữa 7 agent, nhưng `hotel_search` và `flight_search` cùng ghi intent `booking_search` (khác nhau ở `metadata.kind`), `advice` và `web_lookup` cùng ghi intent `advice` (`web_lookup` ghi `metadata = {"searched": true}`). Mô tả `web_lookup` phải nói rõ: không dùng cho khách sạn hay vé (đã có hai agent kia), không dùng cho câu hỏi về plan đang mở.

Router trả `needs_clarification`: stream câu hỏi lại của router như hiện nay, lưu intent `advice` với `metadata = {"clarify": true}` để vẫn đếm được. Router không chọn agent nào (trạng thái khác): `advice`.

`edit_plan` ở /chat không có trip đang mở: trả câu cố định `OPEN_TRIP` như hiện nay.

### Cột `metadata`

Migration đổi tên `messages.suggestions` thành `messages.metadata` (jsonb), bỏ CHECK "phải là mảng". `content` luôn là text (chuỗi rỗng cho thẻ hỏi nhu cầu và form tạo trip).

| Intent | `metadata` |
|---|---|
| `advice` | `null`, `{"clarify": true}` hoặc `{"searched": true}` |
| `edit_plan` | `null` |
| `discover`, thẻ hỏi | `{"kind": "questionnaire", "status": "open" \| "done", "step": 0-6, "answers": {...}, "choices": {...}}` |
| `discover`, gợi ý | `{"kind": "suggestions", "cards": [...]}` (thẻ như `SuggestionCard` hiện nay) |
| `booking_search`, hỏi ngày | `{"kind": "hotel" \| "flight", "status": "need_dates" \| "done", "query": "..."}` |
| `booking_search`, kết quả | `{"kind": "hotel" \| "flight", "status": "results", "query": "...", "dates": {...}, "cards": [...]}`; `cards` có thể rỗng khi không tìm được |
| `create_trip` | `{"status": "open" \| "created" \| "canceled", "draft": {...}, "trip_id": uuid \| null}` |

CHECK mới trên `messages`:

- `intent IN ('advice', 'discover', 'booking_search', 'create_trip', 'edit_plan')` hoặc null (tin nhắn của khách).
- `intent <> 'create_trip' OR coalesce(metadata->>'status', '') IN ('open', 'created', 'canceled')`.
- `intent <> 'booking_search' OR (coalesce(metadata->>'kind', '') IN ('hotel', 'flight') AND coalesce(metadata->>'status', '') IN ('need_dates', 'done', 'results'))`.
- `intent <> 'discover' OR coalesce(metadata->>'kind', '') IN ('questionnaire', 'suggestions')`.

`coalesce` là cần thiết: một CHECK ra NULL (khi `metadata` là null) được Postgres cho qua.

### Migration `0004_chat_intent_redesign.sql`

Trong một transaction:

- `plan_answer`, `travel_advice`, `answer` thành `advice`; `trip_research` thành `advice` với `{"searched": true}`; `clarification` thành `advice` với `{"clarify": true}`.
- `ask` thành `discover` với `{"kind": "questionnaire", "status": "done", "step": 0, "answers": {}}` và giữ `content` là câu hỏi cũ dạng text. `suggest` thành `discover` với `{"kind": "suggestions", "cards": <suggestions cũ>}`.
- `hotel_options` thành `booking_search` với `{"kind": "hotel", "status": "results", "query": "", "dates": null, "cards": <suggestions cũ hoặc []>}`.
- `plan_editor` thành `edit_plan`.
- `trip_form`, `created_trip`, `canceled_trip` thành `create_trip`: `status` lần lượt `open`, `created`, `canceled`; `draft` là JSON trong `content` bỏ khóa `trip_id`; `trip_id` lấy từ `content`; `content` thành `''`.
- Rồi thêm các CHECK ở trên.

Tin nhắn `ask` cũ hiện là câu hỏi text của LLM; frontend hiện nó như text khi `status = done` và `answers` rỗng.

### Thẻ hỏi nhu cầu

Bộ câu hỏi, theo thứ tự:

| Bước | Câu hỏi | Nút chọn nhanh | Ghi vào draft |
|---|---|---|---|
| 1 | Chuyến này bạn muốn cảm thấy thế nào? (chọn nhiều) | Thư giãn, Khám phá, Văn hóa lịch sử, Ăn ngon, Thiên nhiên, Vui chơi về đêm, Mua sắm | `travel_styles` (`relax`, `adventure`, `culture`, `food`, `nature`, `nightlife`, `shopping`) |
| 2 | Bạn đi mấy người? | 1, 2, 3-4, 5+, kèm ô nhập số | `travelers` |
| 3 | Ngân sách mỗi người khoảng bao nhiêu? | Tiết kiệm, Vừa phải, Thoải mái, Cao cấp, Nhập số | `budget_amount`, `budget_scope = per_person`; Tiết kiệm thêm style `budget`, Cao cấp thêm `luxury` |
| 4 | Bạn xuất phát từ đâu? | Hà Nội, TP.HCM, Đà Nẵng, Nơi khác (ô tìm địa điểm) | `origin` |
| 5 | Bạn định đi khi nào? | Tháng này, Tháng sau, Dịp lễ, Chọn ngày | `month` hoặc `start_date` |
| 6 | Đi khoảng mấy ngày? | 2-3 ngày, 4-5 ngày, 1 tuần, Dài hơn | `length_days` |

Mức tiền của Tiết kiệm, Vừa phải, Thoải mái, Cao cấp: (pending). Giá trị `length_days` cho mỗi nút, "3-4" và "5+" ghi số nào, và "Dịp lễ" gồm những dịp nào: (pending), người làm đề xuất trong kế hoạch.

Luồng:

1. Router chọn `discover`. Một lần gọi LLM tách thông tin trong tin nhắn của khách vào draft (dùng lại cách của `CreateTripAgent`, trả `TripFormExtract`), gộp vào `conversations.request_draft`. Lỗi LLM thì bỏ qua bước này, không chặn thẻ.
2. Nếu draft đã có đủ 6 mục: bỏ thẻ, đi thẳng bước gợi ý (5). Không thì lưu tin nhắn `discover` với `metadata.kind = questionnaire`, `step` là bước đầu tiên còn thiếu, `answers` là những gì draft đã có. Gửi event `metadata` (xem API).
3. Mỗi lần khách trả lời một bước, frontend gọi `PATCH /conversations/{cid}/messages/{mid}` với `{"step": n, "answers": {...}, "choice": "<id nút>" | null}`, trong đó `n` (1-6) là bước vừa trả lời. Server kiểm tra từng trường theo kiểu của `RequestDraft` và `choice` theo danh sách nút cố định của bước đó, gộp `answers` vào `metadata.answers` và `conversations.request_draft`, ghi `choices[n] = choice` (null khi khách nhập số hoặc chọn ngày), rồi đặt `step = max(step, n)`. Không gọi LLM. (Quyết định của người viết.)
   - `answers` giữ giá trị đã đổi sang draft (số tiền, số người, tháng); `choices` giữ id nút khách bấm, để thẻ `done` hiện lại nhãn ("Tiết kiệm", "3-4 người") và thống kê được nút nào hay được chọn. Danh sách nút và cách đổi nút sang giá trị nằm ở backend; frontend chỉ gửi id nút, server tự đổi, nên `answers` gửi lên chỉ dùng khi khách nhập tự do.
   - `step` là bước xa nhất khách đã trả lời, chỉ tăng. Quay lại và trả lời lại một bước cũ ghi đè `answers`/`choices` của bước đó, không làm giảm `step`. Bỏ qua câu này gửi `{"step": n, "answers": {}, "choice": null}`. Thống kê "dừng ở đâu" là `step` của thẻ còn `open`.
4. Thẻ có nút Quay lại, Bỏ qua câu này, Gợi ý luôn, và một ô ghi chú tùy chọn ở bước cuối (ghi vào `notes`).
5. Bước cuối hoặc Gợi ý luôn: frontend gọi `POST /chat` với `discover_message_id` = id thẻ, `content` là một câu cố định theo ngôn ngữ ("Gợi ý điểm đến cho tôi" / "Suggest destinations for me"). Server bỏ qua router, đặt `metadata.status = done` cho thẻ, chạy luồng gợi ý hiện có (`run_discovery_turn` nhánh `suggest`: tìm web với domain `discovery`, một lần `DiscoverSuggestAgent`), lưu tin nhắn mới intent `discover` với `{"kind": "suggestions", "cards": [...]}`.
6. Nút "Plan this trip" trên thẻ gợi ý giữ nguyên hành vi hiện nay.

Router chọn `discover` lần nữa trong cùng conversation (quyết định của người viết):

- Còn một thẻ `open` (ví dụ khách gõ "gợi ý luôn đi" thay vì bấm thẻ): không tạo thẻ mới. Chạy bước 1 để tách thông tin, đặt thẻ cũ `status = done`, rồi đi thẳng bước gợi ý với draft hiện có. Như vậy mỗi conversation có nhiều nhất một thẻ `open`.
- Thẻ cũ đã `done` (ví dụ "cho tôi ý tưởng khác"): chạy bước 1 và 2 như lần đầu. Draft đã đủ thì gợi ý lại ngay; khách muốn đổi câu trả lời thì gõ ("đổi thành 3 người"), bước 1 gộp vào draft.

`MAX_ASKS` và `DiscoverAskAgent` bỏ đi; `DiscoverAnswerAgent` bỏ đi (câu hỏi chung thành `advice`).

Thẻ ở trạng thái `done` khi tải lại hiện tóm tắt các câu trả lời, không cho sửa.

### Tìm khách sạn và vé máy bay

Tìm khách sạn hoặc vé cần ngày cụ thể. Ngày chỉ làm câu tìm kiếm sát mùa và dịp hơn: Tavily trả đoạn trích đã index, không phải giá live theo ngày, nên giá trên thẻ vẫn là "Estimate"; link trên thẻ đưa khách tới trang đặt chỗ để xem giá thật.

Lấy ngày (code, không gọi LLM thêm), theo thứ tự: ngày trong câu hỏi (router ghi vào step task, code đọc lại bằng bước tách thông tin của `discover` hoặc một trường ngày trong output của router; người làm chọn), ngày của trip đang mở, `start_date`/`end_date` trong `conversations.request_draft`.

- Khách sạn cần ngày nhận phòng và trả phòng. Vé cần ngày đi (ngày về không bắt buộc) và nơi xuất phát (lấy từ câu hỏi, trip, hoặc draft).
- Có đủ: tìm luôn, lưu một tin nhắn `status = results`.
- Thiếu: lưu tin nhắn `booking_search` với `{"kind", "status": "need_dates", "query"}`, `content` là một câu ngắn cố định theo ngôn ngữ ("Bạn định nhận phòng ngày nào?"), và frontend hiện thẻ chọn ngày (khách sạn: nhận phòng, trả phòng; vé: ngày đi, ngày về tùy chọn, nơi xuất phát nếu còn thiếu, dùng ô tìm địa điểm sẵn có). Không hỏi lại bằng text, vì câu trả lời "15/12" gõ vào chat sẽ phải qua router.
- Khách bấm Tìm: `POST /chat` với `booking_message_id` = id thẻ, `dates` (và `origin` khi có), `content` là câu cố định ("Tìm với ngày đã chọn"). Server bỏ qua router, kiểm tra ngày (không ở quá khứ, trả phòng sau nhận phòng, tối đa 30 đêm), đặt thẻ cũ `status = done`, ghi ngày vào `conversations.request_draft` khi draft chưa có, rồi tìm và lưu tin nhắn mới `status = results`.
- Ngày được đưa vào câu tìm kiếm và vào prompt, để model ưu tiên đoạn trích nói về mùa hoặc tháng đó.

- `hotel_search`: luồng `run_hotel_turn` hiện có, đổi intent thành `booking_search`, metadata `{"kind": "hotel", "status": "results", "query", "dates", "cards"}`.
- `flight_search`: luồng mới song song, cùng khuôn: tìm với task `"transport"` (`SEARCH_DOMAINS["transport"]`: rome2rio, 12go, skyscanner, traveloka, vexere, dsvn; không ra gì thì toàn web như hàm search sẵn có), lưu nguồn `kind = 'transport'`, một lần `call_json` trả `FlightOptionsReply` (`reply` 2-3 câu và tối đa 6 `FlightCard`). `FlightCard`: `carrier` (hãng hoặc nhà xe, tàu), `mode` (`TransportMode`), `route` (ví dụ "Hà Nội - Đà Nẵng"), `duration_text` (trống được), `price_from` (số hoặc trống), `price_currency`, `highlights` (tối đa 3), `source_id`. Code bỏ thẻ có nguồn lạ, gắn `url`, xếp thẻ có giá trước.
- Giá luôn hiện badge "Estimate"; thẻ không giá hiện "Chưa có giá".

### Tạo trip

- Luồng `run_create_trip_turn` giữ nguyên, lưu `content = ''`, `metadata = {"status": "open", "draft": {...}, "trip_id": null}`.
- `POST /trips` với `message_id`: đặt `status = created`, `trip_id`. Chỉ chuyển từ `open`.
- Hủy: `PATCH /conversations/{cid}/messages/{mid}` với `{"status": "canceled"}`. Chỉ chuyển từ `open`, không thì 409.

### API

- `MessageOut`: bỏ `suggestions`, thêm `metadata`. `intent` nhận 5 giá trị mới.
- `PATCH /conversations/{cid}/messages/{mid}`: body là một trong hai dạng, `{"status": "canceled"}` cho tin nhắn `create_trip` hoặc `{"step": int, "answers": object, "choice": string | null}` cho thẻ hỏi nhu cầu đang `open`. Sai loại tin nhắn hoặc sai trạng thái: 409. Trả `MessageOut`.
- `POST /chat`: thêm hai trường tùy chọn, không gửi cùng lúc (422). `discover_message_id`: phải là thẻ hỏi nhu cầu của đúng conversation. `booking_message_id` kèm `dates` (`check_in`, `check_out` cho khách sạn; `depart`, `return` tùy chọn cho vé) và `origin` tùy chọn: phải là thẻ hỏi ngày `need_dates` của đúng conversation. Sai conversation: 404; thẻ đã `done`: 409; ngày sai: 422.
- SSE: các event `suggestions`, `hotels`, `trip_form` thay bằng một event `metadata` mang đúng object sẽ lưu vào `messages.metadata`, gửi một lần sau các `token`. Frontend vẽ tin nhắn đang stream và tin nhắn đã lưu bằng cùng một hàm.

### Frontend

- `api.types.ts`: `MessageIntent` 5 giá trị, `Message.metadata` là union theo intent, event `metadata`.
- `ChatPanel`: chọn component theo `intent` và `metadata.kind` / `status`: thẻ hỏi nhu cầu, thẻ gợi ý, slider khách sạn, slider vé, form tạo trip (đọc `metadata.draft`, không đọc `content`), thẻ trip đã tạo, thẻ đã hủy.
- Component mới: `DiscoverQuestionnaire` (một card, một bước mỗi lúc, chip chọn nhanh theo recipe choice chip, thanh tiến độ 6 bước), `BookingDates` (thẻ chọn ngày, `<input type="date">` như form tạo trip; ở `done` hiện ngày đã chọn), `FlightCard`. `HotelSlider` đổi thành slider chung nhận thẻ khách sạn hoặc vé.
- Chuỗi mới trong `en.json`/`vi.json`; mock MSW và test cập nhật theo.

### Thống kê

```sql
-- Số lần mỗi intent
SELECT intent, count(*) FROM messages WHERE role = 'assistant' GROUP BY intent;
-- Form tạo trip: tạo, hủy, bỏ dở
SELECT metadata->>'status', count(*) FROM messages WHERE intent = 'create_trip' GROUP BY 1;
-- Thẻ hỏi nhu cầu: khách dừng ở bước nào
SELECT metadata->>'status', metadata->>'step', count(*) FROM messages
WHERE intent = 'discover' AND metadata->>'kind' = 'questionnaire' GROUP BY 1, 2;
-- Tìm khách sạn hay vé, phải hỏi ngày bao nhiêu lần, bỏ ngang bao nhiêu lần (need_dates còn lại)
SELECT metadata->>'kind', metadata->>'status', count(*) FROM messages
WHERE intent = 'booking_search' GROUP BY 1, 2;
-- Câu hỏi chung có tìm web hay không, router hỏi lại bao nhiêu lần
SELECT metadata, count(*) FROM messages WHERE intent = 'advice' GROUP BY 1;
```

## Để người làm tự quyết

- Câu chữ mô tả 6 agent trong `CATALOG` và prompt `flight_search`.
- Bố cục thẻ hỏi nhu cầu và thẻ vé trong giới hạn của `frontend/CLAUDE.md`.
- Tách `chat_service._dispatch` thành các hàm nhỏ hay giữ một hàm.
- Thứ tự các task trong kế hoạch.

## Câu hỏi còn mở

- Mức tiền các nút ngân sách, giá trị số cho các nút số người và số ngày, danh sách "Dịp lễ": (pending).
