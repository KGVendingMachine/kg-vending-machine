import { createContext, useContext, useEffect, useState } from 'react'
import type { ReactNode } from 'react'

const STORAGE_KEY = 'kgvm-bookmarked-notice-ids'

interface BookmarkContextValue {
  bookmarkedIds: string[]
  isBookmarked: (noticeId: string) => boolean
  toggleBookmark: (noticeId: string) => void
}

const BookmarkContext = createContext<BookmarkContextValue | null>(null)

function loadBookmarks(): string[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    return raw ? (JSON.parse(raw) as string[]) : []
  } catch {
    return []
  }
}

export function BookmarkProvider({ children }: { children: ReactNode }) {
  const [bookmarkedIds, setBookmarkedIds] = useState<string[]>(loadBookmarks)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(bookmarkedIds))
  }, [bookmarkedIds])

  function isBookmarked(noticeId: string): boolean {
    return bookmarkedIds.includes(noticeId)
  }

  function toggleBookmark(noticeId: string) {
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
