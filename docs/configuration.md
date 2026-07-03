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

## 주의할 점

- **새 프론트엔드 배포 주소가 생기면 `CORS_ORIGINS`에 반드시 추가해야 한다.** 안 그러면 배포된 프론트에서 API 호출 시 브라우저가 차단한다.
- 위 기본값은 전부 **로컬 개발용**이다. 실제 배포 환경에서는 `.env`로 덮어써야 하며, 절대 기본값(`postgres`/`postgres`)을 그대로 쓰면 안 된다.
- 환경변수 이름은 `.env.example`(14단계에서 작성)과 반드시 동일하게 유지한다.
