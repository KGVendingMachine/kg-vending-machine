import { apiFetch } from './client'
import type {
  Notice,
  ReasonItem,
  RequirementCheck,
  ScoreBreakdownItem,
  NoticeSummaryPoint,
} from '../types/notice'

/** GET /match-logs/{id}/results 항목의 공고 요약. */
export interface MatchResultNoticeInfo {
  id: number
  title: string | null
  organization_name: string | null
  category_name: string | null
  status: string | null
  application_end_date: string | null
  amount_label: string | null
  source_url: string | null
  apply_url: string | null
}

/** result_json — matching_service가 저장하는 평가 원본(축별 점수는 0~100). */
interface ResultJson {
  notice_quality?: { status?: string; missing_fields?: string[] }
  score_breakdown?: Record<string, number>
  matched_keywords?: string[]
  cautions?: string[]
}

/**
 * 매칭 결과 한 건. 축별 점수(eligibility_score 등)는 각각 0~100이고,
 * total_score는 지원자격 30% / 아이템적합 25% / 사업화 25% / 성장성 15% /
 * 가점 5% 가중 합산이다 (backend matching_service 참고).
 */
export interface MatchResult {
  id: number
  notice: MatchResultNoticeInfo
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
  result_json: ResultJson | null
}

/** 한 매칭 실행의 결과를 적합도 내림차순으로 조회한다. */
export function getMatchResults(matchLogId: number): Promise<MatchResult[]> {
  return apiFetch<MatchResult[]>(`/api/match-logs/${matchLogId}/results`)
}

type AxisScoreKey =
  | 'eligibility_score'
  | 'item_fit_score'
  | 'business_fit_score'
  | 'growth_score'
  | 'bonus_score'

/** 축별 가중치 — backend matching_service의 total_score 합산 비율과 동일해야 한다. */
const AXIS_WEIGHTS: { key: AxisScoreKey; label: string; weight: number }[] = [
  { key: 'eligibility_score', label: '지원자격', weight: 0.3 },
  { key: 'item_fit_score', label: '아이템 적합', weight: 0.25 },
  { key: 'business_fit_score', label: '사업화 계획', weight: 0.25 },
  { key: 'growth_score', label: '성장 가능성', weight: 0.15 },
  { key: 'bonus_score', label: '가점', weight: 0.05 },
]

/** eligibility_status(영문 코드) → 화면 표시용 한글 라벨. */
const ELIGIBILITY_STATUS_LABELS: Record<string, string> = {
  eligible: '지원가능',
  needs_review: '확인필요',
  likely_ineligible: '지원 어려움',
}

function deadlineInfo(endDate: string | null): {
  deadlineLabel: string
  dueDateLabel: string
  isUrgent: boolean
} {
  if (!endDate) {
    return { deadlineLabel: '상시', dueDateLabel: '상시 모집', isUrgent: false }
  }
  const dueDateLabel = `~${endDate.replaceAll('-', '.')}`
  const end = new Date(`${endDate}T23:59:59`)
  if (Number.isNaN(end.getTime())) {
    return { deadlineLabel: '-', dueDateLabel, isUrgent: false }
  }
  const days = Math.ceil((end.getTime() - Date.now()) / 86_400_000)
  if (days < 0) return { deadlineLabel: '마감', dueDateLabel, isUrgent: false }
  if (days === 0) return { deadlineLabel: 'D-DAY', dueDateLabel, isUrgent: true }
  return { deadlineLabel: `D-${days}`, dueDateLabel, isUrgent: days <= 7 }
}

/**
 * API 매칭 결과를 화면 공용 Notice 형태로 변환한다.
 *
 * NoticeCard·결과 상세 패널 등 기존 UI가 전부 Notice 타입 기준이라, 페이지를
 * 갈아엎는 대신 어댑터로 흡수한다. 목데이터가 완전히 걷히면 UI 타입을 API
 * 응답 기준으로 정리하는 걸 검토한다.
 */
export function matchResultToNotice(result: MatchResult): Notice {
  const { deadlineLabel, dueDateLabel, isUrgent } = deadlineInfo(
    result.notice.application_end_date,
  )
  const score = Math.round(Number(result.total_score ?? 0) || 0)

  // 축별 0~100 점수를 total_score와 같은 가중 배분(30/25/25/15/5점)으로 환산해
  // 표시한다 — 합계가 total_score와 일치해 사용자에게 설명 가능한 분해가 된다.
  const scoreBreakdown: ScoreBreakdownItem[] = AXIS_WEIGHTS.map(
    ({ key, label, weight }) => {
      // Decimal 컬럼이 문자열로 직렬화될 수 있어 Number로 강제 변환한다.
      const axisScore = Number(result[key] ?? 0) || 0
      const max = weight * 100
      return {
        label,
        weightLabel: `가중 ${max}점`,
        score: Math.round(axisScore * weight * 10) / 10,
        max,
        note: '',
        status: axisScore >= 70 ? 'good' : 'warn',
      }
    },
  )

  const reasons: ReasonItem[] = []
  if (result.summary_reason) {
    reasons.push({ tone: 'good', label: '강점', detail: result.summary_reason })
  }
  if (result.weakness) {
    reasons.push({ tone: 'warn', label: '주의', detail: result.weakness })
  }
  if (result.strategy_suggestion) {
    reasons.push({
      tone: 'good',
      label: '전략',
      detail: result.strategy_suggestion,
    })
  }

  // 항목별 자격 체크는 아직 백엔드가 안 주므로, 주의사항(cautions)을
  // 확인 필요 항목으로 노출한다.
  const requirements: RequirementCheck[] = (
    result.result_json?.cautions ?? []
  ).map((caution) => ({
    label: caution,
    detail: '',
    status: 'warn',
  }))

  const matchedKeywords = result.result_json?.matched_keywords ?? []
  if (matchedKeywords.length > 0) {
    reasons.push({
      tone: 'good',
      label: '일치 키워드',
      detail: matchedKeywords.slice(0, 8).join(', '),
    })
  }

  const summaryPoints: NoticeSummaryPoint[] = []
  if (result.notice.organization_name) {
    summaryPoints.push({ label: '주관기관', detail: result.notice.organization_name })
  }
  if (result.notice.amount_label) {
    summaryPoints.push({ label: '지원한도', detail: result.notice.amount_label })
  }
  summaryPoints.push({ label: '신청기간', detail: dueDateLabel })
  if (result.eligibility_status) {
    summaryPoints.push({
      label: '지원가능 여부',
      detail:
        ELIGIBILITY_STATUS_LABELS[result.eligibility_status] ??
        result.eligibility_status,
    })
  }

  return {
    id: String(result.notice.id),
    category: result.notice.category_name ?? '기타',
    deadlineLabel,
    isUrgent,
    title: result.notice.title ?? '(제목 없음)',
    org: result.notice.organization_name ?? '',
    amountLabel: result.notice.amount_label ?? '금액 정보 없음',
    dueDateLabel,
    score,
    scoreLevel: score >= 80 ? 'high' : 'medium',
    matchReasonShort: result.summary_reason ? `근거: ${result.summary_reason}` : '',
    summary: result.summary_reason ?? '',
    summaryPoints,
    scoreBreakdown,
    reasons,
    requirements,
    sourceUrl: result.notice.source_url ?? result.notice.apply_url ?? undefined,
  }
}
