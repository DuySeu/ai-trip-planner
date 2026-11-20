# ai-trip-planner

## Chuẩn bị

Cần Docker (có Compose), uv, Python 3.12 và Node 24 cho frontend. Các lệnh dev bên dưới giả định virtual environment Python đã được kích hoạt.

Tạo file cấu hình ở root rồi điền các giá trị:

```bash
cp .env.example .env
```

- Bắt buộc: `DB_*`, `OPENROUTER_API_KEY`, `TAVILY_API_KEY`, `PLANNER_MODELS`, `CHAT_MODELS`, `CLASSIFIER_MODELS` (model id lấy trong `src/core/constants.py`), `DAILY_LLM_CEILING_NEW_TRIPS`, `DAILY_LLM_CEILING_CHAT`, `DAILY_TAVILY_CEILING`. Các biến còn lại có mặc định trong `src/core/settings.py`.
- `DAILY_LLM_CEILING_CHAT` phải lớn hơn `DAILY_LLM_CEILING_NEW_TRIPS`, nếu không API và worker sẽ dừng ngay khi khởi động. Cả hai cùng so với tổng số lần gọi LLM trong ngày; phần chênh lệch là quota dành riêng cho chat.
- Để `DB_HOST=localhost`. Khi chạy trong Docker, compose tự đổi thành `db`, nên một file `.env` dùng được cho cả dev và production.

## Production

Chạy cả 4 service (Postgres, API, worker, frontend) bằng Docker:

```bash
docker compose up -d --build
docker compose logs -f api worker
```

- Frontend: http://localhost:8080
- API: http://localhost:8000, Swagger ở http://localhost:8000/docs
- `api` và `worker` tự áp migration khi khởi động.
- Sửa `.env` thì chỉ cần `docker compose up -d api worker`; sửa code thì thêm `--build`.
- Chạy nhiều worker song song: `docker compose up -d --scale worker=3`.

URL của API được gắn vào bundle frontend lúc build. Khi deploy lên domain thật, sửa build arg `VITE_API_BASE_URL` của service `frontend` và `CORS_ORIGINS` của service `api` trong `docker-compose.yml`, rồi build lại.

## Dev

Chỉ Postgres chạy trong Docker; API, worker và frontend chạy ở terminal để có hot reload. Mọi lệnh Python chạy trong venv đang kích hoạt.

```bash
uv sync --active --inexact
docker compose up -d db
PYTHONPATH=src python scripts/migrate.py
```

Mỗi lệnh sau một terminal:

```bash
# API, reload khi sửa code
PYTHONPATH=src uvicorn api.main:app_factory --factory --reload

# Worker, khởi động lại khi sửa file .py trong src
PYTHONPATH=src watchfiles --filter python "python -m service.worker.worker" src

# Frontend
cd frontend && npm install && npm run dev
```

- Frontend đọc `frontend/.env` (mẫu ở `frontend/.env.example`). `VITE_API_MOCK=true` trả dữ liệu giả ngay trong trình duyệt; đặt `false` để gọi backend thật ở `VITE_API_BASE_URL`.
- Không cần đặt `CORS_ORIGINS` khi dev, giá trị mặc định đã cho phép frontend dev server.
- Khi worker khởi động lại giữa chừng, job đang chạy sẽ được chạy lại sau khi lease hết hạn, và các lượt gọi LLM của job đó bị mất.
- `uv sync` cần `--active` để cài vào venv đang kích hoạt; thiếu nó uv sẽ tạo `./.venv` riêng trong repo. `--inexact` giữ lại các package khác đã có trong venv.

Test và lint:

```bash
pytest
cd frontend && npm test && npm run lint && npm run build
```

## Sự cố thường gặp

`password authentication failed` hoặc `Role "..." does not exist` khi migrate: Postgres chỉ đọc `DB_USER`, `DB_PASSWORD`, `DB_NAME` lần đầu tạo volume. Nếu đổi các giá trị này sau đó, hoặc đặt `DB_*` về giá trị cũ, hoặc xóa volume để tạo lại (mất toàn bộ dữ liệu trong database):

```bash
docker compose down -v
docker compose up -d --build
```

Tài liệu các endpoint ở `docs/api.md`.
