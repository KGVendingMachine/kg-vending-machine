"""
tests/test_notice_embedding_service.py

ensure_notice_embedded가 Postgres notice_chunk 캐시뿐 아니라 Chroma에도
벡터가 실제로 있는지 확인하는 방어 로직(2026-07-14 추가 — 두 저장소가
볼륨 교체 등으로 어긋난 실제 사례를 계기로 도입)과, 원문이 청크보다 최신이면
재임베딩하는 낡음 판정(2026-07-15 추가)을 검증한다. DB/Chroma 둘 다
monkeypatch로 대체해 실제 인프라 없이 순수 로직만 테스트한다.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.notice import NoticeChunk
from app.services import notice_embedding_service

pytestmark = pytest.mark.anyio

_BASE_TIME = datetime(2026, 7, 1, 0, 0, 0)


def _chunk(
    chunk_id: int, notice_id: int, *, created_at: datetime = _BASE_TIME
) -> NoticeChunk:
    return NoticeChunk(
        id=chunk_id,
        notice_id=notice_id,
        chunk_type="attachment",
        chunk_text="본문",
        created_at=created_at,
    )


def _attachment(
    parsed_text: str, *, updated_at: datetime = _BASE_TIME
) -> SimpleNamespace:
    return SimpleNamespace(parsed_text=parsed_text, updated_at=updated_at)


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
    # 첨부파일이 청크보다 오래됐다(낡지 않음) — 재임베딩 사유가 없어야 한다.
    monkeypatch.setattr(
        notice_embedding_service,
        "ensure_notice_attachment_ocr",
        AsyncMock(return_value=_attachment("본문", updated_at=_BASE_TIME)),
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
    monkeypatch.setattr(
        notice_embedding_service,
        "ensure_notice_attachment_ocr",
        AsyncMock(return_value=_attachment("새로 뽑은 원문", updated_at=_BASE_TIME)),
    )
    monkeypatch.setattr(
        notice_embedding_service, "_is_rd_notice", AsyncMock(return_value=False)
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


async def test_reembeds_when_attachment_updated_after_chunks(monkeypatch):
    """공고 재수집 등으로 첨부파일이 청크보다 나중에 갱신되면, Chroma에
    벡터가 멀쩡히 있어도 낡은 것으로 보고 재임베딩해야 한다(2026-07-15)."""
    existing = [_chunk(1, notice_id=10, created_at=_BASE_TIME)]
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
    monkeypatch.setattr(
        notice_embedding_service,
        "ensure_notice_attachment_ocr",
        AsyncMock(
            return_value=_attachment(
                "재수집된 새 원문", updated_at=_BASE_TIME + timedelta(days=1)
            )
        ),
    )
    monkeypatch.setattr(
        notice_embedding_service, "_is_rd_notice", AsyncMock(return_value=False)
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
    new_rows = [_chunk(2, notice_id=10)]
    monkeypatch.setattr(
        notice_embedding_service.notice_repository,
        "replace_notice_chunks",
        AsyncMock(return_value=new_rows),
    )

    result = await notice_embedding_service.ensure_notice_embedded(
        session=None, notice_id=10
    )

    assert result.embedded is True
    assert result.chunk_count == 1
    embed_texts_mock.assert_awaited_once()


def test_chunks_are_stale_compares_latest_chunk_to_attachment():
    chunks = [
        _chunk(1, notice_id=10, created_at=_BASE_TIME),
        _chunk(2, notice_id=10, created_at=_BASE_TIME + timedelta(hours=1)),
    ]

    older_attachment = _attachment("본문", updated_at=_BASE_TIME)
    newer_attachment = _attachment("본문", updated_at=_BASE_TIME + timedelta(hours=2))

    assert notice_embedding_service._chunks_are_stale(chunks, older_attachment) is False
    assert notice_embedding_service._chunks_are_stale(chunks, newer_attachment) is True
