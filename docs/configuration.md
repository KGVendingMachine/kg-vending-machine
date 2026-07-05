# 환경 설정 (Settings)

`backend/app/core/config.py`의 `Settings` 클래스가 앱 전체 설정을 관리한다. `.env` 파일(gitignore 대상)의 값을 읽고, 없으면 아래 기본값을 사용한다.

| 필드 | 기본값 | 설명 |
| --- | --- | --- |
| `PROJECT_NAME` | `KG Vending Machine` | Swagger 문서 제목 등에 사용 |
| `API_V1_PREFIX` | `/api/v1` | 모든 API 라우터의 공통 prefix |
| `ENVIRONMENT` | `local` | 실행 환경 구분자 (local/dev/prod 등) |
| `DEBUG` | `true` | 디버그 모드 여부 |
| `CORS_ORIGINS` | `["http://localhost:5173"]` | CORS 허용 출처 목록. Frontend 배포 주소가 늘어나면(Vercel 등) 이 목록에 추가해야 한다 |
| `POSTGRES_USER` | `postgres` | DB 계정 |
| `POSTGRES_PASSWORD` | `postgres` | DB 비밀번호 |
| `POSTGRES_HOST` | `localhost` | DB 호스트 |
| `POSTGRES_PORT` | `5432` | DB 포트 |
| `POSTGRES_DB` | `kg_vending` | DB 이름 |
| `BIZINFO_API_KEY` | (없음) | 기업마당 오픈API 인증키 |
| `BIZINFO_API_URL` | bizinfoApi.do 주소 | 기업마당 공고 목록 API |
| `BIZINFO_PAGE_SIZE` | `100` | 한 번에 가져올 공고 수 (`pageUnit` 파라미터로 전달) |
| `BIZINFO_REQUEST_TIMEOUT_SECONDS` | `15` | 요청 타임아웃 |
| `BIZINFO_MAX_RETRIES` | `3` | 실패 시 재시도 횟수 |
| `KSTARTUP_API_KEY` | (없음) | data.go.kr K-Startup 오픈API 인증키(Decoding 키) |
| `KSTARTUP_API_URL` | getAnnouncementInformation01 주소 | K-Startup 공고 목록 API |
| `KSTARTUP_PAGE_SIZE` | `100` | 한 번에 가져올 공고 수 (`perPage` 파라미터로 전달) |
| `KSTARTUP_REQUEST_TIMEOUT_SECONDS` | `15` | 요청 타임아웃 |
| `KSTARTUP_MAX_RETRIES` | `3` | 실패 시 재시도 횟수 |

### 기업마당 API 페이징 주의사항 (#3에서 확인)

기업마당 API는 `searchCnt`만 보내면 페이지 이동 없이 항상 첫 페이지만 반환한다. 실제 페이징은 `pageUnit`(페이지당 개수) + `pageIndex`(페이지 번호) 조합으로 해야 하며, `searchCnt`와 `pageIndex`를 같이 보내면 `"한 페이지의 보여지는 데이터 개수를 입력해주세요"` 에러가 난다. 공식 문서에 명확히 안 나와 있어 실제 호출로 확인한 내용이다. `app/crawler/bizinfo_client.py`가 이미 올바른 조합을 쓰고 있다.

## 예약된 환경변수 (아직 Settings에 미연결)

`backend/.env.example`에는 위 표에 없는 변수도 있다. 아직 해당 기능이 구현되지 않아 이름만 미리 정해둔 상태이며, 지금은 `Settings` 클래스가 이 값을 읽지 않는다.

- `OPENAI_API_KEY` — AI 모듈(정규화, 매칭, RAG)
- `CLOVA_OCR_*` — Naver CLOVA OCR
- `STORAGE_ROOT`, `MAX_UPLOAD_SIZE_BYTES`, `PDF_OCR_TEXT_THRESHOLD`, `PPTX_OCR_TEXT_THRESHOLD` — 사업계획서 업로드/OCR 판별 기준

해당 기능을 실제로 구현하는 시점에 담당자가 자신의 모듈(`app/ai/` 등)에 맞는 Settings(또는 별도 설정 클래스)를 만들어 이 값을 읽도록 연결하면 된다.

## 주의할 점

- **새 프론트엔드 배포 주소가 생기면 `CORS_ORIGINS`에 반드시 추가해야 한다.** 안 그러면 배포된 프론트에서 API 호출 시 브라우저가 차단한다.
- 위 기본값은 전부 **로컬 개발용**이다. 실제 배포 환경에서는 `.env`로 덮어써야 하며, 절대 기본값(`postgres`/`postgres`)을 그대로 쓰면 안 된다.
- 환경변수 이름은 `.env.example`(14단계에서 작성)과 반드시 동일하게 유지한다.
- DB 접속 계정을 `postgres`가 아닌 별도 계정(예: `kg_vending`)으로 바꾸는 경우, 그 계정에게 테이블 DML 권한(GRANT)만 주는 것으로는 부족하다. `alembic`으로 `ALTER TABLE`(제약 추가 등)을 실행하려면 **테이블 소유주(owner)**여야 하므로, 기존에 `postgres`로 만들어둔 테이블은 `ALTER TABLE ... OWNER TO kg_vending;`으로 소유권을 넘겨줘야 한다. 안 그러면 `InsufficientPrivilegeError`가 난다.
