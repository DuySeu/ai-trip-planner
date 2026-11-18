FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH"

WORKDIR /app
RUN pip install --no-cache-dir uv

# Dependencies first so code changes reuse this layer
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY src ./src
COPY sql ./sql
COPY scripts ./scripts
COPY data ./data

EXPOSE 8000
CMD ["uvicorn", "api.main:app_factory", "--factory", "--host", "0.0.0.0", "--port", "8000"]
