"""
services/notice_embedding_service.py

2차 필터링(docs/matching-pipeline.md 4단계)의 "공고 PDF → 벡터 DB" 부분.
공고 하나의 OCR 텍스트(notice_attachment.parsed_text)를 청크로 나눠 임베딩하고
Chroma에 적재한다. 정규화(notice_normalization_service) 단계에서 이미 OCR이
끝나 parsed_text가 채워져 있으면 그걸 그대로 쓰고, 아직 없으면(정규화가
summary_text만으로 진행됐거나 그 뒤 첨부파일이 추가된 경우 등)
notice_ocr_service.ensure_notice_attachment_ocr()로 온디맨드 OCR을 수행한다 —
docs/matching-pipeline.md 4단계 원래 설계("1차로 좁혀진 공고에 한해서만
원문을 연다")대로, 1차 필터링을 통과한 후보에 한해서만(이 함수가 그 후보에
대해서만 호출되므로) 첨부파일을 실제로 열어본다.

벡터 DB 캐싱 규칙(성공만 캐싱)에 따라 이미 청크가 있으면 그대로 재사용하고,
첨부파일 텍스트가 끝내 없으면(문서 자체가 없거나 OCR을 못 연 경우) 임베딩을
시도하지 않는다 — summary_text로 대체하지 않는 이유는 docs/matching-pipeline.md
4단계 "첨부파일이 없는 매칭 후보 공고 처리" 참고(상세 자격요건을 놓칠 위험이
있어 택하지 않은 선택지).

다만 "이미 청크가 있으면"은 Postgres notice_chunk 테이블만 보고 판단하지
않는다 — 실제로 Chroma notice_collection이 (볼륨 교체·초기화 등으로) 비어
있는데 Postgres 캐시만 남아 있던 사례를 실측함(2026-07-14, docker chroma
볼륨 이름이 바뀌면서 이전 임베딩 벡터가 새 볼륨으로 넘어가지 못함 — notice_id
1/2/3의 notice_chunk는 30건 그대로인데 notice_collection.count()는 0).
이 상태를 그냥 "이미 임베딩됨"으로 반환하면 2차 필터링 유사도 검색이 항상
0건으로 끝나는데도 원인을 알 방법이 없어, Chroma에 실제로 있는지 한 번 더
확인한다.
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chroma_client import get_notice_collection
from app.ai.embedding_client import embed_texts
from app.models.category import CategoryName, KgCategory
from app.models.notice import Notice, NoticeAttachment, NoticeChunk
from app.repositories import notice_repository
from app.services.notice_ocr_service import ensure_notice_attachment_ocr
from app.services.rd_notice_chunking import chunk_rd_notice_text
from app.services.text_chunking import chunk_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class NoticeEmbeddingResult:
    embedded: bool
    chunk_count: int
    skipped_reason: str | None = None
    """embedded가 False일 때만 값이 있다. 현재는 "no_text" 하나뿐."""


async def _is_rd_notice(session: AsyncSession, notice_id: int) -> bool:
    """R&D(기술개발) 카테고리 공고인지 확인한다.
    이 경우만 rd_notice_chunking의 섹션 기반 청킹을 쓴다(그 외는 범용 chunk_text)."""
    notice = await session.get(Notice, notice_id)
    if notice is None or notice.category_id is None:
        return False
    rd_category_id = (
        await session.execute(
            select(KgCategory.id).where(KgCategory.name == CategoryName.TECH)
        )
    ).scalar_one_or_none()
    return rd_category_id is not None and notice.category_id == rd_category_id


async def _chunks_exist_in_chroma(chunks: list[NoticeChunk]) -> bool:
    """notice_chunk 캐시 행들이 실제로 Chroma에도 벡터로 남아 있는지 확인한다.

    embeddings/documents는 필요 없고 id 존재 여부만 보면 되므로 include=[]로
    응답 크기를 최소화한다.
    """
    collection = get_notice_collection()
    response = await asyncio.to_thread(
        collection.get,
        ids=[str(chunk.id) for chunk in chunks],
        include=[],
    )
    return len(response.get("ids") or []) == len(chunks)


def _chunks_are_stale(chunks: list[NoticeChunk], target: NoticeAttachment) -> bool:
    """원문(첨부파일)이 청크보다 나중에 갱신됐으면(재수집 등) 낡은 청크로 본다.
    2줄 요약: created_at 기준으로 최신 청크 시각과 첨부파일 updated_at을 비교한다."""
    latest_chunk_at = max(chunk.created_at for chunk in chunks)
    return target.updated_at > latest_chunk_at


async def ensure_notice_embedded(
    session: AsyncSession, notice_id: int
) -> NoticeEmbeddingResult:
    """공고 하나의 2차 필터링 임베딩이 준비돼 있는지 확인하고, 없거나 낡았으면 만든다.

    커밋은 하지 않는다(flush만) — 매칭 파이프라인의 공유 세션 안에서 여러 공고를
    순회하며 호출될 수 있어(secondary_filtering_service), 호출자가 트랜잭션
    경계를 관리한다(match_log_repository.create/replace_results와 동일한 규칙).
    """
    target = await ensure_notice_attachment_ocr(session, notice_id)
    if target is None or not target.parsed_text:
        return NoticeEmbeddingResult(
            embedded=False, chunk_count=0, skipped_reason="no_text"
        )

    existing = await notice_repository.get_notice_chunks_by_notice_id(
        session, notice_id
    )
    if existing and not _chunks_are_stale(existing, target):
        if await _chunks_exist_in_chroma(existing):
            return NoticeEmbeddingResult(embedded=True, chunk_count=len(existing))
        logger.warning(
            "공고 %s의 notice_chunk 캐시(%d건)는 있지만 Chroma에 벡터가 없어 "
            "재임베딩한다 (벡터 DB 유실·볼륨 교체 등으로 캐시 정합성이 깨진 "
            "경우로 추정)",
            notice_id,
            len(existing),
        )
    elif existing:
        logger.info(
            "공고 %s의 원문이 청크보다 최신이라 재임베딩한다 (재수집 등으로 "
            "첨부파일이 갱신된 경우로 추정)",
            notice_id,
        )

    chunks = (
        chunk_rd_notice_text(target.parsed_text)
        if await _is_rd_notice(session, notice_id)
        else chunk_text(target.parsed_text, chunk_type="attachment")
    )
    if not chunks:
        return NoticeEmbeddingResult(
            embedded=False, chunk_count=0, skipped_reason="no_text"
        )

    # 임베딩(외부 API 호출)을 Postgres에 아무것도 쓰기 전에 먼저 시도한다 —
    # 실패해도 되돌릴 DB 상태가 없어야, 공유 세션 안에서 앞서 처리한 다른
    # 공고나 match_log 같은 미커밋 변경을 건드리지 않고 이 공고만 건너뛸 수
    # 있다(아래에서 session.rollback() 대신 이 공고의 행만 지우는 이유와 동일).
    vectors = await embed_texts([chunk.chunk_text for chunk in chunks])

    saved_rows = await notice_repository.replace_notice_chunks(
        session,
        notice_id,
        [(chunk.chunk_type, chunk.chunk_text) for chunk in chunks],
    )
    collection = get_notice_collection()
    try:
        # chromadb의 PersistentClient는 동기 API라, 이벤트 루프를 막지 않도록
        # 스레드로 넘긴다(xuswns/chromadb-embedded-deployment.md 5번 항목 —
        # CPU-bound 구간은 단일 워커의 이벤트 루프를 블로킹할 수 있다는 주의와
        # 동일한 이유).
        await asyncio.to_thread(
            collection.upsert,
            ids=[str(row.id) for row in saved_rows],
            embeddings=vectors,
            documents=[row.chunk_text for row in saved_rows],
            metadatas=[{"notice_id": notice_id} for _ in saved_rows],
        )
    except Exception:
        # session.rollback()은 쓰지 않는다 — 공유 세션에 이미 반영된 다른
        # 미커밋 변경(다른 공고의 청크, match_log 등)까지 통째로 되돌리게 된다.
        # replace_notice_chunks(chunks=[])는 delete 후 아무것도 넣지 않으므로
        # 방금 넣은 이 공고의 청크 행만 정확히 제거한다.
        await notice_repository.replace_notice_chunks(session, notice_id, [])
        raise

    logger.info(
        "공고 임베딩 완료 (notice_id=%s): 청크 %d건", notice_id, len(saved_rows)
    )
    return NoticeEmbeddingResult(embedded=True, chunk_count=len(saved_rows))
