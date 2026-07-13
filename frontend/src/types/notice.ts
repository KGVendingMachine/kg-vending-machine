import type { MatchResult } from '../api/matchLogs'
import type { NoticeDetail } from '../api/notices'
import { formatDeadline } from '../utils/date'

export type ScoreLevel = 'high' | 'medium' | 'low'

/** matching_service가 산출하는 5개 점수 구성 요소 (합산 가중치: 30/25/25/15/5%). */
export interface ScoreBreakdownItem {
  key: 'eligibility' | 'item_fit' | 'business_fit' | 'growth' | 'bonus'
  label: string
  weightLabel: string
  score: number
  max: number
}

const SCORE_BREAKDOWN_META: Record<
  ScoreBreakdownItem['key'],
  { label: string; weightLabel: string }
> = {
  eligibility: { label: '자격 적합도', weightLabel: '가중 30%' },
  item_fit: { label: '아이템 적합도', weightLabel: '가중 25%' },
  business_fit: { label: '사업 정합성', weightLabel: '가중 25%' },
  growth: { label: '성장성', weightLabel: '가중 15%' },
  bonus: { label: '가점 요소', weightLabel: '가중 5%' },
}

/**
 * 공고 상세(NoticeDetail) + (있다면) 한 매칭 실행의 결과(MatchResult)를 합쳐
 * 화면이 실제로 쓰는 필드만 추린 표시용 모델. match 결과가 없는 컨텍스트
 * (예: 북마크 목록)에서는 score 관련 필드가 모두 null이 된다.
 */
export interface MatchedNotice {
  id: number
  category: string | null
  /** 기관명 컬럼이 API에 없어, 대신 공고 출처(기업마당/K-Startup)를 표시한다. */
  org: string
  title: string
  amountLabel: string | null
  deadlineLabel: string
  dueDateLabel: string
  isUrgent: boolean
  sourceUrl: string | null
  applyUrl: string | null
  summary: string | null
  score: number | null
  scoreLevel: ScoreLevel | null
  /** 추천 이유 중 첫 문장 (카드 목록에서 짧게 보여줄 때) */
  matchReasonShort: string | null
  /** summary_reason을 문장 단위로 쪼갠 것 */
  strengths: string[]
  /** weakness를 문장 단위로 쪼갠 것 */
  weaknesses: string[]
  /** result_json.cautions */
  cautions: string[]
  scoreBreakdown: ScoreBreakdownItem[] | null
  eligibilityStatus: string | null
  strategySuggestion: string | null
}

function splitSentences(value: string | null): string[] {
  if (!value) return []
  return value
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
}

function toScoreLevel(recommendationLevel: string | null): ScoreLevel | null {
  switch (recommendationLevel) {
    case 'strong':
    case 'recommended':
      return 'high'
    case 'normal':
      return 'medium'
    case 'low':
      return 'low'
    default:
      return null
  }
}

function toScoreBreakdown(result: MatchResult | undefined): ScoreBreakdownItem[] | null {
  if (!result) return null
  const scores: Record<ScoreBreakdownItem['key'], number | null> = {
    eligibility: result.eligibility_score,
    item_fit: result.item_fit_score,
    business_fit: result.business_fit_score,
    growth: result.growth_score,
    bonus: result.bonus_score,
  }
  return (Object.keys(SCORE_BREAKDOWN_META) as ScoreBreakdownItem['key'][]).map((key) => ({
    key,
    ...SCORE_BREAKDOWN_META[key],
    score: scores[key] ?? 0,
    max: 100,
  }))
}

export function toMatchedNotice(notice: NoticeDetail, result?: MatchResult): MatchedNotice {
  const deadline = formatDeadline(notice.application_end_date)
  const strengths = splitSentences(result?.summary_reason ?? null)

  return {
    id: notice.id,
    category: notice.category,
    org: notice.source,
    title: notice.title ?? '(제목 없음)',
    amountLabel: notice.amount_label,
    deadlineLabel: deadline.label,
    dueDateLabel: deadline.dueDateLabel,
    isUrgent: deadline.isUrgent,
    sourceUrl: notice.source_url,
    applyUrl: notice.apply_url,
    summary: notice.summary_text,
    score: result?.total_score ?? null,
    scoreLevel: toScoreLevel(result?.recommendation_level ?? null),
    matchReasonShort: strengths[0] ?? null,
    strengths,
    weaknesses: splitSentences(result?.weakness ?? null),
    cautions: result?.result_json?.cautions ?? [],
    scoreBreakdown: toScoreBreakdown(result),
    eligibilityStatus: result?.eligibility_status ?? null,
    strategySuggestion: result?.strategy_suggestion ?? null,
  }
}
