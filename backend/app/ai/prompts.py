"""
ai/prompts.py

NRM-001: 사업계획서 정규화용 프롬프트.
JSON 모드(response_format={"type": "json_object"})로 호출하므로 OpenAI가 스키마를
강제해주지 않는다. 그래서 모델이 지켜야 할 필드를 시스템 프롬프트에 JSON 스키마
텍스트로 직접 박아준다. 실제 검증/재시도는 normalizer.py에서 pydantic으로 처리.
"""

import json

from app.schemas.business_plan import NormalizedBusinessPlanSchema

_SCHEMA_JSON = json.dumps(
    NormalizedBusinessPlanSchema.model_json_schema(), ensure_ascii=False
)

SYSTEM_PROMPT = f"""\
당신은 초기 창업기업의 사업계획서를 표준 스키마로 정규화하는 어시스턴트입니다.
사용자가 제공하는 사업계획서 원문을 읽고, 아래 JSON 스키마를 그대로 따르는 JSON 객체
하나만 출력하세요. 설명, 코드블록 표시 등 다른 텍스트는 절대 포함하지 마세요.

규칙:
- 스키마에 정의되지 않은 필드는 만들지 마세요.
- 원문에서 확인할 수 없는 정보는 null(문자열/숫자) 또는 빈 배열로 두세요. 추측하지 마세요.
- 각 카테고리마다 스키마에 없는 회사 특이 정보가 있으면 해당 카테고리의 "extra" 객체에
  문자열 키-값 형태로 자유롭게 담으세요.

JSON 스키마:
{_SCHEMA_JSON}
"""


def build_user_prompt(raw_text: str) -> str:
    return f"다음은 정규화할 사업계획서 원문입니다.\n\n{raw_text}"
