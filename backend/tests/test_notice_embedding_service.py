"""
tests/test_notice_embedding_service.py

ensure_notice_embedded가 Postgres notice_chunk 캐시뿐 아니라 Chroma에도
벡터가 실제로 있는지 확인하는 방어 로직(2026-07-14 추가 — 두 저장소가
볼륨 교체 등으로 어긋난 실제 사례를 계기로 도입)을 검증한다. DB/Chroma
둘 다 monkeypatch로 대체해 실제 인프라 없이 순수 로직만 테스트한다.

ensure_notices_embedded(2026-07-16, RAG 성능 개선 검토로 추가된 배치
버전)는 별도로 아래에서 검증한다 — embed_texts 호출만 병렬화되고, 공고
하나의 임베딩 실패가 다른 공고에 전파되지 않는지가 핵심이다.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.ai.embedding_client import AiEmbeddingError
from app.models.notice import NoticeChunk
from app.services import notice_embedding_service

pytestmark = pytest.mark.anyio


def _chunk(chunk_id: int, notice_id: int) -> NoticeChunk:
    return NoticeChunk(
        id=chunk_id, notice_id=notice_id, chunk_type="attachment", chunk_text="본문"
    )


def _fake_collection(get_ids: list[str]) -> SimpleNamespace:
    return SimpleNamespace(
        get=lambda ids, include: {"ids": [i for i in ids if i in get_ids]},
        upsert=lambda **kwargs: None,
    )


async def test_reuses_existing_chunks_when_chroma_has_them(monkeypatch):
    existing = [_chunk(1, notice_id=10), _chunk(2, notice_id=10)]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "get_notice_chunks_by_notice_id",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "get_notice_collection",
        lambda: _fake_collection(get_ids=["1", "2"]),
    )
    embed_texts_mock = AsyncMock()
    monkeypatch.setattr(notice_embedding_service, "embed_texts", embed_texts_mock)

    result = await notice_embedding_service.ensure_notice_embedded(
        session=None, notice_id=10
    )

    assert result.embedded is True
    assert result.chunk_count == 2
    embed_texts_mock.assert_not_called()


async def test_reembeds_when_postgres_cache_exists_but_chroma_is_empty(monkeypatch):
    existing = [_chunk(1, notice_id=10), _chunk(2, notice_id=10)]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "get_notice_chunks_by_notice_id",
        AsyncMock(return_value=existing),
    )
    # Chroma에는 해당 id들이 하나도 없다 (볼륨 교체 등으로 유실된 상황 재현).
    monkeypatch.setattr(
        notice_embedding_service,
        "get_notice_collection",
        lambda: _fake_collection(get_ids=[]),
    )
    fake_attachment = SimpleNamespace(parsed_text="새로 뽑은 원문")
    monkeypatch.setattr(
        notice_embedding_service,
        "ensure_notice_attachment_ocr",
        AsyncMock(return_value=fake_attachment),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "chunk_text",
        lambda text, chunk_type: [
            SimpleNamespace(chunk_type=chunk_type, chunk_text=text)
        ],
    )
    embed_texts_mock = AsyncMock(return_value=[[0.1, 0.2]])
    monkeypatch.setattr(notice_embedding_service, "embed_texts", embed_texts_mock)
    new_rows = [_chunk(3, notice_id=10)]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "replace_notice_chunks",
        AsyncMock(return_value=new_rows),
    )

    result = await notice_embedding_service.ensure_notice_embedded(
        session=None, notice_id=10
    )

    assert result.embedded is True
    assert result.chunk_count == 1  # 재임베딩된 새 청크(id=3) 기준
    embed_texts_mock.assert_awaited_once()


async def test_ensure_notices_embedded_parallelizes_embedding_calls(monkeypatch):
    notice_ids = [10, 11, 12]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "get_notice_chunks_by_notice_id",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "ensure_notice_attachment_ocr",
        AsyncMock(
            side_effect=lambda session, notice_id: SimpleNamespace(
                parsed_text=f"본문-{notice_id}"
            )
        ),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "chunk_text",
        lambda text, chunk_type: [
            SimpleNamespace(chunk_type=chunk_type, chunk_text=text)
        ],
    )

    concurrent_calls = 0
    max_concurrent = 0

    async def _embed_texts(texts):
        nonlocal concurrent_calls, max_concurrent
        concurrent_calls += 1
        max_concurrent = max(max_concurrent, concurrent_calls)
        await asyncio.sleep(0.05)
        concurrent_calls -= 1
        return [[0.1, 0.2]]

    monkeypatch.setattr(notice_embedding_service, "embed_texts", _embed_texts)
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "replace_notice_chunks",
        AsyncMock(
            side_effect=lambda session, notice_id, chunks: [
                _chunk(notice_id * 100, notice_id)
            ]
        ),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "get_notice_collection",
        lambda: _fake_collection(get_ids=[]),
    )

    results = await notice_embedding_service.ensure_notices_embedded(
        session=None, notice_ids=notice_ids
    )

    # 세마포어 한도(10) 안이라 3건이 순차가 아니라 동시에 진행돼야 한다.
    assert max_concurrent > 1
    assert all(results[notice_id].embedded for notice_id in notice_ids)


async def test_ensure_notices_embedded_isolates_single_notice_failure(monkeypatch):
    notice_ids = [10, 11]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "get_notice_chunks_by_notice_id",
        AsyncMock(return_value=[]),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "ensure_notice_attachment_ocr",
        AsyncMock(
            side_effect=lambda session, notice_id: SimpleNamespace(
                parsed_text=f"본문-{notice_id}"
            )
        ),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "chunk_text",
        lambda text, chunk_type: [
            SimpleNamespace(chunk_type=chunk_type, chunk_text=text)
        ],
    )

    async def _embed_texts(texts):
        if "본문-10" in texts:
            raise AiEmbeddingError("boom")
        return [[0.1, 0.2]]

    monkeypatch.setattr(notice_embedding_service, "embed_texts", _embed_texts)
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "replace_notice_chunks",
        AsyncMock(
            side_effect=lambda session, notice_id, chunks: [
                _chunk(notice_id * 100, notice_id)
            ]
        ),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "get_notice_collection",
        lambda: _fake_collection(get_ids=[]),
    )

    results = await notice_embedding_service.ensure_notices_embedded(
        session=None, notice_ids=notice_ids
    )

    assert results[10].embedded is False
    assert results[10].skipped_reason == "embedding_failed"
    assert results[11].embedded is True


async def test_ensure_notices_embedded_reuses_cache_without_calling_embed(monkeypatch):
    existing = [_chunk(1, notice_id=10)]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "get_notice_chunks_by_notice_id",
        AsyncMock(return_value=existing),
    )
    monkeypatch.setattr(
        notice_embedding_service,
        "get_notice_collection",
        lambda: _fake_collection(get_ids=["1"]),
    )
    embed_texts_mock = AsyncMock()
    monkeypatch.setattr(notice_embedding_service, "embed_texts", embed_texts_mock)

    results = await notice_embedding_service.ensure_notices_embedded(
        session=None, notice_ids=[10]
    )

    assert results[10].embedded is True
    assert results[10].chunk_count == 1
    embed_texts_mock.assert_not_called()
