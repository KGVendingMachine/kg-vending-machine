import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { listBookmarks, deleteBookmark } from '../../api/bookmarks'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { noticeDetailPath } from '../../routes/paths'
import { bookmarkToMatchedNotice } from '../../types/notice'

export function BookmarksPage() {
  const navigate = useNavigate()
  const { data, loading } = useFetchOnMount(() => listBookmarks(), [])
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set())
  const [removedIds, setRemovedIds] = useState<Set<number>>(new Set())

  const notices = (data ?? [])
    .filter((bookmark) => !removedIds.has(bookmark.id))
    .map(bookmarkToMatchedNotice)

  async function handleRemoveBookmark(bookmarkId: number) {
    if (busyIds.has(bookmarkId)) return
    setBusyIds((current) => new Set(current).add(bookmarkId))
    try {
      await deleteBookmark(bookmarkId)
      setRemovedIds((current) => new Set(current).add(bookmarkId))
    } catch {
      // 실패하면 상태를 그대로 두어 다시 시도할 수 있게 한다.
    } finally {
      setBusyIds((current) => {
        const next = new Set(current)
        next.delete(bookmarkId)
        return next
      })
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto w-full max-w-[760px] px-10 py-7">
        <div className="text-[22px] font-extrabold tracking-[-0.5px]">
          북마크한 공고
        </div>
        <div className="mt-1.5 mb-6 text-[13px] text-muted">
          북마크 <span className="font-bold text-primary">{notices.length}</span>건
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
                onClick={() =>
                  navigate(noticeDetailPath(notice.id), { state: { notice } })
                }
                onToggleBookmark={
                  notice.bookmarkId != null
                    ? () => handleRemoveBookmark(notice.bookmarkId!)
                    : undefined
                }
                bookmarkBusy={notice.bookmarkId != null && busyIds.has(notice.bookmarkId)}
                showReason
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
