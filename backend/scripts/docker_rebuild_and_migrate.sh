#!/usr/bin/env bash
# backend/scripts/docker_rebuild_and_migrate.sh
#
# 백엔드 이미지를 캐시 없이 새로 빌드하고, 기존 볼륨(postgres 데이터,
# Chroma 벡터 캐시)은 그대로 둔 채 최신 마이그레이션까지 반영한 뒤 기동한다.
#
# --no-cache가 필요한 이유: docker-compose.yml의 backend 서비스는 로컬
# Dockerfile을 빌드해 쓰는데, 코드만 바뀌고 이미지를 다시 빌드하지 않으면
# 컨테이너가 예전 코드로 계속 떠 있는 채로 재시작될 수 있다(실제로 겪음 —
# 로컬 uvicorn과 별개로 오래된 backend 컨테이너가 포트를 잡고 있어서
# 최신 코드 대신 스테일 이미지가 요청을 처리한 적이 있었다).
#
# docker volume(kg_vending_pgdata, kg_vending_chroma)은 여기서 절대
# 건드리지 않는다 — `docker compose down -v`나 `docker volume rm`을
# 쓰지 않아야 기존 공고·매칭 기록·임베딩 캐시가 보존된다.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

echo "[1/4] backend 이미지 캐시 없이 재빌드"
docker compose build --no-cache backend

echo "[2/4] postgres 기동 (기존 볼륨 데이터 그대로 사용)"
docker compose up -d postgres

echo "[2/4] postgres healthy 대기"
until docker compose exec -T postgres \
  pg_isready -U "${POSTGRES_USER:-kg_vending}" -d "${POSTGRES_DB:-kg_vending}" \
  >/dev/null 2>&1; do
  sleep 1
done

echo "[3/4] 마이그레이션 반영 (backend 서비스 기동 전에 먼저 적용)"
# 이미지 안 의존성은 uv가 관리하는 .venv에 있어(Dockerfile의 CMD도 uv run으로
# 실행) alembic을 직접 exec하면 PATH에 없어 실패한다 — uv run으로 감싼다.
docker compose run --rm backend uv run --no-sync alembic upgrade head

echo "[4/4] backend 기동"
docker compose up -d backend

echo "완료. docker compose ps로 상태 확인 가능."
