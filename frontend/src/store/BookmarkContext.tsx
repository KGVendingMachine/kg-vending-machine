import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'
import { listBookmarks, toggleBookmark as toggleBookmarkApi } from '../api/bookmarks'

interface BookmarkContextValue {
  /** 북마크된 공고 id 목록. */
  bookmarkedIds: number[]
  isBookmarked: (noticeId: number) => boolean
  /** 매칭 컨텍스트 없이 공고 id 기준으로 북마크를 토글한다(NoticeDetailPage 등). */
  toggleBookmark: (noticeId: number) => Promise<void>
}

const BookmarkContext = createContext<BookmarkContextValue | null>(null)

export function BookmarkProvider({ children }: { children: ReactNode }) {
  // 공고 id -> 북마크 id. 해제 요청에 북마크 id가 필요해 값까지 들고 있는다.
  const [bookmarksByNoticeId, setBookmarksByNoticeId] = useState<Map<number, number>>(
    new Map(),
  )

  useEffect(() => {
    listBookmarks()
      .then((bookmarks) => {
        setBookmarksByNoticeId(new Map(bookmarks.map((b) => [b.notice.id, b.id])))
      })
      .catch(() => {
        // 로그인 전 등 조회 실패는 무시 — 북마크 없음으로 취급.
      })
  }, [])

  const isBookmarked = useCallback(
    (noticeId: number) => bookmarksByNoticeId.has(noticeId),
    [bookmarksByNoticeId],
  )

  const toggleBookmark = useCallback(
    async (noticeId: number) => {
      const bookmarkId = bookmarksByNoticeId.get(noticeId) ?? null
      const nextBookmarkId = await toggleBookmarkApi({
        bookmarkId,
        matchResultId: null,
        noticeId,
      })
      setBookmarksByNoticeId((current) => {
        const next = new Map(current)
        if (nextBookmarkId == null) {
          next.delete(noticeId)
        } else {
          next.set(noticeId, nextBookmarkId)
        }
        return next
      })
    },
    [bookmarksByNoticeId],
  )

  return (
    <BookmarkContext.Provider
      value={{
        bookmarkedIds: [...bookmarksByNoticeId.keys()],
        isBookmarked,
        toggleBookmark,
      }}
    >
      {children}
    </BookmarkContext.Provider>
  )
}

export function useBookmarks(): BookmarkContextValue {
  const ctx = useContext(BookmarkContext)
  if (!ctx) throw new Error('useBookmarks must be used within BookmarkProvider')
  return ctx
}
