import logging
import os
from contextlib import asynccontextmanager

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.utils import get_openapi

from app.api.router import api_router
from app.core.config import get_settings

# 앱 로거(app.*) 출력 설정. uvicorn은 자기 로거만 설정하므로 이게 없으면
# 서비스 계층의 logger.info(...)가 전부 버려진다. env LOG_LEVEL=DEBUG로 낮추면
# debug 로그까지 보인다.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(levelname)s:     [%(name)s] %(message)s",
)

logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 이슈 #102: 공고 수집·정규화를 매일 새벽 3시(KST)에 자동 실행한다.
    # 서버가 1대뿐이고(--workers 미사용, ChromaDB 제약 — Dockerfile 참고)
    # 배포도 잦지 않은 지금 규모라, EC2 host crontab보다 앱에 내장해
    # git으로 다 추적되는 이쪽을 택했다(app/scheduler.py 참고).
    from app.scheduler import run_daily_notice_pipeline

    scheduler = AsyncIOScheduler(timezone="Asia/Seoul")
    scheduler.add_job(
        run_daily_notice_pipeline,
        trigger=CronTrigger(hour=3, minute=0),
        id="daily_notice_pipeline",
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("스케줄러 시작: 공고 수집·정규화 매일 03:00(Asia/Seoul)")
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)


app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    lifespan=lifespan,
)


def custom_openapi() -> dict:
    """Swagger에 Bearer 토큰 Authorize 버튼을 항상 노출한다.

    보호 엔드포인트가 아직 없어도 미리 토큰을 넣어둘 수 있게, OpenAPI
    스키마에 HTTPBearer 보안 스킴을 등록한다. 인증 강제는 각 엔드포인트의
    Depends(get_current_user)가 담당하며 여기서는 문서 노출만 한다.
    """
    if app.openapi_schema:
        return app.openapi_schema

    openapi_schema = get_openapi(
        title=app.title,
        version=app.version,
        routes=app.routes,
    )
    openapi_schema.setdefault("components", {})["securitySchemes"] = {
        "HTTPBearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}
    }
    app.openapi_schema = openapi_schema
    return openapi_schema


app.openapi = custom_openapi

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix=settings.API_PREFIX)
