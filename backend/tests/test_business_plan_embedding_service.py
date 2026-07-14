"""
tests/test_business_plan_embedding_service.py

ensure_business_plan_embedded의 Chroma 존재 재확인 로직(tests/
test_notice_embedding_service.py와 동일한 계기로 도입된 대칭 방어 로직)을
검증한다.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.business_plan import BusinessPlanChunk
from app.services import business_plan_embedding_service

pytestmark = pytest.mark.anyio


def _chunk(chunk_id: int, business_plan_id: int) -> BusinessPlanChunk:
    return BusinessPlanChunk(
        id=chunk_id,
        business_plan_id=business_plan_id,
        chunk_type="raw_text",
        chunk_text="본문",
    )


def _fake_collection(get_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        get=lambda ids, include: {"ids": [i for i in ids if i in get_ids]},
        upsert=lambda **kwargs: None,
    )


async def test_reuses_existing_chunks_when_chroma_has_them(monkeypatch):
    existing = [_chunk(1, business_plan_id=63), _chunk(2, business_plan_id=63)]
    monkeypatch.setattr(
        business_plan_embedding_service.business_plan_repository,
        "get_business_plan_chunks",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        business_plan_embedding_service,
        "get_business_plan_collection",
        lambda: _fake_collection(get_ids=["1", "2"]),
    )
    embed_texts_mock = AsyncMock()
    monkeypatch.setattr(
        business_plan_embedding_service, "embed_texts", embed_texts_mock
    )

    result = await business_plan_embedding_service.ensure_business_plan_embedded(
        session=None, business_plan_id=63
    )

    assert result.embedded is True
    assert result.chunk_count == 2
    embed_texts_mock.assert_not_called()


async def test_reembeds_when_postgres_cache_exists_but_chroma_is_empty(monkeypatch):
    existing = [_chunk(1, business_plan_id=63), _chunk(2, business_plan_id=63)]
    monkeypatch.setattr(
        business_plan_embedding_service.business_plan_repository,
        "get_business_plan_chunks",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        business_plan_embedding_service,
        "get_business_plan_collection",
        lambda: _fake_collection(get_ids=[]),
    )
    fake_plan = SimpleNamespace(raw_text="새로 뽑은 원문")
    monkeypatch.setattr(
        business_plan_embedding_service.business_plan_repository,
        "get_by_id",
        AsyncMock(return_value=fake_plan),
    )
    monkeypatch.setattr(
        business_plan_embedding_service,
        "chunk_text",
        lambda text, chunk_type: [
            SimpleNamespace(chunk_type=chunk_type, chunk_text=text)
        ],
    )
    embed_texts_mock = AsyncMock(return_value=[[0.1, 0.2]])
    monkeypatch.setattr(
        business_plan_embedding_service, "embed_texts", embed_texts_mock
    )
    new_rows = [_chunk(3, business_plan_id=63)]
    monkeypatch.setattr(
        business_plan_embedding_service.business_plan_repository,
        "replace_business_plan_chunks",
        AsyncMock(return_value=new_rows),
    )

    result = await business_plan_embedding_service.ensure_business_plan_embedded(
        session=None, business_plan_id=63
    )

    assert result.embedded is True
    assert result.chunk_count == 1  # 재임베딩된 새 청크(id=3) 기준
    embed_texts_mock.assert_awaited_once()
