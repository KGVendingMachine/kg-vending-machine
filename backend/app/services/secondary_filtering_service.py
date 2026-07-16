"""
services/secondary_filtering_service.py

2차 필터링(docs/matching-pipeline.md 4단계)의 유사도 검색·스코어링 부분.
1차 하드필터(지역/대상/업력/기간, notice_eligibility_service.get_eligible_notices,
docs/first-filtering.md) + 품질 필터(matching_service._quality_errors)를 통과한
공고 후보군을, 사업계획서 청크 임베딩으로 Chroma에서 검색해 공고별 유사도
점수를 산출한다.

matching_service.run_matching()이 공유 세션 안에서 후보를 순회하며 호출하므로,
공고·사업계획서 임베딩이 아직 없으면 여기서 바로 만든다(온디맨드 —
notice_embedding_service/business_plan_embedding_service 참고. api/
notice_embedding.py의 job-trigger API는 별도 수동 트리거용이고 이 경로와는
무관하다). 임베딩을 만들 수 없는 공고(첨부파일 없음 등)나 사업계획서는 결과
딕셔너리에서 조용히 빠진다 — 후보 하나의 임베딩 실패로 전체 매칭이 중단되면
안 되기 때문에, matching_service는 점수가 빠진 공고를 "2차 필터링 근거 없음"
(중립 처리)으로 다룬다.

여기서 계산하는 코사인 유사도 점수는 그 자체로 최종 2차 필터링 점수가
아니다 — docs/secondary-filtering-llm-judge-guide.md 설계에 따라
matching_service가 이 점수로 공고 순위를 매겨 상위 K건만
secondary_filtering_judge_service.judge_notice()로 정밀 판정한다(비용이 큰
LLM 호출을 전체 후보가 아니라 유사도로 좁힌 상위권에만 돌리기 위함). 그
판정에 근거 원문이 필요하므로, 유사도 검색 결과의 청크 원문도 `evidence`에
함께 담아 반환한다.

반환값은 점수뿐 아니라 스킵 사유까지 담은 SecondaryFilteringResult다 —
docs/matching-pipeline.md 로깅 요구사항("OCR 대상 공고 수, 임베딩 실패 건수,
유사도 점수 상/하위 분포")을 match_log.secondary_filtering_log로 영속화해
GET /match-logs/{id}/secondary-filtering로 조회할 수 있게 하려면, 단순 점수
딕셔너리만으로는 부족하다.
"""

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.chroma_client import get_business_plan_collection, get_notice_collection
from app.ai.embedding_client import AiEmbeddingError
from app.repositories import business_plan_repository
from app.services.business_plan_embedding_service import ensure_business_plan_embedded
from app.services.notice_embedding_service import ensure_notice_embedded

logger = logging.getLogger(__name__)

# 사업계획서 청크 하나당 후보 공고 청크 중 몇 개까지 볼지. where 필터로 이미
# 1차 필터링 통과 후보로만 좁힌 상태라 넉넉하게 잡아도 비용이 크지 않다.
_N_RESULTS_PER_QUERY = 20

# 공고 하나당 LLM 판정용 근거로 남길 청크 수 상한. bizSupportNavigator
# matching.py의 _MAX_CHUNKS_PER_POLICY(3)과 동일한 값 — 근거가 너무 많으면
# 판정 프롬프트가 길어지기만 하고, 가장 유사도 높은 몇 개면 충분하다.
_MAX_EVIDENCE_CHUNKS_PER_NOTICE = 3


@dataclass(frozen=True)
class SecondaryFilteringSkip:
    notice_id: int
    reason: str
    """"no_text"(임베딩할 원문 없음) 또는 "embedding_failed"(임베딩 API 호출 실패)"""


@dataclass(frozen=True)
class EvidenceChunk:
    content: str
    distance: float


@dataclass
class SecondaryFilteringResult:
    plan_embedded: bool = False
    plan_skip_reason: str | None = None
    """plan_embedded가 False일 때만 값이 있다. "no_text" 또는 "embedding_failed"."""
    scores: dict[int, float] = field(default_factory=dict)
    """유사도 점수를 구한 공고 id -> 점수(35~100)."""
    evidence: dict[int, list[EvidenceChunk]] = field(default_factory=dict)
    """공고 id -> 유사도 상위 청크 원문(최대 _MAX_EVIDENCE_CHUNKS_PER_NOTICE개,
    거리 오름차순). secondary_filtering_judge_service.judge_notice()가 LLM
    판정 근거로 쓴다."""
    skips: list[SecondaryFilteringSkip] = field(default_factory=list)
    """임베딩을 못 구해 유사도 검색 대상에서 빠진 공고 목록."""


def _similarity_to_score(distance: float) -> float:
    """코사인 거리(0=완전히 같음, 2=정반대, get_notice_collection의
    hnsw:space="cosine" 설정 기준)를 기존 스코어링 관례(35~100 스케일,
    matching_service._overlap_score 참고)와 맞춘 0~100 점수로 바꾼다.

    현재 역할: (1) matching_service._judge_top_candidates()가 LLM 판정 대상
    상위 _SECONDARY_FILTERING_JUDGE_TOP_K건을 뽑는 랭킹 기준, (2) 그 K건 밖의
    공고는 LLM 판정을 받지 않으므로 이 값이 그대로 최종 secondary_filter_score로
    쓰인다. (2)에 한해 변환식 자체는 여전히 휴리스틱(실제 검색 결과 분포를
    보고 조정이 필요할 수 있음) — 상위 K건(랭킹용 (1))의 최종 점수에는
    영향이 없다(LLM 판정 결과인 aggregate_secondary_score가 대신 쓰인다).
    """
    similarity = 1.0 - distance
    return max(0.0, min(100.0, 35.0 + similarity * 65.0))


async def run_secondary_filtering(
    session: AsyncSession,
    *,
    business_plan_id: int,
    candidate_notice_ids: list[int],
) -> SecondaryFilteringResult:
    """1차 필터링 통과 후보의 2차 필터링(유사도) 결과를 반환한다.

    임베딩이 없거나 만들 수 없는 공고/사업계획서는 skips에 사유와 함께
    기록되고 scores에서는 빠진다(예외를 던지지 않음).
    """
    result = SecondaryFilteringResult()
    if not candidate_notice_ids:
        return result

    try:
        plan_result = await ensure_business_plan_embedded(session, business_plan_id)
    except AiEmbeddingError:
        logger.warning(
            "2차 필터링 건너뜀 (business_plan_id=%s): 사업계획서 임베딩 실패",
            business_plan_id,
        )
        result.plan_skip_reason = "embedding_failed"
        return result
    if not plan_result.embedded:
        logger.info(
            "2차 필터링 건너뜀 (business_plan_id=%s): 임베딩할 원문 없음",
            business_plan_id,
        )
        result.plan_skip_reason = "no_text"
        return result
    result.plan_embedded = True

    embedded_notice_ids: list[int] = []
    for notice_id in candidate_notice_ids:
        try:
            notice_result = await ensure_notice_embedded(session, notice_id)
        except AiEmbeddingError:
            logger.warning(
                "공고 임베딩 실패로 2차 필터링에서 제외 (notice_id=%s)", notice_id
            )
            result.skips.append(
                SecondaryFilteringSkip(notice_id=notice_id, reason="embedding_failed")
            )
            continue
        if notice_result.embedded:
            embedded_notice_ids.append(notice_id)
        else:
            result.skips.append(
                SecondaryFilteringSkip(
                    notice_id=notice_id,
                    reason=notice_result.skipped_reason or "no_text",
                )
            )

    if not embedded_notice_ids:
        logger.info(
            "2차 필터링 결과 없음 (business_plan_id=%s): 임베딩 가능한 공고 0건 "
            "(후보 %d건 중)",
            business_plan_id,
            len(candidate_notice_ids),
        )
        return result

    plan_chunks = await business_plan_repository.get_business_plan_chunks(
        session, business_plan_id
    )
    plan_collection = get_business_plan_collection()
    plan_vectors_response = await asyncio.to_thread(
        plan_collection.get,
        ids=[str(chunk.id) for chunk in plan_chunks],
        include=["embeddings"],
    )
    plan_vectors = plan_vectors_response.get("embeddings")
    if plan_vectors is None or len(plan_vectors) == 0:
        return result

    notice_collection = get_notice_collection()
    best_score_by_notice: dict[int, float] = {}
    # (notice_id, chunk_content) -> 그 청크의 최소 거리. 같은 청크가 여러
    # 사업계획서 청크 쿼리에서 반복 매칭될 수 있어(중복 근거를 LLM에 그대로
    # 넘기지 않도록) content로 중복 제거하면서 가장 좋은 거리만 남긴다.
    best_distance_by_chunk: dict[tuple[int, str], float] = {}
    for vector in plan_vectors:
        query_result = await asyncio.to_thread(
            notice_collection.query,
            query_embeddings=[vector],
            n_results=_N_RESULTS_PER_QUERY,
            where={"notice_id": {"$in": embedded_notice_ids}},
        )
        metadatas = (query_result.get("metadatas") or [[]])[0]
        distances = (query_result.get("distances") or [[]])[0]
        documents = (query_result.get("documents") or [[]])[0]
        for metadata, distance, document in zip(metadatas, distances, documents):
            notice_id = metadata["notice_id"]
            score = _similarity_to_score(distance)
            if score > best_score_by_notice.get(notice_id, -1.0):
                best_score_by_notice[notice_id] = score
            chunk_key = (notice_id, document)
            if distance < best_distance_by_chunk.get(chunk_key, float("inf")):
                best_distance_by_chunk[chunk_key] = distance

    result.scores = best_score_by_notice
    evidence_by_notice: dict[int, list[EvidenceChunk]] = {}
    for (notice_id, content), distance in best_distance_by_chunk.items():
        evidence_by_notice.setdefault(notice_id, []).append(
            EvidenceChunk(content=content, distance=distance)
        )
    result.evidence = {
        notice_id: sorted(chunks, key=lambda chunk: chunk.distance)[
            :_MAX_EVIDENCE_CHUNKS_PER_NOTICE
        ]
        for notice_id, chunks in evidence_by_notice.items()
    }
    logger.info(
        "2차 필터링 완료 (business_plan_id=%s): 임베딩된 공고 %d건 중 유사도 "
        "점수 산출 %d건",
        business_plan_id,
        len(embedded_notice_ids),
        len(best_score_by_notice),
    )
    return result
