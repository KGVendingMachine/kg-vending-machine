import { getSecondaryFilteringLog, listMatchResults } from '../api/matchLogs'
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
  // 2차 필터링 로그(LLM 판정 근거)는 이 기능 도입 이전 실행에는 없을 수
  // 있어(getSecondaryFilteringLog가 null 반환) 부가 정보로만 취급한다 —
  // 못 가져와도 매칭 결과 자체(점수·공고 상세)는 그대로 보여준다.
  const [results, secondaryLog] = await Promise.all([
    listMatchResults(matchLogId),
    getSecondaryFilteringLog(matchLogId).catch(() => null),
  ])
  const secondaryByNoticeId = new Map(
    (secondaryLog?.notices ?? []).map((notice) => [notice.notice_id, notice]),
  )
  const details = await Promise.all(
    results.map((result) => getNoticeDetail(result.notice_id).catch(() => null)),
  )
  return results
    .map((result, index) => {
      const detail = details[index]
      if (!detail) return null
      return toMatchedNotice(detail, result, secondaryByNoticeId.get(result.notice_id))
    })
    .filter((item): item is MatchedNotice => item !== null)
}
