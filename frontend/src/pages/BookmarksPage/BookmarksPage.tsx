import { useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { notices } from '../../mock/notices'
import { resultDetailPath } from '../../routes/paths'
import { useBookmarks } from '../../store/BookmarkContext'
import styles from './BookmarksPage.module.css'

export function BookmarksPage() {
  const navigate = useNavigate()
  const { bookmarkedIds } = useBookmarks()
  const bookmarkedNotices = notices.filter((notice) =>
    bookmarkedIds.includes(notice.id),
  )

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>북마크한 공고</div>
        <div className={styles.subheading}>
          북마크 <span>{bookmarkedNotices.length}</span>건
        </div>

        {bookmarkedNotices.length > 0 ? (
          <div className={styles.list}>
            {bookmarkedNotices.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={false}
                onClick={() => navigate(resultDetailPath(notice.id))}
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
