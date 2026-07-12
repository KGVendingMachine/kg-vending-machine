# 정규화 품질 검증 리포트

## 검증 범위

- 실행일: 2026-07-12
- 사업계획서 샘플: 30건
- 공고 OCR 샘플: 30건
- 실행 스크립트: `backend/scripts/evaluate_normalization_quality.py`
- 출력 파일: `backend/data/normalization_quality_report.json` (`backend/data/`는 git 제외)

## 검증 결과

### 사업계획서

- 완료: 30/30
- 유효: 30/30
- LLM 파싱 안정성 보완:
  - `extra: null` 응답을 빈 객체로 정규화
  - 배열 필드(`tech_stack`, `differentiators`, `competitors`, `use_of_funds`, `members`)의 `null` 응답을 빈 배열로 정규화
- 프롬프트 보완:
  - `problem.background`
  - `funding.scale_up_strategy`
  - `team.capabilities`
  - 위 필드를 원문에서 어떤 문단/표현으로 채워야 하는지 명시

### 공고

- 완료: 30/30
- 유효: 26/30
- 남은 invalid 4건의 주된 원인:
  - 공고문이 아니라 신청서, 개인정보 동의서, 매뉴얼, 장비 카탈로그류 첨부파일
  - 해당 파일에는 신청방법, 지원내용, 대상 기업 규모 같은 공고 핵심 정보가 충분히 없음
- 후처리 보완:
  - `support.summary`가 있는데 `support.support_content`가 비어 있으면 summary를 support_content에 보존
  - 원문에 기업/사업장/사업자 표현이 있는데 기업 규모가 비어 있으면 `기업`으로 보완
  - 이메일/전화번호가 원문에 있으면 `contact.email`/`contact.phone` 보완
  - 매칭 키워드, 적합 기업 프로필, matching_signals가 비어 있으면 카테고리/지원유형/대상/지역에서 안전한 fallback 생성
  - `contact.email`/`contact.phone`이 배열로 출력되는 LLM 응답은 문자열로 정규화

## 최소 품질 기준

매칭 알고리즘 입력으로 사용하기 위한 최소 기준은 아래와 같이 둔다.

### 사업계획서

필수:

- `problem.background`
- `solution.summary`
- `funding.scale_up_strategy`
- `team.capabilities`

위 4개 필드가 모두 채워진 사업계획서만 매칭 점수 산출 대상으로 사용한다.

### 공고

필수:

- `basic.title`
- `support.summary`
- `support.support_type`
- `support.support_content`
- `matching.keywords`
- `matching.suitable_company_profile`
- `matching.matching_signals`

권장:

- `application.method`
- `eligibility.target_company_size`

공고 OCR 대상이 신청서/동의서/카탈로그류로 잘못 선택된 경우 정규화 품질이 떨어진다. 이 케이스는 프롬프트 문제가 아니라 OCR 대상 파일 선택 문제로 분리해 처리한다.

## 다음 작업

- 공고 OCR 대상 선택 로직에서 신청서/동의서/카탈로그/매뉴얼류 첨부파일을 더 강하게 제외한다.
- 매칭 알고리즘 구현 시 위 최소 품질 기준을 통과한 정규화 JSON만 1차 점수 산출에 사용한다.
- 기준 미달 공고는 `확인필요` 또는 `원문 확인 필요` 경로로 분리한다.
