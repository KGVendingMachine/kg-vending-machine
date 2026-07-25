"""
services/notice_ocr_target.py

공고 첨부파일 중 OCR·정규화에 쓸 "공고문" 하나를 고르는 로직.
app/api/notice_ocr.py(OCR 트리거)와 app/services/notice_normalization_service.py
(정규화, OCR 결과를 그대로 재사용) 양쪽에서 같은 기준으로 첨부파일을
골라야 해서 여기서 공유한다.
"""

from app.models.notice import NoticeAttachment

# extract_text()가 실제로 처리하는 문서 포맷만 대상으로 한다 (이미지/ZIP/
# 엑셀 등은 OCR 대상에서 제외 — DOC/DOCX는 extract_text가 아직 지원하지
# 않아 여기도 포함하지 않는다).
OCR_TARGET_FILE_TYPES = {"PDF", "HWP", "HWPX"}

# 공고 하나에 첨부파일이 여러 개면 "공고문" 하나만 OCR한다(2026-07-11
# 프로토타입 범위 결정, 신청서식/붙임자료는 대상 아님). 기업마당/K-Startup
# API 모두 어떤 파일이 공고문인지 알려주는 필드가 없어 파일명으로 판별해야
# 하는데, 실제 DB 첨부파일명 200건을 확인해보니 공고문은 "공고"/"공모"를
# 포함하고(예: "26년_지원사업_추가_공고문.pdf", "[공모] ...공모요강.pdf"),
# 신청서/서식/붙임/별첨 자료는 이 키워드가 없어 이름만으로 안정적으로
# 구분된다.
_NOTICE_DOCUMENT_KEYWORDS = ("공고", "공모")

# "공고"/"공모"가 들어있어도 신청 양식 자체일 수 있다 — 실제 DB에서 배치
# 트리거를 돌려보다 발견함(이슈 검증 중, 2026-07-11): "붙임1. ...3차 공모
# 융자신청서.hwp"는 "공모"를 포함하지만 실제 공고문은 같은 공고의 다른
# 첨부파일 "[공모] ...공모요강(변경).pdf"였다. "신청서식(변경공고).hwp"처럼
# 신청 양식 파일명에 "공고"가 들어간 경우도 실제로 있었다. 두 키워드가
# 동시에 있으면 신청 양식으로 간주해 후보에서 제외한다.
_APPLICATION_FORM_KEYWORDS = ("신청서", "서식", "동의서", "확인서", "확약서")


def is_notice_document_name(file_name: str | None) -> bool:
    if not file_name:
        return False
    if any(kw in file_name for kw in _APPLICATION_FORM_KEYWORDS):
        return False
    return any(kw in file_name for kw in _NOTICE_DOCUMENT_KEYWORDS)


def pick_ocr_target(attachments: list[NoticeAttachment]) -> NoticeAttachment | None:
    """공고문으로 보이는 첨부파일을 우선 고르고, 그중 이미 OCR된 게 있으면
    그걸 재사용한다.

    파일명으로 공고문을 특정할 수 없는 공고(오래된 데이터, 이름 규칙이
    다른 출처 등)도 있어, 공고문 후보가 하나도 없으면 예전처럼 문서 포맷 중
    첫 번째로 폴백한다 — 아예 처리를 포기하는 것보다 낫다고 판단.
    """
    documents = [a for a in attachments if a.file_type in OCR_TARGET_FILE_TYPES]
    notice_documents = [a for a in documents if is_notice_document_name(a.file_name)]
    candidates = notice_documents or documents

    # parsed_text는 Optional[str]라 None(아직 처리 안 함)과 ""(처리했는데
    # 텍스트가 없었음)을 구분해야 한다 — truthy 체크(`if a.parsed_text`)를
    # 쓰면 빈 문자열도 "아직 처리 안 함"으로 보여 매번 재-OCR하게 된다.
    already_parsed = next((a for a in candidates if a.parsed_text is not None), None)
    if already_parsed is not None:
        return already_parsed
    return candidates[0] if candidates else None
