"""
api/notice_ocr.py

공고 첨부파일 OCR 트리거 라우터.
POST /internal/notices/{notice_id}/ocr             -> OCR 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/ocr/{job_id}     -> 작업 상태/결과 조회

docs/matching-pipeline.md 4단계(2차 필터링)의 "매칭 후보로 좁혀진 공고에
한해 첨부파일 크롤링·OCR" 단계를 공고 하나 단위로 수행한다. K-Startup은
기존 notice_attachment에 메타데이터가 없으면 상세페이지를 크롤링해서
먼저 채운 뒤 다운로드하고, 기업마당은 이미 있는 URL로 바로 다운로드한다.

벡터 DB 캐싱 규칙(성공만 캐싱)과 같은 이유로, 이미 parsed_text가 있는
첨부파일은 재-OCR하지 않고 그대로 재사용한다.
"""

import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import download_bizinfo_attachment
from app.crawler.kstartup_attachment_client import (
    download_kstartup_attachment,
    fetch_kstartup_attachments,
)
from app.db.session import async_session_factory
from app.models.notice import NoticeAttachment
from app.ocr.extract import extract_text
from app.repositories.notice_repository import (
    get_notice_attachments,
    get_notice_detail,
    save_attachment,
    set_attachment_parsed_text,
)
from app.schemas.notice_ocr import (
    NoticeOcrJobAccepted,
    NoticeOcrJobStatus,
    NoticeOcrJobStatusResponse,
)
from app.services.notice_collection_service import KSTARTUP_SOURCE_NAME

router = APIRouter(prefix="/internal/notices", tags=["internal-notices"])

_JOBS: dict[str, NoticeOcrJobStatusResponse] = {}

# extract_text()가 실제로 처리하는 문서 포맷만 대상으로 한다 (이미지/ZIP/
# 엑셀 등은 OCR 대상에서 제외 — DOC/DOCX는 extract_text가 아직 지원하지
# 않아 여기도 포함하지 않는다).
_OCR_TARGET_FILE_TYPES = {"PDF", "HWP", "HWPX"}

_SUFFIX_BY_FILE_TYPE = {"PDF": ".pdf", "HWP": ".hwp", "HWPX": ".hwpx"}


def _file_type_from_name(file_name: str) -> str | None:
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[-1].upper()


def _pick_ocr_target(attachments: list[NoticeAttachment]) -> NoticeAttachment | None:
    """이미 OCR된 게 있으면 그걸 우선하고, 없으면 문서 포맷 중 첫 번째를 고른다."""
    already_parsed = next(
        (
            a
            for a in attachments
            if a.file_type in _OCR_TARGET_FILE_TYPES and a.parsed_text
        ),
        None,
    )
    if already_parsed is not None:
        return already_parsed
    return next((a for a in attachments if a.file_type in _OCR_TARGET_FILE_TYPES), None)


async def _ensure_kstartup_attachments(
    session: AsyncSession, notice_id: int, external_id: str
) -> list[NoticeAttachment]:
    """K-Startup은 수집 시점에 첨부파일을 안 채워두므로, 없으면 여기서
    상세페이지를 크롤링해 채운다 (2차 필터링 시점에만 하기로 한 결정)."""
    fetched = await fetch_kstartup_attachments(int(external_id))
    for file_name, file_url in fetched:
        await save_attachment(
            session, notice_id, file_name, file_url, _file_type_from_name(file_name)
        )
    await session.commit()
    return await get_notice_attachments(session, notice_id)


async def _run_notice_ocr_job(
    session: AsyncSession, job_id: str, notice_id: int
) -> None:
    row = await get_notice_detail(session, notice_id)
    if row is None:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            error_message="해당 id의 공고를 찾을 수 없습니다.",
        )
        return
    notice, source_name, _ = row

    _JOBS[job_id] = NoticeOcrJobStatusResponse(
        job_id=job_id, notice_id=notice_id, status=NoticeOcrJobStatus.RUNNING
    )

    try:
        attachments = await get_notice_attachments(session, notice_id)
        if not attachments and source_name == KSTARTUP_SOURCE_NAME:
            attachments = await _ensure_kstartup_attachments(
                session, notice_id, notice.external_id
            )
    except Exception as exc:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            error_message=f"첨부파일 조회 실패: {exc}",
        )
        return

    target = _pick_ocr_target(attachments)
    if target is None:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id, notice_id=notice_id, status=NoticeOcrJobStatus.NO_ATTACHMENT
        )
        return

    if target.parsed_text:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.COMPLETED,
            attachment_id=target.id,
            file_name=target.file_name,
            char_count=len(target.parsed_text),
        )
        return

    try:
        if source_name == KSTARTUP_SOURCE_NAME:
            data = await download_kstartup_attachment(target.file_url)
        else:
            data = await download_bizinfo_attachment(target.file_url)
    except Exception as exc:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            attachment_id=target.id,
            error_message=f"첨부파일 다운로드 실패: {exc}",
        )
        return

    suffix = _SUFFIX_BY_FILE_TYPE.get(target.file_type or "", ".pdf")
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp_path = tmp.name
    try:
        Path(tmp_path).write_bytes(data)
        text, _ = await extract_text(tmp_path)
    except Exception as exc:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            attachment_id=target.id,
            error_message=f"OCR 실패: {exc}",
        )
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    await set_attachment_parsed_text(session, target.id, text)
    await session.commit()

    _JOBS[job_id] = NoticeOcrJobStatusResponse(
        job_id=job_id,
        notice_id=notice_id,
        status=NoticeOcrJobStatus.COMPLETED,
        attachment_id=target.id,
        file_name=target.file_name,
        char_count=len(text),
    )


async def _execute_notice_ocr_job(job_id: str, notice_id: int) -> None:
    try:
        async with async_session_factory() as session:
            await _run_notice_ocr_job(session, job_id, notice_id)
    except Exception as exc:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            error_message=f"OCR 작업 실행 실패: {exc}",
        )


def _has_active_job_for_notice(notice_id: int) -> bool:
    return any(
        job.notice_id == notice_id
        and job.status in (NoticeOcrJobStatus.PENDING, NoticeOcrJobStatus.RUNNING)
        for job in _JOBS.values()
    )


@router.post(
    "/{notice_id}/ocr",
    response_model=NoticeOcrJobAccepted,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 첨부파일 OCR 시작",
    description="공고 하나의 첨부파일(PDF/HWP/HWPX)을 확인·다운로드해 OCR 텍스트를 추출한다.",
)
async def start_notice_ocr(notice_id: int, background_tasks: BackgroundTasks):
    # 같은 공고에 대해 동시에 두 번 트리거되면 각자 독립적으로 다운로드+OCR을
    # 돌려서 CLOVA 호출 비용이 이중으로 나간다. 매칭 파이프라인이 여러 사용자
    # 요청에서 같은 공고를 후보로 겹쳐 뽑으면 실제로 벌어질 수 있는 상황.
    if _has_active_job_for_notice(notice_id):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 이 공고에 대한 OCR 작업이 진행 중입니다.",
        )

    job_id = str(uuid.uuid4())
    _JOBS[job_id] = NoticeOcrJobStatusResponse(
        job_id=job_id, notice_id=notice_id, status=NoticeOcrJobStatus.PENDING
    )
    background_tasks.add_task(_execute_notice_ocr_job, job_id, notice_id)
    return NoticeOcrJobAccepted(job_id=job_id, status=NoticeOcrJobStatus.PENDING)


@router.get(
    "/{notice_id}/ocr/{job_id}",
    response_model=NoticeOcrJobStatusResponse,
    summary="공고 첨부파일 OCR 상태 조회",
)
async def get_notice_ocr_status(notice_id: int, job_id: str):
    job = _JOBS.get(job_id)
    if job is None or job.notice_id != notice_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 job_id의 OCR 작업을 찾을 수 없습니다.",
        )
    return job
