import type { MatchedNotice } from '../../types/notice'
import { useBookmarks } from '../../store/BookmarkContext'
import styles from './NoticeCard.module.css'

interface NoticeCardProps {
  notice: MatchedNotice
  selected: boolean
  onClick: () => void
}

export function NoticeCard({ notice, selected, onClick }: NoticeCardProps) {
  const { isBookmarked, toggleBookmark } = useBookmarks()
  const bookmarked = isBookmarked(notice.id)

  return (
    <div
      className={selected ? `${styles.card} ${styles.selected}` : styles.card}
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
      <div className={styles.row}>
        <div className={styles.main}>
          <div className={styles.badges}>
            {notice.category ? (
              <span className={styles.category}>{notice.category}</span>
            ) : null}
            <span
              className={
                notice.isUrgent
                  ? `${styles.deadline} ${styles.urgent}`
                  : styles.deadline
              }
            >
              {notice.deadlineLabel}
            </span>
          </div>
          <div className={styles.title}>{notice.title}</div>
          <div className={styles.org}>{notice.org}</div>
          <div className={styles.meta}>
            {notice.amountLabel ? <span>💰 {notice.amountLabel}</span> : null}
            <span>🗓 {notice.dueDateLabel}</span>
          </div>
        </div>
        {notice.score != null && notice.scoreLevel != null ? (
          <div className={styles.scoreCol}>
            <div className={`${styles.scoreValue} ${styles[notice.scoreLevel]}`}>
              {notice.score}
            </div>
            <div className={styles.scoreLabel}>적합도</div>
          </div>
        ) : null}
        <button
          type="button"
          className={
            bookmarked
              ? `${styles.bookmarkButton} ${styles.bookmarked}`
              : styles.bookmarkButton
          }
          aria-label={bookmarked ? '북마크 해제' : '북마크 추가'}
          onClick={(event) => {
            event.stopPropagation()
            toggleBookmark(notice.id)
          }}
        >
          {bookmarked ? '★' : '☆'}
        </button>
      </div>
      {selected && notice.matchReasonShort ? (
        <div className={styles.reason}>{notice.matchReasonShort}</div>
      ) : null}
    </div>
  )
}
