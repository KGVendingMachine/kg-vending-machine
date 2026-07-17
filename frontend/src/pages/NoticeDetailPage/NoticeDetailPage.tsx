import { useState } from 'react'
import { Navigate, useLocation, useNavigate, useParams } from 'react-router-dom'
import { MatchDetailView } from '../../components/MatchDetailView/MatchDetailView'
import { getBookmarkSecondaryFiltering } from '../../api/bookmarks'
import { getNoticeDetail } from '../../api/notices'
import type { NoticeDetail } from '../../api/notices'
import type { SecondaryFilteringNoticeLog } from '../../api/matchLogs'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { PATHS } from '../../routes/paths'
import { useBookmarks } from '../../store/BookmarkContext'
import { toMatchedNotice } from '../../types/notice'
import type { MatchedNotice } from '../../types/notice'

/**
 * 매칭 실행(match_log) 컨텍스트 없이 공고 하나를 보여주는 상세 페이지
 * (북마크 목록 등에서 진입). MatchDetailPage와 같은 화면(MatchDetailView)을
 * 재사용한다. 첨부파일·신청기간 등은 북마크 스냅샷에 없어(BookmarkNoticeInfo는
 * 요약 정보만 담는다) 공고 상세는 항상 새로 조회하고, 북마크 클릭으로 들어온
 * 경우에는 목록에서 이미 들고 있던 점수·추천 근거 스냅샷을 그 위에 덧씌운다.
 */
export function NoticeDetailPage() {
  const { noticeId: noticeIdParam } = useParams<{ noticeId: string }>()
  const noticeId = noticeIdParam ? Number(noticeIdParam) : null
  const navigate = useNavigate()
  const location = useLocation()
  const { isBookmarked, toggleBookmark } = useBookmarks()
  const [bookmarkBusy, setBookmarkBusy] = useState(false)

  const stateNotice = (location.state as { notice?: MatchedNotice } | null)?.notice
  const bookmarkId = stateNotice?.bookmarkId ?? null

  const { data: fetchedDetail, loading } = useFetchOnMount<NoticeDetail>(() => {
    if (noticeId == null || Number.isNaN(noticeId)) return null
    return getNoticeDetail(noticeId)
  }, [noticeId])

  // 북마크 자체엔 요건별 판정 근거가 없어(요약 스냅샷만 얼려 저장) 원본
  // 매칭 실행에서 따로 조회한다. 브라우징 북마크(bookmarkId 없음)거나 원본
  // 실행이 지워졌으면 null — MatchDetailView가 그 경우 섹션을 그리지 않는다.
  const { data: secondaryFiltering } = useFetchOnMount<SecondaryFilteringNoticeLog | null>(
    () => {
      if (bookmarkId == null) return null
      return getBookmarkSecondaryFiltering(bookmarkId)
    },
    [bookmarkId],
  )

  if (noticeId == null || Number.isNaN(noticeId)) {
    return <Navigate to={PATHS.BOOKMARKS} replace />
  }

  const notice: MatchedNotice | null = fetchedDetail
    ? {
        ...toMatchedNotice(fetchedDetail),
        // 북마크 목록에 있던 점수·추천 근거 스냅샷을 우선한다(공고 상세
        // API에는 매칭 컨텍스트가 없어 이 필드들이 항상 null이다).
        ...(stateNotice
          ? {
              score: stateNotice.score,
              scoreLevel: stateNotice.scoreLevel,
              matchReasonShort: stateNotice.matchReasonShort,
              strengths: stateNotice.strengths,
              businessPlanTitle: stateNotice.businessPlanTitle,
            }
          : {}),
        ...(secondaryFiltering?.llm_judged
          ? {
              secondaryFilterJudged: true,
              secondaryFilterReasons: secondaryFiltering.reasons ?? [],
              secondaryFilterScore: secondaryFiltering.secondary_filter_score,
            }
          : {}),
      }
    : null

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
