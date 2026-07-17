import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import async_session_factory, get_db
from app.models.company import CompanyProfile
from app.models.match import MatchLog
from app.models.user import User
from app.repositories import match_log_repository
from app.repositories.business_plan_repository import get_owned_by_user
from app.schemas.business_plan import JobStatus
from app.schemas.match_log import (
    ActiveMatchLogResponse,
    MatchLogCreateRequest,
    MatchLogDeleteResponse,
    MatchLogResponse,
    MatchResultNoticeInfo,
    MatchResultResponse,
    SecondaryFilteringLogResponse,
)
from app.services.matching_service import MatchingNotReadyError, run_matching

logger = logging.getLogger(__name__)

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


def _amount_label(notice) -> str | None:
    if notice.amount_label:
        return notice.amount_label
    normalized = notice.normalized_json or {}
    support = normalized.get("support") if isinstance(normalized, dict) else None
    if not isinstance(support, dict):
        return None
    amount = support.get("support_amount")
    return amount if isinstance(amount, str) and amount.strip() else None


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
            amount_label=_amount_label(item.notice),
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
        is_bookmarked=item.bookmark_id is not None,
        bookmark_id=item.bookmark_id,
        created_at=result.created_at,
    )


async def _run_matching_job(
    session: AsyncSession, log_id: int, *, business_plan_id: int, max_results: int
) -> None:
    """매칭(OCR·정규화·임베딩·LLM 판정)을 실행하고 log 상태를 갱신한다.

    실측 2~3분까지 걸려(2026-07-15, match_log_id=119 기준 2분27초) 요청-응답
    안에서 동기로 처리하면 Vercel 같은 리버스 프록시의 게이트웨이 타임아웃
    (보통 30초 안팎)에 먼저 끊긴다 — 백엔드는 결국 성공해서 DB에 저장하는데도
    사용자에게는 실패로 보이는 원인이었다. run_status를 폴링 대상으로 써서
    완료를 기다리게 한다.
    """
    log = await session.get(MatchLog, log_id)
    plan = await get_owned_by_user(session, business_plan_id, log.user_id)
    profile = await session.get(CompanyProfile, log.company_profile_id)
    try:
        await run_matching(
            session,
            log=log,
            plan=plan,
            profile=profile,
            max_results=max_results,
        )
    except MatchingNotReadyError as exc:
        logger.info("매칭 실패 (match_log_id=%s): %s", log_id, exc)
        log.run_status = JobStatus.FAILED.value
        log.completed_at = None
        await session.commit()
        return
    await session.commit()


async def _execute_matching_job(
    log_id: int, *, business_plan_id: int, max_results: int
) -> None:
    """백그라운드 진입점. 요청 스코프 session이 아니라 새 세션을 직접 연다
    (notice_collection.py의 배치 수집 실행기와 동일한 이유 — 요청이 끝나면
    요청 스코프 session은 닫힌다). _run_matching_job이 잡는 예외 외의 실패
    (세션 확보 실패 등)까지 여기서 잡아야 job이 processing에 영원히
    멈추지 않는다(_execute_notice_ocr_job과 같은 이유)."""
    try:
        async with async_session_factory() as session:
            await _run_matching_job(
                session,
                log_id,
                business_plan_id=business_plan_id,
                max_results=max_results,
            )
    except Exception:
        logger.exception("매칭 작업 실행 실패 (match_log_id=%s)", log_id)
        async with async_session_factory() as session:
            log = await session.get(MatchLog, log_id)
            if log is not None:
                log.run_status = JobStatus.FAILED.value
                log.completed_at = None
                await session.commit()


@router.post(
    "",
    response_model=MatchLogResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Start notice matching for a normalized business plan",
    description=(
        "매칭 실행을 백그라운드로 시작하고 즉시 processing 상태로 응답한다 — "
        "OCR·정규화·임베딩·LLM 판정을 합치면 실측 2~3분까지 걸려 요청-응답 "
        "안에서 동기로 처리할 수 없다(프록시 게이트웨이 타임아웃에 걸림). "
        "GET /match-logs/{id}로 run_status가 completed/failed가 될 때까지 "
        "폴링해야 한다."
    ),
)
async def create_match_log(
    payload: MatchLogCreateRequest,
    background_tasks: BackgroundTasks,
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

    # 같은 유저가 매칭을 여러 개 동시에 돌리면 세마포어·OpenAI 호출 한도를
    # 겹쳐 쓰게 돼 하나가 비정상적으로 오래 걸린다(실측 2026-07-16,
    # match_log_id=180이 겹친 요청 때문에 14분 넘게 걸림).
    existing = await match_log_repository.get_processing_by_user(
        session, current_user.id
    )
    if existing is not None:
        if existing.business_plan_id == plan.id:
            # 같은 계획서로 재요청 — 새로 만들지 않고 이미 도는 로그를 그대로
            # 돌려줘 폴링만 이어붙게 한다(notice_ocr.py 배치 트리거의
            # "이미 진행 중이면 기존 job 반환" 패턴과 동일).
            existing_row = await match_log_repository.get_owned_by_user(
                session, existing.id, current_user.id
            )
            existing_log, existing_title = existing_row
            return _to_response(existing_log, existing_title)
        # 다른 계획서 매칭이 이미 도는 중 — 여기서 새로 시작하면 그 계획서와
        # 자원을 다투게 되므로, 그게 끝날 때까지 명시적으로 대기시킨다.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="다른 매칭이 이미 진행 중입니다. 완료된 뒤 다시 시도해주세요.",
        )

    log = await match_log_repository.create(
        session,
        user_id=current_user.id,
        company_profile_id=plan.company_profile_id,
        business_plan_id=plan.id,
        run_status=JobStatus.PROCESSING.value,
        query_json=plan.analysis_json,
    )
    await session.commit()

    background_tasks.add_task(
        _execute_matching_job,
        log.id,
        business_plan_id=plan.id,
        max_results=payload.max_results,
    )

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
    "/active",
    response_model=ActiveMatchLogResponse | None,
    summary="Get my in-progress matching run (for resume after refresh)",
    description=(
        "현재 유저가 진행 중(processing)인 매칭 로그를 반환한다. 없으면 null. "
        "새로고침·재접속으로 화면이 초기화돼도 진행 중이던 매칭 폴링을 "
        "이어붙이는 데 쓴다 — create_match_log의 중복 방지와 같은 "
        "get_processing_by_user 기준이라 유저당 최대 1건이다. business_plan_id를 "
        "주면 그 계획서 매칭일 때만 반환한다(다른 계획서가 도는 중이면 null). "
        "이 경로는 '/{match_log_id}'보다 먼저 선언돼야 'active'가 id로 파싱되지 않는다."
    ),
)
async def get_active_match_log(
    business_plan_id: int | None = Query(default=None),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    existing = await match_log_repository.get_processing_by_user(
        session, current_user.id
    )
    if existing is None:
        return None
    if business_plan_id is not None and existing.business_plan_id != business_plan_id:
        return None
    return ActiveMatchLogResponse(
        id=existing.id, run_status=JobStatus(existing.run_status)
    )


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


@router.delete(
    "/{match_log_id}",
    response_model=MatchLogDeleteResponse,
    summary="Delete one matching run",
)
async def delete_match_log(
    match_log_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    deleted = await match_log_repository.delete_owned_by_user(
        session, match_log_id, current_user.id
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match log not found.",
        )
    await session.commit()
    return MatchLogDeleteResponse(match_log_id=match_log_id)


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

    log, _ = row
    results = await match_log_repository.list_results_by_log(
        session,
        match_log_id,
        user_id=current_user.id,
        business_plan_id=log.business_plan_id,
    )
    return [_result_to_response(item) for item in results]


@router.get(
    "/{match_log_id}/secondary-filtering",
    response_model=SecondaryFilteringLogResponse,
    summary="Get the secondary-filtering (embedding similarity) log for one run",
    description=(
        "docs/matching-pipeline.md 4단계(2차 필터링) 실행 로그를 조회한다 — "
        "1차 필터링 통과 후보 중 몇 건이 실제로 임베딩·유사도 검색에 쓰였는지, "
        "공고별 유사도 점수와 스킵 사유(no_text/embedding_failed)를 담는다."
    ),
)
async def get_secondary_filtering_log(
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
    log, _ = row
    if log.secondary_filtering_log is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="이 매칭 실행에는 2차 필터링 로그가 없습니다.",
        )
    return SecondaryFilteringLogResponse(
        match_log_id=log.id, **log.secondary_filtering_log
    )
