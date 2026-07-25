import { useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { MatchDetailView } from '../../components/MatchDetailView/MatchDetailView'
import { getMyCompanyProfile } from '../../api/companyProfile'
import type { CompanyProfile } from '../../api/companyProfile'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import { PATHS, resultDetailPath } from '../../routes/paths'
import { toggleBookmark } from '../../api/bookmarks'

function targetCompanyLabel(profile: CompanyProfile | null): string | null {
  if (!profile) return null
  const parts = [profile.company_size, profile.region_name]
  if (profile.founded_date) {
    parts.push(`${new Date(profile.founded_date).getFullYear()} 설립`)
  }
  const label = parts.filter(Boolean).join(' · ')
  return label || null
}

export function MatchDetailPage() {
  const { noticeId: noticeIdParam } = useParams<{ noticeId: string }>()
  const noticeId = noticeIdParam ? Number(noticeIdParam) : null
  const [searchParams] = useSearchParams()
  const matchLogIdParam = searchParams.get('matchLogId')
  const matchLogId = matchLogIdParam ? Number(matchLogIdParam) : null

  const navigate = useNavigate()
  const { matchedNotices, loading } = useMatchedNotices(matchLogId)
  const { data: profile } = useFetchOnMount<CompanyProfile | null>(
    () => getMyCompanyProfile(),
    [],
  )
  // 별표 상태는 결과에서 온 bookmarkId를 로컬로 들고 토글마다 갱신한다.
  const [bookmarkId, setBookmarkId] = useState<number | null>(null)
  const [bookmarkBusy, setBookmarkBusy] = useState(false)

  useEffect(() => {
    const found = matchedNotices.find((item) => item.id === noticeId)
    setBookmarkId(found?.bookmarkId ?? null)
  }, [matchedNotices, noticeId])

  if (noticeId == null || Number.isNaN(noticeId) || matchLogId == null) {
    return <Navigate to={PATHS.RESULTS} replace />
  }

  const notice = matchedNotices.find((item) => item.id === noticeId)

  if (!notice) {
    if (loading) {
      return (
        <div className="flex items-center gap-8 border-b border-[#eef0f2] bg-white px-10 py-7">
          매칭 상세 정보를 불러오는 중이에요…
        </div>
      )
    }
    return <Navigate to={`${PATHS.RESULTS}?matchLogId=${matchLogId}`} replace />
  }

  const otherNotices = matchedNotices.filter((item) => item.id !== notice.id)
  const bookmarked = bookmarkId != null
  const targetLabel = targetCompanyLabel(profile)

  async function handleToggleBookmark() {
    if (bookmarkBusy || !notice) return
    setBookmarkBusy(true)
    try {
      const nextBookmarkId = await toggleBookmark({
        bookmarkId,
        matchResultId: notice.matchResultId,
        noticeId: notice.id,
      })
      setBookmarkId(nextBookmarkId)
    } catch {
      // 실패하면 상태를 그대로 두어 다시 시도할 수 있게 한다.
    } finally {
      setBookmarkBusy(false)
    }
  }

  return (
    <MatchDetailView
      notice={notice}
      otherNotices={otherNotices}
      targetLabel={targetLabel}
      bookmarked={bookmarked}
      bookmarkBusy={bookmarkBusy}
      onToggleBookmark={handleToggleBookmark}
      onBack={() => navigate(`${PATHS.RESULTS}?matchLogId=${matchLogId}`)}
      backLabel="← 추천 결과"
      onCompareClick={(id) => navigate(resultDetailPath(id, matchLogId))}
    />
  )
}
