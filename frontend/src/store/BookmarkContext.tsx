import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

// 공고 id가 문자열 슬러그(mock)에서 백엔드 notice.id(number)로 바뀌어 키를 갱신한다.
const STORAGE_KEY = 'kgvm-bookmarked-notice-ids-v2'

interface BookmarkContextValue {
  bookmarkedIds: number[]
  isBookmarked: (noticeId: number) => boolean
  toggleBookmark: (noticeId: number) => void
}

const BookmarkContext = createContext<BookmarkContextValue | null>(null)

function loadBookmarks(): number[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as number[]) : []
  } catch {
    return []
  }
}

export function BookmarkProvider({ children }: { children: ReactNode }) {
  const [bookmarkedIds, setBookmarkedIds] = useState<number[]>(loadBookmarks)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(bookmarkedIds))
  }, [bookmarkedIds])

  function isBookmarked(noticeId: number): boolean {
    return bookmarkedIds.includes(noticeId)
  }

  function toggleBookmark(noticeId: number) {
    setBookmarkedIds((current) =>
      current.includes(noticeId)
        ? current.filter((id) => id !== noticeId)
        : [...current, noticeId],
    )
  }

  return (
    <BookmarkContext.Provider
      value={{ bookmarkedIds, isBookmarked, toggleBookmark }}
    >
      {children}
    </BookmarkContext.Provider>
  )
}

export function useBookmarks(): BookmarkContextValue {
  const context = useContext(BookmarkContext)
  if (!context) {
    throw new Error('useBookmarks must be used within a BookmarkProvider')
  }
  return context
}
