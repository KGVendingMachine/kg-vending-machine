import { useEffect, useState } from 'react'
import { listMatchResults } from '../api/matchLogs'
import { getNoticeDetail } from '../api/notices'
import { toMatchedNotice } from '../types/notice'
import type { MatchedNotice } from '../types/notice'

interface UseMatchedNoticesResult {
  matchedNotices: MatchedNotice[]
  loading: boolean
  error: unknown
}

/**
 * 한 매칭 실행(match_log)의 결과 목록을, 각 공고 상세 정보와 합쳐
 * 화면 표시용 모델로 반환한다. match-logs/{id}/results는 total_score
 * 내림차순으로 이미 정렬돼 있어 그 순서를 그대로 쓴다.
 */
export function useMatchedNotices(matchLogId: number | null): UseMatchedNoticesResult {
  const [matchedNotices, setMatchedNotices] = useState<MatchedNotice[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (matchLogId == null) {
      setMatchedNotices([])
      setError(null)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)

    async function load(id: number) {
      try {
        const results = await listMatchResults(id)
        const details = await Promise.all(
          results.map((result) => getNoticeDetail(result.notice_id).catch(() => null)),
        )
        if (cancelled) return
        const merged = results
          .map((result, index) => {
            const detail = details[index]
            return detail ? toMatchedNotice(detail, result) : null
          })
          .filter((item): item is MatchedNotice => item !== null)
        setMatchedNotices(merged)
      } catch (err) {
        if (!cancelled) setError(err)
      } finally {
        if (!cancelled) setLoading(false)
      }
    }

    load(matchLogId)
    return () => {
      cancelled = true
    }
  }, [matchLogId])

  return { matchedNotices, loading, error }
}
