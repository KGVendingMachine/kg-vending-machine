"""
services/text_chunking.py

2차 필터링(docs/matching-pipeline.md 4단계)에서 공고 첨부파일 OCR 텍스트와
사업계획서 원문을 임베딩 전 청크로 나누는 공통 로직. notice_chunk/
business_plan_chunk 두 테이블이 같은 (chunk_type, chunk_text) 구조를 쓰므로
양쪽 임베딩 서비스가 이 함수 하나를 공유한다.

문단(빈 줄) 단위로 자르되, 문단 하나가 max_chars를 넘으면 그 안에서 다시
문자 길이 기준으로 나눈다 — 문단 구분이 없는 OCR 결과(스캔본 등)에서도
청크가 무한정 커지지 않게 하기 위함.
"""

import re
from dataclasses import dataclass

_PARAGRAPH_RE = re.compile(r"\n\s*\n+")

# text-embedding-3-small은 토큰 기준 8191개까지 받지만, 검색 단위를 세분화해
# 유사도 정밀도를 높이려는 목적이라 훨씬 작게 자른다. 한국어 기준 1200자면
# 대략 1~2단락 분량(TBD — 실측 후 조정 가능, docs/matching-pipeline.md 참고).
DEFAULT_MAX_CHARS = 1200


@dataclass(frozen=True)
class TextChunk:
    chunk_type: str
    chunk_text: str


def chunk_text(
    text: str, *, chunk_type: str = "body", max_chars: int = DEFAULT_MAX_CHARS
) -> list[TextChunk]:
    """text를 max_chars 이하의 청크 목록으로 나눈다.

    빈 문자열/공백만 있는 입력은 빈 목록을 반환한다(임베딩할 내용이 없음을
    호출자가 그대로 판단할 수 있게).
    """
    stripped = text.strip()
    if not stripped:
        return []

    paragraphs = [p.strip() for p in _PARAGRAPH_RE.split(stripped) if p.strip()]
    if not paragraphs:
        paragraphs = [stripped]

    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        for piece in _split_oversized(paragraph, max_chars):
            if not current:
                current = piece
            elif len(current) + 2 + len(piece) <= max_chars:
                current = f"{current}\n\n{piece}"
            else:
                chunks.append(current)
                current = piece
    if current:
        chunks.append(current)

    return [TextChunk(chunk_type=chunk_type, chunk_text=chunk) for chunk in chunks]


def _split_oversized(paragraph: str, max_chars: int) -> list[str]:
    """max_chars보다 긴 문단을 문자 길이 기준으로 잘라 붙인다."""
    if len(paragraph) <= max_chars:
        return [paragraph]
    return [paragraph[i : i + max_chars] for i in range(0, len(paragraph), max_chars)]
