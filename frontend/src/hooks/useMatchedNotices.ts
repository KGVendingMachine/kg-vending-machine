import { listMatchResults } from '../api/matchLogs'
import { getNoticeDetail } from '../api/notices'
import { toMatchedNotice } from '../types/notice'
import type { MatchedNotice } from '../types/notice'
import { useFetchOnMount } from './useFetchOnMount'

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
  const { data, loading, error } = useFetchOnMount<MatchedNotice[]>(() => {
    if (matchLogId == null) return null
    return load(matchLogId)
  }, [matchLogId])

  return { matchedNotices: data ?? [], loading, error }
}

async function load(matchLogId: number): Promise<MatchedNotice[]> {
  const results = await listMatchResults(matchLogId)
  const details = await Promise.all(
    results.map((result) => getNoticeDetail(result.notice_id).catch(() => null)),
  )
  return results
    .map((result, index) => {
      const detail = details[index]
      return detail ? toMatchedNotice(detail, result) : null
    })
    .filter((item): item is MatchedNotice => item !== null)
}
