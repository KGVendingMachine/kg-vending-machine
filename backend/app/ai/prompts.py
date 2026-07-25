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
- 모든 extra 필드는 정보가 없으면 null이 아니라 빈 객체 {{}}로 출력하세요.
- 각 카테고리마다 스키마에 없는 회사 특이 정보가 있으면 해당 카테고리의 "extra" 객체에
  문자열 키-값 형태로 자유롭게 담으세요.
- problem.background에는 "창업 배경", "개발 동기", "문제 인식", "시장/고객 배경" 문단을
  한두 문장으로 요약하세요. 원문에 별도 제목이 없더라도 문제 상황이나 고객 불편이 설명되어
  있으면 반드시 채우세요.
- funding.scale_up_strategy에는 "사업화 추진 전략", "시장진입", "마케팅", "판매채널",
  "고객 확보", "매출 확대", "향후 계획"에 해당하는 문장을 종합해 작성하세요.
  금액 사용처(use_of_funds)만 있고 전략이 없을 때만 null로 두세요.
- team.capabilities에는 대표자/팀원의 "전공", "경력", "역할", "보유 역량", "기술력",
  "창업 경험", "수상/인증/네트워크" 정보를 한 문장으로 요약하세요. 팀원 목록을 찾았는데
  capabilities가 비어 있으면 잘못된 출력입니다.
- company.region_name에는 사업장(본사) 소재지의 시/도만 담으세요. 주소가
  "서울특별시 강남구 …"처럼 상세해도 "서울"처럼 스키마에 나열된 표준 이름 하나로
  줄이세요. 사업장 주소를 확인할 수 없으면 null로 두고, 대표자 거주지나 시장
  설명에 나온 지역으로 추측하지 마세요.
- company.business_type은 사업자등록/법인 설립 언급을 근거로 개인사업자/법인사업자/
  예비창업자 중 하나만 담으세요. "(주)", "주식회사", "법인 설립"이 있으면 법인사업자,
  사업자등록 전·창업 준비 중이면 예비창업자입니다. 근거가 없으면 null로 두세요.
- company.industry_candidates에는 지원사업 매칭에 사용할 사업 분야 후보를 1~3개 담으세요.
  label은 원문 업종/아이템을 바탕으로 "자금", "R&D·기술", "수출·글로벌", "인력",
  "시설·공간·보육", "멘토링·컨설팅", "교육·행사·네트워킹", "기타" 중 가까운 통합
  카테고리나 실제 업종 키워드로 작성하고, confidence는 0~1 사이 숫자로 두세요.
  근거가 부족하면 빈 배열로 두고 추측하지 마세요.
- 출력 전 자체 점검: problem.background, solution.summary, funding.scale_up_strategy,
  team.capabilities가 원문에서 확인 가능한데 null이면 다시 작성하세요.

JSON 스키마:
{_SCHEMA_JSON}
"""


def build_user_prompt(raw_text: str) -> str:
    return f"다음은 정규화할 사업계획서 원문입니다.\n\n{raw_text}"
