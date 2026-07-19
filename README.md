# kg-vending-machine

스타트업/소상공인이 사업계획서를 업로드하면, 기업마당·K-Startup·과학기술정보통신부 등에서
수집한 정부 지원사업 공고 중 실제로 신청 가능하고 사업 내용과 잘 맞는 공고를 AI가 찾아
추천해주는 서비스.

## 매칭 플로우

```
카카오 로그인/회원가입
  → 기업 프로필 입력 (선택 — 비워두면 사업계획서에서 추론)
  → 사업계획서 업로드 (PDF/HWP/HWPX/이미지, OCR·텍스트 추출)
  → 공고 매칭 요청
      1) 1차 필터링 — 지역·대상·업력·신청기간 등 자격요건 하드필터
      2) 2차 필터링 — 공고 PDF를 임베딩해 사업계획서와 유사도 검색,
         상위 후보는 LLM이 요건 문장 단위로 충족 여부까지 판정
      3) AI 매칭 스코어링 — 자격 적합도·아이템 적합도·사업 정합성·
         성장성·가점요소를 종합해 점수 산출
  → 추천 공고 목록 반환
```

세부 설계는 [docs/matching-pipeline.md](docs/matching-pipeline.md),
[docs/first-filtering.md](docs/first-filtering.md),
[docs/secondary-filtering-llm-judge-guide.md](docs/secondary-filtering-llm-judge-guide.md) 참고.

## 구성

- `backend/` — FastAPI, PostgreSQL, SQLAlchemy/Alembic, ChromaDB, OpenAI API. 공고 수집(크롤링),
  Naver CLOVA OCR, AI 매칭·스코어링, 카카오 로그인 등 API 서버 전체 ([backend/README.md](backend/README.md))
- `frontend/` — React 19, TypeScript, React Router ([frontend/README.md](frontend/README.md))
- `docs/` — 아키텍처, 매칭 파이프라인, 설정값 등 설계 문서

## 팀 구성

4인 팀이 아래 영역을 나누어 담당한다 (자세한 폴더 소유권은 [docs/architecture.md](docs/architecture.md) 참고).

- **Backend** — API 라우터/서비스/리포지토리/모델 (`backend/app/api`, `services`, `repositories`, `models` 등)
- **AI** — RAG, 매칭 스코어링 로직 (`backend/app/ai/`)
- **OCR/크롤링·외부 API** — 공공 API 수집, Naver CLOVA OCR (`backend/app/crawler/`, `backend/app/ocr/`)
- **Frontend** — 전체 프론트엔드 (`frontend/`)

## 배포 링크

- 프론트엔드: https://kg-vending-machine.vercel.app/
