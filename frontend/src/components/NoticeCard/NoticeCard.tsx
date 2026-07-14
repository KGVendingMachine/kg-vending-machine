import type { MatchedNotice } from '../../types/notice'

interface NoticeCardProps {
  notice: MatchedNotice
  selected: boolean
  onClick: () => void
  /** 별표 토글 핸들러. 넘기지 않으면 별표를 표시하지 않는다. */
  onToggleBookmark?: () => void
  /** 토글 요청이 진행 중이면 별표를 잠깐 비활성화한다(중복 클릭 방지). */
  bookmarkBusy?: boolean
  /** 선택하지 않아도 추천 사유를 항상 표시한다(북마크 목록 등). */
  showReason?: boolean
}

const SCORE_LEVEL_CLASS: Record<string, string> = {
  high: 'text-success',
  medium: 'text-warning',
  low: 'text-danger',
}

export function NoticeCard({
  notice,
  selected,
  onClick,
  onToggleBookmark,
  bookmarkBusy = false,
  showReason = false,
}: NoticeCardProps) {
  const bookmarked = notice.bookmarkId != null

  return (
    <div
      className={
        selected
          ? 'mb-3.5 block w-full cursor-pointer rounded-md border-[1.5px] border-primary bg-white p-[18px] text-left'
          : 'mb-3.5 block w-full cursor-pointer rounded-md border border-border bg-white p-[18px] text-left'
      }
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault()
          onClick()
        }
      }}
      role="button"
      tabIndex={0}
    >
      <div className="flex justify-between gap-3">
        <div className="flex-1">
          <div className="mb-2 flex items-center gap-2">
            {notice.category ? (
              <span className="rounded-[3px] bg-primary-soft px-2 py-[3px] text-[11px] font-bold text-primary">
                {notice.category}
              </span>
            ) : null}
            <span
              className={
                notice.isUrgent
                  ? 'text-[11px] font-semibold text-danger'
                  : 'text-[11px] font-semibold text-muted'
              }
            >
              {notice.deadlineLabel}
            </span>
          </div>
          <div className="text-base font-extrabold leading-[1.4]">
            {notice.title}
          </div>
          <div className="mt-1 text-[13px] text-muted">{notice.org}</div>
          <div className="mt-3 flex gap-[18px] text-[13px] text-ink">
            {notice.amountLabel ? <span>💰 {notice.amountLabel}</span> : null}
            <span>🗓 {notice.dueDateLabel}</span>
          </div>
        </div>
        {notice.score != null && notice.scoreLevel != null ? (
          <div className="flex-shrink-0 text-center">
            <div
              className={`text-[32px] font-extrabold leading-none ${SCORE_LEVEL_CLASS[notice.scoreLevel]}`}
            >
              {notice.score}
            </div>
            <div className="mt-0.5 text-[11px] text-faint">적합도</div>
          </div>
        ) : null}
        {onToggleBookmark ? (
          <button
            type="button"
            className={
              bookmarked
                ? 'h-7 w-7 flex-shrink-0 self-start rounded bg-transparent text-lg leading-none text-[#f5a623] disabled:opacity-50'
                : 'h-7 w-7 flex-shrink-0 self-start rounded bg-transparent text-lg leading-none text-faint disabled:opacity-50'
            }
            aria-label={bookmarked ? '북마크 해제' : '북마크 추가'}
            disabled={bookmarkBusy}
            onClick={(event) => {
              event.stopPropagation()
              onToggleBookmark()
            }}
          >
            {bookmarked ? '★' : '☆'}
          </button>
        ) : null}
      </div>
      {(selected || showReason) && notice.matchReasonShort ? (
        <div className="mt-3 border-t border-border pt-3 text-xs leading-[1.6] text-muted">
          {notice.matchReasonShort}
        </div>
      ) : null}
    </div>
  )
}
