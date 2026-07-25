"""
api/business_plan.py

사업계획서 파일 업로드 라우터.
POST /business-plans        -> 파일 업로드 (business_plan 행 생성)
GET  /business-plans/me     -> 내 최신 사업계획서 조회

OCR + 정규화 + 임베딩(분석) 파이프라인은 api/business_plan_analysis.py로 분리돼
있다 (POST/GET /business-plans/{id}/analysis). 예전에 있던
POST/GET /business-plans/{id}/normalizations(LLM 정규화만 수행, OCR 없이
extracted_text를 직접 받거나 DB raw_text에 의존)는 analysis 엔드포인트가
OCR까지 포함해 완전히 대체하면서 제거했다 — analysis_status 컬럼도 그쪽에서만
채워지므로(매칭 시작 조건), 남겨둬도 실제로는 쓸 수 없는 경로였다.
"""

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.user import User
from app.schemas.business_plan import (
    BusinessPlanSummaryResponse,
    BusinessPlanUploadResponse,
)
from app.services.business_plan_service import (
    UnsupportedFileTypeError,
    get_my_latest_business_plan,
    upload_business_plan,
)
from app.utils.file_storage import FileTooLargeError

router = APIRouter(prefix="/business-plans", tags=["business-plans"])


@router.post(
    "",
    response_model=BusinessPlanUploadResponse,
    status_code=status.HTTP_201_CREATED,
    summary="사업계획서 파일 업로드",
    description=(
        "사업계획서 파일을 업로드해 business_plan 행을 생성한다. 파일은 서버"
        " 디스크에 저장하고 id를 반환하며, OCR·정규화·매칭은 이후 단계에서"
        " 별도로 처리한다."
    ),
)
async def upload_business_plan_file(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    settings = get_settings()
    try:
        return await upload_business_plan(
            session,
            user_id=current_user.id,
            file=file,
            storage_root=settings.STORAGE_ROOT,
            max_upload_size_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
        )
    except UnsupportedFileTypeError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="파일이 너무 큽니다. 최대 50MB까지 업로드할 수 있습니다.",
        ) from exc


@router.get(
    "/me",
    response_model=BusinessPlanSummaryResponse | None,
    summary="내 최신 사업계획서 조회",
    description="로그인한 유저가 마지막으로 업로드한 사업계획서를 반환한다. 없으면 null.",
)
async def get_my_business_plan(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await get_my_latest_business_plan(session, current_user.id)
