"""
tests/test_secondary_filtering_service.py

app/services/secondary_filtering_service.py의 R&D 전용 검색 범위 확대
로직만 단위 테스트한다(임베딩·Chroma는 전부 monkeypatch로 대체 —
실제 OpenAI/Chroma 호출 없음).
"""

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from app.services import secondary_filtering_service as svc

pytestmark = pytest.mark.anyio


@dataclass(frozen=True)
class _FakeChunk:
    id: int


class _FakeCollection:
    """query 호출 인자를 기록해두는 가짜 Chroma 컬렉션."""

    def __init__(self):
        self.query_calls: list[dict] = []

    def get(self, *, ids, include):
        return {"ids": [str(i) for i in ids], "embeddings": [[0.1, 0.2]] * len(ids)}

    def query(self, *, query_embeddings, n_results, where):
        self.query_calls.append({"n_results": n_results, "where": where})
        notice_ids = where["notice_id"]["$in"]
        return {
            "metadatas": [[{"notice_id": nid} for nid in notice_ids]],
            "distances": [[0.1 for _ in notice_ids]],
            "documents": [[f"청크 {nid}" for nid in notice_ids]],
        }


async def test_run_secondary_filtering_uses_wider_search_for_rd_notices(monkeypatch):
    notice_collection = _FakeCollection()
    plan_collection = _FakeCollection()

    async def _fake_plan_embedded(session, business_plan_id):
        return SimpleNamespace(embedded=True, chunk_count=1, skipped_reason=None)

    async def _fake_notice_embedded(session, notice_id):
        return SimpleNamespace(embedded=True, chunk_count=1, skipped_reason=None)

    async def _fake_get_chunks(session, business_plan_id):
        return [_FakeChunk(id=1)]

    monkeypatch.setattr(svc, "get_notice_collection", lambda: notice_collection)
    monkeypatch.setattr(svc, "get_business_plan_collection", lambda: plan_collection)
    monkeypatch.setattr(svc, "ensure_business_plan_embedded", _fake_plan_embedded)
    monkeypatch.setattr(svc, "ensure_notice_embedded", _fake_notice_embedded)
    monkeypatch.setattr(
        svc.business_plan_repository, "get_business_plan_chunks", _fake_get_chunks
    )

    result = await svc.run_secondary_filtering(
        session=None,
        business_plan_id=1,
        candidate_notice_ids=[10, 20],
        rd_notice_ids={20},
    )

    assert result.scores[10] is not None
    assert result.scores[20] is not None

    n_results_by_where = {
        tuple(call["where"]["notice_id"]["$in"]): call["n_results"]
        for call in notice_collection.query_calls
    }
    assert n_results_by_where[(10,)] == svc._N_RESULTS_PER_QUERY
    assert n_results_by_where[(20,)] == svc._N_RESULTS_PER_QUERY_RD
    assert len(result.evidence[20]) <= svc._MAX_EVIDENCE_CHUNKS_PER_NOTICE_RD


async def test_run_secondary_filtering_skips_rd_query_when_no_rd_candidates(
    monkeypatch,
):
    notice_collection = _FakeCollection()
    plan_collection = _FakeCollection()

    async def _fake_plan_embedded(session, business_plan_id):
        return SimpleNamespace(embedded=True, chunk_count=1, skipped_reason=None)

    async def _fake_notice_embedded(session, notice_id):
        return SimpleNamespace(embedded=True, chunk_count=1, skipped_reason=None)

    async def _fake_get_chunks(session, business_plan_id):
        return [_FakeChunk(id=1)]

    monkeypatch.setattr(svc, "get_notice_collection", lambda: notice_collection)
    monkeypatch.setattr(svc, "get_business_plan_collection", lambda: plan_collection)
    monkeypatch.setattr(svc, "ensure_business_plan_embedded", _fake_plan_embedded)
    monkeypatch.setattr(svc, "ensure_notice_embedded", _fake_notice_embedded)
    monkeypatch.setattr(
        svc.business_plan_repository, "get_business_plan_chunks", _fake_get_chunks
    )

    await svc.run_secondary_filtering(
        session=None,
        business_plan_id=1,
        candidate_notice_ids=[10],
        rd_notice_ids=None,
    )

    # rd_notice_ids가 없으면(빈 그룹) R&D 쪽 쿼리는 아예 안 날려야 한다.
    assert len(notice_collection.query_calls) == 1
    assert notice_collection.query_calls[0]["n_results"] == svc._N_RESULTS_PER_QUERY
