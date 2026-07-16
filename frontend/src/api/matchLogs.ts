import { ApiError, apiFetch } from './client'
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

/**
 * 진행 중 매칭 복구용 최소 응답(backend/app/schemas/match_log.py
 * ActiveMatchLogResponse). 폴링을 이어붙이는 데 필요한 id·run_status만 담는다.
 */
export interface ActiveMatchLog {
  id: number
  run_status: JobStatus
}

/**
 * 이 사업계획서로 지금 진행 중(processing)인 매칭 로그를 조회한다. 없으면 null.
 * 새로고침·재접속으로 화면 state가 초기화돼도 진행 중이던 매칭 폴링을 이어붙여
 * 복구하는 데 쓴다(서버는 유저당 진행 중 매칭을 1건으로 제한하며, 다른 계획서가
 * 도는 중이면 이 계획서 기준으로는 null을 준다).
 */
export function getActiveMatchLog(
  businessPlanId: number,
): Promise<ActiveMatchLog | null> {
  return apiFetch<ActiveMatchLog | null>(
    `/api/match-logs/active?business_plan_id=${businessPlanId}`,
  )
}

/** backend/app/schemas/match_log.py MatchLogDeleteResponse */
export interface MatchLogDeleteResponse {
  match_log_id: number
  deleted: boolean
  message: string
}

/** DELETE /match-logs/{id} — 매칭 기록(및 그 결과)을 삭제한다. */
export function deleteMatchLog(matchLogId: number): Promise<MatchLogDeleteResponse> {
  return apiFetch<MatchLogDeleteResponse>(`/api/match-logs/${matchLogId}`, {
    method: 'DELETE',
  })
}

/**
 * matching_service._score_notice가 채우는 result_json 중 프론트가 쓰는 부분.
 * score_breakdown의 eligibility/item_fit/business_fit/growth/bonus는
 * eligibility_score 등 top-level 컬럼과 같은 값의 중복이라 화면에서는
 * top-level 필드를 쓴다. secondary_filter(2차 필터링 — 공고 PDF·사업계획서
 * 원문 임베딩 유사도)는 top-level 컬럼이 없어 여기서만 읽는다
 * (docs/matching-pipeline.md 4단계, backend/app/services/secondary_filtering_service.py).
 */
export interface MatchResultJson {
  notice_quality: { status: string; missing_fields: string[] }
  score_breakdown: {
    eligibility: number
    item_fit: number
    business_fit: number
    growth: number
    bonus: number
    secondary_filter: number
  }
  score_sources?: Partial<Record<string, string>>
  /** 2차 필터링 근거(임베딩 유사도)가 실제로 있었는지. false면 secondary_filter는
   * 중립값(50)으로 채워진 것 — 공고에 첨부파일이 없거나 임베딩이 실패한 경우. */
  secondary_filter_available: boolean
  matched_keywords: string[]
  cautions: string[]
}

/** backend/app/schemas/match_log.py MatchResultResponse */
export interface MatchResult {
  id: number
  match_log_id: number
  notice_id: number
  notice_title: string | null
  total_score: number | null
  eligibility_score: number | null
  item_fit_score: number | null
  business_fit_score: number | null
  growth_score: number | null
  bonus_score: number | null
  eligibility_status: string | null
  recommendation_level: string | null
  summary_reason: string | null
  weakness: string | null
  strategy_suggestion: string | null
  result_json: MatchResultJson | null
  /** 이 공고가 (현재 유저·이 실행의 사업계획서 기준) 담겨 있는지. 별표 채움 표시용. */
  is_bookmarked: boolean
  /** 담겨 있으면 그 북마크 id(별표 해제 DELETE 에 사용). 아니면 null. */
  bookmark_id: number | null
  created_at: string
}

/** 한 매칭 실행(match_log)의 결과를 총점 내림차순으로 조회한다. */
export function listMatchResults(matchLogId: number): Promise<MatchResult[]> {
  return apiFetch<MatchResult[]>(`/api/match-logs/${matchLogId}/results`)
}

/** 2차 필터링 LLM 판정에서 요건 문장 하나가 어떻게 판정됐는지. */
export interface SecondaryFilteringReasonLog {
  criterion: string
  /** "충족" / "미충족" / "정보부족" 중 하나. */
  status: string
  evidence: string | null
  group?: string | null
  /** true면 제외요건("~에 해당하지 않음"으로 재구성된 문장) 판정이다. */
  is_exclusion?: boolean
}

/** 2차 필터링에서 공고 하나가 어떻게 처리됐는지 (GET .../secondary-filtering의 notices[]). */
export interface SecondaryFilteringNoticeLog {
  notice_id: number
  title: string | null
  embedded: boolean
  /** 임베딩 유사도 점수(35~100) — LLM 판정 대상을 고르는 데만 쓰인 값이라
   * secondary_filter_score와 다를 수 있다. 이 필드가 없던 구버전 로그는 undefined. */
  similarity_score?: number | null
  /** 유사도 상위 K건에 들어 LLM이 실제로 판정을 수행했는지. */
  llm_judged?: boolean
  /** 제외요건이 확정돼 secondary_filter_score가 낮은 값으로 캡됐는지. */
  excluded?: boolean
  /** llm_judged가 true일 때만 값이 있다 — 요건 문장별 판정 근거. */
  reasons?: SecondaryFilteringReasonLog[]
  /** total_score에 실제로 반영된 최종값. */
  secondary_filter_score: number | null
  /** embedded가 false일 때만 값이 있다. "no_text" 또는 "embedding_failed". */
  skip_reason: string | null
}

/** backend/app/schemas/match_log.py SecondaryFilteringLogResponse
 * (GET /api/match-logs/{id}/secondary-filtering) — 2차 필터링(공고 PDF·
 * 사업계획서 원문 임베딩 유사도) 실행 로그. 이 기능 도입 이전에 만들어진
 * match_log는 로그가 없어 404가 온다(getSecondaryFilteringLog 참고). */
export interface SecondaryFilteringLog {
  match_log_id: number
  plan_embedded: boolean
  plan_skip_reason: string | null
  candidate_count: number
  embedded_count: number
  /** 유사도 상위 K건 중 실제로 LLM 판정까지 수행된 공고 수. 이 필드가 없던
   * 구버전 로그는 undefined. */
  judged_count?: number
  skipped_count: number
  score_stats: { min: number; max: number; avg: number } | null
  notices: SecondaryFilteringNoticeLog[]
}

/**
 * 한 매칭 실행의 2차 필터링 로그를 조회한다. 이 기능 이전에 실행된
 * match_log는 로그가 없어 404가 오는데, 호출부가 "로그 없음"을 구분할 수
 * 있도록 null로 정규화해 반환한다(에러를 던지지 않음).
 */
export async function getSecondaryFilteringLog(
  matchLogId: number,
): Promise<SecondaryFilteringLog | null> {
  try {
    return await apiFetch<SecondaryFilteringLog>(
      `/api/match-logs/${matchLogId}/secondary-filtering`,
    )
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
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
