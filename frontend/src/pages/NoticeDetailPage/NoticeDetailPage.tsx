import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { getNoticeDetail } from '../../api/notices'
import type { NoticeDetail } from '../../api/notices'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { PATHS } from '../../routes/paths'
import { useBookmarks } from '../../store/BookmarkContext'
import { formatDeadline } from '../../utils/date'

/**
 * 매칭 컨텍스트 없이 공고 자체의 정보만 보여주는 상세 페이지.
 * MatchDetailPage(/results/:noticeId)는 특정 매칭 실행(match_log) 기준
 * 점수·추천 근거가 있어야 해서 matchLogId가 필수지만, 북마크 목록처럼
 * "이 공고가 뭔지"만 보면 되는 곳에서는 matchLogId가 없다 — 그 자리를
 * 채우는 페이지.
 */
export function NoticeDetailPage() {
  const { noticeId: noticeIdParam } = useParams<{ noticeId: string }>()
  const noticeId = noticeIdParam ? Number(noticeIdParam) : null
  const navigate = useNavigate()
  const { isBookmarked, toggleBookmark } = useBookmarks()

  const { data: notice, loading, error } = useFetchOnMount<NoticeDetail>(() => {
    if (noticeId == null || Number.isNaN(noticeId)) return null
    return getNoticeDetail(noticeId)
  }, [noticeId])

  if (noticeId == null || Number.isNaN(noticeId)) {
    return <Navigate to={PATHS.BOOKMARKS} replace />
  }

  if (loading) {
    return (
      <div className="flex flex-1 flex-col">
        <AppHeader />
        <div className="flex items-center gap-8 border-b border-[#eef0f2] bg-white px-10 py-7">
          공고 정보를 불러오는 중이에요…
        </div>
      </div>
    )
  }

  if (error || !notice) {
    return (
      <div className="flex flex-1 flex-col">
        <AppHeader />
        <div className="flex flex-1 flex-col items-center justify-center gap-3 px-10 py-12 text-center">
          <div className="text-[15px] font-bold">공고를 찾을 수 없어요</div>
          <button
            type="button"
            className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-primary"
            onClick={() => navigate(PATHS.BOOKMARKS)}
          >
            북마크로 돌아가기
          </button>
        </div>
      </div>
    )
  }

  const deadline = formatDeadline(notice.application_end_date)
  const bookmarked = isBookmarked(notice.id)

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />

      <div className="flex h-14 items-center gap-[14px] border-b border-[#eef0f2] bg-white px-6">
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-primary"
          onClick={() => navigate(-1)}
        >
          ← 뒤로
        </button>
        <div className="text-[15px] font-extrabold">공고 상세</div>
        <button
          type="button"
          className={
            bookmarked
              ? 'ml-auto h-8 cursor-pointer rounded border border-[#f5a623] bg-white px-3 text-[13px] font-semibold text-[#f5a623]'
              : 'ml-auto h-8 cursor-pointer rounded border border-border-strong bg-white px-3 text-[13px] font-semibold text-muted'
          }
          aria-label={bookmarked ? '북마크 해제' : '북마크 추가'}
          onClick={() => toggleBookmark(notice.id)}
        >
          {bookmarked ? '★ 북마크됨' : '☆ 북마크'}
        </button>
      </div>

      <div className="border-b border-[#eef0f2] bg-white px-10 py-7">
        <div className="mb-[10px] flex items-center gap-2">
          {notice.category ? (
            <span className="rounded-[3px] bg-primary-soft px-2 py-[3px] text-[11px] font-bold text-primary">
              {notice.category}
            </span>
          ) : null}
          <span
            className={
              deadline.isUrgent
                ? 'text-[11px] font-semibold text-danger'
                : 'text-[11px] font-semibold text-muted'
            }
          >
            {deadline.label} · {deadline.dueDateLabel} 마감
          </span>
          {notice.is_actionable === false ? (
            <span className="rounded-[3px] bg-surface-subtle px-2 py-[3px] text-[11px] font-bold text-faint">
              신청 마감
            </span>
          ) : null}
        </div>
        <div className="text-2xl font-extrabold tracking-[-0.5px]">{notice.title ?? '(제목 없음)'}</div>
        <div className="mt-[5px] text-sm text-muted">
          {notice.source}
          {notice.amount_label ? ` · ${notice.amount_label}` : ''}
        </div>
        {notice.regions.length > 0 || notice.target_types.length > 0 ? (
          <div className="mt-2 flex flex-wrap gap-1.5">
            {notice.regions.map((region) => (
              <span
                key={region}
                className="rounded-[3px] bg-surface-subtle px-2 py-[3px] text-[11px] font-semibold text-muted"
              >
                {region}
              </span>
            ))}
            {notice.target_types.map((type) => (
              <span
                key={type}
                className="rounded-[3px] bg-surface-subtle px-2 py-[3px] text-[11px] font-semibold text-muted"
              >
                {type}
              </span>
            ))}
          </div>
        ) : null}
      </div>

      <div className="grid flex-1 grid-cols-2">
        <div className="border-r border-[#eef0f2] bg-white px-8 py-7">
          <div className="mb-1.5 text-[15px] font-extrabold">공고 요약</div>
          <div className="mb-6 text-[13px] leading-[1.6] text-[#374151]">
            {notice.summary_text || '요약 정보가 없어요.'}
          </div>

          <div className="mb-1.5 text-[15px] font-extrabold">첨부파일</div>
          {notice.attachments.length > 0 ? (
            <div className="flex flex-col gap-2">
              {notice.attachments.map((attachment, index) => (
                <div
                  key={`${attachment.file_url ?? attachment.file_name ?? index}`}
                  className="flex items-center justify-between rounded border border-border px-3 py-2.5 text-[13px]"
                >
                  <span className="truncate">{attachment.file_name ?? '(파일명 없음)'}</span>
                  {attachment.file_url ? (
                    <a
                      href={attachment.file_url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-3 flex-shrink-0 text-[12.5px] font-semibold text-primary no-underline"
                    >
                      다운로드
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="text-[13px] text-faint">첨부파일이 없어요.</div>
          )}
        </div>

        <div className="bg-white px-8 py-7">
          <div className="mb-1.5 text-[15px] font-extrabold">신청 정보</div>
          <div className="mb-6 flex flex-col gap-2 text-[13px] text-[#374151]">
            <div>
              <b>신청기간</b> —{' '}
              {notice.application_start_date && notice.application_end_date
                ? `${notice.application_start_date} ~ ${notice.application_end_date}`
                : '상시 모집'}
            </div>
            <div>
              <b>모집상태</b> — {notice.status ?? '확인 필요'}
            </div>
          </div>

          <div className="flex flex-col gap-2.5">
            {notice.source_url ? (
              <a
                href={notice.source_url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-md border border-border-strong px-4 py-3 text-center text-[13px] font-semibold text-ink no-underline"
              >
                원문 공고 보기 ↗
              </a>
            ) : null}
            {notice.apply_url ? (
              <a
                href={notice.apply_url}
                target="_blank"
                rel="noreferrer"
                className="block rounded-md bg-primary px-4 py-3 text-center text-[13px] font-semibold text-white no-underline"
              >
                신청하러 가기 ↗
              </a>
            ) : null}
          </div>

          <div className="mt-6 rounded-md bg-surface-subtle px-4 py-3.5 text-xs leading-[1.6] text-muted">
            정확한 자격요건·제출서류는 원문 공고를 반드시 확인하세요.
          </div>
        </div>
      </div>
    </div>
  )
}
