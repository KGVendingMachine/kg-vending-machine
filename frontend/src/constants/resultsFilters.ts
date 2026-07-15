/** 결과 페이지 마감 필터 체크박스 라벨 */
export const DEADLINE_FILTERS = ['7일 이내', '30일 이내', '상시 모집']

/** 결과 페이지 분야 필터 탭(단일 선택). value는 notice.category 원문과 비교한다
 * ('전체'는 필터를 걸지 않는다는 뜻의 'all'). */
export const CATEGORY_FILTERS = [
  { label: '전체', value: 'all' },
  { label: '자금', value: '자금' },
  { label: 'R&D', value: 'R&D·기술' },
] as const

export type CategoryFilterValue = (typeof CATEGORY_FILTERS)[number]['value']
