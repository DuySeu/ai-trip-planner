# Intent của tin nhắn chat

Mỗi tin nhắn của người dùng được router (`OrchestratorAgent`) đọc cùng 10 tin nhắn gần nhất, rồi chọn một agent trong `CATALOG` (`src/chat/chat_service.py:42`). Agent được chọn quyết định intent của câu trả lời, và intent đó được lưu ở `messages.intent`. Mô tả của từng agent trong `CATALOG` là thứ duy nhất router dựa vào để chọn, nên muốn đổi cách phân loại thì sửa mô tả đó.

## Câu hỏi nào ra intent nào

| Intent | Agent | Câu hỏi có nội dung như thế nào | Ví dụ | Chỉ có trong |
|---|---|---|---|---|
| `plan_answer` | `plan_answer` | Hỏi về plan của trip đang mở: lịch ngày nào, giá món nào, đi gì, ở đâu trong plan | "Ngày 2 đi những đâu?", "Tổng chi phí là bao nhiêu?" | Chat của trip |
| `plan_editor` | `plan_editor` | Muốn sửa plan của trip đang mở: thêm, dời, thay, bỏ một mục, hoặc đổi ngày, số người, điểm xuất phát, ngôn ngữ | "Bỏ chợ đêm ngày 1", "Đổi thành 3 người" | Chat của trip |
| `trip_research` | `trip_research` | Cần thông tin mới mà plan chưa có, phải tìm trên web | "Có khách sạn nào rẻ hơn gần biển không?" | Chat của trip (về lý thuyết cũng chạy ở /chat) |
| `travel_advice` | `travel_advice` | Hỏi mẹo, kinh nghiệm du lịch chung, không gắn với plan và không phải đang chọn điểm đến. Gồm cả câu hỏi khi đang tính đi đâu đó mà chưa nhờ lên plan | "Tôi muốn đi Hải Phòng 3 ngày, nên ở khu nào và đi lại bằng gì?", "Đi Phú Quốc tháng 7 có bị mưa nhiều không?" | Cả hai |
| `hotel_options` | `hotel_options` | Hỏi về khách sạn ở một nơi đã nêu tên: giá mỗi đêm, chọn khách sạn mấy sao hay theo ngân sách | "Khách sạn 4 sao ở Đà Nẵng giá bao nhiêu một đêm?", "khách sạn gần biển Đồ Sơn giá rẻ" | Cả hai |
| `trip_form` | `create_trip` | Nhờ thẳng app lên plan cho một trip mới ngay bây giờ, hoặc trả lời "có", "ok", "yes" ngay sau khi assistant hỏi có muốn lên plan không | "Tạo plan trip Đà Lạt 3 ngày cho 2 người đi từ Hà Nội cho tôi", "make the plan for me" | Cả hai, trừ khi muốn sửa trip đang mở |
| `ask` | `discover_ask` | Đang tìm xem nên đi đâu nhưng còn thiếu thông tin cơ bản: thời gian hoặc tháng, ngân sách, nơi xuất phát, ai đi | "Tôi muốn đi du lịch biển" | Luồng tìm điểm đến |
| `suggest` | `discover_suggest` | Đang tìm xem nên đi đâu và đã có đủ thông tin cơ bản, hoặc bảo cứ gợi ý | "Gợi ý vài bãi biển cho 2 người đi từ Hà Nội tháng 7, 4 ngày, ngân sách 10 triệu" | Luồng tìm điểm đến |
| `answer` | `discover_answer` | Đang chọn điểm đến và hỏi chung về nơi chốn, mùa, chi phí, visa mà không cần thẻ gợi ý | "Thái Lan có cần visa không?" | Luồng tìm điểm đến |
| `clarification` | không có | Router không giao cho agent nào: câu không nói rõ cần làm gì, nhắc tới thứ không xác định được ("cái đó"), hoặc không agent nào làm được việc được hỏi (đặt phòng, thanh toán, gửi tin nhắn) | "Làm cái đó giúp tôi", "Đặt phòng giúp tôi" | Cả hai |

## Intent không đến từ câu hỏi

| Intent | Khi nào xuất hiện |
|---|---|
| `created_trip` | Người dùng bấm Create trên form trong chat. `POST /trips` với `message_id` chuyển tin nhắn `trip_form` thành `created_trip` (`src/api/routes/trips.py:54`) |
| `canceled_trip` | Người dùng bấm Cancel trên form. `PATCH /conversations/{id}/messages/{message_id}` chuyển `trip_form` thành `canceled_trip` |

## Các quy tắc code đè lên lựa chọn của router

- Router trả một trạng thái khác `routed` và `needs_clarification`, nên không có agent nào được chọn: intent là `plan_answer` khi đang ở trong trip, `travel_advice` khi không (`src/chat/chat_service.py:197-198`).
- Router chọn `plan_answer` mà trip chưa có plan: chuyển sang `travel_advice` (`src/chat/chat_service.py:199-200`).
- Router chia câu hỏi thành nhiều bước: chỉ bước đầu tiên chạy, các bước sau bị bỏ (`src/chat/chat_service.py:194-195`).
- Hội thoại đã có 2 câu trả lời `ask` (`MAX_ASKS = 2`, `src/chat/discovery_turn.py:32`): lần chọn `ask` tiếp theo chạy thành `suggest`, để người dùng không bị hỏi mãi.
- `plan_editor` ở /chat (không có trip đang mở): trả câu cố định "Hãy mở chuyến đi bạn muốn thay đổi rồi nhắn lại cho mình nhé." (`src/chat/handlers.py:55-58`).

## Ranh giới dễ nhầm

- `travel_advice` và `trip_form`: nói muốn đi đâu đó kèm một câu hỏi (ở đâu, đi bằng gì, xem gì) là `travel_advice`. Chỉ khi nhờ thẳng "lên plan", "tạo trip" mới ra `trip_form`.
- `travel_advice` và `answer`: cả hai đều là hỏi đáp chung. `answer` chỉ dùng khi người dùng đang trong quá trình chọn điểm đến, còn lại là `travel_advice`.
- `travel_advice` và `hotel_options`: hỏi về khách sạn ở một nơi cụ thể (giá, số sao) là `hotel_options`. Hỏi chung nên ở khu nào là `travel_advice`.
- `trip_research` và `hotel_options`: trong trip, hỏi tìm khách sạn có giá hoặc số sao cụ thể nên ra `hotel_options` (có thẻ). Tìm thông tin khác mà plan chưa có là `trip_research`.
- `ask` và `clarification`: cả hai đều hỏi lại. `ask` hỏi thông tin cơ bản của chuyến đi khi đang tìm điểm đến. `clarification` là router không hiểu câu hỏi hoặc không có agent làm được.

## Kết quả thử trên /chat ngày 2026-11-20

| Câu hỏi | Dự kiến | Thực tế |
|---|---|---|
| Tôi muốn đi du lịch biển | `ask` | `clarification` |
| Gợi ý vài bãi biển cho 2 người đi từ Hà Nội tháng 7, 4 ngày, ngân sách 10 triệu | `suggest` | `suggest` |
| Đi Phú Quốc tháng 7 có bị mưa nhiều không? | `answer` | `travel_advice` |
| Tôi muốn đi Hải Phòng 3 ngày, nên ở khu nào và đi lại bằng gì? | `travel_advice` | `travel_advice` |
| Khách sạn 4 sao ở Đà Nẵng giá bao nhiêu một đêm? | `hotel_options` | `hotel_options` |
| Tạo plan trip Đà Lạt 3 ngày cho 2 người đi từ Hà Nội cho tôi | `trip_form` | `trip_form` |

Router dùng model miễn phí trên OpenRouter, nên cùng một câu có thể ra intent khác nhau giữa các lần chạy.
