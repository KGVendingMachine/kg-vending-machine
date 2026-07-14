import type { CSSProperties, ReactNode } from 'react'
import type { MatchLog } from '../../api/matchLogs'
import { formatMatchLogDate } from '../../api/matchLogs'
import type { CompanyProfile } from '../../api/companyProfile'
import type { MatchedNotice } from '../../types/notice'

/**
 * 결과 목록에서 "상위 3건 비교 리포트"로 다운로드(브라우저 인쇄 → PDF 저장)되는
 * 인쇄 전용 레이아웃. 화면에는 보이지 않고(@media print 에서만 노출), 사장님이
 * "그래서 뭐부터 지원하지?"를 한 장으로 판단하도록 상위 공고를 나란히 비교한다.
 * 별도 데이터 없이 화면이 이미 쓰는 MatchedNotice 필드만 재사용한다.
 */

function eligibilityLabel(status: string | null): { text: string; tone: string } {
  switch (status) {
    case 'eligible':
      return { text: '충족 ✓', tone: 'text-success' }
    case 'needs_review':
      return { text: '확인 필요 !', tone: 'text-warning' }
    case null:
      return { text: '-', tone: 'text-faint' }
    default:
      return { text: '미충족', tone: 'text-danger' }
  }
}

function scoreTone(level: MatchedNotice['scoreLevel']): string {
  return level === 'medium' || level === 'low' ? 'text-warning' : 'text-success'
}

/** 리포트 생성일(오늘). 인쇄물의 "작성일"로만 쓰인다. */
function todayLabel(): string {
  return new Intl.DateTimeFormat('ko-KR', {
    year: 'numeric',
    month: 'long',
    day: 'numeric',
  }).format(new Date())
}

function targetCompanyLabel(profile: CompanyProfile | null): string | null {
  if (!profile) return null
  const parts = [profile.company_size, profile.region_name].filter(Boolean)
  return parts.length ? parts.join(' · ') : null
}

interface ComparisonReportProps {
  notices: MatchedNotice[]
  matchLog: MatchLog | null
  profile: CompanyProfile | null
}

export function ComparisonReport({
  notices,
  matchLog,
  profile,
}: ComparisonReportProps) {
  const cols = notices.slice(0, 3)
  if (cols.length === 0) return null

  const top = cols[0]
  const planTitle = matchLog?.business_plan_title ?? '사업계획서'
  const target = targetCompanyLabel(profile)

  const rankHeaders = ['1위', '2위', '3위']
  const gridStyle = {
    gridTemplateColumns: `92px repeat(${cols.length}, minmax(0, 1fr))`,
  }

  return (
    <div className="print-only px-10 py-8 text-[12px] leading-[1.5] text-ink">
      {/* 표지 머리말 — 회사/사업계획서 · 작성일 */}
      <div className="mb-5 border-b-2 border-ink pb-3">
        <div className="flex items-baseline justify-between">
          <div className="text-[18px] font-extrabold tracking-[-0.3px]">
            맞춤 공고 비교 리포트
          </div>
          <div className="text-[11px] text-muted">{todayLabel()}</div>
        </div>
        <div className="mt-1.5 text-[13px] font-bold">{planTitle}</div>
        <div className="mt-0.5 text-[11px] text-muted">
          {matchLog ? `${formatMatchLogDate(matchLog.created_at)} 매칭 결과` : '매칭 결과'}
          {target ? ` · 대상 기업 ${target}` : ''}
        </div>
      </div>

      {/* 한 줄 결론 */}
      <div className="mb-5 rounded-md bg-primary-soft px-4 py-3 text-[12.5px]">
        <b>결론</b> — 상위 {cols.length}건 중{' '}
        <b className="text-primary">{top.title}</b>부터 검토를 권장합니다
        {top.score != null ? ` (적합도 ${top.score}` : ''}
        {top.score != null ? `, ${top.deadlineLabel} 마감).` : '.'}
      </div>

      {/* 비교표 */}
      <div className="overflow-hidden rounded-md border border-border">
        {/* 헤더 */}
        <div className="grid bg-surface-subtle font-bold" style={gridStyle}>
          <div className="px-3 py-2" />
          {cols.map((notice, index) => (
            <div
              className="border-l border-border px-3 py-2 text-[11px] text-muted"
              key={notice.id}
            >
              {rankHeaders[index]}
            </div>
          ))}
        </div>

        {/* 공고명 */}
        <Row label="공고명" grid={gridStyle} cols={cols}>
          {(notice) => (
            <div className="font-bold leading-[1.4]">{notice.title}</div>
          )}
        </Row>

        {/* 적합도 */}
        <Row label="적합도" grid={gridStyle} cols={cols}>
          {(notice) => (
            <span className={`text-[15px] font-extrabold ${scoreTone(notice.scoreLevel)}`}>
              {notice.score ?? '-'}
            </span>
          )}
        </Row>

        {/* 분야 */}
        <Row label="분야" grid={gridStyle} cols={cols}>
          {(notice) => notice.category ?? '-'}
        </Row>

        {/* 지원규모 */}
        <Row label="지원규모" grid={gridStyle} cols={cols}>
          {(notice) => notice.amountLabel ?? '-'}
        </Row>

        {/* 마감 */}
        <Row label="마감" grid={gridStyle} cols={cols}>
          {(notice) => (
            <span className={notice.isUrgent ? 'font-bold text-danger' : ''}>
              {notice.deadlineLabel} · {notice.dueDateLabel}
            </span>
          )}
        </Row>

        {/* 자격 */}
        <Row label="자격" grid={gridStyle} cols={cols}>
          {(notice) => {
            const el = eligibilityLabel(notice.eligibilityStatus)
            return <span className={`font-bold ${el.tone}`}>{el.text}</span>
          }}
        </Row>

        {/* 핵심 강점 */}
        <Row label="핵심 강점" grid={gridStyle} cols={cols}>
          {(notice) => (
            <span className="leading-[1.4] text-[#374151]">
              {notice.strengths[0] ?? '-'}
            </span>
          )}
        </Row>

        {/* 주의 */}
        <Row label="주의" grid={gridStyle} cols={cols} last>
          {(notice) => (
            <span className="leading-[1.4] text-[#374151]">
              {notice.weaknesses[0] ?? notice.cautions[0] ?? '-'}
            </span>
          )}
        </Row>
      </div>

      {/* 원문 링크 */}
      <div className="mt-4 text-[10.5px] leading-[1.7] text-muted">
        {cols.map((notice, index) =>
          notice.sourceUrl ? (
            <div key={notice.id}>
              {rankHeaders[index]} 원문 공고: {notice.sourceUrl}
            </div>
          ) : null,
        )}
      </div>

      <div className="mt-4 rounded-md bg-surface-subtle px-4 py-3 text-[10.5px] leading-[1.6] text-muted">
        본 적합도는 AI 분석 결과이며 실제 선정 여부를 보장하지 않습니다. 자격요건은
        원문 공고를 반드시 확인하세요.
      </div>
    </div>
  )
}

/** 비교표의 한 행. 왼쪽 라벨 + 공고 수만큼의 값 셀. */
function Row({
  label,
  grid,
  cols,
  last,
  children,
}: {
  label: string
  grid: CSSProperties
  cols: MatchedNotice[]
  last?: boolean
  children: (notice: MatchedNotice) => ReactNode
}) {
  return (
    <div
      className={last ? 'grid' : 'grid border-b border-[#eef0f2]'}
      style={grid}
    >
      <div className="bg-surface-subtle px-3 py-2 text-[11px] font-bold text-muted">
        {label}
      </div>
      {cols.map((notice) => (
        <div className="border-l border-border px-3 py-2" key={notice.id}>
          {children(notice)}
        </div>
      ))}
    </div>
  )
}
