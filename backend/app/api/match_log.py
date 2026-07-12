"""
api/match_log.py

매칭 실행 로그 라우터.
POST /match-logs        -> 매칭 실행: 분석 완료된 사업계획서로 match_log 생성
GET  /match-logs        -> 내 매칭 로그 리스트 (분석 페이지의 "이전 매칭 기록")
GET  /match-logs/{id}   -> 단건 조회 (결과 페이지가 어떤 실행인지 표시)

공고 매칭(스코어링·결과 생성) 로직은 아직 미구현이다. POST는 실행 1회를
나타내는 match_log를 만들고 질의 재료(analysis_json)를 스냅샷한 뒤 곧바로
completed로 기록한다 — 이후 매칭 로직이 생기면 이 지점에서 running으로 만들고
스코어링이 match_result를 채운 뒤 completed로 바꾸는 구조로 확장한다.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.match import MatchLog
from app.models.user import User
from app.repositories import match_log_repository
from app.repositories.business_plan_repository import get_owned_by_user
from app.schemas.business_plan import JobStatus
from app.schemas.match_log import MatchLogCreateRequest, MatchLogResponse

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
