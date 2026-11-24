# Frontend

Giao diện web của AI trip planner: React 19, TypeScript, Vite, Tailwind CSS v4, TanStack Query và React Router. Cách chạy cả hệ thống nằm ở `README.md` ở thư mục gốc; quy định giao diện nằm ở `CLAUDE.md` và `ui-component-principles.md` trong thư mục này.

## Chạy

```bash
npm install
cp .env.example .env
npm run dev
```

- `VITE_API_BASE_URL`: địa chỉ backend, mặc định `http://localhost:8000`.
- `VITE_API_MOCK=true`: mọi request được trả lời ngay trong trình duyệt bằng dữ liệu giả (MSW, `src/mocks/`), không cần backend. Đặt `false` để gọi backend thật.

## Lệnh

| Lệnh | Việc làm |
|---|---|
| `npm run dev` | Dev server có hot reload |
| `npm test` | Vitest, chạy một lần |
| `npm run lint` | ESLint |
| `npm run typecheck` | `tsc -b` |
| `npm run build` | Typecheck rồi build vào `dist/` |
| `npm run preview` | Xem bản build |

## Thư mục `src/`

- `pages/`: các trang theo route (`NamePage`, `HomePage`, `NewTripPage`, `ChatPage`, `TripPage`).
- `components/`: các thành phần giao diện, kể cả các thẻ trong chat (form tạo trip, thẻ hỏi nhu cầu, thẻ chọn ngày, slider khách sạn và vé).
- `api/`: kiểu dữ liệu của API và các hook TanStack Query; `chat/` đọc stream SSE của `POST /chat`.
- `mocks/`: backend giả cho chế độ mock và cho test.
- `i18n/`: chuỗi giao diện tiếng Anh và tiếng Việt (`en.json`, `vi.json`).
- `styles/recipes.ts`: các class dùng chung; token màu nằm ở `index.css`.
- `format/`, `layout/`, `session/`, `theme/`, `test/`: định dạng tiền và ngày, khung trang, tên người dùng, chế độ sáng tối, tiện ích cho test.
