"""
api/notice_attachment_precollection.py

공고 첨부파일 사전 OCR 트리거 라우터.
POST /internal/notices/attachment-ocr/precollect -> 사전 OCR 대상 조회 + 일괄 시작 (202 Accepted)

온디맨드 OCR(notice_ocr_service, notice_normalization_service)의 첫 요청이
느려지는 문제를 막기 위해 수집 직후 미리 parsed_text를 채운다(전체 출처 대상).
실제 실행은 notice_ocr.py의 배치 트리거를 재사용해 로직을 중복 구현하지 않는다.
"""

from fastapi import APIRouter, BackgroundTasks, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.notice_ocr import start_notice_ocr_batch
from app.db.session import get_db
from app.repositories.notice_repository import get_notice_ids_pending_attachment_ocr
from app.schemas.notice_attachment_precollection import (
    NoticeAttachmentPrecollectRequest,
    NoticeAttachmentPrecollectResponse,
)
from app.schemas.notice_ocr import NoticeOcrBatchTriggerRequest

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

# NoticeOcrBatchTriggerRequest.notice_ids 상한(30건)과 동일 — 넘는 만큼은 나눠 호출한다.
_BATCH_CHUNK_SIZE = 30


@router.post(
    "/attachment-ocr/precollect",
    response_model=NoticeAttachmentPrecollectResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 첨부파일 사전 OCR 트리거",
    description=(
        "모든 출처(기업마당/K-Startup/과학기술정보통신부) 공고 중 첨부파일 "
        "OCR이 아직 안 된 공고를 찾아 일괄로 OCR을 시작한다. 실제 진행 상태는 "
        "응답의 job_id로 기존 OCR 상태 조회 API(GET /internal/notices/ocr/batch/status)를 그대로 쓴다."
    ),
)
async def precollect_notice_attachment_ocr(
    background_tasks: BackgroundTasks,
    request: NoticeAttachmentPrecollectRequest = NoticeAttachmentPrecollectRequest(),
    session: AsyncSession = Depends(get_db),
):
    notice_ids = await get_notice_ids_pending_attachment_ocr(
        session, limit=request.limit, exclude_source_names=set()
    )
    if not notice_ids:
        return NoticeAttachmentPrecollectResponse(notice_ids=[], items=[])

    items = []
    for i in range(0, len(notice_ids), _BATCH_CHUNK_SIZE):
        chunk = notice_ids[i : i + _BATCH_CHUNK_SIZE]
        batch_response = await start_notice_ocr_batch(
            NoticeOcrBatchTriggerRequest(notice_ids=chunk), background_tasks
        )
        items.extend(batch_response.items)

    return NoticeAttachmentPrecollectResponse(notice_ids=notice_ids, items=items)
