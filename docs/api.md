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
| GET | `/stats/health` | Sức khỏe hệ thống: lượt gọi LLM so với trần, lỗi, hàng đợi job, provider bị chặn |
| GET | `/stats/usage` | Số liệu người dùng, trip và chat trong 7, 30 hoặc 90 ngày |

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

Khi có `message_id`, trong cùng transaction với trip và job, server kiểm tra tin nhắn là form tạo trip (`intent = create_trip`) thuộc một hội thoại của chính `user_id`, đặt `metadata` của tin nhắn thành `{"status": "created", "draft": <các giá trị đã gửi, không có user_id và message_id>, "trip_id": "uuid"}`, và xóa `request_draft` của hội thoại. `message_id` không được ghi vào request của trip. Nếu form không còn `open` (ví dụ hai tab cùng bấm tạo) hoặc tin nhắn không phải form thì trả 409 và không tạo trip hay job nào.

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
  "plan": {}
}
```

- `id` đến `updated_at` là phần `TripSummary`, cũng là phần tử của `GET /users/{user_id}/trips`.
- `total_cost_vnd`, `over_budget`: `null` khi chưa có plan.
- `local_currency`: mã tiền tệ địa phương khi đi nước ngoài, `null` khi đi trong nước.
- `failure_reason`: lý do lỗi khi `status = failed`.
- `plan_revision`: tăng mỗi lần plan bị ghi đè; gửi lại giá trị này ở `POST /chat` để tránh ghi đè lên plan mới hơn.
- `plan`: `null` khi chưa xong. Cấu trúc theo `Plan` trong `src/domain/plan.py:148`: `title`, `summary`, `currencies`, `days` (mỗi ngày có `date`, `theme`, `weather`, `items`), `transport_options`, `accommodation`, `checklist`, `warnings`.

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
      "metadata": null,
      "created_at": "2026-11-19T03:05:00Z"
    }
  ]
}
```

- `role`: `user` hoặc `assistant`.
- `intent`: luồng đã trả lời, một trong `advice`, `discover`, `booking_search`, `create_trip`, `edit_plan`; `null` cho tin nhắn của khách.
- `metadata`: phần có cấu trúc của câu trả lời, theo `intent`:

| `intent` | `metadata` |
|---|---|
| `advice` | `null`; `{"clarify": true}` khi assistant hỏi lại vì chưa rõ câu hỏi; `{"searched": true}` khi câu trả lời dựa trên tìm web; `{"blocked": true, "guard": "travel_only" \| "denylist", "category": "off_topic" \| "prompt_injection" \| "harmful" \| "denylist" \| null}` khi guardrail chặn tin nhắn (câu trả lời cố định, không qua router) |
| `edit_plan` | `null` |
| `discover`, thẻ hỏi nhu cầu | `{"kind": "questionnaire", "status": "open" \| "done", "step": 0-6, "answers": {...}, "choices": {...}}`; `content` là `""` |
| `discover`, gợi ý | `{"kind": "suggestions", "cards": [...]}`, thẻ là `SuggestionCard` (`src/domain/discovery.py:60`) |
| `booking_search`, chờ ngày | `{"kind": "hotel" \| "flight", "status": "need_dates" \| "done", "query": "..."}`; `content` là câu hỏi ngày |
| `booking_search`, kết quả | `{"kind": "hotel" \| "flight", "status": "results", "query": "...", "dates": {...}, "cards": [...]}`; `cards` có thể rỗng |
| `create_trip` | `{"status": "open" \| "created" \| "canceled", "draft": {...}, "trip_id": "uuid" \| null}`; `content` là `""` |

- Thẻ hỏi nhu cầu: `step` là bước xa nhất khách đã trả lời (0 khi chưa trả lời bước nào), `answers` là các trường `RequestDraft` đã biết, `choices` ghi id nút khách bấm theo số bước (`null` khi khách nhập tay hoặc bỏ qua). Tin nhắn `ask` cũ (trước migration 0004) có `status = done`, `answers` rỗng và `content` là câu hỏi dạng text.
- `dates` của kết quả: `{"check_in", "check_out"}` cho khách sạn, `{"depart", "return"}` cho vé (`return` có thể `null`); `null` ở tin nhắn khách sạn cũ trước migration 0004.
- Thẻ khách sạn (`HotelCard`, `src/domain/hotels.py:25`): `name`, `area`, `stars` (1-5 hoặc `null`), `price_per_night` (số hoặc `null`), `price_currency`, `highlights`, `source_id`, `url`. Thẻ vé (`FlightCard`, `src/domain/flights.py:26`): `carrier`, `mode` (`flight`, `train`, `bus`, `car`, `motorbike`, `boat`), `route`, `duration_text`, `price_from` (số hoặc `null`), `price_currency`, `highlights`, `source_id`, `url`. `url` do server gắn từ nguồn; tối đa 6 thẻ, thẻ có giá đứng trước.
- Form tạo trip chỉ đi từ `open` sang `created` (qua `POST /trips` với `message_id`) hoặc `canceled` (qua `PATCH` bên dưới).

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

Hủy một form tạo trip, hoặc trả lời một bước của thẻ hỏi nhu cầu. Không gọi AI. Code: `src/api/routes/chat.py:130`.

Payload hủy form (`metadata.status` từ `open` sang `canceled`, giữ nguyên `draft`):

```json
{ "status": "canceled" }
```

Payload trả lời thẻ hỏi nhu cầu đang `open`:

```json
{ "step": 3, "choice": "saver", "answers": {} }
```

| Field | Bắt buộc | Ràng buộc |
|---|---|---|
| `step` | có | 1 đến 6: `styles`, `travelers`, `budget`, `origin`, `when`, `length` |
| `choice` | không | Id nút của bước (`OPTIONS`, `src/domain/questionnaire.py:56`); bước 1 là mảng id. `null` khi khách nhập tay hoặc bỏ qua |
| `answers` | không | Giá trị khách nhập khi `choice` là `null`, chỉ các trường của bước đó: `travel_styles`, `travelers`, `budget_amount`, `origin`, `start_date` (không ở quá khứ), `length_days`. Bước 6 nhận thêm `notes` cạnh một nút |

Server đổi nút sang giá trị (`answer_for`, `src/domain/questionnaire.py:69`), gộp vào `metadata.answers` và `request_draft` của hội thoại, ghi `choices[step]`, và đặt `step` bằng giá trị lớn hơn giữa bước cũ và bước vừa trả lời. `choice` và `answers` cùng rỗng là bỏ qua bước.

Output 200: `data` là `MessageOut` (xem `GET /conversations/{conversation_id}`).

Lỗi: 404 khi không có tin nhắn hoặc tin nhắn không thuộc hội thoại trong URL; 409 `conflict` khi form không còn `open`, thẻ đã `done`, hoặc body không hợp với loại tin nhắn (hủy một thẻ hỏi, trả lời một form); 422 khi body không khớp dạng nào, `step` ngoài 1-6, id nút lạ hoặc giá trị nhập sai. Route không kiểm tra user, giống các route hội thoại khác.

### DELETE /conversations/{conversation_id}

Xóa hội thoại và toàn bộ tin nhắn. Code: `src/api/routes/chat.py:141`.

- Payload: không có.
- Output: 204, không có body.
- Lỗi: 404 khi không có hội thoại.

## Chat

### POST /chat

Gửi một tin nhắn vào hội thoại và nhận câu trả lời dạng server-sent events. Nếu có `trip_id`, câu hỏi gắn với trip đang mở và assistant có thể sửa plan của trip đó. Tin nhắn đầu tiên đặt làm tiêu đề hội thoại nếu hội thoại chưa có (80 ký tự đầu). Code: `src/api/routes/chat.py:170`.

Thường thì router chọn luồng trả lời. Khi có `discover_message_id` hoặc `booking_message_id`, server bỏ qua router và chạy luồng của thẻ đó: gợi ý điểm đến từ draft hiện có, hoặc tìm khách sạn/vé với ngày khách chọn. Thẻ được đặt `status = done` trước khi trả lời.

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
| `discover_message_id` | không | Id của thẻ hỏi nhu cầu đang `open` trong hội thoại này; không gửi cùng `booking_message_id` |
| `booking_message_id` | không | Id của thẻ chờ ngày (`need_dates`) trong hội thoại này; cần `dates` |
| `dates` | khi có `booking_message_id` | Khách sạn: `check_in`, `check_out` (không ở quá khứ, trả phòng sau nhận phòng, tối đa 30 đêm). Vé: `depart` (không ở quá khứ), `return` tùy chọn (không trước `depart`) |
| `origin` | không | Nơi xuất phát cho thẻ vé; bắt buộc khi trip đang mở và draft đều không có |

Ngày và nơi xuất phát được ghi vào `request_draft` khi draft chưa có.

Thẻ được đặt `done` trước khi lưu tin nhắn của người dùng và trước khi stream bắt đầu, nên lần bấm thứ hai (cùng tab hay tab khác) nhận 409 và không lưu gì. Nếu stream lỗi hoặc bị đóng trước token đầu tiên, thẻ được mở lại (`open` hoặc `need_dates`) để bấm lần nữa.

Lỗi trả về trước khi stream bắt đầu (dạng envelope JSON): 404 khi không có hội thoại, trip, hoặc thẻ không thuộc hội thoại; 409 `conflict` khi `plan_revision` đã cũ, trip chưa có plan, hoặc thẻ đã `done`; 422 khi `content` rỗng hoặc quá dài, gửi cả hai id, `booking_message_id` thiếu `dates`, hoặc ngày sai luật; 429 `rate_limited` khi vượt giới hạn chat theo IP hoặc theo user; 429 `quota_exhausted` khi hết quota OpenRouter.

Output 200: `Content-Type: text/event-stream`. Mỗi event có dạng:

```
event: <type>
data: <json>

```

| `event` | `data` | Ý nghĩa |
|---|---|---|
| `token` | `{ "text": "..." }` | Một đoạn câu trả lời (mỗi từ một event), nối lại theo thứ tự |
| `plan` | `{ "plan_revision": 2 }` | Plan của trip đã được ghi đè; client tải lại `GET /trips/{trip_id}` |
| `metadata` | `{ "message_id": "uuid" \| null, "metadata": {...} }` | Phần có cấu trúc của câu trả lời, đúng object sẽ lưu vào `messages.metadata` (bảng ở `GET /conversations/{conversation_id}`), gửi một lần sau các `token`. `message_id` có giá trị khi tin nhắn đã được lưu trước event (thẻ hỏi nhu cầu, thẻ chờ ngày, form tạo trip), `null` khi tin nhắn được lưu lúc stream kết thúc (gợi ý, kết quả tìm). Thẻ hỏi nhu cầu và form tạo trip không có `token` đi kèm |
| `error` | `{ "code": "...", "message": "..." }` | Câu trả lời dừng vì lỗi; `code` là `quota_exhausted` (kèm `blocked_until`), `conflict`, `not_found`, `invalid_output` hoặc `llm_unavailable` |
| `done` | `{}` | Kết thúc câu trả lời |

Nếu client ngắt kết nối giữa chừng, phần câu trả lời đã gửi vẫn được lưu vào hội thoại.

## Stats

Số liệu cho trang `/dashboard`. Hai endpoint này không cần xác thực (như mọi endpoint khác), nên chỉ trả số đếm và nhãn gộp (tên điểm đến, model, intent), không trả tên user, id, ghi chú trip, `jobs.last_error` hay `quota_blocks.reason`. Trip user đã xóa không được tính; tin nhắn của user không có trip bị xóa sau 90 ngày không hoạt động.

### GET /stats/health

Không có tham số. Số liệu tính theo giờ của database; "hôm nay" của LLM là ngày UTC, giống trần quota.

Output 200:

```json
{
  "generated_at": "2026-11-24T12:00:00Z",
  "llm_today": { "calls": 812, "input_tokens": 1200000, "output_tokens": 340000, "ceiling_new_trips": 800, "ceiling_chat": 950 },
  "llm_last_hour": { "calls": 120, "errors": 17, "outcomes": [{ "key": "ok", "count": 103 }], "p50_latency_ms": 2100.0, "p95_latency_ms": 8200.0 },
  "jobs": { "queued": 3, "running": 1, "oldest_queued_s": 120 },
  "plans_last_day": { "succeeded": 40, "p50_s": 48.0, "p95_s": 110.0, "failed": 2, "last_failure": { "reason": "generation_failed", "finished_at": "2026-11-24T11:20:00Z" } },
  "blocks": [{ "service": "openrouter", "blocked_until": "2026-11-25T00:00:00Z" }]
}
```

- `llm_today.calls`: tổng lượt gọi từ 00:00 UTC. Trip mới bị từ chối khi đạt `ceiling_new_trips`, chat bị từ chối khi đạt `ceiling_chat`.
- `llm_last_hour`: `errors` là các call có `outcome` khác `ok`; percentile là `null` khi không có call nào có latency.
- `jobs.oldest_queued_s`: tuổi (giây) của job đang chờ lâu nhất, `null` khi không có job chờ.
- `plans_last_day`: các job kết thúc trong 24 giờ; thời gian tạo plan tính từ lúc vào hàng đợi; `last_failure.reason` là `trips.failure_reason`, `null` khi không có job lỗi.
- `blocks`: provider đang bị chặn.

### GET /stats/usage

Query: `days` = `7`, `30` hoặc `90` (mặc định `30`); giá trị khác trả 422. Khoảng thời gian là `days` ngày lịch Việt Nam gần nhất, tính cả hôm nay.

Output 200:

```json
{
  "days": 30,
  "users": { "total": 310, "new": 42, "active": 96 },
  "trips": { "created": 118, "by_status": [{ "key": "ready", "count": 107 }], "domestic": 85, "abroad": 33, "avg_days": 4.2, "avg_travelers": 2.3, "median_budget_per_person_vnd": 6000000.0, "with_plan": 107, "over_budget": 19 },
  "daily": [{ "day": "2026-11-24", "trips": 5, "messages": 40 }],
  "conversations": 204,
  "messages": 1204,
  "intents": [{ "key": "advice", "count": 600 }],
  "trip_forms": [{ "key": "created", "count": 30 }],
  "destinations": [{ "name": "Đà Lạt", "country": "VN", "trips": 21 }],
  "styles": [{ "key": "food", "count": 72 }],
  "models": [{ "model_id": "a/b:free", "calls": 4100, "errors": 250 }]
}
```

- `users.active`: user có `last_seen_at` trong khoảng.
- `trips`: trip tạo trong khoảng. `median_budget_per_person_vnd` là trung vị ngân sách mỗi người (VND), `null` khi không có trip; `over_budget` đếm trong các trip đã có plan (`with_plan`).
- `daily`: đủ `days` phần tử, ngày trống là 0; `messages` chỉ đếm tin nhắn của user.
- `messages`: tin nhắn của user; `intents`: tin nhắn trả lời theo intent; `trip_forms`: form tạo trip trong chat theo trạng thái (`open`, `created`, `canceled`).
- `destinations`: tối đa 10, nhiều trip nhất trước.
- Các list `{ key, count }` xếp theo `count` giảm dần, rồi theo `key`.
