# kg-vending-machine backend

스타트업 사업계획서를 업로드하면 기업마당·K-Startup·과학기술정보통신부 등에서 수집한
정부 지원사업 공고와 AI로 매칭해, 적합한 공고를 추천해주는 서비스의 API 서버(FastAPI, PostgreSQL).

공고 수집(OCR/크롤링), 정규화, AI 매칭·스코어링, 인증(카카오 로그인) 등을 담당한다.
전체 프로젝트 구성은 [루트 README](../README.md) 참고.

## 배포 링크

- 프론트엔드: https://kg-vending-machine.vercel.app/

## 최초 세팅

```bash
cd backend
uv sync                     # 의존성 설치 (.venv 자동 생성, Python 3.12)
cp .env.example .env        # 환경변수 파일 생성 (값은 필요시 docs/configuration.md 참고)
docker compose -f ../docker-compose.local.yml up -d  # 로컬 postgres 컨테이너 기동 (5434)
uv run alembic upgrade head # 최신 스키마로 테이블 구성
cd .. && backend/.venv/bin/pre-commit install  # 커밋 시 black/ruff 자동 검사 훅 등록
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

