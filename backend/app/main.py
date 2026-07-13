import logging
import os

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

settings = get_settings()

app = FastAPI(
    title=settings.PROJECT_NAME,
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
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
