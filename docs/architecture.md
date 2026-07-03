# 아키텍처 및 폴더 구조

## 계층 구조 (Backend)

Backend는 아래 순서로만 의존하는 계층형 구조를 사용한다.

```
Router (api/v1)
  ↓
Service (services)
  ↓
Repository (repositories)
  ↓
Database (models, db)
```

- Router: HTTP 요청/응답 처리, Pydantic 스키마(`schemas`) 검증만 담당. 비즈니스 로직을 넣지 않는다.
- Service: 비즈니스 로직. 여러 Repository를 조합해 하나의 유스케이스를 완성한다.
- Repository: SQLAlchemy 세션을 직접 다루는 유일한 계층. DB 쿼리는 여기에만 존재한다.
- Models: SQLAlchemy ORM 모델 정의.

역방향 의존(Repository가 Service를 호출하는 등)은 만들지 않는다.

## 폴더 구조

```
kg-vending-machine/
├── backend/
│   └── app/
│       ├── api/v1/       # Router
│       ├── services/     # Service
│       ├── repositories/ # Repository
│       ├── models/       # SQLAlchemy 모델
│       ├── schemas/      # Pydantic 스키마
│       ├── db/           # 엔진, 세션, Base
│       ├── core/         # 설정(config.py) 등 공통 구성
│       ├── utils/        # 공통 유틸 함수
│       ├── ai/           # AI 담당 코드 (LangChain, RAG, 매칭 스코어링)
│       ├── crawler/      # OCR·크롤링 담당 코드 (공공API 수집, NaverCLOVA OCR)
│       └── main.py       # FastAPI 진입점
├── frontend/
│   └── src/
│       ├── api/ components/ hooks/ layouts/ pages/ routes/ store/ types/ utils/
├── docs/                 # 이 문서들
└── docker-compose.yml    # (추후 별도 작업에서 추가 예정)
```

## 팀 역할과 폴더 소유권

| 역할 | 담당자 | 소유 폴더 |
| --- | --- | --- |
| Backend | 김동민 | `backend/app/api`, `core`, `db`, `models`, `repositories`, `schemas`, `services`, `utils` |
| AI | - | `backend/app/ai/` |
| OCR/크롤링 | - | `backend/app/crawler/` |
| Frontend | - | `frontend/` 전체 |

AI, OCR/크롤링 담당자의 코드도 하나의 FastAPI 앱(`backend/app`) 안에 모듈로 포함된다. 별도 서비스로 분리하지 않는 이유는, 현재 단계에서는 하나의 백엔드 프로세스 안에서 함수 호출로 연동하는 것이 가장 단순하기 때문이다. 이후 트래픽/배포 구조가 커지면 별도 서비스 분리를 재검토할 수 있다.
