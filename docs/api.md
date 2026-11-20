# API backend

Danh sách các endpoint của FastAPI app trong `src/api`, lấy từ `src/api/routes/*.py` và `src/api/schemas/*.py`. Khi chạy local, base URL là `http://localhost:8000`; Swagger tự sinh ở `/docs`.

## Quy ước chung

Mọi response JSON (thành công hay lỗi) đều dùng chung một envelope (`src/api/envelope.py`):

```json
{
  "success": true,
  "data": {},
  "error": null,
  "meta": null
}
```

- `data`: nội dung trả về, `null` khi lỗi.
- `error`: `{ "code": "...", "message": "..." }` khi lỗi, `null` khi thành công.
- `meta`: chỉ có ở các endpoint phân trang, dạng `{ "total": 0, "limit": 20, "offset": 0 }`.

Ngoại lệ: `DELETE` trả về 204 không có body, `POST /chat` trả về stream SSE, `GET /trips/{trip_id}/export.xlsx` trả về file Excel.

Mã lỗi (`src/api/errors.py`):

| HTTP | `error.code` | Khi nào |
|---|---|---|
| 404 | `not_found` | Không tìm thấy user, trip, conversation hoặc route |
| 405 | `method_not_allowed` | Sai method |
| 409 | `conflict` | Trạng thái hiện tại không cho phép thao tác (ví dụ plan chưa có, trip đang được tạo plan) |
| 413 | `payload_too_large` | Body lớn hơn 64 KB (`src/api/middleware.py:18`) |
| 422 | `invalid_request` | Body hoặc query sai; message liệt kê tối đa 5 lỗi dạng `body.field: lý do` |
| 429 | `rate_limited` | Vượt giới hạn theo IP hoặc theo user mỗi ngày |
| 429 | `quota_exhausted` | Hết quota AI/Tavily miễn phí; message có thời điểm reset |
| 503 | `unavailable` | Database hoặc dịch vụ tìm địa điểm không phản hồi |
| 500 | `internal_error` | Lỗi không lường trước; header `X-Request-ID` để tra log |

Giới hạn: mọi endpoint trừ `/health` và `/ready` tính vào giới hạn request mỗi phút theo IP (`IP_REQUESTS_PER_MINUTE`). `POST /trips` còn tính vào `IP_TRIPS_PER_DAY` và `USER_TRIPS_PER_DAY`; `POST /chat` tính vào `IP_CHAT_PER_MINUTE`, `IP_CHAT_PER_DAY` và `USER_CHAT_PER_DAY`.

Văn bản tự do (tên, địa điểm, ghi chú, tin nhắn) được chuẩn hóa NFC, bỏ ký tự điều khiển (giữ xuống dòng và tab) và cắt khoảng trắng đầu cuối trước khi kiểm tra độ dài.

## Tổng quan

| Method | Path | Mô tả |
|---|---|---|
| GET | `/health` | Kiểm tra process còn sống |
| GET | `/ready` | Kiểm tra database có phản hồi |
| POST | `/users` | Nhận một tên, hoặc lấy lại user đã có tên đó |
| GET | `/users/{user_id}` | Thông tin user và số trip |
| GET | `/users/{user_id}/trips` | Danh sách trip của user, phân trang |
| GET | `/places` | Tìm điểm đến theo tên |
| POST | `/trips` | Tạo trip và đưa việc tạo plan vào hàng đợi |
| GET | `/trips/{trip_id}` | Trip kèm trạng thái, bước đang chạy và plan hiện tại |
| POST | `/trips/{trip_id}/retry` | Chạy lại việc tạo plan cho trip bị lỗi |
| DELETE | `/trips/{trip_id}` | Xóa trip |
| GET | `/trips/{trip_id}/export.xlsx` | Tải plan dưới dạng file Excel |
| POST | `/conversations` | Bắt đầu một cuộc hội thoại |
| GET | `/users/{user_id}/conversations` | Danh sách hội thoại của user, phân trang |
| GET | `/conversations/{conversation_id}` | Hội thoại kèm một trang tin nhắn |
| PATCH | `/conversations/{conversation_id}` | Đổi tên hội thoại |
| PATCH | `/conversations/{conversation_id}/messages/{message_id}` | Hủy một form tạo trip trong chat |
| DELETE | `/conversations/{conversation_id}` | Xóa hội thoại và tin nhắn |
| POST | `/chat` | Gửi tin nhắn, nhận câu trả lời dạng SSE |

## Health

### GET /health

Liveness: process đang chạy. Không tính vào rate limit. Code: `src/api/routes/health.py:16`.

- Payload: không có.
- Output 200: `data = { "status": "ok" }`.

### GET /ready

Readiness: chạy `SELECT 1` trên database với timeout 2 giây. Không tính vào rate limit. Code: `src/api/routes/health.py:22`.

- Payload: không có.
- Output 200: `data = { "status": "ready" }`.
- Lỗi: 503 `unavailable` khi database không kết nối được.

## Users

### POST /users

Nhận một tên. Nếu tên đã tồn tại (so sánh không phân biệt hoa thường, sau khi cắt khoảng trắng) thì trả về user cũ, không tạo mới. Code: `src/api/routes/users.py:23`.

Payload:

```json
{ "name": "Duy" }
```

- `name`: bắt buộc, 1 đến 50 ký tự sau khi chuẩn hóa.

Output 200, `data` là `UserOut`:

```json
{
  "id": "uuid",
  "name": "Duy",
  "created_at": "2026-11-19T03:00:00Z",
  "trip_count": 0
}
```

Lỗi: 422 khi tên rỗng hoặc dài quá 50 ký tự.

### GET /users/{user_id}

Lấy một user và số trip của họ. Code: `src/api/routes/users.py:31`.

- Payload: không có. `user_id` là UUID.
- Output 200: `data` là `UserOut` như trên.
- Lỗi: 404 khi không có user.

### GET /users/{user_id}/trips

Danh sách trip của user, mới nhất trước. Code: `src/api/routes/users.py:38`.

- Query: `limit` (1 đến 100, mặc định 20), `offset` (từ 0, mặc định 0).
- Output 200: `data` là mảng `TripSummary` (xem phần Trips), `meta = { total, limit, offset }`.
- Lỗi: 404 khi không có user.

## Places

### GET /places

Tìm điểm đến cho form tạo trip, trả về tối đa 10 kết quả; kết quả được cache trong database. Code: `src/api/routes/places.py:25`.

- Query: `q` (bắt buộc, 2 đến 100 ký tự sau khi cắt khoảng trắng), `language` (`en` hoặc `vi`, mặc định `en`).

Output 200, `data` là mảng `PlaceOut`:

```json
[
  {
    "name": "Đà Lạt",
    "admin1": "Lâm Đồng",
    "country_code": "VN",
    "lat": 11.94,
    "lon": 108.44
  }
]
```

- `admin1`: tỉnh/bang, có thể `null`.

Lỗi: 422 khi `q` quá ngắn hoặc quá dài; 503 `unavailable` khi dịch vụ tìm địa điểm lỗi.

## Trips

Trạng thái trip (`status`): `queued`, `researching`, `planning`, `ready`, `failed`. Bước của job đang chạy (`stage`): `researching`, `planning`, `validating`, hoặc `null` khi không có job nào đang chạy.

### POST /trips

Tạo trip và job tạo plan trong cùng một transaction. API trả về ngay; worker sẽ lấy job và viết plan, client poll `GET /trips/{id}` để xem tiến độ. Code: `src/api/routes/trips.py:23`.

Payload (`CreateTripBody` = `TripRequest` + `user_id` + `message_id` tùy chọn, `src/domain/trip_request.py:74`):

```json
{
  "user_id": "uuid",
  "destination": {
    "name": "Đà Lạt",
    "country_code": "VN",
    "lat": 11.94,
    "lon": 108.44
  },
  "origin": "Hà Nội",
  "start_date": "2026-12-20",
  "end_date": "2026-12-23",
  "travelers": 2,
  "travel_styles": ["nature", "food"],
  "budget_amount": 8000000,
  "budget_scope": "total",
  "language": "vi",
  "notes": "Không ăn cay"
}
```

| Field | Bắt buộc | Ràng buộc |
|---|---|---|
| `user_id` | có | UUID của user đã tồn tại |
| `message_id` | không | UUID của tin nhắn form tạo trip trong chat mà trip này được tạo từ đó; xem bên dưới |
| `destination` | có | Lấy từ `GET /places`; `name` 1 đến 200 ký tự, `country_code` 2 chữ in hoa, `lat` từ -90 đến 90, `lon` từ -180 đến 180 |
| `origin` | có | 1 đến 200 ký tự |
| `start_date` | có | Từ hôm nay trở đi (theo giờ Việt Nam) |
| `end_date` | có | Không trước `start_date`; trip dài tối đa 30 ngày |
| `travelers` | có | 1 đến 50 |
| `travel_styles` | có | Ít nhất 1 giá trị trong `relax`, `adventure`, `culture`, `food`, `nature`, `nightlife`, `shopping`, `luxury`, `budget`; giá trị lặp bị bỏ |
| `budget_amount` | có | Lớn hơn 0, tối đa 14 chữ số và 2 chữ số thập phân, tính bằng VND |
| `budget_scope` | có | `per_person` hoặc `total` |
| `language` | không | `en` (mặc định) hoặc `vi` |
| `notes` | không | Tối đa 2000 ký tự; chuỗi rỗng thành `null` |

Không gửi tiền tệ địa phương; server tự suy ra từ `country_code`.

Khi có `message_id`, trong cùng transaction với trip và job, server kiểm tra tin nhắn thuộc một hội thoại của chính `user_id`, chuyển `intent` của tin nhắn từ `trip_form` sang `created_trip`, ghi `content` thành các giá trị đã gửi kèm `trip_id` (không có `user_id` và `message_id`), và xóa `request_draft` của hội thoại. `message_id` không được ghi vào request của trip. Nếu tin nhắn không còn là `trip_form` (ví dụ hai tab cùng bấm tạo) thì trả 409 và không tạo trip hay job nào.

Output 202, `data` là `TripCreated`:

```json
{ "id": "uuid", "status": "queued" }
```

Lỗi: 404 khi không có user, hoặc `message_id` không có hay thuộc hội thoại của user khác; 409 `conflict` khi form đã được dùng hoặc đã hủy; 422 khi sai ràng buộc hoặc quốc gia chưa được hỗ trợ; 429 `rate_limited` khi vượt giới hạn tạo trip theo IP hoặc theo user; 429 `quota_exhausted` khi hết quota OpenRouter hoặc Tavily.

### GET /trips/{trip_id}

Trip kèm request gốc, tiến độ và plan hiện tại. Code: `src/api/routes/trips.py:69`.

- Payload: không có.

Output 200, `data` là `TripOut`:

```json
{
  "id": "uuid",
  "destination": { "name": "Đà Lạt", "country_code": "VN", "lat": 11.94, "lon": 108.44 },
  "start_date": "2026-12-20",
  "end_date": "2026-12-23",
  "travelers": 2,
  "status": "ready",
  "total_cost_vnd": "7500000.00",
  "over_budget": false,
  "created_at": "2026-11-19T03:00:00Z",
  "updated_at": "2026-11-19T03:02:00Z",
  "origin": "Hà Nội",
  "travel_styles": ["nature", "food"],
  "budget_amount": "8000000.00",
  "budget_scope": "total",
  "local_currency": null,
  "language": "vi",
  "notes": "Không ăn cay",
  "stage": null,
  "failure_reason": null,
  "plan_revision": 1,
  "plan": {},
  "expires_at": "2026-12-19T03:00:00Z"
}
```

- `id` đến `updated_at` là phần `TripSummary`, cũng là phần tử của `GET /users/{user_id}/trips`.
- `total_cost_vnd`, `over_budget`: `null` khi chưa có plan.
- `local_currency`: mã tiền tệ địa phương khi đi nước ngoài, `null` khi đi trong nước.
- `failure_reason`: lý do lỗi khi `status = failed`.
- `plan_revision`: tăng mỗi lần plan bị ghi đè; gửi lại giá trị này ở `POST /chat` để tránh ghi đè lên plan mới hơn.
- `plan`: `null` khi chưa xong. Cấu trúc theo `Plan` trong `src/domain/plan.py:148`: `title`, `summary`, `currencies`, `days` (mỗi ngày có `date`, `theme`, `weather`, `items`), `transport_options`, `accommodation`, `checklist`, `warnings`.
- `expires_at`: thời điểm trip bị xóa nếu không được dùng tiếp.

Lỗi: 404 khi không có trip.

### POST /trips/{trip_id}/retry

Đưa trip bị lỗi trở lại hàng đợi. Code: `src/api/routes/trips.py:77`.

- Payload: không có.
- Output 202: `data = { "id": "uuid", "status": "queued" }`.
- Lỗi: 404 khi không có trip; 409 `conflict` khi trip đang có job chạy hoặc `status` khác `failed`; 429 `quota_exhausted` khi hết quota.

### DELETE /trips/{trip_id}

Xóa trip và mọi dữ liệu thuộc về nó. Code: `src/api/routes/trips.py:94`.

- Payload: không có.
- Output: 204, không có body.
- Lỗi: 404 khi không có trip.

### GET /trips/{trip_id}/export.xlsx

Tải plan hiện tại dưới dạng file Excel dựng từ `data/trip-template.xlsx`. Code: `src/api/routes/exports.py:35`.

- Payload: không có.
- Output 200: file với `Content-Type: application/vnd.openxmlformats-officedocument.spreadsheetml.sheet`. Header `Content-Disposition` có hai tên file: `filename` dạng ASCII (bỏ dấu) và `filename*` dạng UTF-8, cả hai lấy từ tên điểm đến.
- Lỗi: 404 khi không có trip; 409 `conflict` khi plan chưa sẵn sàng.

## Conversations

### POST /conversations

Bắt đầu hội thoại, có thể mang theo các field của form đã nhập dở. Code: `src/api/routes/chat.py:66`.

Payload:

```json
{
  "user_id": "uuid",
  "draft": {
    "destination": null,
    "origin": "Hà Nội",
    "start_date": null,
    "end_date": null,
    "month": "12",
    "length_days": 4,
    "travelers": 2,
    "travel_styles": ["nature"],
    "budget_amount": 8000000,
    "budget_scope": "total",
    "language": "vi",
    "notes": null
  }
}
```

- `user_id`: bắt buộc.
- `draft`: không bắt buộc. Mọi field đều có thể bỏ trống; ràng buộc giống `POST /trips`, thêm `month` (chuỗi) và `length_days` (1 đến 30). Server chỉ giữ các field có giá trị (`RequestDraft`, `src/domain/discovery.py:33`).

Output 201, `data` là `ConversationOut`:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "title": null,
  "request_draft": { "origin": "Hà Nội", "travelers": 2 },
  "created_at": "2026-11-19T03:00:00Z",
  "updated_at": "2026-11-19T03:00:00Z"
}
```

Lỗi: 404 khi không có user; 422 khi draft sai ràng buộc.

### GET /users/{user_id}/conversations

Danh sách hội thoại của user, hội thoại có hoạt động gần nhất đứng trước. Code: `src/api/routes/chat.py:75`.

- Query: `limit` (1 đến 100, mặc định 20), `offset` (mặc định 0).
- Output 200: `data` là mảng `ConversationOut`, `meta = { total, limit, offset }`.
- Lỗi: 404 khi không có user.

### GET /conversations/{conversation_id}

Hội thoại kèm một trang tin nhắn. Code: `src/api/routes/chat.py:94`.

- Query: `limit` (1 đến 200, mặc định 50), `offset` (mặc định 0). `meta.total` là tổng số tin nhắn.

Output 200, `data` là `ConversationOut` thêm `messages`:

```json
{
  "id": "uuid",
  "user_id": "uuid",
  "title": "Đi đâu cuối năm cho mát?",
  "request_draft": null,
  "created_at": "2026-11-19T03:00:00Z",
  "updated_at": "2026-11-19T03:05:00Z",
  "messages": [
    {
      "id": "uuid",
      "role": "user",
      "content": "Đi đâu cuối năm cho mát?",
      "intent": null,
      "suggestions": null,
      "created_at": "2026-11-19T03:05:00Z"
    }
  ]
}
```

- `role`: `user` hoặc `assistant`.
- `intent`: loại câu trả lời của assistant, một trong `plan_answer`, `plan_editor`, `trip_research`, `travel_advice`, `clarification`, `ask`, `suggest`, `answer`, `trip_form`, `created_trip`, `canceled_trip`, `hotel_options`; có thể `null`.
- `suggestions`: mảng thẻ gợi ý điểm đến khi `intent = suggest`, mảng thẻ khách sạn khi `intent = hotel_options` (có thể `null` khi không tìm được khách sạn nào), còn lại `null`.
- `trip_form`, `created_trip`, `canceled_trip`: ba trạng thái của một form tạo trip trong chat. `content` là chuỗi JSON các trường của `RequestDraft` (thêm `trip_id` khi `created_trip`), không phải văn bản. Tin nhắn chỉ đi từ `trip_form` sang một trong hai trạng thái kia, qua `POST /trips` với `message_id` hoặc `PATCH` bên dưới.

Lỗi: 404 khi không có hội thoại.

### PATCH /conversations/{conversation_id}

Đổi tên hội thoại; `updated_at` giữ nguyên để thứ tự danh sách không đổi. Code: `src/api/routes/chat.py:116`.

Payload:

```json
{ "title": "Đà Lạt tháng 12" }
```

- `title`: bắt buộc, 1 đến 80 ký tự.

Output 200: `data` là `ConversationOut`.

Lỗi: 404 khi không có hội thoại; 422 khi title rỗng hoặc quá dài.

### PATCH /conversations/{conversation_id}/messages/{message_id}

Hủy một form tạo trip: chuyển `intent` của tin nhắn từ `trip_form` sang `canceled_trip`, giữ nguyên `content`. Code: `src/api/routes/chat.py:126`.

Payload:

```json
{ "intent": "canceled_trip" }
```

- `intent`: bắt buộc, chỉ nhận `canceled_trip`.

Output 200: `data` là `MessageOut` (xem `GET /conversations/{conversation_id}`).

Lỗi: 404 khi không có tin nhắn hoặc tin nhắn không thuộc hội thoại trong URL; 409 `conflict` khi tin nhắn không còn là `trip_form` (đã tạo trip hoặc đã hủy); 422 khi `intent` khác `canceled_trip`. Route không kiểm tra user, giống các route hội thoại khác.

### DELETE /conversations/{conversation_id}

Xóa hội thoại và toàn bộ tin nhắn. Code: `src/api/routes/chat.py:141`.

- Payload: không có.
- Output: 204, không có body.
- Lỗi: 404 khi không có hội thoại.

## Chat

### POST /chat

Gửi một tin nhắn vào hội thoại và nhận câu trả lời dạng server-sent events. Nếu có `trip_id`, câu hỏi gắn với trip đang mở và assistant có thể sửa plan của trip đó. Tin nhắn đầu tiên đặt làm tiêu đề hội thoại nếu hội thoại chưa có (80 ký tự đầu). Code: `src/api/routes/chat.py:151`.

Payload:

```json
{
  "conversation_id": "uuid",
  "content": "Đổi bữa tối ngày 2 sang quán chay",
  "trip_id": "uuid",
  "plan_revision": 1
}
```

| Field | Bắt buộc | Ràng buộc |
|---|---|---|
| `conversation_id` | có | UUID của hội thoại đã tồn tại |
| `content` | có | 1 đến 4000 ký tự |
| `trip_id` | không | Trip đang mở trên màn hình |
| `plan_revision` | không | `plan_revision` client đang thấy; nếu khác giá trị hiện tại thì trả về 409 |

Lỗi trả về trước khi stream bắt đầu (dạng envelope JSON): 404 khi không có hội thoại hoặc trip; 409 `conflict` khi `plan_revision` đã cũ hoặc trip chưa có plan; 422 khi `content` rỗng hoặc quá dài; 429 `rate_limited` khi vượt giới hạn chat theo IP hoặc theo user; 429 `quota_exhausted` khi hết quota OpenRouter.

Output 200: `Content-Type: text/event-stream`. Mỗi event có dạng:

```
event: <type>
data: <json>

```

| `event` | `data` | Ý nghĩa |
|---|---|---|
| `token` | `{ "text": "..." }` | Một đoạn câu trả lời (mỗi từ một event), nối lại theo thứ tự |
| `plan` | `{ "plan_revision": 2 }` | Plan của trip đã được ghi đè; client tải lại `GET /trips/{trip_id}` |
| `suggestions` | `{ "cards": [...] }` | Thẻ gợi ý điểm đến (`SuggestionCard`, `src/domain/discovery.py:60`): `name`, `country_code`, `why`, `length_days`, `est_cost_per_person_vnd`, `best_months`, `highlights`, `source_ids` |
| `hotels` | `{ "cards": [...] }` | Thẻ khách sạn cho câu hỏi về giá hoặc lựa chọn khách sạn, sau các `token` (`HotelCard`, `src/domain/hotels.py`): `name`, `area`, `stars` (1-5 hoặc `null`), `price_per_night` (số hoặc `null`), `price_currency`, `highlights`, `source_id`, `url` (trang nguồn, do server gắn). Tối đa 6 thẻ, thẻ có giá đứng trước; không có event này khi không còn thẻ nào |
| `trip_form` | `{ "message_id": "uuid", "draft": {...} }` | Chat nhận ra ý định tạo trip mới và đã lưu một tin nhắn `intent = trip_form`; `draft` là các trường `RequestDraft` điền sẵn từ cuộc trò chuyện (`destination` có tọa độ do server tìm). Không có `token` đi kèm |
| `error` | `{ "code": "...", "message": "..." }` | Câu trả lời dừng vì lỗi; `code` là `quota_exhausted` (kèm `blocked_until`), `conflict`, `not_found`, `invalid_output` hoặc `llm_unavailable` |
| `done` | `{}` | Kết thúc câu trả lời |

Nếu client ngắt kết nối giữa chừng, phần câu trả lời đã gửi vẫn được lưu vào hội thoại.
