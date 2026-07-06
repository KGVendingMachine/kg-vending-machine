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
