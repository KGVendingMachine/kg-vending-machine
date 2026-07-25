"""1차 필터링(하드필터) 라우터.

인증된 사용자의 대표 기업 프로필을 기준으로 하드필터를 통과한 공고 id
목록을 반환한다. 프로필 소유 확인은 get_current_user + 대표 프로필 조회로
자연히 보장된다(남의 프로필을 지정할 경로가 없다).
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notice_eligibility import EligibleNoticesResponse
from app.services import company_service, notice_eligibility_service

router = APIRouter(prefix="/eligible-notices", tags=["eligible-notices"])


@router.get(
    "/me",
    response_model=EligibleNoticesResponse,
    summary="내 기업 프로필 기준 1차 필터 통과 공고",
    responses={
        401: {"description": "인증되지 않음"},
        404: {"description": "기업 프로필 없음"},
    },
)
async def get_my_eligible_notices(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> EligibleNoticesResponse:
    """본인 대표 기업 프로필로 하드필터를 통과한 공고 id와 축별 집계를 반환."""
    profile = await company_service.get_my_profile(session, current_user.id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="기업 프로필이 아직 없습니다.",
        )
    result = await notice_eligibility_service.get_eligible_notices(session, profile)
    return EligibleNoticesResponse(notice_ids=result.notice_ids, counts=result.counts)
