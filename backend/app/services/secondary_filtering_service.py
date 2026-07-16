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
from app.ai.embedding_client import AiEmbeddingError, embed_texts
from app.repositories import business_plan_repository
from app.services.business_plan_embedding_service import ensure_business_plan_embedded
from app.services.notice_embedding_service import ensure_notices_embedded

logger = logging.getLogger(__name__)

# 사업계획서 청크 하나당 후보 공고 청크 중 몇 개까지 볼지. where 필터로 이미
# 1차 필터링 통과 후보로만 좁힌 상태라 넉넉하게 잡아도 비용이 크지 않다.
_N_RESULTS_PER_QUERY = 20

# 공고 하나당 LLM 판정용 근거로 남길 청크 수 상한. bizSupportNavigator
# matching.py의 _MAX_CHUNKS_PER_POLICY(3)과 동일한 값 — 근거가 너무 많으면
# 판정 프롬프트가 길어지기만 하고, 가장 유사도 높은 몇 개면 충분하다.
_MAX_EVIDENCE_CHUNKS_PER_NOTICE = 3

# 공고 유사도 점수를 "가장 가까운 청크 1개"가 아니라 상위 N개 거리의 평균으로
# 낸다 — 자격요건이 여러 문단에 흩어진 공고가 청크 1개짜리 우연한 일치에
# 저평가/과평가되지 않도록. 3으로 하면 근거가 부족한 공고에서 평균이 과도하게
# 낮아질 수 있어 2로 시작(2026-07-16, RAG 성능 개선 검토).
_TOP_CHUNKS_FOR_SCORE = 2

# criterion 문장 하나당 조회할 공고 청크 수. _MAX_EVIDENCE_CHUNKS_PER_NOTICE와
# 같은 이유로 작게 잡는다 — get_criterion_evidence 참고.
_CRITERION_N_RESULTS = 3


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


def _top_n_average(distances: list[float], n: int) -> float:
    """거리 오름차순(가까운 순) 상위 n개의 평균. n보다 적으면 있는 만큼만."""
    return sum(sorted(distances)[:n]) / min(len(distances), n)


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

    # 공고별 임베딩 확인·생성(캐시확인/OCR/DB쓰기는 순차, embed_texts 호출만
    # 병렬 — ensure_notices_embedded 참고, 2026-07-16 RAG 성능 개선 검토에서
    # 순차 루프가 병목이라 병렬화).
    embedding_results = await ensure_notices_embedded(session, candidate_notice_ids)
    embedded_notice_ids: list[int] = []
    for notice_id in candidate_notice_ids:
        notice_result = embedding_results[notice_id]
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
            chunk_key = (notice_id, document)
            if distance < best_distance_by_chunk.get(chunk_key, float("inf")):
                best_distance_by_chunk[chunk_key] = distance

    distances_by_notice: dict[int, list[float]] = {}
    for (notice_id, _content), distance in best_distance_by_chunk.items():
        distances_by_notice.setdefault(notice_id, []).append(distance)
    # 청크(문서 내 중복 제거 완료) 거리 오름차순 상위 _TOP_CHUNKS_FOR_SCORE개
    # 평균을 그 공고의 유사도 점수로 쓴다 — 근거 청크가 1개뿐인 공고는 그
    # 1개만으로 계산된다.
    result.scores = {
        notice_id: _similarity_to_score(
            _top_n_average(distances, _TOP_CHUNKS_FOR_SCORE)
        )
        for notice_id, distances in distances_by_notice.items()
    }
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
        len(result.scores),
    )
    return result


async def get_criterion_evidence(
    notice_id: int, criterion_statements: list[str]
) -> list[EvidenceChunk]:
    """요건 문장 자체를 쿼리로 써서 공고 청크를 검색한다(criterion-aware
    evidence, 2026-07-16 RAG 성능 개선 검토).

    run_secondary_filtering의 evidence는 사업계획서 청크와의 유사도로만
    뽑혀서, 개별 요건(예: "사업장 지역")과 무관한 근거(예: 제품 설명 청크)가
    섞일 수 있다. 요건 문장 자체로 검색하면 그 요건에 실제로 관련된 청크를
    직접 찾을 수 있다.

    비용 통제를 위해 공고 전체가 아니라 matching_service._judge_top_candidates가
    실제로 LLM 판정할 상위 K건에만 쓴다. 요건이 보통 5~11개인데 하나씩
    임베딩하면 그만큼 API 호출이 늘어나므로, 공고 하나당 요건 전체를
    embed_texts 한 번으로 묶어 호출하고(추가 비용은 "공고당 +1회"로 제한),
    Chroma 쿼리(로컬, 무료)만 요건 수만큼 돌린다.
    """
    if not criterion_statements:
        return []

    try:
        vectors = await embed_texts(criterion_statements)
    except AiEmbeddingError:
        logger.warning(
            "criterion-aware evidence 검색 건너뜀 (notice_id=%s): 요건 문장 "
            "임베딩 실패",
            notice_id,
        )
        return []

    collection = get_notice_collection()
    best_distance_by_chunk: dict[str, float] = {}
    for vector in vectors:
        query_result = await asyncio.to_thread(
            collection.query,
            query_embeddings=[vector],
            n_results=_CRITERION_N_RESULTS,
            where={"notice_id": notice_id},
        )
        distances = (query_result.get("distances") or [[]])[0]
        documents = (query_result.get("documents") or [[]])[0]
        for distance, document in zip(distances, documents):
            if distance < best_distance_by_chunk.get(document, float("inf")):
                best_distance_by_chunk[document] = distance

    chunks = [
        EvidenceChunk(content=content, distance=distance)
        for content, distance in best_distance_by_chunk.items()
    ]
    return sorted(chunks, key=lambda chunk: chunk.distance)[
        :_MAX_EVIDENCE_CHUNKS_PER_NOTICE
    ]


def merge_evidence(
    *evidence_lists: list[EvidenceChunk],
) -> list[EvidenceChunk]:
    """여러 출처(사업계획서 유사도 기반 + criterion 기반 등)의 evidence를
    합친다. 같은 청크 내용이 여러 출처에서 나오면 더 가까운 거리만 남긴다."""
    best_by_content: dict[str, EvidenceChunk] = {}
    for chunks in evidence_lists:
        for chunk in chunks:
            existing = best_by_content.get(chunk.content)
            if existing is None or chunk.distance < existing.distance:
                best_by_content[chunk.content] = chunk
    return sorted(best_by_content.values(), key=lambda chunk: chunk.distance)
