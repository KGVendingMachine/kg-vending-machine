export const PATHS = {
  LANDING: '/',
  LOGIN: '/login',
  COMPANY_PROFILE: '/company-profile',
  UPLOAD: '/upload',
  ANALYSIS: '/analysis',
  RESULTS: '/results',
  RESULT_DETAIL: '/results/:noticeId',
  NOTICE_DETAIL: '/notices/:noticeId',
  BOOKMARKS: '/bookmarks',
  MYPAGE: '/mypage',
} as const

/**
 * 매칭 상세 페이지 경로. 점수·추천 근거는 공고 단독이 아니라 특정 매칭
 * 실행(match_log) 기준이라 matchLogId를 함께 실어야 한다.
 */
export function resultDetailPath(noticeId: number, matchLogId: number): string {
  return `/results/${noticeId}?matchLogId=${matchLogId}`
}

/**
 * 결과 페이지 경로. matchLogId를 넘기면 그 매칭 실행 기준으로 표시한다.
 * router state 대신 쿼리로 넘겨 새로고침·재방문에도 유지되게 한다.
 */
export function resultsPath(matchLogId?: number): string {
  return matchLogId != null
    ? `${PATHS.RESULTS}?matchLogId=${matchLogId}`
    : PATHS.RESULTS
}

/**
 * 매칭 컨텍스트 없는 공고 단독 상세 페이지 경로 (북마크 목록 등에서 사용).
 * 점수·추천 근거가 필요하면 resultDetailPath를 대신 쓴다.
 */
export function noticeDetailPath(noticeId: number): string {
  return `/notices/${noticeId}`
}
