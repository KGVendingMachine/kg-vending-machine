"""
api/business_plan_analysis.py

사업계획서 분석(OCR + 정규화) 라우터.
POST /business-plans/{id}/analysis            -> 분석 작업 시작 (202 Accepted)
GET  /business-plans/{id}/analysis/{job_id}   -> 상태/결과 조회 (폴링)

진행 상태는 인메모리 딕셔너리(_ANALYSIS_JOBS)에 보관한다. OCR/정규화 결과 자체는
business_plan 행(raw_text/analysis_json)에 저장되지만, 상태 추적은 DB를 쓰지 않고
메모리로 가볍게 관리한다. 서버 재시작/멀티워커에서는 상태가 유실될 수 있어
영속화는 추후 과제 (기존 정규화 엔드포인트와 동일한 한계).
"""

import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.normalizer import AiNormalizationError, normalize_text
from app.api.deps import get_current_user
from app.db.session import async_session_factory, get_db
from app.models.business_plan import BusinessPlan
from app.models.user import User
from app.ocr.extract import extract_text
from app.repositories.business_plan_repository import (
    BusinessPlanNotFoundError,
    get_owned_by_user,
)
from app.schemas.business_plan import JobStatus
from app.schemas.business_plan_analysis import (
    AnalysisJobAccepted,
    AnalysisStatusResponse,
    AnalysisStep,
)
from app.services.business_plan_analysis_service import (
    NoUploadedFileError,
    run_analysis,
)
from app.services.business_plan_service import NoSourceTextError

router = APIRouter(prefix="/business-plans", tags=["business-plans"])

_ANALYSIS_JOBS: dict[str, AnalysisStatusResponse] = {}


async def require_owned_business_plan(
    business_plan_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> BusinessPlan:
    """path의 business_plan이 현재 유저 소유인지 검증하고 그 행을 반환한다.

    JWT 인증(get_current_user)만으로는 남의 business_plan_id로 분석·조회를 막지
    못한다. 소유(company_profile 경유)가 아니면 존재 여부를 노출하지 않도록 404.
    """
    plan = await get_owned_by_user(session, business_plan_id, current_user.id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 사업계획서를 찾을 수 없습니다.",
        )
    return plan


async def _run_analysis_job(
    session: AsyncSession, job_id: str, business_plan_id: int
) -> None:
    """분석 실행 + _ANALYSIS_JOBS 상태 갱신. session 생명주기는 호출하는 쪽 책임."""

    def set_step(step: AnalysisStep) -> None:
        current = _ANALYSIS_JOBS[job_id]
        _ANALYSIS_JOBS[job_id] = current.model_copy(
            update={"status": JobStatus.PROCESSING, "step": step}
        )

    try:
        outcome = await run_analysis(
            session,
            business_plan_id,
            extract_fn=extract_text,
            normalize_fn=normalize_text,
            on_step=set_step,
        )
    except (
        BusinessPlanNotFoundError,
        NoUploadedFileError,
        NoSourceTextError,
        AiNormalizationError,
    ) as exc:
        _ANALYSIS_JOBS[job_id] = AnalysisStatusResponse(
            business_plan_id=business_plan_id,
            job_id=job_id,
            status=JobStatus.FAILED,
            error_message=str(exc),
        )
        return
    except Exception as exc:  # noqa: BLE001
        # OCR(CLOVA) 호출 실패 등 예상 못한 오류. 백그라운드라 응답으로 못 알리므로
        # 잡 상태에 남겨 폴링으로 확인하게 한다.
        _ANALYSIS_JOBS[job_id] = AnalysisStatusResponse(
            business_plan_id=business_plan_id,
            job_id=job_id,
            status=JobStatus.FAILED,
            error_message=f"분석 중 오류가 발생했습니다: {exc}",
        )
        return

    _ANALYSIS_JOBS[job_id] = AnalysisStatusResponse(
        business_plan_id=business_plan_id,
        job_id=job_id,
        status=JobStatus.COMPLETED,
        analysis_json=outcome.normalized,
        analyzed_at=outcome.analyzed_at,
    )


async def _execute_analysis_job(job_id: str, business_plan_id: int) -> None:
    """
    BackgroundTasks 진입점. 요청 스코프 세션(Depends(get_db))은 응답이 나간 뒤
    백그라운드 태스크가 돌 때 이미 정리됐을 수 있어서, 여기서 새 세션을 직접 연다.
    """
    async with async_session_factory() as session:
        await _run_analysis_job(session, job_id, business_plan_id)


@router.post(
    "/{business_plan_id}/analysis",
    response_model=AnalysisJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="사업계획서 분석 시작(OCR + 정규화)",
    description=(
        "업로드된 사업계획서 파일을 OCR로 추출하고 LLM으로 정규화하는 작업을"
        " 백그라운드에서 시작한다. 무거운 작업이라 즉시 job_id를 반환하고,"
        " 진행 상태는 폴링으로 조회한다."
    ),
)
async def create_analysis(
    background_tasks: BackgroundTasks,
    plan: BusinessPlan = Depends(require_owned_business_plan),
):
    business_plan_id = plan.id
    job_id = str(uuid.uuid4())
    _ANALYSIS_JOBS[job_id] = AnalysisStatusResponse(
        business_plan_id=business_plan_id, job_id=job_id, status=JobStatus.PENDING
    )
    background_tasks.add_task(_execute_analysis_job, job_id, business_plan_id)

    return AnalysisJobAccepted(
        business_plan_id=business_plan_id,
        job_id=job_id,
        status=JobStatus.PENDING,
    )


@router.get(
    "/{business_plan_id}/analysis/{job_id}",
    response_model=AnalysisStatusResponse,
    summary="사업계획서 분석 상태 조회(폴링)",
    description="분석 작업 상태와 결과(analysis_json)를 조회한다.",
)
async def get_analysis_status(
    job_id: str,
    plan: BusinessPlan = Depends(require_owned_business_plan),
):
    job = _ANALYSIS_JOBS.get(job_id)
    if job is None or job.business_plan_id != plan.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 분석 작업을 찾을 수 없습니다.",
        )
    return job
