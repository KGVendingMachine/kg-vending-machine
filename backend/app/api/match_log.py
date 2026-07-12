"""
api/match_log.py

매칭 실행 로그 라우터.
POST /match-logs              -> 매칭 실행: 분석 완료된 사업계획서로 match_log 생성
GET  /match-logs              -> 내 매칭 로그 리스트 (분석 페이지의 "이전 매칭 기록")
GET  /match-logs/{id}         -> 단건 조회 (결과 페이지가 어떤 실행인지 표시)
GET  /match-logs/{id}/results -> 실행의 매칭 결과(match_result ⨝ notice) 리스트

공고 매칭(스코어링) 로직은 아직 미구현이다. POST는 실행 1회를 나타내는
match_log를 만들고 질의 재료(analysis_json)를 스냅샷한 뒤, DB의 실제 공고에
샘플 평가 템플릿(data/match_result_samples.json)을 입힌 match_result를 함께
생성하고 completed로 기록한다 — 결과 페이지를 실 API 흐름으로 개발·시연하기
위한 스텁이며, 실제 스코어링이 생기면 템플릿 적용 부분만 LLM 평가로 바꾼다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.match import MatchLog
from app.models.user import User
from app.repositories import match_log_repository, match_result_repository
from app.repositories.business_plan_repository import get_owned_by_user
from app.schemas.business_plan import JobStatus
from app.schemas.match_log import (
    MatchLogCreateRequest,
    MatchLogResponse,
    MatchResultNoticeInfo,
    MatchResultResponse,
)
from app.services.sample_match_result_loader import load_sample_match_results

router = APIRouter(prefix="/match-logs", tags=["match-logs"])

# 스텁이 한 실행에서 평가하는 공고 수. 샘플 템플릿 수와 맞춰둔다.
_STUB_RESULT_COUNT = 5

# 샘플 템플릿에서 match_result 컬럼으로 그대로 옮기는 필드들.
_TEMPLATE_FIELDS = (
    "total_score",
    "eligibility_score",
    "item_fit_score",
    "business_fit_score",
    "growth_score",
    "bonus_score",
    "eligibility_status",
    "recommendation_level",
    "summary_reason",
    "weakness",
    "strategy_suggestion",
    "result_json",
)


def _to_response(log: MatchLog, business_plan_title: str | None) -> MatchLogResponse:
    return MatchLogResponse(
        id=log.id,
        business_plan_id=log.business_plan_id,
        business_plan_title=business_plan_title,
        run_status=JobStatus(log.run_status) if log.run_status else None,
        created_at=log.created_at,
        completed_at=log.completed_at,
    )


@router.post(
    "",
    response_model=MatchLogResponse,
    status_code=status.HTTP_201_CREATED,
    summary="공고 매칭 실행(매칭 로그 생성)",
    description=(
        "분석이 완료된 사업계획서로 공고 매칭 실행을 기록한다. 매칭 스코어링은"
        " 아직 미구현이라 로그를 만들고 즉시 completed로 기록하며, 추후 스코어링"
        " 로직이 이 실행에 match_result를 채우는 구조로 확장된다."
    ),
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
            detail="해당 사업계획서를 찾을 수 없습니다.",
        )
    # 매칭 질의 재료는 정규화 결과(analysis_json)다. 분석이 안 끝난 plan으로는
    # 실행 자체가 의미 없으므로 막는다.
    if plan.analysis_status != JobStatus.COMPLETED.value or plan.analysis_json is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="분석이 완료된 사업계획서만 매칭할 수 있습니다.",
        )

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    log = await match_log_repository.create(
        session,
        user_id=current_user.id,
        company_profile_id=plan.company_profile_id,
        business_plan_id=plan.id,
        # 스코어링 미구현 스텁: 생성 즉시 완료 처리. 매칭 로직 도입 시
        # processing으로 만들고 백그라운드 잡이 completed로 바꾸도록 변경한다.
        run_status=JobStatus.COMPLETED.value,
        query_json=plan.analysis_json,
        completed_at=now,
    )

    # 스코어링 스텁: DB의 실제 공고에 샘플 평가 템플릿을 순환 적용해 결과를
    # 만든다. 공고가 없으면 결과 없이 로그만 남는다(결과 페이지 빈 상태).
    notices = await match_result_repository.pick_stub_notices(
        session, _STUB_RESULT_COUNT
    )
    if notices:
        templates = load_sample_match_results()
        rows = [
            {
                "notice_id": notice.id,
                **{
                    field: templates[index % len(templates)].get(field)
                    for field in _TEMPLATE_FIELDS
                },
            }
            for index, notice in enumerate(notices)
        ]
        await match_result_repository.create_many(session, log.id, rows)

    await session.commit()
    return _to_response(log, plan.title)


@router.get(
    "",
    response_model=list[MatchLogResponse],
    summary="내 매칭 로그 리스트",
    description=(
        "현재 유저의 매칭 실행 기록을 최신순으로 반환한다. limit/offset으로"
        " '더보기' 페이지네이션한다 — 응답 개수가 limit보다 적으면 끝이다."
    ),
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
    summary="매칭 로그 단건 조회",
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
            detail="해당 매칭 기록을 찾을 수 없습니다.",
        )
    log, title = row
    return _to_response(log, title)


@router.get(
    "/{match_log_id}/results",
    response_model=list[MatchResultResponse],
    summary="매칭 실행의 결과 리스트",
    description=(
        "한 매칭 실행(match_log)의 공고별 평가 결과를 적합도 내림차순으로"
        " 반환한다. 결과가 아직 없으면 빈 배열."
    ),
)
async def list_match_results(
    match_log_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    # 남의 로그의 결과를 조회하지 못하도록 로그 소유부터 확인한다.
    row = await match_log_repository.get_owned_by_user(
        session, match_log_id, current_user.id
    )
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 매칭 기록을 찾을 수 없습니다.",
        )

    items = await match_result_repository.list_by_match_log(session, match_log_id)
    return [
        MatchResultResponse(
            id=item.result.id,
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
            total_score=item.result.total_score,
            eligibility_score=item.result.eligibility_score,
            item_fit_score=item.result.item_fit_score,
            business_fit_score=item.result.business_fit_score,
            growth_score=item.result.growth_score,
            bonus_score=item.result.bonus_score,
            eligibility_status=item.result.eligibility_status,
            recommendation_level=item.result.recommendation_level,
            summary_reason=item.result.summary_reason,
            weakness=item.result.weakness,
            strategy_suggestion=item.result.strategy_suggestion,
            result_json=item.result.result_json,
        )
        for item in items
    ]
