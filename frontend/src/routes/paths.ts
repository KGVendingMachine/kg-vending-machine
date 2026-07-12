export const PATHS = {
  LANDING: '/',
  LOGIN: '/login',
  COMPANY_PROFILE: '/company-profile',
  UPLOAD: '/upload',
  ANALYSIS: '/analysis',
  RESULTS: '/results',
  RESULT_DETAIL: '/results/:noticeId',
  BOOKMARKS: '/bookmarks',
  MYPAGE: '/mypage',
} as const

export function resultDetailPath(noticeId: string): string {
  return `/results/${noticeId}`
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
