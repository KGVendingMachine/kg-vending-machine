# 환경 설정 (Settings)

`backend/app/core/config.py`의 `Settings` 클래스가 앱 전체 설정을 관리한다. `.env` 파일(gitignore 대상)의 값을 읽고, 없으면 아래 기본값을 사용한다.

| 필드 | 기본값 | 설명 |
| --- | --- | --- |
| `PROJECT_NAME` | `KG Vending Machine` | Swagger 문서 제목 등에 사용 |
| `API_PREFIX` | `/api` | 모든 API 라우터의 공통 prefix. 버전 번호(v1) 없이 도메인명으로 구분한다 |
| `ENVIRONMENT` | `local` | 실행 환경 구분자 (local/dev/prod 등) |
| `DEBUG` | `true` | 디버그 모드 여부 |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | CORS 허용 출처 목록. Frontend 배포 주소가 늘어나면(Vercel 등) 이 목록에 추가해야 한다 |
| `POSTGRES_USER` | `kg_vending` | DB 계정 |
| `POSTGRES_PASSWORD` | `1234` | DB 비밀번호 |
| `POSTGRES_HOST` | `localhost` | DB 호스트 |
| `POSTGRES_PORT` | `5432` | DB 포트 |
| `POSTGRES_DB` | `kg_vending` | DB 이름 |

## 예약된 환경변수 (아직 Settings에 미연결)

`backend/.env.example`에는 위 표에 없는 변수도 있다. OCR/크롤링 기능(기업마당·K-Startup API 수집, Naver CLOVA OCR)이 실제로 구현되기 전까지는 이름만 미리 정해둔 상태이며, 지금은 `Settings` 클래스가 이 값을 읽지 않는다.

- `BIZINFO_*` — 기업마당 공고 수집 API
- `KSTARTUP_*` — K-Startup 공고 수집 API
- `CLOVA_OCR_*` — Naver CLOVA OCR
- `STORAGE_ROOT`, `MAX_UPLOAD_SIZE_BYTES`, `PDF_OCR_TEXT_THRESHOLD`, `PPTX_OCR_TEXT_THRESHOLD` — 사업계획서 업로드/OCR 판별 기준

해당 기능을 실제로 구현하는 시점에 담당자가 자신의 모듈(`app/crawler/`, `app/ai/` 등)에 맞는 Settings(또는 별도 설정 클래스)를 만들어 이 값을 읽도록 연결하면 된다.

## 주의할 점

- **새 프론트엔드 배포 주소가 생기면 `CORS_ORIGINS`에 반드시 추가해야 한다.** 안 그러면 배포된 프론트에서 API 호출 시 브라우저가 차단한다.
- 위 기본값은 전부 **로컬 개발용**이다. 실제 배포 환경에서는 `.env`로 덮어써야 하며, 절대 기본값(`kg_vending`/`1234`)을 그대로 쓰면 안 된다.
- 환경변수 이름은 `.env.example`(14단계에서 작성)과 반드시 동일하게 유지한다.
- 로컬 PostgreSQL에는 `postgres` 슈퍼유저 계정 외에 `kg_vending` 계정을 별도로 만들어 `kg_vending` DB에 대한 전체 권한을 부여해야 한다 (`CREATE ROLE kg_vending WITH LOGIN PASSWORD '1234';` 후 DB/스키마/테이블/시퀀스 권한 GRANT).
