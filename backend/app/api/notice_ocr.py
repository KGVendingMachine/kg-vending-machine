"""
api/notice_ocr.py

공고 첨부파일 OCR 트리거 라우터.
POST /internal/notices/{notice_id}/ocr             -> OCR 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/ocr/{job_id}     -> 작업 상태/결과 조회
POST /internal/notices/ocr/batch                   -> 여러 공고 OCR 작업 일괄 시작 (202 Accepted)

배치 트리거는 매칭 파이프라인이 1차 필터링을 통과한 후보 여러 건에 대해
한 번에 OCR을 걸어야 하는 상황(및 AI 팀 개발·검증용 실데이터 확보)을 위한
것으로, 공고 하나씩 반복 호출하는 것과 동작은 동일하고 요청 한 번으로
묶어주는 것뿐이다 — 이미 진행 중인 공고는 새로 트리거하지 않고 기존
job을 그대로 반환한다.

docs/matching-pipeline.md 4단계(2차 필터링)의 "매칭 후보로 좁혀진 공고에
한해 첨부파일 크롤링·OCR" 단계를 공고 하나 단위로 수행한다. K-Startup은
기존 notice_attachment에 메타데이터가 없으면 상세페이지를 크롤링해서
먼저 채운 뒤 다운로드하고, 기업마당은 이미 있는 URL로 바로 다운로드한다.

공고 하나에 첨부파일이 여러 개여도 "공고문"으로 보이는 파일 하나만
OCR한다(2026-07-11 프로토타입 범위 결정, `_pick_ocr_target` 참고) —
신청서식/붙임자료까지 합쳐 뽑지 않는다.

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
    NoticeOcrBatchJobItem,
    NoticeOcrBatchTriggerRequest,
    NoticeOcrBatchTriggerResponse,
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

# 공고 하나에 첨부파일이 여러 개면 "공고문" 하나만 OCR한다(2026-07-11
# 프로토타입 범위 결정, 신청서식/붙임자료는 대상 아님). 기업마당/K-Startup
# API 모두 어떤 파일이 공고문인지 알려주는 필드가 없어 파일명으로 판별해야
# 하는데, 실제 DB 첨부파일명 200건을 확인해보니 공고문은 "공고"/"공모"를
# 포함하고(예: "26년_지원사업_추가_공고문.pdf", "[공모] ...공모요강.pdf"),
# 신청서/서식/붙임/별첨 자료는 이 키워드가 없어 이름만으로 안정적으로
# 구분된다.
_NOTICE_DOCUMENT_KEYWORDS = ("공고", "공모")


def _is_notice_document_name(file_name: str | None) -> bool:
    return bool(file_name) and any(kw in file_name for kw in _NOTICE_DOCUMENT_KEYWORDS)


def _file_type_from_name(file_name: str) -> str | None:
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[-1].upper()


def _pick_ocr_target(attachments: list[NoticeAttachment]) -> NoticeAttachment | None:
    """공고문으로 보이는 첨부파일을 우선 고르고, 그중 이미 OCR된 게 있으면
    그걸 재사용한다.

    파일명으로 공고문을 특정할 수 없는 공고(오래된 데이터, 이름 규칙이
    다른 출처 등)도 있어, 공고문 후보가 하나도 없으면 예전처럼 문서 포맷 중
    첫 번째로 폴백한다 — 아예 처리를 포기하는 것보다 낫다고 판단.
    """
    documents = [a for a in attachments if a.file_type in _OCR_TARGET_FILE_TYPES]
    notice_documents = [a for a in documents if _is_notice_document_name(a.file_name)]
    candidates = notice_documents or documents

    already_parsed = next((a for a in candidates if a.parsed_text), None)
    if already_parsed is not None:
        return already_parsed
    return candidates[0] if candidates else None


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
        status_ = (
            NoticeOcrJobStatus.NO_ATTACHMENT
            if not attachments
            else NoticeOcrJobStatus.UNSUPPORTED_FORMAT
        )
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id, notice_id=notice_id, status=status_
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


def _active_job_for_notice(notice_id: int) -> NoticeOcrJobStatusResponse | None:
    return next(
        (
            job
            for job in _JOBS.values()
            if job.notice_id == notice_id
            and job.status in (NoticeOcrJobStatus.PENDING, NoticeOcrJobStatus.RUNNING)
        ),
        None,
    )


def _has_active_job_for_notice(notice_id: int) -> bool:
    return _active_job_for_notice(notice_id) is not None


def _start_notice_ocr_job(
    notice_id: int, background_tasks: BackgroundTasks
) -> NoticeOcrJobStatusResponse:
    """공고 하나에 대한 OCR job을 새로 만들어 백그라운드로 실행시킨다.

    단건 트리거(start_notice_ocr)와 배치 트리거가 동일한 시작 로직을
    쓰도록 공용화했다 — 동시 트리거 가드(진행 중이면 재사용)는 호출자가
    각자의 방식(단건은 409, 배치는 기존 job 그대로 반환)으로 처리한다.
    """
    job_id = str(uuid.uuid4())
    job = NoticeOcrJobStatusResponse(
        job_id=job_id, notice_id=notice_id, status=NoticeOcrJobStatus.PENDING
    )
    _JOBS[job_id] = job
    background_tasks.add_task(_execute_notice_ocr_job, job_id, notice_id)
    return job


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

    job = _start_notice_ocr_job(notice_id, background_tasks)
    return NoticeOcrJobAccepted(job_id=job.job_id, status=job.status)


@router.post(
    "/ocr/batch",
    response_model=NoticeOcrBatchTriggerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="공고 첨부파일 OCR 배치 시작",
    description=(
        "여러 공고에 대해 한 번에 OCR을 트리거한다. 이미 진행 중인 공고는 "
        "새로 시작하지 않고 기존 job을 그대로 반환한다."
    ),
)
async def start_notice_ocr_batch(
    request: NoticeOcrBatchTriggerRequest, background_tasks: BackgroundTasks
):
    items = []
    for notice_id in dict.fromkeys(request.notice_ids):  # 순서 유지하며 중복 제거
        existing = _active_job_for_notice(notice_id)
        job = existing or _start_notice_ocr_job(notice_id, background_tasks)
        items.append(
            NoticeOcrBatchJobItem(
                notice_id=notice_id, job_id=job.job_id, status=job.status
            )
        )
    return NoticeOcrBatchTriggerResponse(items=items)


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
