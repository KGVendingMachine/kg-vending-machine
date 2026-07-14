"""
ai/chroma_client.py

2차 필터링(docs/matching-pipeline.md 4단계) 벡터 DB 클라이언트.
별도 Chroma 서버 없이 프로세스 안에서 로컬 디스크에 바로 저장하는 embedded
persistent client 방식을 쓴다 (xuswns/chromadb-embedded-deployment.md 참고).

PersistentClient는 내부적으로 SQLite에 메타데이터를 쓰기 때문에 다중 프로세스
동시 쓰기를 지원하지 않는다 — 배포 시 uvicorn/gunicorn 워커는 반드시 1개여야
한다(Dockerfile 참고). get_chroma_client()의 생성 비용(디스크 인덱스 로드)이
작지 않으므로 get_settings()와 동일하게 @lru_cache로 프로세스당 하나만 만든다.
"""

from functools import lru_cache

import chromadb
from chromadb.api import ClientAPI
from chromadb.api.models.Collection import Collection

from app.core.config import get_settings


@lru_cache
def get_chroma_client() -> ClientAPI:
    settings = get_settings()
    return chromadb.PersistentClient(path=settings.CHROMA_PERSIST_DIR)


def get_notice_collection() -> Collection:
    """공고 첨부파일 청크 임베딩 컬렉션. 메타데이터에 notice_id를 담아
    secondary_filtering_service가 1차 필터링 통과 후보로 좁혀 검색할 수 있게 한다.

    hnsw:space="cosine"을 명시한다 — Chroma 기본값(squared L2)이 아니라
    코사인 유사도를 쓴다. OpenAI 임베딩(text-embedding-3-*)은 단위 벡터로
    정규화돼 있어 코사인 유사도가 의미상 자연스러운 거리 척도다."""
    settings = get_settings()
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_NOTICE_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )


def get_business_plan_collection() -> Collection:
    """사업계획서 청크 임베딩 컬렉션. 메타데이터에 business_plan_id를 담는다.
    get_notice_collection과 동일한 이유로 코사인 거리를 쓴다."""
    settings = get_settings()
    client = get_chroma_client()
    return client.get_or_create_collection(
        name=settings.CHROMA_BUSINESS_PLAN_COLLECTION,
        metadata={"hnsw:space": "cosine"},
    )
