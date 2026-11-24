# Intent của tin nhắn chat

Mỗi tin nhắn của người dùng được router (`OrchestratorAgent`) đọc cùng 10 tin nhắn gần nhất, rồi chọn một trong 7 agent của `CATALOG` (`src/chat/chat_service.py:43`). Agent được chọn quyết định intent của câu trả lời (`AGENT_INTENT`, `src/chat/chat_service.py:93`), và intent đó được lưu ở `messages.intent`; phần có cấu trúc của câu trả lời nằm ở `messages.metadata` (bảng ở `docs/api.md`, mục `GET /conversations/{conversation_id}`). Mô tả của từng agent trong `CATALOG` là thứ duy nhất router dựa vào để chọn, nên muốn đổi cách phân loại thì sửa mô tả đó.

## Câu hỏi nào ra intent nào

| Intent | Agent | Câu hỏi có nội dung như thế nào | Ví dụ | Chỉ có trong |
|---|---|---|---|---|
| `advice` | `advice` | Hỏi về plan của trip đang mở, hoặc mẹo, kinh nghiệm du lịch chung, kể cả câu hỏi khi đang tính đi đâu đó. Không tìm web; có plan thì trả lời từ plan | "Ngày 2 đi những đâu?", "Tôi muốn đi Hải Phòng 3 ngày, nên ở khu nào?" | Cả hai |
| `advice` | `web_lookup` | Cần thông tin mới trên web mà plan và kiến thức chung không có. `metadata = {"searched": true}` | "Tháng 7 Đà Nẵng có lễ hội gì?", quy định visa năm nay | Cả hai |
| `discover` | `discover` | Muốn ý tưởng đi đâu, hoặc muốn đi chơi mà chưa có điểm đến. Draft còn thiếu thì mở thẻ hỏi nhu cầu 6 bước, đủ rồi thì gợi ý điểm đến | "Tôi muốn đi du lịch biển", "gợi ý chỗ đi chơi cuối tuần" | Cả hai |
| `booking_search` | `hotel_search` | Tìm khách sạn ở một nơi đã nêu tên, hoặc giá mỗi đêm | "Khách sạn 4 sao ở Đà Nẵng giá bao nhiêu một đêm?" | Cả hai |
| `booking_search` | `flight_search` | Tìm vé máy bay, tàu, xe giữa hai nơi, hoặc giá vé | "vé máy bay Hà Nội đi Đà Nẵng" | Cả hai |
| `create_trip` | `create_trip` | Nhờ thẳng app lên plan cho một trip mới ngay bây giờ, hoặc trả lời "có", "ok", "yes" ngay sau khi assistant hỏi có muốn lên plan không | "Tạo plan trip Đà Lạt 3 ngày cho 2 người đi từ Hà Nội cho tôi" | Cả hai, trừ khi muốn sửa trip đang mở |
| `edit_plan` | `edit_plan` | Sửa plan của trip đang mở: thêm, dời, thay, bỏ, đổi ngày, số người, nơi đi, ngôn ngữ | "Đổi ngày 2 sang đi Cát Bà" | Chat của trip |

## Tin nhắn không qua router

| Khi nào | Chạy gì |
|---|---|
| Tin nhắn gõ tay bị guardrail chặn (`GUARDRAIL_CONFIG` trong `src/chat/guard_turn.py`, prompt và denylist ở `src/guardrail/prompt/*.txt`: `denylist`, rồi `travel_only` chấm `off_topic`, `prompt_injection`, `harmful` từ 0.7) | Trả câu cố định `OFF_TOPIC` (`src/chat/guard_turn.py`), lưu `advice` với `{"blocked": true, "guard": ..., "category": ...}`. Guard chạy trước router (`src/chat/chat_service.py`, `_dispatch`); guard lỗi thì tin nhắn đi tiếp. Bấm thẻ không qua guard |
| `POST /chat` có `discover_message_id` | Đóng thẻ hỏi nhu cầu, gợi ý điểm đến từ draft hiện có. Lưu `discover` với `{"kind": "suggestions"}` |
| `POST /chat` có `booking_message_id` và `dates` | Đóng thẻ chờ ngày, tìm khách sạn hoặc vé với ngày đã chọn. Lưu `booking_search` với `status = results` |
| `PATCH /conversations/{id}/messages/{message_id}` trả lời một bước | Ghi câu trả lời vào thẻ và draft, không gọi AI |
| Bấm Create trên form | `POST /trips` với `message_id` đặt `metadata.status` của form từ `open` thành `created` kèm `trip_id` (`src/api/routes/trips.py`) |
| Bấm Cancel trên form | `PATCH` với `{"status": "canceled"}` đặt `metadata.status` thành `canceled` |

## Các quy tắc code đè lên lựa chọn của router

- Router hỏi lại vì chưa rõ câu hỏi (`needs_clarification`): lưu `advice` với `metadata = {"clarify": true}` (`src/chat/chat_service.py:254-257`).
- Router chọn một agent không có trong `CATALOG`, hoặc không chọn được agent nào sau một lần sửa: chạy `advice` (`src/chat/chat_service.py:262`).
- Router chia câu hỏi thành nhiều bước: chỉ bước đầu tiên chạy, các bước sau bị bỏ (`src/chat/chat_service.py:259-260`).
- `discover` khi đã có thẻ hỏi nhu cầu đang mở (người dùng gõ thay vì bấm): đóng thẻ đó rồi gợi ý luôn, không mở thẻ mới (`src/chat/discovery_turn.py:92-94`).
- `hotel_search` hoặc `flight_search` khi trip đang mở và draft đều không có ngày, ngày đó đã qua hoặc sai luật (hoặc vé chưa có nơi đi): lưu thẻ chờ ngày `need_dates` thay vì tìm (`src/chat/booking_turn.py:55-58`).
- `edit_plan` khi không có trip đang mở có plan: trả câu cố định "Hãy mở chuyến đi bạn muốn thay đổi rồi nhắn lại cho mình nhé." (`src/chat/handlers.py:251-253`).

## Ranh giới dễ nhầm

- `advice` và `create_trip`: nói muốn đi đâu đó kèm một câu hỏi (ở đâu, đi bằng gì, xem gì) là `advice`. Chỉ khi nhờ thẳng "lên plan", "tạo trip" mới ra `create_trip`.
- `advice` và `web_lookup`: cả hai đều lưu intent `advice`. `web_lookup` chỉ khi cần tin mới (lễ hội năm nay, giá vé tham quan, quy định mới); câu hỏi về plan đang mở luôn là `advice`.
- `advice` và `hotel_search`: hỏi khách sạn ở một nơi cụ thể (giá, số sao) là `hotel_search`, có thẻ. Hỏi chung nên ở khu nào là `advice`.
- `discover` và `advice`: chưa có điểm đến và cần ý tưởng là `discover`. Đã nêu điểm đến và hỏi về nó là `advice`.
- `advice` với `clarify` và thẻ hỏi nhu cầu: thẻ hỏi thông tin cơ bản của chuyến đi khi đang tìm điểm đến. `clarify` là router không hiểu câu hỏi.
