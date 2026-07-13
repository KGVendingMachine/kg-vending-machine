from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.company import CompanyProfile
from app.models.match import MatchLog
from app.models.user import User
from app.repositories import match_log_repository
from app.repositories.business_plan_repository import get_owned_by_user
from app.schemas.business_plan import JobStatus
from app.schemas.match_log import (
    MatchLogCreateRequest,
    MatchLogResponse,
    MatchResultNoticeInfo,
    MatchResultResponse,
)
from app.services.matching_service import MatchingNotReadyError, run_matching

router = APIRouter(prefix="/match-logs", tags=["match-logs"])


def _to_response(log: MatchLog, business_plan_title: str | None) -> MatchLogResponse:
    return MatchLogResponse(
        id=log.id,
        business_plan_id=log.business_plan_id,
        business_plan_title=business_plan_title,
        run_status=JobStatus(log.run_status) if log.run_status else None,
        created_at=log.created_at,
        completed_at=log.completed_at,
    )


def _result_to_response(
    item: match_log_repository.MatchResultWithNotice,
) -> MatchResultResponse:
    result = item.result
    return MatchResultResponse(
        id=result.id,
        match_log_id=result.recommendation_run_id,
        notice_id=result.notice_id,
        notice_title=item.notice.title,
        notice=MatchResultNoticeInfo(
            id=item.notice.id,
            title=item.notice.title,
            organization_name=item.organization_name,
            category_name=item.category_name,
            status=item.notice.status,
            application_end_date=item.notice.application_end_date,
            amount_label=item.notice.amount_label,
            source_url=item.notice.source_url,
            apply_url=item.notice.apply_url,
        ),
        total_score=result.total_score,
        eligibility_score=result.eligibility_score,
        item_fit_score=result.item_fit_score,
        business_fit_score=result.business_fit_score,
        growth_score=result.growth_score,
        bonus_score=result.bonus_score,
        eligibility_status=result.eligibility_status,
        recommendation_level=result.recommendation_level,
        summary_reason=result.summary_reason,
        weakness=result.weakness,
        strategy_suggestion=result.strategy_suggestion,
        result_json=result.result_json,
        created_at=result.created_at,
    )


@router.post(
    "",
    response_model=MatchLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Run notice matching for a normalized business plan",
)
async def create_match_log(
    payload: MatchLogCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    plan = await get_owned_by_user(session, payload.business_plan_id, current_user.id)
    if plan is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Business plan not found.",
        )
    if plan.analysis_status != JobStatus.COMPLETED.value or plan.analysis_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only completed business-plan analyses can be matched.",
        )

    profile = await session.get(CompanyProfile, plan.company_profile_id)
    if profile is None or profile.user_id != current_user.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Company profile not found.",
        )

    log = await match_log_repository.create(
        session,
        user_id=current_user.id,
        company_profile_id=plan.company_profile_id,
        business_plan_id=plan.id,
        run_status=JobStatus.PROCESSING.value,
        query_json=plan.analysis_json,
    )
    try:
        await run_matching(
            session,
            log=log,
            plan=plan,
            profile=profile,
            max_results=payload.max_results,
        )
    except MatchingNotReadyError as exc:
        # 실행 이력은 남기되(실패 원인 추적용) 빈 결과로 완료 처리하지 않는다.
        log.run_status = JobStatus.FAILED.value
        log.completed_at = None
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc
    await session.commit()
    return _to_response(log, plan.title)


@router.get(
    "",
    response_model=list[MatchLogResponse],
    summary="List my matching runs",
)
async def list_match_logs(
    limit: int = Query(5, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    rows = await match_log_repository.list_by_user(
        session, current_user.id, limit=limit, offset=offset
    )
    return [_to_response(log, title) for log, title in rows]


@router.get(
    "/{match_log_id}",
    response_model=MatchLogResponse,
    summary="Get one matching run",
)
async def get_match_log(
    match_log_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    row = await match_log_repository.get_owned_by_user(
        session, match_log_id, current_user.id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match log not found.",
        )
    log, title = row
    return _to_response(log, title)


@router.get(
    "/{match_log_id}/results",
    response_model=list[MatchResultResponse],
    summary="List matching results for one run",
)
async def list_match_results(
    match_log_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    row = await match_log_repository.get_owned_by_user(
        session, match_log_id, current_user.id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match log not found.",
        )

    results = await match_log_repository.list_results_by_log(session, match_log_id)
    return [_result_to_response(item) for item in results]
