import { useEffect, useMemo, useState } from 'react'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { listBookmarks, deleteBookmark } from '../../api/bookmarks'
import type { Bookmark } from '../../api/bookmarks'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { noticeDetailPath } from '../../routes/paths'
import { toMatchedNotice } from '../../types/notice'
import type { MatchedNotice } from '../../types/notice'
import { useBookmarks } from '../../store/BookmarkContext'

export function BookmarksPage() {
  const navigate = useNavigate()
  const { bookmarkedIds } = useBookmarks()
  const { data, loading } = useFetchOnMount<MatchedNotice[]>(async () => {
    const results = await Promise.all(
      bookmarkedIds.map((id) =>
        getNoticeDetail(id)
          .then((detail) => toMatchedNotice(detail))
          .catch(() => null),
      ),
    )
    return results.filter((item): item is MatchedNotice => item !== null)
  }, [bookmarkedIds])
  const notices = data ?? []

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />
      <div className="mx-auto w-full max-w-[760px] px-10 py-7">
        <div className="text-[22px] font-extrabold tracking-[-0.5px]">
          북마크한 공고
        </div>
        <div className="mt-1.5 mb-6 text-[13px] text-muted">
          북마크 <span className="font-bold text-primary">{bookmarks.length}</span>건
        </div>

        {loading ? (
          <div className="rounded-lg border border-dashed border-border-strong px-6 py-12 text-center text-[13.5px] leading-[1.6] text-faint">
            불러오는 중이에요…
          </div>
        ) : notices.length > 0 ? (
          <div className="flex flex-col">
            {notices.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={false}
                onClick={() => navigate(noticeDetailPath(notice.id))}
              />
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border-strong px-6 py-12 text-center text-[13.5px] leading-[1.6] text-faint">
            아직 북마크한 공고가 없어요. 추천 결과에서 ☆ 아이콘을 눌러
            저장해보세요.
          </div>
        )}
      </div>
    </div>
  )
}
