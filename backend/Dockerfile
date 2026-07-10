FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

# 의존성 레이어를 코드 레이어보다 먼저 캐싱 — 코드만 바뀌면 uv sync를 다시 안 돌리게
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8000

# --workers 옵션을 추가하지 않는다 — ChromaDB PersistentClient가 SQLite 기반이라
# 다중 프로세스 동시 쓰기를 지원하지 않는다 (xuswns/chromadb-embedded-deployment.md 4번 항목)
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
