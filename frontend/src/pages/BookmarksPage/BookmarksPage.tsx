import { useEffect, useState } from 'react'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { getNoticeDetail } from '../../api/notices'
import { toMatchedNotice } from '../../types/notice'
import type { MatchedNotice } from '../../types/notice'
import { useBookmarks } from '../../store/BookmarkContext'
import styles from './BookmarksPage.module.css'

export function BookmarksPage() {
  const { bookmarkedIds } = useBookmarks()
  const [notices, setNotices] = useState<MatchedNotice[]>([])
  const [loading, setLoading] = useState(false)

  useEffect(() => {
    if (bookmarkedIds.length === 0) {
      setNotices([])
      return
    }
    let cancelled = false
    setLoading(true)
    Promise.all(
      bookmarkedIds.map((id) =>
        getNoticeDetail(id)
          .then((detail) => toMatchedNotice(detail))
          .catch(() => null),
      ),
    )
      .then((results) => {
        if (!cancelled) {
          setNotices(results.filter((item): item is MatchedNotice => item !== null))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [bookmarkedIds])

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>북마크한 공고</div>
        <div className={styles.subheading}>
          북마크 <span>{notices.length}</span>건
        </div>

        {loading ? (
          <div className={styles.empty}>불러오는 중이에요…</div>
        ) : notices.length > 0 ? (
          <div className={styles.list}>
            {notices.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={false}
                onClick={() => {
                  if (notice.sourceUrl) {
                    window.open(notice.sourceUrl, '_blank', 'noreferrer')
                  }
                }}
              />
            ))}
          </div>
        ) : (
          <div className={styles.empty}>
            아직 북마크한 공고가 없어요. 추천 결과에서 ☆ 아이콘을 눌러
            저장해보세요.
          </div>
        )}
      </div>
    </div>
  )
}
