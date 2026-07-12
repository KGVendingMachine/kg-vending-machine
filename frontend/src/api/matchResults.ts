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

/** result_json.axes 항목 — 축별 점수와 근거. */
interface ResultAxis {
  key?: string
  label?: string
  score?: number
  max?: number
  reason?: string
}

/** result_json.eligibility_checks 항목 — 자격요건 점검. */
interface EligibilityCheck {
  item?: string
  requirement?: string
  value?: string
  pass?: boolean | null
}

interface ResultJson {
  axes?: ResultAxis[]
  eligibility_checks?: EligibilityCheck[]
  caution_points?: string[]
}

/**
 * 매칭 결과 한 건. 점수 만점은 지원자격 30 / 아이템적합 25 / 사업화 20 /
 * 성장성 15 / 가점 10 (합계 100), 축별 근거는 result_json.axes에 있다.
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
  const score = Math.round(result.total_score ?? 0)

  const axes = result.result_json?.axes ?? []
  const scoreBreakdown: ScoreBreakdownItem[] = axes.map((axis) => {
    const max = axis.max ?? 0
    const axisScore = axis.score ?? 0
    return {
      label: axis.label ?? axis.key ?? '',
      weightLabel: `가중 ${max}점`,
      score: axisScore,
      max: max || 1,
      note: axis.reason ?? '',
      status: max > 0 && axisScore / max >= 0.7 ? 'good' : 'warn',
    }
  })

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

  const requirements: RequirementCheck[] = (
    result.result_json?.eligibility_checks ?? []
  ).map((check) => ({
    label: check.item ?? '',
    detail: [check.requirement, check.value].filter(Boolean).join(' · '),
    status: check.pass === true ? 'ok' : 'warn',
  }))

  const summaryPoints: NoticeSummaryPoint[] = []
  if (result.notice.organization_name) {
    summaryPoints.push({ label: '주관기관', detail: result.notice.organization_name })
  }
  if (result.notice.amount_label) {
    summaryPoints.push({ label: '지원한도', detail: result.notice.amount_label })
  }
  summaryPoints.push({ label: '신청기간', detail: dueDateLabel })
  if (result.eligibility_status) {
    summaryPoints.push({ label: '지원가능 여부', detail: result.eligibility_status })
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
