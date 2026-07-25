from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    PROJECT_NAME: str = "KG Vending Machine"
    API_PREFIX: str = "/api"
    ENVIRONMENT: str = "local"
    DEBUG: bool = True

    CORS_ORIGINS: list[str] = ["http://localhost:5173"]
    FRONTEND_URL: str = "http://localhost:5173"
    """카카오 로그인 완료 후 되돌아갈 프론트 주소."""

    POSTGRES_USER: str = "kg_vending"
    POSTGRES_PASSWORD: str = "1234"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "kg_vending"

    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT_SECONDS: float = 30.0
    OPENAI_MAX_RETRIES: int = 3
    OPENAI_EMBEDDING_MODEL: str = "text-embedding-3-small"
    OPENAI_EMBEDDING_TIMEOUT_SECONDS: float = 30.0
    OPENAI_EMBEDDING_MAX_RETRIES: int = 3
    SECONDARY_FILTERING_JUDGE_CONCURRENCY_LIMIT: int = 10
    """2차 필터링 LLM 판정(secondary_filtering_judge_service.judge_notice) 동시
    호출 수 제한. notice_normalization_service._NOTICE_LLM_CONCURRENCY_LIMIT과
    같은 이유(계정 전체 동시 호출 한도가 실측된 적 없음, 매칭 요청과 정규화
    배치가 겹칠 때 레이트리밋/타임아웃 위험)로 동일한 기본값을 쓴다."""
    MATCHING_PIPELINE_CONCURRENCY_LIMIT: int = 2
    """run_matching() 전체를 동시에 몇 건까지 실행할지. 매칭 한 건 안에서도
    임베딩·LLM 판정이 각자 최대 10건씩 동시 호출하므로, 서로 다른 유저의
    매칭 요청이 겹치면 그 한도가 곱절로 늘어 OpenAI 레이트리밋에 걸려 하나가
    비정상적으로 오래 걸린다(실측 2026-07-16, 겹친 요청 하나가 21분 걸림).
    유저별 중복 실행 방지(match_log_repository.get_processing_by_user)와 별개로,
    서로 다른 유저끼리 겹치는 것도 여기서 막는다."""
    BUSINESS_PLAN_SAMPLE_JSON_PATH: str = ""
    NOTICE_SAMPLE_JSON_PATH: str = ""

    # 2차 필터링(docs/matching-pipeline.md 4단계) 벡터 DB - AI 담당
    # xuswns/chromadb-embedded-deployment.md 참고: 별도 서버 없이 프로세스 안에서
    # 로컬 디스크에 바로 저장하는 embedded persistent client 방식.
    CHROMA_PERSIST_DIR: str = "data/chroma"
    CHROMA_NOTICE_COLLECTION: str = "notice_attachments"
    CHROMA_BUSINESS_PLAN_COLLECTION: str = "business_plan_chunks"

    BIZINFO_API_KEY: str = ""
    BIZINFO_API_URL: str = "https://www.bizinfo.go.kr/uss/rss/bizinfoApi.do"
    BIZINFO_PAGE_SIZE: int = 100
    BIZINFO_REQUEST_TIMEOUT_SECONDS: int = 15
    BIZINFO_MAX_RETRIES: int = 3

    KSTARTUP_API_KEY: str = ""
    KSTARTUP_API_URL: str = (
        "https://apis.data.go.kr/B552735/kisedKstartupService01/getAnnouncementInformation01"
    )
    KSTARTUP_PAGE_SIZE: int = 100
    KSTARTUP_REQUEST_TIMEOUT_SECONDS: int = 15
    KSTARTUP_MAX_RETRIES: int = 3

    MSIT_API_KEY: str = ""
    MSIT_API_URL: str = (
        "https://apis.data.go.kr/1721000/msitannouncementinfo/businessAnnouncMentList"
    )
    # 문서상 http로 나와있지만 실제로는 https가 아니면 400(Request Blocked)이
    # 반환되는 것을 실측으로 확인함(2026-07-13).
    MSIT_PAGE_SIZE: int = 100
    MSIT_REQUEST_TIMEOUT_SECONDS: int = 15
    MSIT_MAX_RETRIES: int = 3

    CLOVA_OCR_INVOKE_URL: str = ""
    CLOVA_OCR_SECRET_KEY: str = ""
    CLOVA_OCR_TIMEOUT_SECONDS: int = 30
    CLOVA_OCR_MAX_RETRIES: int = 3
    CLOVA_OCR_LANGUAGE: str = "ko"

    PDF_OCR_TEXT_THRESHOLD: int = 50

    # 파일 업로드 저장 (로컬 디스크). STORAGE_ROOT는 서버 실행 위치(backend/)
    # 기준 상대경로다. S3 전환 시 저장 계층만 교체하면 된다.
    STORAGE_ROOT: str = "storage/uploads"
    MAX_UPLOAD_SIZE_BYTES: int = 52_428_800  # 50MB (프론트 업로드 제한과 일치)

    # 카카오 로그인 (OAuth2)
    KAKAO_CLIENT_ID: str = ""
    """카카오 개발자 콘솔의 REST API 키"""
    KAKAO_CLIENT_SECRET: str = ""
    """활성화한 경우에만 사용. 비어 있으면 토큰 교환 시 전송하지 않는다."""
    KAKAO_REDIRECT_URI: str = "http://localhost:8000/api/auth/kakao/callback"
    KAKAO_AUTHORIZE_URL: str = "https://kauth.kakao.com/oauth/authorize"
    KAKAO_TOKEN_URL: str = "https://kauth.kakao.com/oauth/token"
    KAKAO_USER_INFO_URL: str = "https://kapi.kakao.com/v2/user/me"
    KAKAO_UNLINK_URL: str = "https://kapi.kakao.com/v1/user/unlink"
    KAKAO_ADMIN_KEY: str = ""
    """카카오 개발자 콘솔의 Admin 키. 회원탈퇴 시 연결 끊기(unlink)에 쓴다.
    비어 있으면 unlink를 건너뛴다(로컬 개발용)."""
    KAKAO_REQUEST_TIMEOUT_SECONDS: int = 10

    # JWT (자체 발급 토큰)
    JWT_SECRET: str = "change-me-in-env"
    """운영 환경에서는 반드시 .env에서 안전한 랜덤 값으로 덮어쓴다."""
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 14

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
