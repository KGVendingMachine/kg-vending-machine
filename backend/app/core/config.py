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

    POSTGRES_USER: str = "kg_vending"
    POSTGRES_PASSWORD: str = "1234"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "kg_vending"


    OPENAI_API_KEY: str = ""
    OPENAI_MODEL: str = "gpt-4o-mini"
    OPENAI_TIMEOUT_SECONDS: float = 30.0
    OPENAI_MAX_RETRIES: int = 3

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

    CLOVA_OCR_INVOKE_URL: str = ""
    CLOVA_OCR_SECRET_KEY: str = ""
    CLOVA_OCR_TIMEOUT_SECONDS: int = 30
    CLOVA_OCR_MAX_RETRIES: int = 3
    CLOVA_OCR_LANGUAGE: str = "ko"

    PDF_OCR_TEXT_THRESHOLD: int = 50

    # 카카오 로그인 (OAuth2)
    KAKAO_CLIENT_ID: str = ""
    """카카오 개발자 콘솔의 REST API 키"""
    KAKAO_CLIENT_SECRET: str = ""
    """활성화한 경우에만 사용. 비어 있으면 토큰 교환 시 전송하지 않는다."""
    KAKAO_REDIRECT_URI: str = "http://localhost:5173/auth/callback"
    KAKAO_TOKEN_URL: str = "https://kauth.kakao.com/oauth/token"
    KAKAO_USER_INFO_URL: str = "https://kapi.kakao.com/v2/user/me"
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
