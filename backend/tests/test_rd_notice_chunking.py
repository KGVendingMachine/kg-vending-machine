"""
tests/test_rd_notice_chunking.py

app/services/rd_notice_chunking.py 테스트.
docs/msit-rd-notice-chunking-guide.md에서 실측 검증한 헤더 인식 규칙(번호/기호
+ 키워드 + 30자 이하, 순수 숫자 줄 제외)과 섹션 그룹 분류(match_relevant/
procedural/excluded)를 순수 함수 단위로 검증한다.
"""

from app.services.rd_notice_chunking import (
    chunk_rd_notice_text,
    split_rd_notice_sections,
)


def test_recognizes_numbered_header():
    text = (
        "1. 신청자격\n중소기업만 신청 가능합니다.\n2. 지원내용\n최대 5억원 지원합니다."
    )
    sections = split_rd_notice_sections(text)

    headers = [s.header for s in sections]
    assert "신청자격" in headers
    assert "지원내용" in headers


def test_recognizes_symbol_header():
    text = "□ 지원대상\n중소기업, 중견기업\n○ 선정평가\n서면평가 후 발표평가"
    sections = split_rd_notice_sections(text)

    headers = [s.header for s in sections]
    assert "지원대상" in headers
    assert "선정평가" in headers


def test_pure_number_lines_are_not_headers():
    # HWP/PDF 표가 셀 단위로 줄바꿈되며 생기는 순수 숫자 줄(페이지 번호,
    # 표 값)은 헤더로 오인하면 안 된다(가이드 3장 "주의").
    text = "1. 신청자격\n중소기업\n25\n5\n2. 지원내용\n최대 5억원"
    sections = split_rd_notice_sections(text)

    assert all(s.header not in {"25", "5"} for s in sections)
    body_texts = "\n".join(s.text for s in sections)
    # 숫자 줄 자체는 헤더로 안 잡힐 뿐 본문에는 그대로 남아야 한다(정보 손실 방지).
    assert "25" in body_texts
    assert "5" in body_texts


def test_long_line_containing_keyword_is_not_treated_as_header():
    # 30자를 넘는 줄은 본문 문장이 우연히 키워드를 포함한 것이지 섹션
    # 제목이 아니다(가이드 3장 헤더 판정 기준).
    long_line = (
        "본 사업의 신청자격 요건은 아래 세부 조건을 모두 충족하는 중소기업에 한합니다"
    )
    text = f"1. 사업개요\n{long_line}\n중소기업 대상"
    sections = split_rd_notice_sections(text)

    headers = [s.header for s in sections]
    assert headers == ["사업개요"]


def test_section_groups_are_classified_correctly():
    text = (
        "1. 신청자격\n중소기업\n"
        "2. 신청방법\n온라인 접수\n"
        "3. 기술료 납부에 관한 사항\n수익의 일부를 정부에 반납\n"
    )
    sections = split_rd_notice_sections(text)
    group_by_header = {s.header: s.group for s in sections}

    assert group_by_header["신청자격"] == "match_relevant"
    assert group_by_header["신청방법"] == "procedural"
    assert group_by_header["기술료 납부에 관한 사항"] == "excluded"


def test_rd_synonym_a_group_keywords_are_match_relevant():
    # 가이드 4장 (A)그룹 — R&D 특유 용어로 포장돼 있을 뿐 실제로는 사업목적/
    # 지원규모와 같은 성격이라 매칭 관련으로 분류돼야 한다.
    text = "1. 연구개발목표\nOO기술 TRL 5 달성\n2. 가감점 제도\n여성기업 가점 2점"
    sections = split_rd_notice_sections(text)
    group_by_header = {s.header: s.group for s in sections}

    assert group_by_header["연구개발목표"] == "match_relevant"
    assert group_by_header["가감점 제도"] == "match_relevant"


def test_preamble_before_first_header_is_kept_as_headnote():
    text = "2026년도 OO기술개발사업 신규과제 공고\n1. 신청자격\n중소기업"
    sections = split_rd_notice_sections(text)

    assert sections[0].header == "머리말"
    assert "OO기술개발사업" in sections[0].text
    assert sections[0].group == "match_relevant"


def test_falls_back_to_single_section_when_no_headers_found():
    # 실측 6.3%는 헤더를 하나도 못 찾는다 — 못 나눴다고 임베딩 대상에서
    # 빼면 그 공고 전체가 2차 필터링에서 사라지므로 전체를 하나로 폴백한다.
    text = "특이한 형식의 공고문입니다. 섹션 구분 없이 줄글로만 작성되어 있습니다."
    sections = split_rd_notice_sections(text)

    assert len(sections) == 1
    assert sections[0].header == "전체"
    assert sections[0].group == "match_relevant"


def test_chunk_rd_notice_text_excludes_excluded_group():
    text = (
        "1. 신청자격\n중소기업\n"
        "2. 연구개발과제의 성실 수행\n목표 미달성해도 성실수행 인정 시 실패 아님\n"
    )
    chunks = chunk_rd_notice_text(text)

    chunk_types = [c.chunk_type for c in chunks]
    assert "신청자격" in chunk_types
    assert "연구개발과제의 성실 수행" not in chunk_types


def test_chunk_rd_notice_text_keeps_procedural_group():
    # 매칭 스코어링엔 안 쓰지만(호출부가 chunk_type으로 걸러 쓸 수 있게) 청크
    # 자체는 만들어 원문 조회에 쓸 수 있게 남긴다.
    text = "1. 문의처\n담당자 02-000-0000\n2. 신청자격\n중소기업\n"
    chunks = chunk_rd_notice_text(text)

    chunk_types = [c.chunk_type for c in chunks]
    assert "문의처" in chunk_types
    assert "신청자격" in chunk_types


def test_chunk_rd_notice_text_splits_oversized_section():
    long_body = "가" * 3000
    text = f"1. 지원내용\n{long_body}"
    chunks = chunk_rd_notice_text(text, max_chars=1200)

    support_chunks = [c for c in chunks if c.chunk_type == "지원내용"]
    assert len(support_chunks) > 1
    assert all(len(c.chunk_text) <= 1200 for c in support_chunks)


def test_chunk_rd_notice_text_returns_empty_for_blank_input():
    assert chunk_rd_notice_text("   \n\n  ") == []
