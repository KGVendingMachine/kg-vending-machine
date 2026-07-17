/**
 * 기업 프로필 입력 폼의 선택지. 백엔드 검증 집합
 * (backend/app/schemas/company.py의 BUSINESS_TYPES · COMPANY_STAGES ·
 * REGION_CODES · KSIC_INDUSTRIES)과 값이 일치해야 한다.
 */

/** 사업자유형 */
export const BUSINESS_TYPES = ['개인사업자', '법인사업자', '예비창업자'] as const

/** 기업 단계. 예비창업자는 사업자유형이 표현하고, 소상공인은 단계가 아니라
 * 규모라 제외(규모는 서버가 산출). */
export const COMPANY_STAGES = ['초기창업', '중소기업'] as const

/** 사업장 시/도 (region_name으로 전송, 코드 변환은 서버 담당) */
export const REGIONS = [
  '서울',
  '부산',
  '대구',
  '인천',
  '광주',
  '대전',
  '울산',
  '세종',
  '경기',
  '강원',
  '충북',
  '충남',
  '전북',
  '전남',
  '경북',
  '경남',
  '제주',
] as const

/** 한국표준산업분류(KSIC) 대분류. value=코드(industry_code로 전송) */
export const KSIC_INDUSTRIES = [
  { code: 'A', label: '농업, 임업 및 어업' },
  { code: 'B', label: '광업' },
  { code: 'C', label: '제조업' },
  { code: 'D', label: '전기, 가스, 증기 및 공기 조절 공급업' },
  { code: 'E', label: '수도, 하수 및 폐기물 처리, 원료 재생업' },
  { code: 'F', label: '건설업' },
  { code: 'G', label: '도매 및 소매업' },
  { code: 'H', label: '운수 및 창고업' },
  { code: 'I', label: '숙박 및 음식점업' },
  { code: 'J', label: '정보통신업' },
  { code: 'K', label: '금융 및 보험업' },
  { code: 'L', label: '부동산업' },
  { code: 'M', label: '전문, 과학 및 기술 서비스업' },
  { code: 'N', label: '사업시설 관리, 사업 지원 및 임대 서비스업' },
  { code: 'P', label: '교육 서비스업' },
  { code: 'Q', label: '보건업 및 사회복지 서비스업' },
  { code: 'R', label: '예술, 스포츠 및 여가관련 서비스업' },
  { code: 'S', label: '협회 및 단체, 수리 및 기타 개인 서비스업' },
] as const
