"""
tests/test_secondary_filtering_service.py

run_secondary_filtering()의 유사도 집계 방식(2026-07-16, RAG 성능 개선
검토 — 청크 1개 max 대신 상위 _TOP_CHUNKS_FOR_SCORE개 평균)과
get_criterion_evidence/merge_evidence(criterion-aware evidence 보강)를
검증한다. DB/Chroma는 monkeypatch로 대체해 순수 로직만 테스트한다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.embedding_client import AiEmbeddingError
from app.services import secondary_filtering_service
from app.services.secondary_filtering_service import (
    EvidenceChunk,
    _similarity_to_score,
    _top_n_average,
    get_criterion_evidence,
    merge_evidence,
    run_secondary_filtering,
)

pytestmark = pytest.mark.anyio


def test_top_n_average_uses_closest_n_distances():
    assert _top_n_average([0.5, 0.1, 0.3], 2) == pytest.approx((0.1 + 0.3) / 2)


def test_top_n_average_falls_back_when_fewer_than_n():
    assert _top_n_average([0.2], 2) == pytest.approx(0.2)


def test_similarity_to_score_is_monotonic_in_distance():
    assert (
        _similarity_to_score(0.0)
        > _similarity_to_score(0.5)
        > _similarity_to_score(1.0)
    )


def _fake_plan_collection(chunk_ids: list[str]) -> SimpleNamespace:
    vectors = {cid: [float(i)] for i, cid in enumerate(chunk_ids)}
    return SimpleNamespace(
        get=lambda ids, include: {"embeddings": [vectors[i] for i in ids]}
    )


def _fake_notice_collection(query_results: list[dict]) -> SimpleNamespace:
    """query_results[i]는 i번째 query() 호출에 대한 응답(metadatas/distances/documents 리스트)."""
    calls = iter(query_results)

    def _query(query_embeddings, n_results, where):
        result = next(calls)
        return {
            "metadatas": [result["metadatas"]],
            "distances": [result["distances"]],
            "documents": [result["documents"]],
        }

    return SimpleNamespace(query=_query)


async def test_notice_score_averages_top_two_chunk_distances(monkeypatch):
    monkeypatch.setattr(
        secondary_filtering_service,
        "ensure_business_plan_embedded",
        AsyncMock(return_value=SimpleNamespace(embedded=True)),
    )

    async def _fake_ensure_notices_embedded(session, notice_ids):
        return {
            notice_id: SimpleNamespace(embedded=True, skipped_reason=None)
            for notice_id in notice_ids
        }

    monkeypatch.setattr(
        secondary_filtering_service,
        "ensure_notices_embedded",
        _fake_ensure_notices_embedded,
    )
    monkeypatch.setattr(
        secondary_filtering_service.business_plan_repository,
        "get_business_plan_chunks",
        AsyncMock(return_value=[SimpleNamespace(id=1), SimpleNamespace(id=2)]),
    )
    monkeypatch.setattr(
        secondary_filtering_service,
        "get_business_plan_collection",
        lambda: _fake_plan_collection(["1", "2"]),
    )
    # 사업계획서 청크 1(쿼리1)은 공고 A 청크(거리 0.1)와 공고 B 청크(거리 0.1)에 매칭.
    # 사업계획서 청크 2(쿼리2)는 공고 A의 다른 청크(거리 0.3)에만 매칭 -> A는 청크 2개,
    # B는 청크 1개.
    monkeypatch.setattr(
        secondary_filtering_service,
        "get_notice_collection",
        lambda: _fake_notice_collection(
            [
                {
                    "metadatas": [{"notice_id": 100}, {"notice_id": 200}],
                    "distances": [0.1, 0.1],
                    "documents": ["A청크1", "B청크1"],
                },
                {
                    "metadatas": [{"notice_id": 100}],
                    "distances": [0.3],
                    "documents": ["A청크2"],
                },
            ]
        ),
    )

    result = await run_secondary_filtering(
        session=None, business_plan_id=1, candidate_notice_ids=[100, 200]
    )

    assert result.scores[100] == pytest.approx(_similarity_to_score((0.1 + 0.3) / 2))
    assert result.scores[200] == pytest.approx(_similarity_to_score(0.1))


def test_merge_evidence_dedupes_and_keeps_closer_distance():
    plan_based = [EvidenceChunk(content="공통청크", distance=0.5)]
    criterion_based = [
        EvidenceChunk(content="공통청크", distance=0.2),
        EvidenceChunk(content="새청크", distance=0.4),
    ]

    merged = merge_evidence(plan_based, criterion_based)

    assert [c.content for c in merged] == ["공통청크", "새청크"]
    assert merged[0].distance == pytest.approx(0.2)  # 더 가까운 쪽이 남는다


async def test_get_criterion_evidence_returns_empty_for_no_criteria():
    result = await get_criterion_evidence(notice_id=1, criterion_statements=[])
    assert result == []


async def test_get_criterion_evidence_queries_per_criterion_and_dedupes(monkeypatch):
    embed_texts_mock = AsyncMock(return_value=[[0.1], [0.2]])
    monkeypatch.setattr(secondary_filtering_service, "embed_texts", embed_texts_mock)

    call_count = 0

    def _query(query_embeddings, n_results, where):
        nonlocal call_count
        call_count += 1
        assert where == {"notice_id": 42}
        if call_count == 1:
            return {"distances": [[0.3]], "documents": [["지역 요건 청크"]]}
        return {
            "distances": [[0.1]],
            "documents": [["지역 요건 청크"]],
        }  # 같은 청크, 더 가까움

    monkeypatch.setattr(
        secondary_filtering_service,
        "get_notice_collection",
        lambda: SimpleNamespace(query=_query),
    )

    result = await get_criterion_evidence(
        notice_id=42, criterion_statements=["요건1", "요건2"]
    )

    embed_texts_mock.assert_awaited_once_with(["요건1", "요건2"])
    assert call_count == 2
    assert len(result) == 1  # 두 쿼리 모두 같은 청크를 가리켜 중복 제거됨
    assert result[0].distance == pytest.approx(0.1)


async def test_get_criterion_evidence_returns_empty_on_embedding_failure(monkeypatch):
    monkeypatch.setattr(
        secondary_filtering_service,
        "embed_texts",
        AsyncMock(side_effect=AiEmbeddingError("boom")),
    )

    result = await get_criterion_evidence(notice_id=1, criterion_statements=["요건1"])

    assert result == []
