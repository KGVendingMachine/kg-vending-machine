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

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chroma_client import get_notice_collection
from app.ai.embedding_client import AiEmbeddingError, embed_texts
from app.models.notice import NoticeChunk
from app.repositories import notice_repository
from app.services.notice_ocr_service import ensure_notice_attachment_ocr
from app.services.text_chunking import TextChunk, chunk_text

logger = logging.getLogger(__name__)

# 공고 정규화 배치와 동일한 값(notice_normalization_service._NOTICE_LLM_CONCURRENCY_LIMIT)
# — 계정 전체 동시 호출 한도가 실측된 적 없어 같은 보수적 기본값으로 시작.
_EMBEDDING_CONCURRENCY_LIMIT = 10


@dataclass(frozen=True)
class NoticeEmbeddingResult:
    embedded: bool
    chunk_count: int
    skipped_reason: str | None = None
    """embedded가 False일 때만 값이 있다. "no_text" 또는 "embedding_failed"."""


@dataclass(frozen=True)
class _PendingEmbedding:
    notice_id: int
    chunks: list[TextChunk]


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


async def ensure_notice_embedded(
    session: AsyncSession, notice_id: int
) -> NoticeEmbeddingResult:
    """공고 하나의 2차 필터링 임베딩이 준비돼 있는지 확인하고, 없으면 만든다.

    커밋은 하지 않는다(flush만) — 매칭 파이프라인의 공유 세션 안에서 여러 공고를
    순회하며 호출될 수 있어(secondary_filtering_service), 호출자가 트랜잭션
    경계를 관리한다(match_log_repository.create/replace_results와 동일한 규칙).
    """
    existing = await notice_repository.get_notice_chunks_by_notice_id(
        session, notice_id
    )
    if existing:
        if await _chunks_exist_in_chroma(existing):
            return NoticeEmbeddingResult(embedded=True, chunk_count=len(existing))
        logger.warning(
            "공고 %s의 notice_chunk 캐시(%d건)는 있지만 Chroma에 벡터가 없어 "
            "재임베딩한다 (벡터 DB 유실·볼륨 교체 등으로 캐시 정합성이 깨진 "
            "경우로 추정)",
            notice_id,
            len(existing),
        )

    target = await ensure_notice_attachment_ocr(session, notice_id)
    if target is None or not target.parsed_text:
        return NoticeEmbeddingResult(
            embedded=False, chunk_count=0, skipped_reason="no_text"
        )

    chunks = chunk_text(target.parsed_text, chunk_type="attachment")
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


async def ensure_notices_embedded(
    session: AsyncSession, notice_ids: list[int]
) -> dict[int, NoticeEmbeddingResult]:
    """여러 공고의 2차 필터링 임베딩을 한 번에 준비한다(2026-07-16, RAG 성능
    개선 검토 — secondary_filtering_service의 순차 루프가 병목이라 병렬화).

    ensure_notice_embedded와 달리, 세션이 필요한 작업(캐시 확인·OCR·DB
    쓰기)은 절대 병렬화하지 않고 순차로 실행한다 — SQLAlchemy AsyncSession은
    동시 접근이 공식적으로 지원되지 않는다. 세션이 필요 없는 임베딩 API
    호출(embed_texts)만 세마포어로 동시 실행한다. 이 원칙은
    notice_normalization_service._resolve_candidate_text/_try_normalize_candidate가
    세션을 아예 받지 않고, DB 쓰기 직전에 session.commit()으로 커넥션을
    반납한 뒤에야 LLM 호출을 병렬화하는 것과 동일하다(그쪽 주석에 배치
    트리거 다건 동시 실행 시 커넥션 풀 고갈을 실제로 재현한 적 있다고
    기록돼 있음).

    ensure_notice_embedded와 달리 임베딩 실패(AiEmbeddingError)나 저장 실패를
    예외로 던지지 않고 skipped_reason="embedding_failed"인 결과로 돌려준다 —
    호출자(run_secondary_filtering)가 공고 하나의 실패로 전체 매칭이
    중단되지 않도록 이미 개별 격리하고 있어, 그 계약을 여기서 그대로
    구현한다(기존에는 이 함수를 호출하는 쪽의 try/except AiEmbeddingError로
    격리했었는데, Chroma upsert 실패 같은 AiEmbeddingError가 아닌 예외는
    잡히지 않고 전체 매칭을 중단시키는 허점이 있었다 — 이번에 같이 없앤다).

    커밋은 하지 않는다(flush만) — ensure_notice_embedded와 동일하게 호출자가
    트랜잭션 경계를 관리한다.
    """
    results: dict[int, NoticeEmbeddingResult] = {}
    pending: list[_PendingEmbedding] = []

    # 1단계(순차, session 필요): 캐시 확인 + OCR + 청킹.
    for notice_id in notice_ids:
        existing = await notice_repository.get_notice_chunks_by_notice_id(
            session, notice_id
        )
        if existing:
            if await _chunks_exist_in_chroma(existing):
                results[notice_id] = NoticeEmbeddingResult(
                    embedded=True, chunk_count=len(existing)
                )
                continue
            logger.warning(
                "공고 %s의 notice_chunk 캐시(%d건)는 있지만 Chroma에 벡터가 없어 "
                "재임베딩한다 (벡터 DB 유실·볼륨 교체 등으로 캐시 정합성이 깨진 "
                "경우로 추정)",
                notice_id,
                len(existing),
            )

        target = await ensure_notice_attachment_ocr(session, notice_id)
        if target is None or not target.parsed_text:
            results[notice_id] = NoticeEmbeddingResult(
                embedded=False, chunk_count=0, skipped_reason="no_text"
            )
            continue

        chunks = chunk_text(target.parsed_text, chunk_type="attachment")
        if not chunks:
            results[notice_id] = NoticeEmbeddingResult(
                embedded=False, chunk_count=0, skipped_reason="no_text"
            )
            continue

        pending.append(_PendingEmbedding(notice_id=notice_id, chunks=chunks))

    if not pending:
        return results

    # 2단계(병렬, session 없음): 임베딩 API 호출만 세마포어로 동시 실행.
    semaphore = asyncio.Semaphore(_EMBEDDING_CONCURRENCY_LIMIT)

    async def _embed_one(
        item: _PendingEmbedding,
    ) -> tuple[_PendingEmbedding, list[list[float]] | None]:
        async with semaphore:
            try:
                vectors = await embed_texts([c.chunk_text for c in item.chunks])
            except AiEmbeddingError:
                logger.warning(
                    "공고 임베딩 실패로 2차 필터링에서 제외 (notice_id=%s)",
                    item.notice_id,
                )
                return item, None
            return item, vectors

    embedded = await asyncio.gather(*(_embed_one(item) for item in pending))

    # 3단계(순차, session 필요): DB 쓰기 + Chroma upsert.
    collection = get_notice_collection()
    for item, vectors in embedded:
        if vectors is None:
            results[item.notice_id] = NoticeEmbeddingResult(
                embedded=False, chunk_count=0, skipped_reason="embedding_failed"
            )
            continue

        saved_rows = await notice_repository.replace_notice_chunks(
            session,
            item.notice_id,
            [(chunk.chunk_type, chunk.chunk_text) for chunk in item.chunks],
        )
        try:
            # chromadb의 PersistentClient는 동기 API라, 이벤트 루프를 막지
            # 않도록 스레드로 넘긴다(ensure_notice_embedded와 동일한 이유).
            await asyncio.to_thread(
                collection.upsert,
                ids=[str(row.id) for row in saved_rows],
                embeddings=vectors,
                documents=[row.chunk_text for row in saved_rows],
                metadatas=[{"notice_id": item.notice_id} for _ in saved_rows],
            )
        except Exception:
            # session.rollback() 대신 이 공고의 청크 행만 지운다
            # (ensure_notice_embedded와 동일한 이유 — 공유 세션의 다른
            # 미커밋 변경을 건드리지 않기 위함). 단, 여기서는 재발생시키지
            # 않고 이 공고만 건너뛴다 — 공고 하나의 Chroma 실패로 나머지
            # 후보 전부의 결과가 날아가면 안 되기 때문.
            await notice_repository.replace_notice_chunks(session, item.notice_id, [])
            logger.warning(
                "공고 %s Chroma 저장 실패로 2차 필터링에서 제외",
                item.notice_id,
                exc_info=True,
            )
            results[item.notice_id] = NoticeEmbeddingResult(
                embedded=False, chunk_count=0, skipped_reason="embedding_failed"
            )
            continue

        logger.info(
            "공고 임베딩 완료 (notice_id=%s): 청크 %d건",
            item.notice_id,
            len(saved_rows),
        )
        results[item.notice_id] = NoticeEmbeddingResult(
            embedded=True, chunk_count=len(saved_rows)
        )

    return results
