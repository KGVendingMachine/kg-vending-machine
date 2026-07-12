"""
api/notice_ocr.py

공고 첨부파일 OCR 트리거 라우터.
POST /internal/notices/{notice_id}/ocr                              -> OCR 작업 시작 (202 Accepted)
GET  /internal/notices/{notice_id}/ocr/{job_id}                      -> 작업 상태/결과 조회
POST /internal/notices/ocr/batch                                     -> 여러 공고 OCR 작업 일괄 시작 (202 Accepted)
GET  /internal/notices/ocr/batch/status                              -> 배치 상태 일괄 조회
GET  /internal/notices/{notice_id}/attachments/{attachment_id}/text  -> OCR 추출 텍스트 조회

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

import asyncio
import tempfile
import uuid
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.bizinfo_client import download_bizinfo_attachment
from app.crawler.kstartup_attachment_client import (
    download_kstartup_attachment,
    fetch_kstartup_attachments,
)
from app.db.session import async_session_factory, get_db
from app.models.notice import NoticeAttachment
from app.ocr.extract import extract_text
from app.repositories.notice_repository import (
    get_notice_attachment,
    get_notice_attachments,
    get_notice_detail,
    save_attachment,
    set_attachment_parsed_text,
)
from app.schemas.notice_ocr import (
    NoticeAttachmentTextResponse,
    NoticeOcrBatchJobItem,
    NoticeOcrBatchStatusResponse,
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

# "공고"/"공모"가 들어있어도 신청 양식 자체일 수 있다 — 실제 DB에서 배치
# 트리거를 돌려보다 발견함(이슈 검증 중, 2026-07-11): "붙임1. ...3차 공모
# 융자신청서.hwp"는 "공모"를 포함하지만 실제 공고문은 같은 공고의 다른
# 첨부파일 "[공모] ...공모요강(변경).pdf"였다. "신청서식(변경공고).hwp"처럼
# 신청 양식 파일명에 "공고"가 들어간 경우도 실제로 있었다. 두 키워드가
# 동시에 있으면 신청 양식으로 간주해 후보에서 제외한다.
_APPLICATION_FORM_KEYWORDS = ("신청서", "서식", "동의서", "확인서", "확약서")


def _is_notice_document_name(file_name: str | None) -> bool:
    if not file_name:
        return False
    if any(kw in file_name for kw in _APPLICATION_FORM_KEYWORDS):
        return False
    return any(kw in file_name for kw in _NOTICE_DOCUMENT_KEYWORDS)


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

    # parsed_text는 Optional[str]라 None(아직 처리 안 함)과 ""(처리했는데
    # 텍스트가 없었음)을 구분해야 한다 — truthy 체크(`if a.parsed_text`)를
    # 쓰면 빈 문자열도 "아직 처리 안 함"으로 보여 매번 재-OCR하게 된다.
    already_parsed = next((a for a in candidates if a.parsed_text is not None), None)
    if already_parsed is not None:
        return already_parsed
    return candidates[0] if candidates else None


async def _save_kstartup_attachments(
    session: AsyncSession, notice_id: int, fetched: list[tuple[str, str]]
) -> list[NoticeAttachment]:
    for file_name, file_url in fetched:
        await save_attachment(
            session, notice_id, file_name, file_url, _file_type_from_name(file_name)
        )
    await session.commit()
    return await get_notice_attachments(session, notice_id)


async def _run_notice_ocr_job(job_id: str, notice_id: int) -> None:
    """DB가 필요한 부분(공고/첨부파일 조회, 결과 저장)만 세션을 열고,
    다운로드·CLOVA OCR처럼 DB가 필요 없는 느린 외부 호출(길면 100초 이상,
    실측: 이미지 48개짜리 문서 122초) 동안은 세션을 닫아 커넥션을
    반납한다. 배치 트리거로 여러 건을 동시에 돌릴 때, DB pool
    기본값(pool_size=5)을 느린 외부 호출 때문에 다 붙들고 있다가 다른
    요청이 커넥션을 못 받는 상황을 막기 위함(2026-07-11 확인)."""
    async with async_session_factory() as session:
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
        external_id = notice.external_id

        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id, notice_id=notice_id, status=NoticeOcrJobStatus.RUNNING
        )

        try:
            attachments = await get_notice_attachments(session, notice_id)
        except Exception as exc:
            _JOBS[job_id] = NoticeOcrJobStatusResponse(
                job_id=job_id,
                notice_id=notice_id,
                status=NoticeOcrJobStatus.FAILED,
                error_message=f"첨부파일 조회 실패: {exc}",
            )
            return

    needs_kstartup_crawl = not attachments and source_name == KSTARTUP_SOURCE_NAME
    if needs_kstartup_crawl:
        # K-Startup 상세페이지 크롤링은 최대 15초 x 3회 재시도(최대 45초)
        # 걸릴 수 있는 외부 호출이라, 위 세션을 닫은 뒤(DB 커넥션 반납한
        # 채로) 수행한다 — 다운로드·OCR과 같은 이유(2026-07-11).
        try:
            fetched = await fetch_kstartup_attachments(int(external_id))
        except Exception as exc:
            _JOBS[job_id] = NoticeOcrJobStatusResponse(
                job_id=job_id,
                notice_id=notice_id,
                status=NoticeOcrJobStatus.FAILED,
                error_message=f"첨부파일 조회 실패: {exc}",
            )
            return

        async with async_session_factory() as session:
            attachments = await _save_kstartup_attachments(session, notice_id, fetched)

    # _pick_ocr_target은 이미 메모리에 있는 attachments만 보는 순수 로직이라
    # DB 세션이 필요 없다.
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

    if target.parsed_text is not None:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.COMPLETED,
            attachment_id=target.id,
            file_name=target.file_name,
            char_count=len(target.parsed_text),
        )
        return

    attachment_id = target.id
    attachment_file_url = target.file_url
    attachment_file_type = target.file_type
    attachment_file_name = target.file_name

    try:
        if source_name == KSTARTUP_SOURCE_NAME:
            data = await download_kstartup_attachment(attachment_file_url)
        else:
            data = await download_bizinfo_attachment(attachment_file_url)
    except Exception as exc:
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            attachment_id=attachment_id,
            error_message=f"첨부파일 다운로드 실패: {exc}",
        )
        return

    suffix = _SUFFIX_BY_FILE_TYPE.get(attachment_file_type or "", ".pdf")
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
            attachment_id=attachment_id,
            error_message=f"OCR 실패: {exc}",
        )
        return
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    async with async_session_factory() as session:
        saved = await set_attachment_parsed_text(session, attachment_id, text)
        await session.commit()

    if not saved:
        # 다운로드·OCR이 도는 동안 "기업마당 우선 정책"으로 이 공고 자체가
        # 정리(cascade 삭제)됐을 수 있다 — 이 경우 COMPLETED로 잘못
        # 보고하면 실제로는 저장 안 된 결과를 저장됐다고 오인하게 된다.
        _JOBS[job_id] = NoticeOcrJobStatusResponse(
            job_id=job_id,
            notice_id=notice_id,
            status=NoticeOcrJobStatus.FAILED,
            attachment_id=attachment_id,
            error_message="OCR은 끝났지만 첨부파일이 더 이상 존재하지 않아 저장하지 못했습니다"
            "(다른 출처의 중복 공고로 정리됐을 수 있습니다).",
        )
        return

    _JOBS[job_id] = NoticeOcrJobStatusResponse(
        job_id=job_id,
        notice_id=notice_id,
        status=NoticeOcrJobStatus.COMPLETED,
        attachment_id=attachment_id,
        file_name=attachment_file_name,
        char_count=len(text),
    )


async def _execute_notice_ocr_job(job_id: str, notice_id: int) -> None:
    try:
        await _run_notice_ocr_job(job_id, notice_id)
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


def _create_pending_job(notice_id: int) -> NoticeOcrJobStatusResponse:
    """PENDING 상태의 job을 만들어 _JOBS에 등록한다 (백그라운드 실행은 등록하지
    않음). 단건/배치 트리거 둘 다 여기서 job을 만들고, 실행 방식(백그라운드
    태스크를 개별로 등록할지 묶어서 등록할지)만 호출자가 다르게 가져간다."""
    job_id = str(uuid.uuid4())
    job = NoticeOcrJobStatusResponse(
        job_id=job_id, notice_id=notice_id, status=NoticeOcrJobStatus.PENDING
    )
    _JOBS[job_id] = job
    return job


def _start_notice_ocr_job(
    notice_id: int, background_tasks: BackgroundTasks
) -> NoticeOcrJobStatusResponse:
    """공고 하나에 대한 OCR job을 새로 만들어 백그라운드로 실행시킨다.

    단건 트리거(start_notice_ocr)에서만 쓴다 — 배치 트리거는 여러 건을
    동시에 돌려야 해서 _run_batch_notice_ocr_jobs를 따로 쓴다(아래 참고).
    """
    job = _create_pending_job(notice_id)
    background_tasks.add_task(_execute_notice_ocr_job, job.job_id, notice_id)
    return job


# 배치 안의 job을 전부 동시에 돌리면 CLOVA 호출이 한꺼번에 몰릴 수 있어
# 이미지 OCR과 같은 이유로 동시 실행 수를 제한한다(extract.py의
# _MAX_CONCURRENT_IMAGE_OCR과 같은 값).
_MAX_CONCURRENT_BATCH_OCR = 5


async def _run_batch_notice_ocr_jobs(job_notice_pairs: list[tuple[str, int]]) -> None:
    """배치로 새로 만든 job들을 동시에 실행한다.

    FastAPI BackgroundTasks는 같은 응답에 등록된 task를 순서대로 하나씩
    await하며 실행한다 — job마다 background_tasks.add_task를 따로 부르면
    (실제로 그렇게 했다가 확인함) 공고 하나의 OCR이 오래 걸릴 때 뒤에 등록된
    "첨부파일 없음"처럼 즉시 끝나는 job까지 전부 그 뒤에서 기다리게 된다.
    배치를 만든 의미가 없어지므로, 여기서 직접 세마포어로 동시 실행한다.
    """
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_BATCH_OCR)

    async def _run_one(job_id: str, notice_id: int) -> None:
        async with semaphore:
            await _execute_notice_ocr_job(job_id, notice_id)

    await asyncio.gather(
        *(_run_one(job_id, notice_id) for job_id, notice_id in job_notice_pairs)
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
    new_jobs: list[tuple[str, int]] = []
    for notice_id in dict.fromkeys(request.notice_ids):  # 순서 유지하며 중복 제거
        existing = _active_job_for_notice(notice_id)
        if existing is not None:
            items.append(
                NoticeOcrBatchJobItem(
                    notice_id=notice_id, job_id=existing.job_id, status=existing.status
                )
            )
            continue

        job = _create_pending_job(notice_id)
        new_jobs.append((job.job_id, notice_id))
        items.append(
            NoticeOcrBatchJobItem(
                notice_id=notice_id, job_id=job.job_id, status=job.status
            )
        )

    if new_jobs:
        background_tasks.add_task(_run_batch_notice_ocr_jobs, new_jobs)
    return NoticeOcrBatchTriggerResponse(items=items)


@router.get(
    "/ocr/batch/status",
    response_model=NoticeOcrBatchStatusResponse,
    summary="공고 첨부파일 OCR 배치 상태 일괄 조회",
    description=(
        "배치 트리거(POST /ocr/batch) 응답의 job_id 목록으로 진행 상태를 한 번에 "
        "조회한다. 트리거는 여러 건을 한 번에 시작할 수 있는데 상태 확인은 "
        "건마다 따로 해야 하는 비대칭을 없애기 위한 용도. 존재하지 않는 "
        "job_id는 조용히 결과에서 빠진다(단건 조회의 404와 다름 — 배치 중 "
        "일부만 잘못된 job_id를 보내도 나머지 조회 자체가 실패하지 않게 함). "
        "job_ids를 아예 안 보내면(호출자가 자기 쪽에서 이미 완료 처리한 job을 "
        "다 걸러내고 남은 게 없는 경우 등) 422 대신 빈 목록을 반환한다."
    ),
)
async def get_notice_ocr_batch_status(job_ids: list[str] = Query(default=[])):
    # 배치 트리거(start_notice_ocr_batch)가 notice_id 중복을 순서 유지하며
    # 제거하는 것과 동일하게, 같은 job_id가 여러 번 들어와도 응답에
    # 중복으로 나가지 않게 한다.
    items = [_JOBS[job_id] for job_id in dict.fromkeys(job_ids) if job_id in _JOBS]
    return NoticeOcrBatchStatusResponse(items=items)


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


@router.get(
    "/{notice_id}/attachments/{attachment_id}/text",
    response_model=NoticeAttachmentTextResponse,
    summary="첨부파일 OCR 추출 텍스트 조회",
    description=(
        "OCR job 상태 조회(GET /{notice_id}/ocr/{job_id})는 char_count만 "
        "알려주고 실제 추출 텍스트는 주지 않는다 — 실제 내용을 확인하려면 "
        "이 API로 조회한다. 아직 OCR이 끝나지 않았으면 parsed_text가 null로 "
        "온다(빈 문자열과 구분 — _pick_ocr_target 참고)."
    ),
)
async def get_notice_attachment_text(
    notice_id: int, attachment_id: int, session: AsyncSession = Depends(get_db)
):
    attachment = await get_notice_attachment(session, notice_id, attachment_id)
    if attachment is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="해당 공고에서 첨부파일을 찾을 수 없습니다.",
        )
    return NoticeAttachmentTextResponse(
        notice_id=notice_id,
        attachment_id=attachment_id,
        file_name=attachment.file_name,
        file_type=attachment.file_type,
        parsed_text=attachment.parsed_text,
        char_count=(
            len(attachment.parsed_text) if attachment.parsed_text is not None else None
        ),
    )
