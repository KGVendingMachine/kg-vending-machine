import { useEffect, useMemo, useState } from 'react'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { listBookmarks, deleteBookmark } from '../../api/bookmarks'
import type { Bookmark } from '../../api/bookmarks'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { bookmarkToMatchedNotice } from '../../types/notice'

interface BookmarkGroup {
  key: string
  title: string
  isStale: boolean
  isBrowse: boolean
  items: Bookmark[]
}

/**
 * 북마크를 사업계획서(=추천 맥락) 단위로 묶는다. 현재 계획서 기준(최신) 그룹을
 * 맨 위에, 예전 계획서(stale) 그룹을 그 아래, 추천 밖에서 직접 담은 공고를
 * 맨 마지막에 둔다. 같은 계획서 그룹은 is_stale 값이 모두 같다.
 */
function groupBookmarks(bookmarks: Bookmark[]): BookmarkGroup[] {
  const groups = new Map<string, BookmarkGroup>()
  for (const bookmark of bookmarks) {
    const isBrowse = bookmark.business_plan_id == null
    const key = isBrowse ? 'browse' : String(bookmark.business_plan_id)
    let group = groups.get(key)
    if (!group) {
      group = {
        key,
        title: isBrowse
          ? '직접 담은 공고'
          : (bookmark.business_plan_title ?? '삭제된 사업계획서'),
        isStale: bookmark.is_stale,
        isBrowse,
        items: [],
      }
      groups.set(key, group)
    }
    group.items.push(bookmark)
  }

  // 현재 계획서(최신) → 예전 계획서 → 직접 담기 순.
  return [...groups.values()].sort((a, b) => {
    const rank = (g: BookmarkGroup) => (g.isBrowse ? 2 : g.isStale ? 1 : 0)
    return rank(a) - rank(b)
  })
}

export function BookmarksPage() {
  const { data, loading } = useFetchOnMount<Bookmark[]>(() => listBookmarks(), [])
  // 삭제(handleRemove)로 목록을 바로 갱신하기 위해 조회 결과를 로컬 상태로 관리한다.
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    setBookmarks(data ?? [])
  }, [data])

  const groups = useMemo(() => groupBookmarks(bookmarks), [bookmarks])

  async function handleRemove(bookmark: Bookmark) {
    if (busyIds.has(bookmark.id)) return
    setBusyIds((current) => new Set(current).add(bookmark.id))
    try {
      await deleteBookmark(bookmark.id)
      setBookmarks((current) => current.filter((item) => item.id !== bookmark.id))
    } catch {
      // 실패하면 목록을 그대로 두어 다시 시도할 수 있게 한다.
    } finally {
      setBusyIds((current) => {
        const next = new Set(current)
        next.delete(bookmark.id)
        return next
      })
    }
  }

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
        ) : bookmarks.length > 0 ? (
          groups.map((group) => (
            <section key={group.key} className="mt-7">
              <div className="mb-3 flex items-center gap-2">
                <span className="text-[15px] font-bold">{group.title}</span>
                <span className="text-[13px] text-muted">{group.items.length}건</span>
                {group.isStale ? (
                  <span
                    className="rounded-full bg-[#fef3c7] px-2 py-0.5 text-xs font-semibold text-[#b45309]"
                    title="이 추천은 예전 사업계획서 기준이에요. 지금 계획서로 다시 매칭해 보세요."
                  >
                    예전 사업계획서 기준
                  </span>
                ) : null}
              </div>
              <div className="flex flex-col">
                {group.items.map((bookmark) => (
                  <NoticeCard
                    key={bookmark.id}
                    notice={bookmarkToMatchedNotice(bookmark)}
                    selected={false}
                    onClick={() => {
                      if (bookmark.notice.source_url) {
                        window.open(
                          bookmark.notice.source_url,
                          '_blank',
                          'noreferrer',
                        )
                      }
                    }}
                    onToggleBookmark={() => handleRemove(bookmark)}
                    bookmarkBusy={busyIds.has(bookmark.id)}
                    showReason
                  />
                ))}
              </div>
            </section>
          ))
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
