# Lựa chọn khách sạn trong chat: thiết kế

## Mục đích

Khi khách hỏi giá hoặc lựa chọn khách sạn ở một nơi (ví dụ "khách sạn ở Hải Phòng 4 sao khoảng tầm bao nhiêu tiền/đêm"), chat tìm trên các trang đặt phòng trong `SEARCH_DOMAINS["accommodation"]` và trả về một câu trả lời ngắn kèm các thẻ khách sạn xếp thành slider ngang. Mỗi thẻ có link về trang nguồn để khách tự xem giá thật. Hiện câu hỏi này đi vào `trip_research`, chỉ đọc `GUIDES`, nên ra Wikivoyage và một đoạn văn dài không có nguồn đặt phòng.

Không làm: giá phòng theo ngày nhận phòng (cần API đối tác), đặt phòng, so sánh giá giữa các trang, thêm khách sạn vào plan từ thẻ.

## Cách làm đã chọn

Cách A: Tavily tìm trên các domain accommodation, model tách đoạn trích thành từng khách sạn. Đã cân nhắc B (thêm Tavily Extract để mở trang, tốn credit và Booking/Agoda hay chặn) và C (API giá theo ngày, cần key mới và có phí).

## Thiết kế

- **Định tuyến:** thêm agent `hotel_options` vào `CATALOG` trong `src/chat/chat_service.py`: câu hỏi về giá, hạng sao hoặc gợi ý khách sạn ở một nơi cụ thể. Step task là câu tìm kiếm. Bỏ ví dụ "where should I stay" khỏi mô tả `travel_advice` để hai agent không chồng nhau; câu hỏi chung kiểu "nên ở khu nào" vẫn là `travel_advice`.
- **Luồng `src/chat/hotel_turn.py`:** tìm với task `"accommodation"` (hàm search sẵn có tự tìm lại toàn web khi các domain không trả gì), lưu hit thành nguồn `kind='accommodation'` của trip hoặc conversation, rồi một lần gọi model (purpose `answer`) qua `call_json` trả `HotelOptionsReply`. Stream `reply` thành token, gửi event `hotels`, lưu message assistant intent `hotel_options` với thẻ trong cột `suggestions` sẵn có.
- **`HotelOptionsReply`** (`src/domain/hotels.py`): `reply` (2-3 câu, cùng ngôn ngữ với khách, nói rõ giá là tham khảo) và `cards`, tối đa 6. Mỗi `HotelCard`: `name`, `area`, `stars` (1-5 hoặc trống), `price_per_night` (số hoặc trống), `price_currency` (mặc định VND), `highlights` (tối đa 3), `source_id` (bắt buộc). Code bỏ thẻ có `source_id` không nằm trong nguồn vừa lưu, và tự gắn `url` từ nguồn; model không bao giờ viết URL.
- **Không tìm được hoặc không thẻ nào dùng được:** chỉ trả lời bằng chữ như `trip_research` hiện nay, không có slider.
- **Database:** migration `0003_hotel_options_intent.sql` thêm `hotel_options` vào `messages_intent_check`. Không thêm cột.
- **Frontend:** `HotelCard` và `HotelSlider` trong `frontend/src/components/`. Slider dùng `overflow-x-auto` + `snap-x` (không thêm thư viện), thẻ rộng khoảng 280px, có nút trước/sau từ 640px trở lên. Thẻ: tên, sao, khu vực, giá "từ X/đêm" kèm badge "Tham khảo" hoặc "Chưa có giá", tối đa 3 điểm nổi bật, link "Xem trên booking.com" (tên miền lấy từ `url`, mở tab mới). Tin nhắn đã lưu có intent `hotel_options` hiện slider từ `suggestions`; khi đang stream thì lấy từ event `hotels`. Thêm chuỗi vào `en.json`/`vi.json`, thêm kịch bản mock và test.

## Để người làm tự quyết

Câu chữ của prompt, cách sắp thẻ (có giá trước), vị trí nút trước/sau.

## Ngoài phạm vi, ghi lại

Chat hiện nguyên dấu `**` vì không render markdown, và trích dẫn kiểu `【26†...】` của model lọt ra câu trả lời. Đây là hai lỗi riêng.
