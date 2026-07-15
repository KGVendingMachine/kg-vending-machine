import { useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { MatchDetailView } from '../../components/MatchDetailView/MatchDetailView'
import { getNoticeDetail } from '../../api/notices'
import type { NoticeDetail } from '../../api/notices'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { PATHS } from '../../routes/paths'
import { useBookmarks } from '../../store/BookmarkContext'
import { toMatchedNotice } from '../../types/notice'
import type { MatchedNotice } from '../../types/notice'

/**
 * 매칭 실행(match_log) 컨텍스트 없이 공고 하나를 보여주는 상세 페이지
 * (북마크 목록 등에서 진입). MatchDetailPage와 같은 화면(MatchDetailView)을
 * 재사용한다 — 북마크 클릭 시에는 목록에서 이미 들고 있던 점수·추천 근거
 * 스냅샷을 router state로 그대로 넘겨받아 재조회 없이 보여주고, state 없이
 * 직접 URL로 들어오면 공고 정보만 새로 조회해 보여준다(점수 관련 섹션은
 * 데이터가 없어 자연히 숨겨진다).
 */
export function NoticeDetailPage() {
  const { noticeId: noticeIdParam } = useParams<{ noticeId: string }>()
  const noticeId = noticeIdParam ? Number(noticeIdParam) : null
  const navigate = useNavigate()
  const location = useLocation()
  const { isBookmarked, toggleBookmark } = useBookmarks()
  const [bookmarkBusy, setBookmarkBusy] = useState(false)

  const stateNotice = (location.state as { notice?: MatchedNotice } | null)?.notice

  const { data: fetchedDetail, loading } = useFetchOnMount<NoticeDetail>(() => {
    if (stateNotice) return null
    if (noticeId == null || Number.isNaN(noticeId)) return null
    return getNoticeDetail(noticeId)
  }, [noticeId, stateNotice])

  if (noticeId == null || Number.isNaN(noticeId)) {
    return <Navigate to={PATHS.BOOKMARKS} replace />
  }

  const notice = stateNotice ?? (fetchedDetail ? toMatchedNotice(fetchedDetail) : null)

  if (!notice) {
    if (loading) {
      return (
        <div className="flex items-center gap-8 border-b border-[#eef0f2] bg-white px-10 py-7">
          공고 정보를 불러오는 중이에요…
        </div>
      )
    }
    return (
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
    )
  }

  const bookmarked = isBookmarked(notice.id)

  async function handleToggleBookmark() {
    if (bookmarkBusy || !notice) return
    setBookmarkBusy(true)
    try {
      await toggleBookmark(notice.id)
    } finally {
      setBookmarkBusy(false)
    }
  }

  return (
    <MatchDetailView
      notice={notice}
      otherNotices={[]}
      targetLabel={null}
      bookmarked={bookmarked}
      bookmarkBusy={bookmarkBusy}
      onToggleBookmark={handleToggleBookmark}
      onBack={() => navigate(PATHS.BOOKMARKS)}
      backLabel="← 북마크"
      onCompareClick={() => {}}
    />
  )
}
