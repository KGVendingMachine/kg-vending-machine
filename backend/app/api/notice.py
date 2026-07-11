"""
api/notice.py

공고 조회 라우터 (프론트/AI가 실제로 목록·상세를 가져다 쓰는 공개 API).
GET /notices              -> 목록 (출처/카테고리/지역 필터, 페이지네이션)
GET /notices/{notice_id}  -> 상세
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.notice_repository import (
    get_notice_attachments_for_display,
    get_notice_detail,
    get_notice_regions,
    get_notice_regions_by_ids,
    get_notice_target_types,
    list_notices,
)
from app.schemas.notice import (
    NoticeAttachmentInfo,
    NoticeDetail,
    NoticeListResponse,
    NoticeSummary,
)

router = APIRouter(prefix="/notices", tags=["notices"])


@router.get(
    "",
    response_model=NoticeListResponse,
    summary="공고 목록 조회",
    description="출처/카테고리/지역으로 필터링하고, 기본적으로 마감 공고는 제외한다.",
)
async def get_notices(
    source: str | None = Query(default=None, description="기업마당 / K-Startup"),
    category: str | None = Query(
        default=None, description="자금, R&D·기술 등 통합 카테고리명"
    ),
    region_code: str | None = Query(default=None, description="행정표준코드, 전국=ALL"),
    exclude_closed: bool = Query(default=True, description="마감 공고 제외 여부"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
):
    rows, total = await list_notices(
        session,
        source_name=source,
        category_name=category,
        region_code=region_code,
        exclude_closed=exclude_closed,
        limit=limit,
        offset=offset,
    )
    regions_by_notice = await get_notice_regions_by_ids(
        session, [notice.id for notice, _, _ in rows]
    )

    items = [
        NoticeSummary(
            id=notice.id,
            source=source_name,
            title=notice.title,
            category=category_name,
            status=notice.status,
            application_start_date=notice.application_start_date,
            application_end_date=notice.application_end_date,
            regions=regions_by_notice.get(notice.id, []),
        )
        for notice, source_name, category_name in rows
    ]
    return NoticeListResponse(total=total, items=items)


@router.get(
    "/{notice_id}",
    response_model=NoticeDetail,
    summary="공고 상세 조회",
)
async def get_notice(
    notice_id: int,
    session: AsyncSession = Depends(get_db),
):
    row = await get_notice_detail(session, notice_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 id의 공고를 찾을 수 없습니다.",
        )
    notice, source_name, category_name = row

    regions = await get_notice_regions(session, notice_id)
    target_types = await get_notice_target_types(session, notice_id)
    attachments = await get_notice_attachments_for_display(session, notice_id)

    return NoticeDetail(
        id=notice.id,
        source=source_name,
        title=notice.title,
        category=category_name,
        status=notice.status,
        is_actionable=notice.is_actionable,
        application_start_date=notice.application_start_date,
        application_end_date=notice.application_end_date,
        source_url=notice.source_url,
        apply_url=notice.apply_url,
        summary_text=notice.summary_text,
        amount_label=notice.amount_label,
        regions=regions,
        target_types=target_types,
        attachments=[
            NoticeAttachmentInfo(
                file_name=a.file_name, file_url=a.file_url, file_type=a.file_type
            )
            for a in attachments
        ],
        created_at=notice.created_at,
        updated_at=notice.updated_at,
    )
