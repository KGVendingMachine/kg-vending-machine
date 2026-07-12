import { apiFetch } from './client'
import type { JobStatus } from './businessPlanAnalysis'

/**
 * 매칭 실행 로그 한 건. created_at/completed_at은 서버가 UTC(타임존 표기 없음)로
 * 내려주므로 표시할 때 formatMatchLogDate를 거친다.
 */
export interface MatchLog {
  id: number
  business_plan_id: number | null
  business_plan_title: string | null
  run_status: JobStatus | null
  created_at: string
  completed_at: string | null
}

/**
 * 공고 매칭을 실행한다(매칭 로그 생성). 스코어링이 아직 미구현이라 서버가
 * 로그를 만들고 즉시 completed로 돌려준다 — 추후 로직이 붙으면 processing
 * 상태를 폴링하는 구조로 확장한다.
 */
export function createMatchLog(businessPlanId: number): Promise<MatchLog> {
  return apiFetch<MatchLog>('/api/match-logs', {
    method: 'POST',
    body: JSON.stringify({ business_plan_id: businessPlanId }),
  })
}

/**
 * 내 매칭 실행 기록을 최신순으로 조회한다. "더보기" 페이지네이션용으로
 * limit/offset을 받고, 응답 개수가 limit보다 적으면 더 없는 것이다.
 */
export function listMatchLogs(
  limit: number,
  offset: number,
): Promise<MatchLog[]> {
  return apiFetch<MatchLog[]>(`/api/match-logs?limit=${limit}&offset=${offset}`)
}

/** 매칭 로그 단건 조회 (결과 페이지가 어떤 실행인지 표시할 때). */
export function getMatchLog(matchLogId: number): Promise<MatchLog> {
  return apiFetch<MatchLog>(`/api/match-logs/${matchLogId}`)
}

/** 서버의 UTC naive 일시 문자열을 사용자 로컬 시간 표기로 바꾼다. */
export function formatMatchLogDate(value: string): string {
  // 타임존 표기가 없으면 UTC로 해석되도록 Z를 붙인다.
  const iso = /[zZ]|[+-]\d{2}:\d{2}$/.test(value) ? value : `${value}Z`
  const date = new Date(iso)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
