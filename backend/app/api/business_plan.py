"""
api/business_plan.py

NRM-001: 사업계획서 표준 정규화 라우터
POST /business-plans/{business_plan_id}/normalizations
GET  /business-plans/{business_plan_id}/normalizations/{job_id}

작업 상태는 인메모리 딕셔너리(_JOBS)에 보관한다. 서버 재시작하면 사라지고
멀티 워커 환경에서는 워커마다 따로 관리됨 - 영속화는 추후 과제 (재정규화 정책과
함께 팀 논의 필요).
"""

import uuid

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.normalizer import AiNormalizationError, normalize_text
from app.api.deps import get_current_user
from app.core.config import get_settings
from app.db.session import async_session_factory, get_db
from app.models.user import User
from app.repositories.business_plan_repository import BusinessPlanNotFoundError
from app.schemas.business_plan import (
    BusinessPlanSummaryResponse,
    BusinessPlanUploadResponse,
    JobStatus,
    NormalizeJobAccepted,
    NormalizeRequest,
    NormalizeStatusResponse,
)
from app.services.business_plan_service import (
    CompanyProfileRequiredError,
    NoSourceTextError,
    UnsupportedFileTypeError,
    get_my_latest_business_plan,
    normalize_business_plan,
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
    except CompanyProfileRequiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="기업 프로필을 먼저 등록해주세요.",
        ) from exc
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


_JOBS: dict[str, NormalizeStatusResponse] = {}


async def _run_normalization_job(
    session: AsyncSession,
    job_id: str,
    business_plan_id: int,
    extracted_text: str | None,
) -> None:
    """정규화 실행 + _JOBS 상태 갱신. session 생명주기는 호출하는 쪽 책임."""
    try:
        outcome = await normalize_business_plan(
            session,
            business_plan_id=business_plan_id,
            normalize_fn=normalize_text,
            extracted_text=extracted_text,
        )
    except (BusinessPlanNotFoundError, NoSourceTextError, AiNormalizationError) as exc:
        _JOBS[job_id] = NormalizeStatusResponse(
            business_plan_id=business_plan_id,
            job_id=job_id,
            status=JobStatus.FAILED,
            error_message=str(exc),
        )
        return

    _JOBS[job_id] = NormalizeStatusResponse(
        business_plan_id=business_plan_id,
        job_id=job_id,
        status=JobStatus.COMPLETED,
        normalized_json=outcome.normalized,
        validation_result=outcome.validation_result,
        analyzed_at=outcome.analyzed_at,
    )


async def _execute_normalization_job(
    job_id: str, business_plan_id: int, extracted_text: str | None
) -> None:
    """
    BackgroundTasks 진입점. 요청 스코프 세션(Depends(get_db))은 응답이 나간 뒤
    백그라운드 태스크가 돌 때 이미 정리됐을 수 있어서, 여기서 새 세션을 직접 연다.
    """
    async with async_session_factory() as session:
        await _run_normalization_job(session, job_id, business_plan_id, extracted_text)


@router.post(
    "/{business_plan_id}/normalizations",
    response_model=NormalizeJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="사업계획서 정규화 시작",
    description="사업계획서 원문을 LLM으로 정규화하는 작업을 백그라운드에서 시작한다.",
)
async def create_normalization(
    business_plan_id: int,
    background_tasks: BackgroundTasks,
    request: NormalizeRequest | None = None,
):
    extracted_text = request.extracted_text if request else None

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NormalizeStatusResponse(
        business_plan_id=business_plan_id, job_id=job_id, status=JobStatus.PENDING
    )
    background_tasks.add_task(
        _execute_normalization_job, job_id, business_plan_id, extracted_text
    )

    return NormalizeJobAccepted(
        business_plan_id=business_plan_id,
        job_id=job_id,
        status=JobStatus.PENDING,
    )


@router.get(
    "/{business_plan_id}/normalizations/{job_id}",
    response_model=NormalizeStatusResponse,
    summary="사업계획서 정규화 상태 조회",
    description="정규화 작업 상태와 결과(normalized_json, validation_result)를 조회한다.",
)
async def get_normalization_status(business_plan_id: int, job_id: str):
    job = _JOBS.get(job_id)
    if job is None or job.business_plan_id != business_plan_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 정규화 작업을 찾을 수 없습니다.",
        )
    return job
