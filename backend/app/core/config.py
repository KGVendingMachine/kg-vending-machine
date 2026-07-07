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

    @property
    def DATABASE_URL(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
