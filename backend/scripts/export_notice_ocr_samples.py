"""실제 DB에 수집된 공고(notice) 중 PDF/HWP/HWPX 첨부파일이 있는 것을 골라
다운로드 → 텍스트 추출(extract_text) → 공고 메타데이터와 합쳐서 AI 팀원에게
줄 샘플 JSON을 만든다.

기업마당 + K-Startup 둘 다 포함하되, 소스 비율은 상관없이 전체
_TOTAL_SAMPLE_COUNT건을 채우는 게 목표다. 기업마당은 목록 API 응답에
첨부파일이 이미 있어(수집 시점에 채워짐) DB 조회만 하면 되지만,
K-Startup은 목록 API에 첨부파일 정보가 없어 상세페이지를 크롤링해
첨부파일을 먼저 찾는다(app/crawler/kstartup_attachment_client.py,
notice_ocr.py의 _save_kstartup_attachments와 같은 방식) — 기업마당
쪽에서 목표치를 못 채우면 그 부족분만큼 K-Startup을 크롤링해서라도
채운다.

올해~작년 공고로 한정한다. 그래도 목표치를 못 채우면(예: 조건에 맞는
공고 자체가 부족) 있는 만큼만 담는다.

실행: uv run python scripts/export_notice_ocr_samples.py
"""

import asyncio
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.crawler.kstartup_attachment_client import fetch_kstartup_attachments
from app.db.session import async_session_factory
from app.models.category import KgCategory
from app.models.notice import Notice, NoticeAttachment
from app.models.notice_source import NoticeSource
from app.ocr.extract import extract_text

_TOTAL_SAMPLE_COUNT = 30
_TARGET_FILE_TYPES = {"PDF", "HWP", "HWPX"}
_KSTARTUP_CANDIDATE_POOL_SIZE = _TOTAL_SAMPLE_COUNT * 5
"""K-Startup은 후보 공고 중 첨부파일이 아예 없거나 대상 포맷이 아닌 경우가
많아(약 76%가 첨부파일 없음, docs/matching-pipeline.md 참고), 필요한
건수보다 넉넉하게 후보를 뽑아서 그중 실제로 채워지는 만큼만 쓴다."""
_SINCE_LAST_YEAR = date(datetime.now().year - 1, 1, 1)  # 작년 1/1부터 (올해 포함)
_OUTPUT_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "notice_ocr_samples.json"
)
_DOWNLOAD_TIMEOUT_SECONDS = 30


def _file_type_from_name(file_name: str) -> str | None:
    if "." not in file_name:
        return None
    return file_name.rsplit(".", 1)[-1].upper()


async def _fetch_bizinfo_candidates(
    session: AsyncSession,
) -> list[tuple[Notice, str, str | None, str, str]]:
    """기업마당 후보를 (Notice, source_name, category_name, file_name, file_url) 튜플로 반환한다."""
    stmt = (
        select(NoticeAttachment, Notice, NoticeSource.source_name, KgCategory.name)
        .join(Notice, Notice.id == NoticeAttachment.notice_id)
        .join(NoticeSource, NoticeSource.id == Notice.source_id)
        .outerjoin(KgCategory, KgCategory.id == Notice.category_id)
        .where(
            NoticeAttachment.file_type.in_(_TARGET_FILE_TYPES),
            NoticeSource.source_name == "기업마당",
            Notice.application_start_date.isnot(None),
            Notice.application_start_date >= _SINCE_LAST_YEAR,
        )
        .order_by(Notice.application_end_date.desc())
        .limit(_TOTAL_SAMPLE_COUNT)
    )
    result = await session.execute(stmt)
    return [
        (notice, source_name, category_name, attachment.file_name, attachment.file_url)
        for attachment, notice, source_name, category_name in result.all()
    ]


async def _fetch_kstartup_candidate_notices(
    session: AsyncSession,
) -> list[tuple[Notice, str, str | None]]:
    """K-Startup은 첨부파일이 DB에 없어 후보 공고만 먼저 넉넉히 뽑고,
    첨부파일은 나중에 상세페이지를 크롤링해서 찾는다."""
    stmt = (
        select(Notice, NoticeSource.source_name, KgCategory.name)
        .join(NoticeSource, NoticeSource.id == Notice.source_id)
        .outerjoin(KgCategory, KgCategory.id == Notice.category_id)
        .where(
            NoticeSource.source_name == "K-Startup",
            Notice.application_start_date.isnot(None),
            Notice.application_start_date >= _SINCE_LAST_YEAR,
        )
        .order_by(Notice.application_end_date.desc())
        .limit(_KSTARTUP_CANDIDATE_POOL_SIZE)
    )
    result = await session.execute(stmt)
    return list(result.all())


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.content


async def _build_sample(
    client: httpx.AsyncClient,
    notice: Notice,
    source_name: str,
    category_name: str | None,
    file_name: str,
    file_url: str,
    attachment_id: int | None,
) -> dict:
    suffix = "." + file_name.rsplit(".", 1)[-1].lower()
    file_bytes = await _download(client, file_url)
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
        tmp.write(file_bytes)
        tmp_path = tmp.name
    try:
        raw_text, file_type = await extract_text(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {
        "notice_id": notice.id,
        "attachment_id": attachment_id,
        "source": source_name,
        "category": category_name,
        "title": notice.title,
        "status": notice.status,
        "application_start_date": str(notice.application_start_date),
        "application_end_date": str(notice.application_end_date),
        "file_name": file_name,
        "file_type": file_type,
        "char_count": len(raw_text),
        "raw_text": raw_text,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


async def _collect_bizinfo_samples(client: httpx.AsyncClient) -> list[dict]:
    async with async_session_factory() as session:
        candidates = await _fetch_bizinfo_candidates(session)

    samples = []
    for notice, source_name, category_name, file_name, file_url in candidates:
        print(f"[기업마당] 처리 중: notice_id={notice.id} {file_name}")
        try:
            samples.append(
                await _build_sample(
                    client,
                    notice,
                    source_name,
                    category_name,
                    file_name,
                    file_url,
                    None,
                )
            )
        except Exception as exc:
            print(f"  실패: {exc}")
    return samples


async def _collect_kstartup_samples(
    client: httpx.AsyncClient, needed: int
) -> list[dict]:
    """기업마당에서 못 채운 나머지(needed건)를 K-Startup 크롤링으로 채운다."""
    if needed <= 0:
        return []

    async with async_session_factory() as session:
        candidate_notices = await _fetch_kstartup_candidate_notices(session)

    samples = []
    for notice, source_name, category_name in candidate_notices:
        if len(samples) >= needed:
            break
        try:
            attachments = await fetch_kstartup_attachments(int(notice.external_id))
        except Exception as exc:
            print(f"[K-Startup] 첨부파일 조회 실패: notice_id={notice.id} {exc}")
            continue

        target = next(
            (
                (name, url)
                for name, url in attachments
                if _file_type_from_name(name) in _TARGET_FILE_TYPES
            ),
            None,
        )
        if target is None:
            continue
        file_name, file_url = target

        print(f"[K-Startup] 처리 중: notice_id={notice.id} {file_name}")
        try:
            samples.append(
                await _build_sample(
                    client,
                    notice,
                    source_name,
                    category_name,
                    file_name,
                    file_url,
                    None,
                )
            )
        except Exception as exc:
            print(f"  실패: {exc}")
    return samples


async def main() -> None:
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS) as client:
        bizinfo_samples = await _collect_bizinfo_samples(client)
        remaining = _TOTAL_SAMPLE_COUNT - len(bizinfo_samples)
        kstartup_samples = await _collect_kstartup_samples(client, remaining)

    samples = bizinfo_samples + kstartup_samples
    if not samples:
        print("조건에 맞는 첨부파일이 있는 공고를 찾지 못했습니다.")
        return

    _OUTPUT_PATH.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(
        f"{len(samples)}건 저장 완료 (기업마당 {len(bizinfo_samples)}건, "
        f"K-Startup {len(kstartup_samples)}건): {_OUTPUT_PATH}"
    )


if __name__ == "__main__":
    asyncio.run(main())
