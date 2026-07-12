"""기업 프로필 라우터.

본인(get_current_user로 인증된 유저)의 기업 프로필만 저장/조회한다. 쿠키
또는 Bearer 어느 인증이든 통과하면 된다.
"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.company import CompanyProfile
from app.models.user import User
from app.schemas.company import CompanyProfileResponse, CompanyProfileUpdate
from app.services import company_service
from app.services.company_service import CompanyProfileInconsistentError

router = APIRouter(prefix="/company-profile", tags=["company-profile"])


@router.get(
    "/me",
    response_model=CompanyProfileResponse | None,
    summary="내 기업 프로필 조회",
    responses={401: {"description": "인증되지 않음"}},
)
async def get_my_company_profile(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CompanyProfile | None:
    """본인의 기업 프로필을 반환한다. 아직 저장 전이면 null."""
    return await company_service.get_my_profile(session, current_user.id)


@router.put(
    "/me",
    response_model=CompanyProfileResponse,
    summary="내 기업 프로필 저장(부분 갱신)",
    responses={
        400: {"description": "사업자유형과 기업 단계 조합이 올바르지 않음"},
        401: {"description": "인증되지 않음"},
    },
)
async def save_my_company_profile(
    payload: CompanyProfileUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> CompanyProfile:
    """보낸 필드만 반영해 본인 프로필을 저장한다(없으면 생성)."""
    fields = payload.model_dump(exclude_unset=True)
    try:
        return await company_service.save_my_profile(session, current_user.id, fields)
    except CompanyProfileInconsistentError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc
