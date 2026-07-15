import type {
  MatchResult,
  SecondaryFilteringNoticeLog,
  SecondaryFilteringReasonLog,
} from '../api/matchLogs'
import type { Bookmark } from '../api/bookmarks'
import type { NoticeAttachmentInfo, NoticeDetail } from '../api/notices'
import { formatDeadline } from '../utils/date'

export type ScoreLevel = 'high' | 'medium' | 'low'

/** matching_service가 산출하는 6개 점수 구성 요소 (합산 가중치: 25/20/20/10/5/20%).
 * secondary_filter는 2차 필터링(공고 PDF·사업계획서 원문 임베딩 유사도) 점수 —
 * 근거가 없으면(첨부파일 없음 등) 중립값 50으로 채워진다(toScoreBreakdown 참고). */
export interface ScoreBreakdownItem {
  key: 'eligibility' | 'item_fit' | 'business_fit' | 'growth' | 'bonus' | 'secondary_filter'
  label: string
  weightLabel: string
  score: number
  max: number
}

const SCORE_BREAKDOWN_META: Record<
  ScoreBreakdownItem['key'],
  { label: string; weightLabel: string }
> = {
  eligibility: { label: '자격 적합도', weightLabel: '가중 25%' },
  item_fit: { label: '아이템 적합도', weightLabel: '가중 20%' },
  business_fit: { label: '사업 정합성', weightLabel: '가중 20%' },
  growth: { label: '성장성', weightLabel: '가중 10%' },
  bonus: { label: '가점 요소', weightLabel: '가중 5%' },
  secondary_filter: { label: '공고 원문 유사도', weightLabel: '가중 20%' },
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
  /** 2차 필터링 유사도 상위 후보로 뽑혀 LLM이 자격/제외 요건을 실제로
   * 판정했는지. false면 secondaryFilterReasons는 비어 있고, scoreBreakdown의
   * secondary_filter는 임베딩 유사도 값(또는 근거 없음 중립값 50)이다. */
  secondaryFilterJudged: boolean
  /** LLM 판정으로 제외요건 확정(secondary_filter_score가 낮게 캡됨)이 있었는지. */
  secondaryFilterExcluded: boolean
  /** secondaryFilterJudged가 true일 때만 값이 있다 — 요건 문장별 판정 근거. */
  secondaryFilterReasons: SecondaryFilteringReasonLog[]
  /** 별표 토글 시 담을 대상 match_result id. 매칭 컨텍스트가 없으면(북마크 목록) null. */
  matchResultId: number | null
  /** 담겨 있으면 그 북마크 id(해제 시 사용), 아니면 null. */
  bookmarkId: number | null
  /** 모집상태 원문(예: "접수중"). 북마크 스냅샷에는 있고, 매칭 결과 컨텍스트에는 없다. */
  status: string | null
  /** 신청 시작일. 공고 상세(NoticeDetail)에만 있고 북마크 스냅샷에는 없다. */
  applicationStartDate: string | null
  /** 신청 종료일 원문(YYYY-MM-DD). deadlineLabel 계산에 쓰인 것과 같은 값. */
  applicationEndDate: string | null
  /** 첨부파일. 공고 상세(NoticeDetail)에만 있고 북마크 스냅샷에는 없다. */
  attachments: NoticeAttachmentInfo[]
  /** 이 추천이 어떤 사업계획서 기준인지. 매칭 실행 컨텍스트(결과 페이지 등)는
   * 화면 상단 배너에 이미 표시되므로 null — 북마크 목록처럼 여러 실행이
   * 섞여 보이는 화면에서만 채운다. 브라우징으로 담은 북마크(사업계획서
   * 맥락 없음)도 null. */
  businessPlanTitle: string | null
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

function toScoreBreakdown(
  result: MatchResult | undefined,
  judged: boolean,
): ScoreBreakdownItem[] | null {
  if (!result) return null
  const scores: Record<ScoreBreakdownItem['key'], number | null> = {
    eligibility: result.eligibility_score,
    item_fit: result.item_fit_score,
    business_fit: result.business_fit_score,
    growth: result.growth_score,
    bonus: result.bonus_score,
    // secondary_filter는 top-level 컬럼이 없어 result_json에서만 읽는다
    // (api/matchLogs.ts의 MatchResultJson 주석 참고).
    secondary_filter: result.result_json?.score_breakdown.secondary_filter ?? null,
  }
  return (Object.keys(SCORE_BREAKDOWN_META) as ScoreBreakdownItem['key'][]).map((key) => ({
    key,
    ...SCORE_BREAKDOWN_META[key],
    // secondary_filter만 유사도 검색 상위 후보로 뽑혀 LLM이 실제 판정한
    // 경우와 임베딩 유사도만 쓴 경우를 라벨로 구분한다 — 나머지 항목은 항상
    // 규칙 기반 점수라 고정 라벨을 그대로 쓴다.
    label:
      key === 'secondary_filter' && judged
        ? 'AI 정밀 판정(공고 원문)'
        : SCORE_BREAKDOWN_META[key].label,
    score: scores[key] ?? 0,
    max: 100,
  }))
}

export function toMatchedNotice(
  notice: NoticeDetail,
  result?: MatchResult,
  secondaryFiltering?: SecondaryFilteringNoticeLog,
): MatchedNotice {
  const deadline = formatDeadline(notice.application_end_date)
  const strengths = splitSentences(result?.summary_reason ?? null)
  const judged = secondaryFiltering?.llm_judged ?? false

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
    scoreBreakdown: toScoreBreakdown(result, judged),
    eligibilityStatus: result?.eligibility_status ?? null,
    strategySuggestion: result?.strategy_suggestion ?? null,
    secondaryFilterJudged: judged,
    secondaryFilterExcluded: secondaryFiltering?.excluded ?? false,
    secondaryFilterReasons: judged ? (secondaryFiltering?.reasons ?? []) : [],
    matchResultId: result?.id ?? null,
    bookmarkId: result?.bookmark_id ?? null,
    status: notice.status,
    applicationStartDate: notice.application_start_date,
    applicationEndDate: notice.application_end_date,
    attachments: notice.attachments,
    businessPlanTitle: null,
  }
}

/**
 * 북마크 목록의 한 건을 카드 표시용 모델로 바꾼다. 점수·추천 이유는 담을
 * 당시(frozen) 스냅샷(bookmark.recommendation)에서 온다. 북마크 응답에는
 * match_result_id 가 없어 matchResultId 는 null(목록에서 토글은 해제만 필요).
 */
export function bookmarkToMatchedNotice(bookmark: Bookmark): MatchedNotice {
  const { notice, recommendation } = bookmark
  const deadline = formatDeadline(notice.application_end_date)
  const strengths = splitSentences(recommendation?.summary_reason ?? null)

  return {
    id: notice.id,
    category: notice.category_name,
    org: notice.organization_name ?? '',
    title: notice.title ?? '(제목 없음)',
    amountLabel: notice.amount_label,
    deadlineLabel: deadline.label,
    dueDateLabel: deadline.dueDateLabel,
    isUrgent: deadline.isUrgent,
    sourceUrl: notice.source_url,
    applyUrl: notice.apply_url,
    summary: null,
    score: recommendation?.total_score ?? null,
    scoreLevel: toScoreLevel(recommendation?.recommendation_level ?? null),
    matchReasonShort: strengths[0] ?? null,
    strengths,
    weaknesses: [],
    cautions: [],
    scoreBreakdown: null,
    eligibilityStatus: null,
    strategySuggestion: null,
    secondaryFilterJudged: false,
    secondaryFilterExcluded: false,
    secondaryFilterReasons: [],
    matchResultId: null,
    bookmarkId: bookmark.id,
    status: notice.status,
    applicationStartDate: null,
    applicationEndDate: notice.application_end_date,
    attachments: [],
    businessPlanTitle: bookmark.business_plan_title,
  }
}
