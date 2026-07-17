import { apiFetch } from './client'
import type { SecondaryFilteringNoticeLog } from './matchLogs'

/** backend/app/schemas/notice_bookmark.py BookmarkNoticeInfo */
export interface BookmarkNoticeInfo {
  id: number
  title: string | null
  organization_name: string | null
  category_name: string | null
  status: string | null
  application_end_date: string | null
  amount_label: string | null
  source_url: string | null
  apply_url: string | null
}

/** backend BookmarkRecommendation — 담을 당시(frozen) 추천 근거 */
export interface BookmarkRecommendation {
  total_score: number | null
  recommendation_level: string | null
  summary_reason: string | null
}

/** backend BookmarkResponse — 북마크 한 건 */
export interface Bookmark {
  id: number
  source: string
  business_plan_id: number | null
  business_plan_title: string | null
  /** 이 추천의 기반 사업계획서가 현재 최신 계획서와 다른지. 브라우징 북마크는 항상 false. */
  is_stale: boolean
  notice: BookmarkNoticeInfo
  recommendation: BookmarkRecommendation | null
  created_at: string
}

/** GET /bookmarks — 내 북마크 목록(최신순).
 * 비로그인 상태에서도 앱 마운트 시 호출되므로 401이어도 로그인 페이지로 보내지 않는다. */
export function listBookmarks(): Promise<Bookmark[]> {
  return apiFetch<Bookmark[]>('/api/bookmarks', { redirectOn401: false })
}

/** 추천 카드에서 담기 — 서버가 공고·사업계획서·점수 맥락을 채운다. */
export function createBookmarkByResult(matchResultId: number): Promise<Bookmark> {
  return apiFetch<Bookmark>('/api/bookmarks', {
    method: 'POST',
    body: JSON.stringify({ match_result_id: matchResultId }),
  })
}

/** 공고 목록 브라우징에서 담기 — 사업계획서 맥락 없이 공고만. */
export function createBookmarkByNotice(noticeId: number): Promise<Bookmark> {
  return apiFetch<Bookmark>('/api/bookmarks', {
    method: 'POST',
    body: JSON.stringify({ notice_id: noticeId }),
  })
}

/** DELETE /bookmarks/{id} — 북마크 해제. */
export function deleteBookmark(bookmarkId: number): Promise<void> {
  return apiFetch<void>(`/api/bookmarks/${bookmarkId}`, { method: 'DELETE' })
}

/**
 * 북마크 담을 당시 매칭 실행에 남아있는 2차 필터링 요건별 판정 근거를
 * 조회한다. 브라우징으로 담았거나 원본 매칭 실행/결과가 삭제됐으면 null
 * (서버가 그대로 null을 준다 — getSecondaryFilteringLog처럼 404를 null로
 * 정규화할 필요가 없다).
 */
export function getBookmarkSecondaryFiltering(
  bookmarkId: number,
): Promise<SecondaryFilteringNoticeLog | null> {
  return apiFetch<SecondaryFilteringNoticeLog | null>(
    `/api/bookmarks/${bookmarkId}/secondary-filtering`,
  )
}

/**
 * 별표 토글. 이미 담겼으면(bookmarkId 있음) 해제하고, 아니면 담는다.
 * 추천 카드면 matchResultId 로, 브라우징이면 noticeId 로 담는다.
 * 새 상태의 bookmarkId(해제됐으면 null)를 돌려주므로 호출부가 카드 상태를 갱신한다.
 */
export async function toggleBookmark(args: {
  bookmarkId: number | null
  matchResultId: number | null
  noticeId: number
}): Promise<number | null> {
  if (args.bookmarkId != null) {
    await deleteBookmark(args.bookmarkId)
    return null
  }
  const created =
    args.matchResultId != null
      ? await createBookmarkByResult(args.matchResultId)
      : await createBookmarkByNotice(args.noticeId)
  return created.id
}
