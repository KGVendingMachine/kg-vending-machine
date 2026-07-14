import { useEffect, useState } from 'react'
import { getSecondaryFilteringLog, listMatchResults } from '../api/matchLogs'
import { getNoticeDetail } from '../api/notices'
import { toMatchedNotice } from '../types/notice'
import type { MatchedNotice } from '../types/notice'

interface UseMatchedNoticesResult {
  matchedNotices: MatchedNotice[]
  loading: boolean
  error: unknown
  /** 별표 토글 후 해당 공고의 bookmarkId를 갱신한다(해제면 null). */
  applyBookmark: (noticeId: number, bookmarkId: number | null) => void
}

/**
 * 한 매칭 실행(match_log)의 결과 목록을, 각 공고 상세 정보와 합쳐
 * 화면 표시용 모델로 반환한다. match-logs/{id}/results는 total_score
 * 내림차순으로 이미 정렬돼 있어 그 순서를 그대로 쓴다.
 *
 * matchedNotices를 자체 상태로 들고 조회 결과를 직접 반영한다(useFetchOnMount +
 * 별도 로컬 상태로 감싸면 loading이 false로 바뀐 렌더와 matchedNotices가 채워지는
 * 렌더 사이에 한 틱의 간극이 생겨, 그 사이에 MatchDetailPage가 "로딩 끝 + 아직
 * 못 찾음"으로 오판해 결과 페이지로 튕겨나가는 문제가 있었다).
 */
export function useMatchedNotices(matchLogId: number | null): UseMatchedNoticesResult {
  const [matchedNotices, setMatchedNotices] = useState<MatchedNotice[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    if (matchLogId == null) {
      setMatchedNotices([])
      setError(null)
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)
    load(matchLogId).then(
      (result) => {
        if (cancelled) return
        setMatchedNotices(result)
        setLoading(false)
      },
      (err) => {
        if (cancelled) return
        setError(err)
        setLoading(false)
      },
    )
    return () => {
      cancelled = true
    }
  }, [matchLogId])

  function applyBookmark(noticeId: number, bookmarkId: number | null) {
    setMatchedNotices((current) =>
      current.map((notice) =>
        notice.id === noticeId ? { ...notice, bookmarkId } : notice,
      ),
    )
  }

  return { matchedNotices, loading, error, applyBookmark }
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
