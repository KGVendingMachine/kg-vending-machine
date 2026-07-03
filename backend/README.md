## 최초 세팅

```bash
cd backend
uv sync                     # 의존성 설치 (.venv 자동 생성, Python 3.12)
cp .env.example .env        # 환경변수 파일 생성 (값은 필요시 docs/configuration.md 참고)
docker compose up -d        # 로컬 postgres 컨테이너 기동
uv run alembic upgrade head # 최신 스키마로 테이블 구성
```

## 서버 실행

```bash
uv run uvicorn app.main:app --reload
```

- Swagger: http://localhost:8000/docs


## 모델(테이블) 변경 시

```bash
# app/models/에 SQLAlchemy 모델 추가/수정 후
uv run alembic revision --autogenerate -m "설명"
uv run alembic upgrade head
```

생성된 `alembic/versions/*.py` 파일은 일반 코드처럼 git에 commit & push해야 다른 사람에게 공유됩니다.

