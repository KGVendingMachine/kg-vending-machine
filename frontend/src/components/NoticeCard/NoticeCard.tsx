import type { Notice } from '../../types/notice'
import styles from './NoticeCard.module.css'

interface NoticeCardProps {
  notice: Notice
  selected: boolean
  onClick: () => void
}

export function NoticeCard({ notice, selected, onClick }: NoticeCardProps) {
  return (
    <button
      type="button"
      className={selected ? `${styles.card} ${styles.selected}` : styles.card}
      onClick={onClick}
    >
      <div className={styles.row}>
        <div className={styles.main}>
          <div className={styles.badges}>
            <span className={styles.category}>{notice.category}</span>
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
            <span>💰 {notice.amountLabel}</span>
            <span>🗓 {notice.dueDateLabel}</span>
          </div>
        </div>
        <div className={styles.scoreCol}>
          <div
            className={`${styles.scoreValue} ${styles[notice.scoreLevel]}`}
          >
            {notice.score}
          </div>
          <div className={styles.scoreLabel}>적합도</div>
        </div>
      </div>
      {selected ? <div className={styles.reason}>{notice.matchReasonShort}</div> : null}
    </button>
  )
}
