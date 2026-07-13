import { useEffect, useMemo, useState } from 'react'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { listBookmarks, deleteBookmark } from '../../api/bookmarks'
import type { Bookmark } from '../../api/bookmarks'
import { bookmarkToMatchedNotice } from '../../types/notice'
import styles from './BookmarksPage.module.css'

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
  const [bookmarks, setBookmarks] = useState<Bookmark[]>([])
  const [loading, setLoading] = useState(true)
  const [busyIds, setBusyIds] = useState<Set<number>>(new Set())

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listBookmarks()
      .then((data) => {
        if (!cancelled) setBookmarks(data)
      })
      .catch(() => {
        if (!cancelled) setBookmarks([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

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
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>북마크한 공고</div>
        <div className={styles.subheading}>
          북마크 <span>{bookmarks.length}</span>건
        </div>

        {loading ? (
          <div className={styles.empty}>불러오는 중이에요…</div>
        ) : bookmarks.length > 0 ? (
          groups.map((group) => (
            <section key={group.key} className={styles.group}>
              <div className={styles.groupHeader}>
                <span className={styles.groupTitle}>{group.title}</span>
                <span className={styles.groupCount}>{group.items.length}건</span>
                {group.isStale ? (
                  <span
                    className={styles.staleBadge}
                    title="이 추천은 예전 사업계획서 기준이에요. 지금 계획서로 다시 매칭해 보세요."
                  >
                    예전 사업계획서 기준
                  </span>
                ) : null}
              </div>
              <div className={styles.list}>
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
                  />
                ))}
              </div>
            </section>
          ))
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
