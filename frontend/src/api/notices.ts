import { apiFetch } from './client'

/** backend/app/schemas/notice.py NoticeAttachmentInfo */
export interface NoticeAttachmentInfo {
  file_name: string | null
  file_url: string | null
  file_type: string | null
}

/** backend/app/schemas/notice.py NoticeSummary — 목록용 요약 정보 */
export interface NoticeSummary {
  id: number
  source: string
  title: string | null
  category: string | null
  status: string | null
  application_start_date: string | null
  application_end_date: string | null
  regions: string[]
}

/** backend/app/schemas/notice.py NoticeListResponse */
export interface NoticeListResponse {
  total: number
  items: NoticeSummary[]
}

/** backend/app/schemas/notice.py NoticeDetail — 상세 조회용 전체 정보 */
export interface NoticeDetail {
  id: number
  source: string
  title: string | null
  category: string | null
  status: string | null
  is_actionable: boolean | null
  application_start_date: string | null
  application_end_date: string | null
  source_url: string | null
  apply_url: string | null
  summary_text: string | null
  amount_label: string | null
  support_types: string[]
  support_contents: string[]
  regions: string[]
  target_types: string[]
  attachments: NoticeAttachmentInfo[]
  created_at: string
  updated_at: string
}

export interface ListNoticesParams {
  source?: string
  category?: string
  regionCode?: string
  excludeClosed?: boolean
  limit?: number
  offset?: number
}

/** GET /notices — 출처/카테고리/지역 필터 + 페이지네이션. */
export function listNotices(
  params: ListNoticesParams = {},
): Promise<NoticeListResponse> {
  const query = new URLSearchParams()
  if (params.source) query.set('source', params.source)
  if (params.category) query.set('category', params.category)
  if (params.regionCode) query.set('region_code', params.regionCode)
  if (params.excludeClosed !== undefined) {
    query.set('exclude_closed', String(params.excludeClosed))
  }
  if (params.limit !== undefined) query.set('limit', String(params.limit))
  if (params.offset !== undefined) query.set('offset', String(params.offset))

  const qs = query.toString()
  return apiFetch<NoticeListResponse>(`/api/notices${qs ? `?${qs}` : ''}`)
}

/** GET /notices/{notice_id} — 공고 상세 조회. */
export function getNoticeDetail(noticeId: number): Promise<NoticeDetail> {
  return apiFetch<NoticeDetail>(`/api/notices/${noticeId}`)
}
