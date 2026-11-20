# Tạo trip ngay trong chat

## Mục đích

Khi người dùng nói trong chat là muốn lập kế hoạch ("tạo plan trip cho tôi"), chat hiện tại trả lời "chưa có agent nào tạo trip" vì bộ phân loại (`src/chat/chat_service.py:34`) không có agent cho việc này. Người dùng phải tự sang trang `/trips/new` và gõ lại những gì đã nói. Tính năng này giữ người dùng trong chat: chat nhận ra nhu cầu, hiện form tạo trip ngay trong luồng tin nhắn với những gì đã biết từ cuộc trò chuyện, người dùng sửa rồi bấm "Tạo kế hoạch" hoặc "Hủy", và tiến độ tạo plan hiện ngay tại tin nhắn đó.

## Mục tiêu

- Nhận diện ý định tạo trip mới trong chat và trả về một tin nhắn có form.
- Form được điền sẵn từ lịch sử chat và `conversations.request_draft`; trường nào chưa biết thì để mặc định như form hiện tại.
- Hai nút: "Tạo kế hoạch" và "Hủy".
- Sau khi tạo, tin nhắn hiện tiến độ (xếp hàng, nghiên cứu, lập kế hoạch), rồi link mở trip khi xong, hoặc lý do lỗi và nút thử lại.
- Tải lại trang thì form, trạng thái đã hủy và tiến độ vẫn còn nguyên.

## Không làm

- Không stream tiến độ qua SSE; tin nhắn poll `GET /trips/{id}` như trang trip.
- Không đổi nút "Lên kế hoạch" của thẻ gợi ý điểm đến (vẫn mở `/trips/new`).
- Không hiện cả plan trong chat; chỉ có link sang trang trip.
- Không thêm cột vào `messages`.

## Ràng buộc

- Dữ liệu form nằm ở `messages.content` dưới dạng chuỗi JSON (quyết định của người dùng).
- Trạng thái nằm ở `messages.intent`: thêm `trip_form`, `created_trip`, `canceled_trip` vào `CHECK` bằng migration `sql/migrations/0002_trip_form_intents.sql`.
- Tọa độ điểm đến do code đặt, không do model (quy tắc của repo).
- Giới hạn tạo trip theo ngày và quota của `POST /trips` vẫn áp dụng.

## Các cách đã cân nhắc

- **Chọn: agent `create_trip` trong bộ phân loại, 1 lần gọi LLM để rút thông tin từ lịch sử chat.** Tốn thêm 1 lần gọi LLM mỗi khi nhận diện, nhưng form được điền từ những gì người dùng thật sự đã nói.
- Chỉ dùng `request_draft` có sẵn, không gọi LLM: draft chỉ được ghi ở các lượt discovery, nên ở luồng như screenshot (câu đầu vào `travel_advice`) form gần như rỗng.
- Lưu trạng thái ở 2 cột mới (`trip_form`, `trip_id`): giữ được khóa ngoại và constraint, nhưng người dùng chọn không thêm cột.
- Lưu trạng thái trong `suggestions` jsonb: lẫn hai loại dữ liệu trong một cột tên sai nghĩa; người dùng chọn `content` + `intent`.

## Thiết kế

### Vòng đời của tin nhắn form

Một tin nhắn assistant duy nhất, được cập nhật tại chỗ (không thêm tin nhắn mới khi người dùng thao tác):

| `intent` | `content` | UI |
|---|---|---|
| `trip_form` | JSON các giá trị đã điền sẵn | Form có nút "Tạo kế hoạch" và "Hủy" |
| `created_trip` | JSON các giá trị người dùng đã gửi, kèm `trip_id` | Thẻ tiến độ, rồi link mở trip hoặc lỗi và nút thử lại |
| `canceled_trip` | JSON giữ nguyên như lúc hủy | Một dòng mờ "Đã hủy tạo chuyến đi" |

Chỉ chuyển được từ `trip_form` sang một trong hai trạng thái kia; chuyển lần hai trả về 409 `conflict`. Câu lệnh UPDATE có điều kiện `WHERE intent = 'trip_form'` để hai tab bấm cùng lúc không tạo được hai trip.

Dạng `content` là các trường của `RequestDraft` (`src/domain/discovery.py:28`), thêm `trip_id` khi đã tạo:

```json
{"destination": {"name": "Hải Phòng", "country_code": "VN", "lat": 20.86, "lon": 106.68}, "origin": "Hà Nội", "length_days": 3, "travelers": 2, "travel_styles": ["food"], "budget_scope": "per_person"}
```

### Backend

- **Bộ phân loại:** thêm `AgentSpec(name="create_trip", ...)` vào `CATALOG`, mô tả: người dùng muốn lập kế hoạch hoặc lịch trình cho một chuyến mới ngay bây giờ (không phải đang chọn điểm đến, không phải sửa trip đang mở).
- **Agent rút thông tin:** `src/agents/create_trip_agent.py`, theo mẫu `DiscoverAskAgent`, purpose `discover`, đầu vào là `discovery_content` (hôm nay, draft, lịch sử, tin nhắn). Đầu ra là `RequestDraft` (ẩn `destination`) cộng thêm `destination_name: str | None`. Prompt mới `create_trip_prompt` trong `src/core/prompts.py`: chỉ ghi những gì người dùng đã nói, không đoán ngày, quy đổi "3 ngày 2 đêm" thành `length_days`.
- **Tìm tọa độ:** code gọi `search_places` (`src/research/places.py:34`) với `destination_name` và ngôn ngữ của tin nhắn, lấy kết quả đầu tiên. Không có kết quả hoặc lỗi tìm kiếm thì để `destination` trống.
- **Lượt chat:** `src/chat/create_trip_turn.py` gộp draft (`merge_draft`), lưu vào `conversations.request_draft`, lưu tin nhắn `intent='trip_form'`, `content=json.dumps(draft)`, rồi phát một sự kiện SSE mới `trip_form` với `{"message_id", "draft"}`. Không có token text; lời dẫn ("Mình đã điền sẵn form...") do frontend viết bằng i18n.
- **Lịch sử đưa vào LLM:** ở mọi chỗ dựng lịch sử (`load_context`, `run_discovery_turn`, `_classify`), tin nhắn có 3 intent mới được thay bằng một dòng ngắn thay vì JSON thô, ví dụ `[trip form: Hải Phòng, 3 days, created]`, để model không bị nhiễu và biết trip đã được tạo.
- **Tạo trip:** `POST /trips` nhận thêm trường tùy chọn `message_id`. Khi có, trong cùng transaction với tạo trip và job: kiểm tra tin nhắn thuộc conversation của cùng user và đang là `trip_form`, rồi cập nhật `intent='created_trip'` và `content` thành giá trị đã gửi kèm `trip_id`. `message_id` không được ghi vào request của trip.
- **Hủy:** `PATCH /conversations/{conversation_id}/messages/{message_id}` với body `{"intent": "canceled_trip"}`; chỉ chấp nhận giá trị này và chỉ khi tin nhắn đang là `trip_form`.
- **Đọc lại:** `GET /conversations/{id}` không đổi; frontend tự parse `content` khi `intent` là một trong 3 giá trị trên.

### Frontend

- `useChatStream` xử lý sự kiện `trip_form` (lưu vào state đang stream); sau khi stream xong thì refetch conversation như hiện tại.
- `ChatPanel` render tin nhắn theo `intent`:
  - `trip_form`: lời dẫn, rồi `TripForm` dùng `fromDraft(JSON.parse(content))`. Ẩn nút "Lấy ý tưởng" (prop `onGetIdeas` thành tùy chọn), thêm nút "Hủy". Gửi thì gọi `useCreateTrip` với `message_id`, rồi refetch conversation, không chuyển trang.
  - `created_trip`: thẻ mới `ChatTripProgress` dùng `useTrip(trip_id)` (poll 2 giây khi đang chạy) và `JobProgress`. Khi `ready` thì hiện tên điểm đến, ngày và link "Mở chuyến đi". Khi `failed` thì có nút thử lại qua `useRetryTrip`. Trip trả 404 (đã xóa) thì hiện "Chuyến đi này đã bị xóa".
  - `canceled_trip`: dòng chữ mờ.
  - `content` không parse được thì hiện như tin nhắn lỗi chung, không làm sập thread.
- Chuỗi mới vào `frontend/src/i18n/en.json` và `vi.json`.
- Theo `frontend/CLAUDE.md` và cập nhật `frontend/ui-component-principles.md` nếu đụng vào chat input hoặc sidebar.

### Kiểm thử

- Unit: agent rút thông tin (model trả destination_name, code đặt tọa độ; không tìm thấy thì destination trống), chuyển history thành dòng ngắn.
- Integration: migration nhận intent mới; lượt chat `create_trip` lưu tin nhắn và draft; `POST /trips` với `message_id` cập nhật tin nhắn trong cùng transaction; tạo lần hai và hủy sau khi tạo trả 409; tin nhắn của user khác trả 404.
- Frontend: `ChatPanel` render đủ 3 trạng thái; tạo trip gửi `message_id`; hủy gọi PATCH.
- Cập nhật `docs/api.md` cho trường `message_id`, endpoint PATCH và sự kiện SSE `trip_form`.

### Các trường hợp biên (quyết định của người viết thiết kế, người dùng duyệt lại)

- **Draft sau khi tạo trip:** trong cùng transaction của `POST /trips` có `message_id`, `conversations.request_draft` được xóa về `NULL`. Nếu không, `merge_draft` không bao giờ bỏ trường nào, nên form thứ hai trong cùng conversation ("giờ lên plan Đà Nẵng") sẽ mang ngày, số người và ngân sách của trip đầu. Trip đã tạo vẫn còn trong lịch sử qua dòng `[trip form: ..., created]`.
- **Lỗi khi rút thông tin:** model không trả lời hoặc trả sai sau một lần sửa thì vẫn hiện form, điền từ `request_draft` và mặc định, vì mục đích là giữ người dùng trong chat. Riêng hết quota AI (`QuotaExhausted`, `LLMBudgetExceeded`) thì trả sự kiện `error` như hiện tại, không lưu tin nhắn.
- **Quyền khi hủy:** theo các route conversation hiện có, không kiểm tra user; chỉ kiểm tra tin nhắn thuộc đúng conversation trong URL. `POST /trips` với `message_id` thì kiểm tra `conversation.user_id == body.user_id`, sai thì 404.
- **Sửa form chưa gửi:** tải lại trang thì form quay về giá trị đã điền sẵn; phần người dùng sửa mà chưa gửi không được lưu.

## Để lại cho người làm

- Câu chữ của lời dẫn, dòng đã hủy và thẻ tiến độ.
- Có tự hủy các form `trip_form` cũ trong cùng conversation khi tạo form mới hay không (đề xuất: không, mỗi form độc lập).
