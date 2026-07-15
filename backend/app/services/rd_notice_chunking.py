"""
services/rd_notice_chunking.py

R&D(기술개발) 공고 전용 청킹. docs/msit-rd-notice-chunking-guide.md에서
과학기술정보통신부 공고 300건을 직접 읽어 실측 검증한 결과를 그대로 코드화한다
(헤더 인식 성공률 93.7%, 표본을 늘려도 안정적으로 재현됨).

일반 공고(text_chunking.chunk_text)는 빈 줄 기준으로 문단을 나누는 범용
로직인데, R&D 공고는 "신청자격/선정평가/지원내용" 같은 섹션이 번호·기호로
시작하는 짧은 제목 줄 뒤에 이어지는 구조가 뚜렷해서, 섹션 헤더 기준으로 잘라야
임베딩 검색·LLM 판정 둘 다에서 자격요건 문장을 안 놓친다. 또한 "선정된 다음에
지켜야 할 행정 의무"(기술료 납부 등)나 "순수 서식 규칙"(분량 제한 등)처럼
매칭과 무관한 섹션은 애초에 임베딩 대상에서 빼서 신호를 안 흐린다(가이드 5장
제안 2·3).
"""

import re
from dataclasses import dataclass

from app.services.text_chunking import DEFAULT_MAX_CHARS, TextChunk, _split_oversized

# 매칭에 실질적으로 쓰이는 섹션 — 자격요건/지원내용/선정기준과, R&D 특유
# 용어로 포장돼 있을 뿐 같은 성격인 항목(가이드 4장 (A)그룹)을 합쳐 취급한다.
_MATCH_RELEVANT_KEYWORDS = (
    "신청자격",
    "신청제한",
    "신청 제한사항",
    "제외대상",
    "지원 제외",
    "지원제외",
    "지원대상",
    "사업개요",
    "사업 개요",
    "사업목적",
    "추진배경",
    "지원내용",
    "사업내용",
    "사업 내용",
    "연구개발목표",
    "지원규모",
    "정부지원연구개발비의 지원기준",
    "기관부담연구개발비의 부담기준",
    "선정평가",
    "선정절차",
    "평가절차",
    "평가방법",
    "가감점 제도",
    "기타사항",
    "특기사항",
    "유의사항",
    "신청 시 유의사항",
)

# 절차성 — 매칭 스코어링에는 안 쓰지만 청크 자체는 만들어 원문 조회(공고 상세
# 화면 등)에 쓸 수 있게 남긴다.
_PROCEDURAL_KEYWORDS = (
    "신청기간",
    "신청방법",
    "제출서류",
    "구비서류",
    "신청·접수",
    "신청 접수",
    "문의처",
    "문의 절차",
    "공고문 및 양식 확인 방법",
    "향후일정(안)",
    "적용 법령 및 규정",
)

# 매칭과 무관 — 선정 이후 행정/재무 의무이거나 순수 서식 규칙이라 임베딩
# 대상에서 아예 제외한다(가이드 4장 (B)(C)그룹).
_EXCLUDED_KEYWORDS = (
    "기술료 납부에 관한 사항",
    "연구개발과제의 성실 수행",
    "사업수행체계 및 용어",
    "연구개발계획서 분량 제한",
    "연구과제 상세 계획",
    "연구데이터 관리",
    "데이터 개요",
    "데이터 수집",
    "데이터 가공",
    "젠더혁신 관점 연구",
)

_ALL_KEYWORDS = _MATCH_RELEVANT_KEYWORDS + _PROCEDURAL_KEYWORDS + _EXCLUDED_KEYWORDS

# 번호(1. / 1)) 또는 기호(□○◎Ⅰ~Ⅴ)로 시작하고 위 키워드를 포함하는 줄만 헤더
# 후보로 본다. 헤더 판정 자체는 아래 _looks_like_header에서 길이(30자 이하)와
# 순수 숫자 줄(표 셀·페이지 번호 노이즈, 가이드 3장 "주의") 제외까지 함께 본다.
_HEADER_PATTERN = re.compile(
    r"^\s*(?:[0-9]{1,2}[.\)]\s*|[□○◎ⅠⅡⅢⅣⅤ]\s*)?("
    + "|".join(re.escape(keyword) for keyword in _ALL_KEYWORDS)
    + r")"
)
_PURE_NUMBER_RE = re.compile(r"^[0-9]+$")
_MAX_HEADER_LINE_LENGTH = 30


def _looks_like_header(stripped_line: str) -> re.Match | None:
    if not stripped_line or len(stripped_line) > _MAX_HEADER_LINE_LENGTH:
        return None
    if _PURE_NUMBER_RE.match(stripped_line):
        return None
    return _HEADER_PATTERN.match(stripped_line)


def _section_group(header: str) -> str:
    if header in _EXCLUDED_KEYWORDS:
        return "excluded"
    if header in _PROCEDURAL_KEYWORDS:
        return "procedural"
    return "match_relevant"


@dataclass(frozen=True)
class RdSection:
    header: str
    """섹션 제목(원문 키워드). 헤더를 하나도 못 찾은 문서는 "전체"로 폴백."""
    group: str
    """"match_relevant" | "procedural" | "excluded" 중 하나."""
    text: str


def split_rd_notice_sections(text: str) -> list[RdSection]:
    """줄 단위로 순회하며 섹션 헤더를 찾아, 그 지점부터 다음 헤더 전까지를
    한 섹션으로 묶는다.

    헤더를 하나도 못 찾으면(실측 6.3%) 문서 전체를 "match_relevant" 섹션
    하나로 폴백한다 — 못 나눴다고 임베딩 대상에서 빼버리면 그 공고 전체가
    2차 필터링에서 사라진다.
    """
    lines = text.splitlines()
    raw_sections: list[tuple[str | None, list[str]]] = []
    current_header: str | None = None
    current_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        match = _looks_like_header(stripped)
        if match:
            if current_header is not None or current_lines:
                raw_sections.append((current_header, current_lines))
            current_header = match.group(1)
            current_lines = []
            continue
        current_lines.append(line)
    if current_header is not None or current_lines:
        raw_sections.append((current_header, current_lines))

    if not any(header is not None for header, _ in raw_sections):
        return [RdSection(header="전체", group="match_relevant", text=text.strip())]

    sections: list[RdSection] = []
    for header, body_lines in raw_sections:
        body_text = "\n".join(body_lines).strip()
        if header is None:
            # 첫 헤더 이전 내용(공고명 등 머리말) — 매칭에 참고할 수 있어 포함.
            if body_text:
                sections.append(
                    RdSection(header="머리말", group="match_relevant", text=body_text)
                )
            continue
        if body_text:
            sections.append(
                RdSection(header=header, group=_section_group(header), text=body_text)
            )
    return sections


def chunk_rd_notice_text(
    text: str, *, max_chars: int = DEFAULT_MAX_CHARS
) -> list[TextChunk]:
    """R&D 공고 원문을 섹션 기준으로 청킹해 임베딩용 청크 목록을 만든다.

    chunk_type에 섹션명을 그대로 남겨, 나중에 "신청자격 청크끼리만 비교" 같은
    섹션별 비교도 가능하게 한다(가이드 5장 제안 4). "excluded" 그룹(선정 후
    행정의무, 순수 서식 규칙)은 청크를 만들지 않는다 — 원문 자체는
    notice_attachment.parsed_text에 그대로 남아있으므로 정보 손실은 없다.
    """
    stripped = text.strip()
    if not stripped:
        return []

    chunks: list[TextChunk] = []
    for section in split_rd_notice_sections(stripped):
        if section.group == "excluded":
            continue
        for piece in _split_oversized(section.text, max_chars):
            chunks.append(TextChunk(chunk_type=section.header, chunk_text=piece))
    return chunks
