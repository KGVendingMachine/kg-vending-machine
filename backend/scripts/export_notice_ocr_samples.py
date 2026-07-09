"""실제 DB에 수집된 공고(notice) 중 PDF 첨부파일이 있는 것을 골라 다운로드 →
텍스트 추출(extract_text) → 공고 메타데이터와 합쳐서 AI 팀원에게 줄 샘플
JSON을 만든다.

올해~작년(2025~2026년) 공고 중 기업마당 출처로 한정한다.

실행: uv run python scripts/export_notice_ocr_samples.py
"""

import asyncio
import json
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

import httpx
from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.category import KgCategory
from app.models.notice import Notice, NoticeAttachment
from app.models.notice_source import NoticeSource
from app.ocr.extract import extract_text

_SAMPLE_COUNT = 5
_SOURCE_NAME = "기업마당"
_SINCE_LAST_YEAR = date(datetime.now().year - 1, 1, 1)  # 작년 1/1부터 (올해 포함)
_OUTPUT_PATH = Path(__file__).resolve().parent.parent / "data" / "notice_ocr_samples.json"
_DOWNLOAD_TIMEOUT_SECONDS = 30


async def _fetch_candidates() -> list[tuple[NoticeAttachment, Notice, str, str | None]]:
    stmt = (
        select(NoticeAttachment, Notice, NoticeSource.source_name, KgCategory.name)
        .join(Notice, Notice.id == NoticeAttachment.notice_id)
        .join(NoticeSource, NoticeSource.id == Notice.source_id)
        .outerjoin(KgCategory, KgCategory.id == Notice.category_id)
        .where(
            NoticeAttachment.file_type == "PDF",
            NoticeSource.source_name == _SOURCE_NAME,
            Notice.application_start_date.isnot(None),
            Notice.application_start_date >= _SINCE_LAST_YEAR,
        )
        .order_by(Notice.application_end_date.desc())
        .limit(_SAMPLE_COUNT)
    )
    async with async_session_factory() as session:
        result = await session.execute(stmt)
        rows = result.all()
    return [(row[0], row[1], row[2], row[3]) for row in rows]


async def _download(client: httpx.AsyncClient, url: str) -> bytes:
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    return response.content


async def _build_sample(
    client: httpx.AsyncClient,
    attachment: NoticeAttachment,
    notice: Notice,
    source_name: str,
    category_name: str | None,
) -> dict:
    pdf_bytes = await _download(client, attachment.file_url)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(pdf_bytes)
        tmp_path = tmp.name
    try:
        raw_text, file_type = await extract_text(tmp_path)
    finally:
        Path(tmp_path).unlink(missing_ok=True)

    return {
        "notice_id": notice.id,
        "attachment_id": attachment.id,
        "source": source_name,
        "category": category_name,
        "title": notice.title,
        "status": notice.status,
        "application_start_date": str(notice.application_start_date),
        "application_end_date": str(notice.application_end_date),
        "file_name": attachment.file_name,
        "file_type": file_type,
        "char_count": len(raw_text),
        "raw_text": raw_text,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }


async def main() -> None:
    candidates = await _fetch_candidates()
    if not candidates:
        print("조건에 맞는 PDF 첨부파일이 있는 공고를 찾지 못했습니다.")
        return

    samples = []
    async with httpx.AsyncClient(timeout=_DOWNLOAD_TIMEOUT_SECONDS) as client:
        for attachment, notice, source_name, category_name in candidates:
            print(f"처리 중: notice_id={notice.id} {attachment.file_name}")
            try:
                samples.append(
                    await _build_sample(
                        client, attachment, notice, source_name, category_name
                    )
                )
            except Exception as exc:
                print(f"  실패: {exc}")

    _OUTPUT_PATH.write_text(
        json.dumps(samples, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(samples)}건 저장 완료: {_OUTPUT_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
