from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.schemas.notice_bookmark import BookmarkCreateRequest, BookmarkResponse
from app.services.bookmark_service import (
    BookmarkTargetNotFoundError,
    add_bookmark,
    list_bookmarks,
    remove_bookmark,
)

router = APIRouter(prefix="/bookmarks", tags=["bookmarks"])


@router.get(
    "",
    response_model=list[BookmarkResponse],
    summary="내 북마크 목록",
    description="최신순. 각 항목의 기반 사업계획서 제목과 stale(예전 계획서 기준) 여부를 함께 준다.",
)
async def get_bookmarks(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    return await list_bookmarks(session, user=current_user)


@router.post(
    "",
    response_model=BookmarkResponse,
    status_code=status.HTTP_201_CREATED,
    summary="북마크 담기",
    description=(
        "추천 카드에서 담을 땐 match_result_id 를, 공고 목록에서 담을 땐 "
        "notice_id 를 보낸다. 이미 담긴 (공고, 사업계획서) 면 기존 것을 그대로 돌려준다."
    ),
)
async def create_bookmark(
    payload: BookmarkCreateRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    try:
        return await add_bookmark(session, user=current_user, req=payload)
    except BookmarkTargetNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="담으려는 공고 또는 추천 결과를 찾을 수 없습니다.",
        ) from exc


@router.delete(
    "/{bookmark_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="북마크 해제",
)
async def delete_bookmark(
    bookmark_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
):
    deleted = await remove_bookmark(session, user=current_user, bookmark_id=bookmark_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="북마크를 찾을 수 없습니다.",
        )
