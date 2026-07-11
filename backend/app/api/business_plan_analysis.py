"""
api/business_plan_analysis.py

사업계획서 분석(OCR + 정규화) 라우터.
POST /business-plans/{id}/analysis   -> 분석 작업 시작 (202 Accepted)
GET  /business-plans/{id}/analysis   -> 상태/결과 조회 (폴링)

진행 상태는 business_plan 행의 analysis_* 컬럼에 저장한다. 서버 재시작·멀티워커
에서도 상태가 유지되고, 프론트가 job_id 없이 plan id만으로 조회할 수 있어 창을
닫았다 다시 들어와도 진행 중인 분석을 복구할 수 있다.

중복 실행 방지: POST는 조건부 UPDATE(try_claim_analysis)로 processing 전환을
원자적으로 선점한 요청만 백그라운드 태스크를 등록한다. 이미 processing이면
기존 상태를 그대로 돌려준다(멱등) — 진행 페이지 새로고침으로 비싼 OCR·LLM
호출이 중복으로 나가지 않는다.
"""

import logging
from datetime import datetime, timedelta, timezone

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
    finish_analysis,
    get_owned_by_user,
    set_analysis_step,
    try_claim_analysis,
)
from app.schemas.business_plan import JobStatus
from app.schemas.business_plan_analysis import (
    AnalysisStatusResponse,
    AnalysisStep,
)
from app.services.business_plan_analysis_service import (
    NoUploadedFileError,
    run_analysis,
)
from app.services.business_plan_service import NoSourceTextError

router = APIRouter(prefix="/business-plans", tags=["business-plans"])

logger = logging.getLogger(__name__)

# processing인 채 이 시간이 지나면 잡 도중 서버가 죽어 박제된 것으로 보고
# 재시작(재선점)을 허용한다. 실측 기준 분석은 보통 1~2분에 끝난다.
_STALE_PROCESSING_TIMEOUT = timedelta(minutes=10)


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


def _status_response(plan: BusinessPlan) -> AnalysisStatusResponse:
    """business_plan 행의 analysis_* 컬럼을 응답 스키마로 변환한다.

    analysis_json/analyzed_at은 재분석 중에도 이전 성공분이 행에 남아 있으므로,
    completed일 때만 실어 진행 중 상태와 이전 결과가 섞여 보이지 않게 한다.
    """
    job_status = JobStatus(plan.analysis_status) if plan.analysis_status else None
    completed = job_status == JobStatus.COMPLETED
    return AnalysisStatusResponse(
        business_plan_id=plan.id,
        status=job_status,
        step=AnalysisStep(plan.analysis_step) if plan.analysis_step else None,
        analysis_json=plan.analysis_json if completed else None,
        analyzed_at=plan.analyzed_at if completed else None,
        error_message=plan.analysis_error if job_status == JobStatus.FAILED else None,
    )


async def _run_analysis_job(session: AsyncSession, business_plan_id: int) -> None:
    """분석 실행 + business_plan 행의 잡 상태 갱신. session 생명주기는 호출하는 쪽 책임."""

    async def set_step(step: AnalysisStep) -> None:
        await set_analysis_step(session, business_plan_id, step.value)

    try:
        await run_analysis(
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
        # 실패 지점까지의 미커밋 변경이 상태 기록에 섞여 커밋되지 않도록 비운다.
        await session.rollback()
        await finish_analysis(
            session,
            business_plan_id,
            status=JobStatus.FAILED.value,
            error_message=str(exc),
        )
    except Exception:  # noqa: BLE001
        # OCR(CLOVA) 호출 실패 등 예상 못한 오류. 백그라운드라 응답으로 못 알리므로
        # 잡 상태에 남겨 폴링으로 확인하게 한다. 원본 예외 문자열은 내부 정보
        # (URL·스택 일부 등)가 섞일 수 있어 사용자에게 노출하지 않고 로그로만 남긴다.
        logger.exception(
            "사업계획서 분석 중 예상 못한 오류 (business_plan_id=%s)",
            business_plan_id,
        )
        await session.rollback()
        await finish_analysis(
            session,
            business_plan_id,
            status=JobStatus.FAILED.value,
            error_message="분석 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.",
        )
    else:
        await finish_analysis(
            session, business_plan_id, status=JobStatus.COMPLETED.value
        )


async def _execute_analysis_job(business_plan_id: int) -> None:
    """
    BackgroundTasks 진입점. 요청 스코프 세션(Depends(get_db))은 응답이 나간 뒤
    백그라운드 태스크가 돌 때 이미 정리됐을 수 있어서, 여기서 새 세션을 직접 연다.
    """
    async with async_session_factory() as session:
        await _run_analysis_job(session, business_plan_id)


@router.post(
    "/{business_plan_id}/analysis",
    response_model=AnalysisStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="사업계획서 분석 시작(OCR + 정규화)",
    description=(
        "업로드된 사업계획서 파일을 OCR로 추출하고 LLM으로 정규화하는 작업을"
        " 백그라운드에서 시작한다. 무거운 작업이라 즉시 202를 반환하고, 진행"
        " 상태는 GET으로 폴링한다. 이미 진행 중이면 새 작업을 만들지 않고"
        " 현재 상태를 그대로 반환한다(멱등)."
    ),
)
async def create_analysis(
    background_tasks: BackgroundTasks,
    plan: BusinessPlan = Depends(require_owned_business_plan),
    session: AsyncSession = Depends(get_db),
):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    claimed = await try_claim_analysis(
        session, plan.id, stale_before=now - _STALE_PROCESSING_TIMEOUT
    )
    if claimed:
        background_tasks.add_task(_execute_analysis_job, plan.id)

    # 선점 실패(이미 진행 중)든 성공이든, 커밋된 최신 잡 상태를 그대로 돌려준다.
    # expire_on_commit=False라 선점 UPDATE가 ORM 객체에 반영되지 않으므로
    # 명시적으로 refresh해서 읽는다.
    await session.refresh(plan)
    return _status_response(plan)


@router.get(
    "/{business_plan_id}/analysis",
    response_model=AnalysisStatusResponse,
    summary="사업계획서 분석 상태 조회(폴링)",
    description=(
        "분석 작업 상태와 결과(analysis_json)를 조회한다. 아직 분석을 시작한"
        " 적이 없으면 status가 null이다."
    ),
)
async def get_analysis_status(
    plan: BusinessPlan = Depends(require_owned_business_plan),
):
    return _status_response(plan)
