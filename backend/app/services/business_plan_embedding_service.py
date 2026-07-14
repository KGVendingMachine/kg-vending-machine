"""
services/business_plan_embedding_service.py

2차 필터링(docs/matching-pipeline.md 4단계)의 사업계획서 쪽 대응물.
사업계획서 원문(business_plan.raw_text — OCR로 이미 추출된 텍스트)을 청크로
나눠 임베딩하고 Chroma에 적재한다. notice_embedding_service와 대칭 구조지만,
사업계획서는 업로드당 1건뿐이라(공고처럼 후보군 순회가 없음) 업로드 분석
흐름(business_plan_analysis_service.run_analysis)에서 정규화 직후 한 번만
호출된다.

notice_embedding_service.ensure_notice_embedded와 동일한 이유로, Postgres
business_plan_chunk 캐시가 있어도 Chroma에 실제로 벡터가 있는지 한 번 더
확인한다 — 두 저장소가 (볼륨 교체·초기화 등으로) 어긋난 사례를 실측했다
(2026-07-14, business_plan_chunk 93건인데 business_plan_chunks 컬렉션은
63건).
"""

import asyncio
import logging
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chroma_client import get_business_plan_collection
from app.ai.embedding_client import embed_texts
from app.models.business_plan import BusinessPlanChunk
from app.repositories import business_plan_repository
from app.repositories.business_plan_repository import BusinessPlanNotFoundError
from app.services.text_chunking import chunk_text

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BusinessPlanEmbeddingResult:
    embedded: bool
    chunk_count: int
    skipped_reason: str | None = None
    """embedded가 False일 때만 값이 있다. 현재는 "no_text" 하나뿐."""


async def _chunks_exist_in_chroma(chunks: list[BusinessPlanChunk]) -> bool:
    """business_plan_chunk 캐시 행들이 실제로 Chroma에도 벡터로 남아 있는지
    확인한다(notice_embedding_service._chunks_exist_in_chroma와 동일)."""
    collection = get_business_plan_collection()
    response = await asyncio.to_thread(
        collection.get,
        ids=[str(chunk.id) for chunk in chunks],
        include=[],
    )
    return len(response.get("ids") or []) == len(chunks)


async def ensure_business_plan_embedded(
    session: AsyncSession, business_plan_id: int
) -> BusinessPlanEmbeddingResult:
    """사업계획서 하나의 2차 필터링 임베딩이 준비돼 있는지 확인하고, 없으면
    만든다. notice_embedding_service.ensure_notice_embedded와 동일하게
    커밋은 하지 않는다(flush만) — 호출자가 트랜잭션 경계를 관리한다.
    """
    existing = await business_plan_repository.get_business_plan_chunks(
        session, business_plan_id
    )
    if existing:
        if await _chunks_exist_in_chroma(existing):
            return BusinessPlanEmbeddingResult(embedded=True, chunk_count=len(existing))
        logger.warning(
            "사업계획서 %s의 business_plan_chunk 캐시(%d건)는 있지만 Chroma에 "
            "벡터가 없어 재임베딩한다 (벡터 DB 유실·볼륨 교체 등으로 캐시 "
            "정합성이 깨진 경우로 추정)",
            business_plan_id,
            len(existing),
        )

    plan = await business_plan_repository.get_by_id(session, business_plan_id)
    if plan is None:
        raise BusinessPlanNotFoundError(business_plan_id)
    if not plan.raw_text:
        return BusinessPlanEmbeddingResult(
            embedded=False, chunk_count=0, skipped_reason="no_text"
        )

    chunks = chunk_text(plan.raw_text, chunk_type="raw_text")
    if not chunks:
        return BusinessPlanEmbeddingResult(
            embedded=False, chunk_count=0, skipped_reason="no_text"
        )

    # notice_embedding_service와 동일한 이유로 임베딩(외부 호출)을 DB 쓰기보다
    # 먼저 시도한다.
    vectors = await embed_texts([chunk.chunk_text for chunk in chunks])

    saved_rows = await business_plan_repository.replace_business_plan_chunks(
        session,
        business_plan_id,
        [(chunk.chunk_type, chunk.chunk_text) for chunk in chunks],
    )
    collection = get_business_plan_collection()
    try:
        # notice_embedding_service.ensure_notice_embedded와 동일한 이유로
        # chromadb의 동기 API를 스레드로 넘긴다.
        await asyncio.to_thread(
            collection.upsert,
            ids=[str(row.id) for row in saved_rows],
            embeddings=vectors,
            documents=[row.chunk_text for row in saved_rows],
            metadatas=[{"business_plan_id": business_plan_id} for _ in saved_rows],
        )
    except Exception:
        # notice_embedding_service.ensure_notice_embedded와 동일한 이유로
        # session.rollback() 대신 이 사업계획서의 청크 행만 지운다.
        await business_plan_repository.replace_business_plan_chunks(
            session, business_plan_id, []
        )
        raise

    logger.info(
        "사업계획서 임베딩 완료 (business_plan_id=%s): 청크 %d건",
        business_plan_id,
        len(saved_rows),
    )
    return BusinessPlanEmbeddingResult(embedded=True, chunk_count=len(saved_rows))
