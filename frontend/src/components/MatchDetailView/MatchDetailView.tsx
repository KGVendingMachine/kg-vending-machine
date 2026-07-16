import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { ScoreGauge } from '../ScoreGauge/ScoreGauge'
import { PATHS } from '../../routes/paths'
import type { MatchedNotice } from '../../types/notice'

const APPLICATION_CHECKLIST = [
  '사업자등록증·중소기업 확인서 준비',
  '자부담 자금조달 계획 수립',
  '설비 도입 견적서 확보',
  '온라인 신청서 제출',
]

/** 공고 요약 원문을 문단 목록으로 나눈다. 일부 출처(K-Startup 등)는
 * summary에 <p>·<br> 같은 HTML 태그를 그대로 담아 내려주므로, HTML로
 * 보이면 DOMParser로 파싱해 텍스트만 추출한다(innerHTML로 그대로 렌더링하지
 * 않아 XSS 위험이 없다). 그 외에는 빈 줄 기준으로 문단을 나누고
 * whitespace-pre-line으로 원문 줄바꿈을 보존한다. */
function summaryParagraphs(summary: string): string[] {
  if (/<[a-z][\s\S]*>/i.test(summary)) {
    return htmlSummaryToParagraphs(summary)
  }
  return summary
    .split(/\n\s*\n/)
    .map((paragraph) => paragraph.trim())
    .filter(Boolean)
}

function htmlSummaryToParagraphs(html: string): string[] {
  const body = new DOMParser().parseFromString(html, 'text/html').body
  body.querySelectorAll('br').forEach((br) => br.replaceWith('\n'))

  const blocks = Array.from(body.querySelectorAll('p, li, div'))
  const nodes = blocks.length > 0 ? blocks : [body]

  return nodes
    .map((node) => (node.textContent ?? '').replace(/ /g, ' ').trim())
    .filter(Boolean)
}

function secondaryReasonGroupLabel(
  reason: MatchedNotice['secondaryFilterReasons'][number],
): string {
  const group = reason.group ?? (reason.is_exclusion ? 'exclusion' : 'eligibility')
  switch (group) {
    case 'exclusion':
      return '검토요건'
    case 'criteria_fit':
      return '평가기준'
    case 'bonus_fit':
      return '우대조건'
    default:
      return '자격요건'
  }
}

interface MatchDetailViewProps {
  notice: MatchedNotice
  /** 비교 대상 공고 목록. 매칭 실행 컨텍스트가 없으면(북마크 등) 빈 배열. */
  otherNotices: MatchedNotice[]
  targetLabel: string | null
  bookmarked: boolean
  bookmarkBusy: boolean
  onToggleBookmark: () => void
  onBack: () => void
  backLabel: string
  onCompareClick: (noticeId: number) => void
}

/**
 * 공고 하나에 대한 매칭 상세 분석 화면. 매칭 실행 결과(MatchDetailPage)와
 * 북마크(NoticeDetailPage) 양쪽에서 재사용한다 — 점수 구성·자격요건 대조·
 * 비교 등은 해당 데이터가 없으면(북마크는 breakdown/otherNotices가 없다)
 * 섹션 자체를 그리지 않아 자연스럽게 축약된 화면이 된다.
 */
export function MatchDetailView({
  notice,
  otherNotices,
  targetLabel,
  bookmarked,
  bookmarkBusy,
  onToggleBookmark,
  onBack,
  backLabel,
  onCompareClick,
}: MatchDetailViewProps) {
  const navigate = useNavigate()
  const location = useLocation()

  // 신청 전 체크리스트는 이 화면에서만 쓰는 로컬 진행 표시라 저장하지 않고,
  // 공고를 나갔다 들어오면 초기화된다.
  const [checkedItems, setCheckedItems] = useState<Set<string>>(new Set())

  // group이 "eligibility"인 항목만 프로필 필드로 판정한다 — criteria_fit/
  // bonus_fit/item_fit은 프로필을 채워도 해결 안 되므로 여기서 제외한다.
  const infoInsufficientCount = notice.secondaryFilterReasons.filter(
    (reason) => reason.status === '정보부족' && reason.group === 'eligibility',
  ).length

  function toggleChecklistItem(label: string) {
    setCheckedItems((current) => {
      const next = new Set(current)
      if (next.has(label)) next.delete(label)
      else next.add(label)
      return next
    })
  }

  return (
    <div className="flex flex-1 flex-col">
      <div className="flex h-14 items-center gap-[14px] border-b border-[#eef0f2] bg-white px-6">
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-primary"
          onClick={onBack}
        >
          {backLabel}
        </button>
        <div className="text-[15px] font-extrabold">매칭 상세 분석</div>
        <button
          type="button"
          className={
            bookmarked
              ? 'ml-auto h-8 cursor-pointer rounded border border-[#f5a623] bg-white px-3 text-[13px] font-semibold text-[#f5a623]'
              : 'ml-auto h-8 cursor-pointer rounded border border-border-strong bg-white px-3 text-[13px] font-semibold text-muted'
          }
          aria-label={bookmarked ? '북마크 해제' : '북마크 추가'}
          disabled={bookmarkBusy}
          onClick={onToggleBookmark}
        >
          {bookmarked ? '★ 북마크됨' : '☆ 북마크'}
        </button>
        {notice.sourceUrl ? (
          <a
            className="flex h-8 items-center justify-center rounded border-none bg-primary px-3 text-[13px] font-semibold text-white no-underline"
            href={notice.sourceUrl}
            target="_blank"
            rel="noreferrer"
          >
            원문 공고 ↗
          </a>
        ) : (
          <button
            type="button"
            className="h-8 cursor-not-allowed rounded border border-border bg-surface-subtle px-3 text-[13px] font-semibold text-faint"
            disabled
          >
            원문 공고 ↗
          </button>
        )}
      </div>

      {notice.secondaryFilterExcluded ? (
        <div className="border-b border-[#eef0f2] bg-danger-soft px-10 py-3 text-[13px] leading-[1.6] text-danger">
          ⚠ AI가 공고 원문을 확인한 결과, 제외요건에 해당하는 것으로 판단돼
          적합도 점수가 낮게 반영됐어요. "AI 정밀 판정 근거"의 공고 원문 정밀
          판정을 확인해주세요.
        </div>
      ) : null}

      <div className="flex items-center gap-8 border-b border-[#eef0f2] bg-white px-10 py-7">
        <div className="flex-1">
          <div className="mb-[10px] flex items-center gap-2">
            {notice.category ? (
              <span className="rounded-[3px] bg-primary-soft px-2 py-[3px] text-[11px] font-bold text-primary">
                {notice.category}
              </span>
            ) : null}
            <span className="text-[11px] font-semibold text-danger">
              {notice.deadlineLabel} · {notice.dueDateLabel} 마감
            </span>
          </div>
          <div className="text-2xl font-extrabold tracking-[-0.5px]">{notice.title}</div>
          <div className="mt-[5px] text-sm text-muted">
            {notice.org}
            {notice.amountLabel ? ` · ${notice.amountLabel}` : ''}
          </div>
          {targetLabel ? (
            <div className="mt-1 text-[13px] text-faint">대상 기업 {targetLabel}</div>
          ) : null}
          {notice.businessPlanTitle ? (
            <div className="mt-1 text-[13px] text-faint">
              📄 {notice.businessPlanTitle} 기준 추천
            </div>
          ) : null}
        </div>
        {notice.score != null ? (
          <div className="border-l border-[#eef0f2] pl-8 text-center">
            <ScoreGauge score={notice.score} />
            <div className="mt-1.5 text-xs font-bold text-success">
              적합도{' '}
              {notice.scoreLevel === 'high'
                ? '매우 높음'
                : notice.scoreLevel === 'medium'
                  ? '보통'
                  : '낮음'}
            </div>
            <div className="text-[11px] text-faint">
              {notice.score >= 90 ? '전체 추천 중 상위권' : '전체 추천 결과 기준'}
            </div>
          </div>
        ) : null}
      </div>

      {notice.summary ? (
        <div className="border-b border-[#eef0f2] bg-white px-10 py-6">
          <div className="mb-4 flex items-baseline justify-between">
            <div className="flex items-baseline gap-[10px]">
              <span className="text-[15px] font-extrabold">공고 요약</span>
              <span className="text-[12.5px] text-faint">
                공고 원문에서 핵심 내용만 정리했어요
              </span>
            </div>
          </div>
          <div className="flex flex-col gap-3 rounded-md border border-[#eef0f2] bg-surface-subtle px-5 py-4 text-[13px] leading-[1.7] text-[#374151]">
            {summaryParagraphs(notice.summary).map((paragraph, index) => (
              <p className="whitespace-pre-line" key={index}>
                {paragraph}
              </p>
            ))}
          </div>
        </div>
      ) : null}

      <div className="grid flex-1 grid-cols-2">
        <div className="border-r border-[#eef0f2] bg-white px-8 py-7">
          <div className="mb-1.5 text-[15px] font-extrabold">공고 정보</div>
          <div className="mb-6 flex flex-col gap-2 text-[13px] text-[#374151]">
            <div>
              <b>모집상태</b> — {notice.status ?? '확인 필요'}
            </div>
            <div>
              <b>신청기간</b> —{' '}
              {notice.applicationStartDate && notice.applicationEndDate
                ? `${notice.applicationStartDate} ~ ${notice.applicationEndDate}`
                : notice.applicationEndDate
                  ? `~${notice.applicationEndDate}`
                  : '상시 모집'}
            </div>
          </div>

          <div className="mb-1.5 text-[15px] font-extrabold">첨부파일</div>
          {notice.attachments.length > 0 ? (
            <div className="mb-6 flex flex-col gap-2">
              {notice.attachments.map((attachment, index) => (
                <div
                  key={`${attachment.file_url ?? attachment.file_name ?? index}`}
                  className="flex items-center justify-between rounded border border-border px-3 py-2.5 text-[13px]"
                >
                  <span className="truncate">{attachment.file_name ?? '(파일명 없음)'}</span>
                  {attachment.file_url ? (
                    <a
                      href={attachment.file_url}
                      target="_blank"
                      rel="noreferrer"
                      className="ml-3 flex-shrink-0 text-[12.5px] font-semibold text-primary no-underline"
                    >
                      다운로드
                    </a>
                  ) : null}
                </div>
              ))}
            </div>
          ) : (
            <div className="mb-6 text-[13px] text-faint">첨부파일이 없어요.</div>
          )}

          {notice.scoreBreakdown ? (
            <>
              <div className="mb-1.5 text-[15px] font-extrabold">점수 구성</div>
              <div className="mb-5 text-[12.5px] text-faint">
                항목별 가중치 기준으로 합산된 적합도입니다
              </div>

              {notice.scoreBreakdown.map((item) => (
                <div className="mb-5" key={item.key}>
                  <div className="mb-[7px] flex items-baseline justify-between">
                    <span className="text-[13.5px] font-bold">
                      {item.label}{' '}
                      <span className="text-[11px] font-medium text-faint">
                        {item.weightLabel}
                      </span>
                      {item.source === 'llm' ? (
                        <span className="ml-1 text-[11px] font-medium text-primary">
                          원문 LLM 반영
                        </span>
                      ) : null}
                    </span>
                    <span
                      className={
                        item.score < 50
                          ? 'text-[13.5px] font-extrabold text-warning'
                          : 'text-[13.5px] font-extrabold text-success'
                      }
                    >
                      {item.score} / {item.max}
                    </span>
                  </div>
                  <div className="h-[7px] rounded bg-border">
                    <div
                      className={
                        item.score < 50
                          ? 'h-full rounded bg-warning'
                          : 'h-full rounded bg-success'
                      }
                      style={{ width: `${(item.score / item.max) * 100}%` }}
                    />
                  </div>
                </div>
              ))}

              <div className="my-6 h-px bg-[#eef0f2]" />
            </>
          ) : null}

          {notice.eligibilityStatus || notice.cautions.length > 0 ? (
            <>
              <div className="mb-1.5 text-[15px] font-extrabold">자격요건 대조</div>
              <div className="flex flex-col gap-[11px]">
                {notice.eligibilityStatus ? (
                  <div className="flex items-start gap-[10px] text-[13px]">
                    <span
                      className={
                        notice.eligibilityStatus === 'eligible'
                          ? 'font-extrabold text-success'
                          : 'font-extrabold text-warning'
                      }
                    >
                      {notice.eligibilityStatus === 'eligible' ? '✓' : '!'}
                    </span>
                    <div>
                      <b>자격 상태</b> —{' '}
                      <span className="text-faint">
                        {notice.eligibilityStatus === 'eligible'
                          ? '자격요건을 충족합니다'
                          : notice.eligibilityStatus === 'needs_review'
                            ? '일부 확인이 필요합니다'
                            : '자격 요건 충족 가능성이 낮습니다'}
                      </span>
                    </div>
                  </div>
                ) : null}
                {notice.cautions.map((caution) => (
                  <div className="flex items-start gap-[10px] text-[13px]" key={caution}>
                    <span className="font-extrabold text-warning">!</span>
                    <div>
                      <span className="text-faint">{caution}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>

        <div className="bg-white px-8 py-7">
          {notice.strengths.length > 0 || notice.weaknesses.length > 0 ? (
            <>
              <div className="mb-1.5 text-[15px] font-extrabold">AI 정밀 판정 근거</div>
              <div className="mb-[26px] flex flex-col gap-2 text-[12.5px] leading-[1.6]">
                {notice.strengths.map((reason) => (
                  <div className="border-l-2 border-success pl-2.5" key={reason}>
                    <span className="font-semibold text-success">[강점]</span>{' '}
                    <span className="text-[#374151]">{reason}</span>
                  </div>
                ))}
                {notice.weaknesses.map((reason) => (
                  <div className="border-l-2 border-warning pl-2.5" key={reason}>
                    <span className="font-semibold text-warning">[주의]</span>{' '}
                    <span className="text-[#374151]">{reason}</span>
                  </div>
                ))}
                {notice.strategySuggestion ? (
                  <div className="border-l-2 border-success pl-2.5">
                    <span className="font-semibold text-success">[제안]</span>{' '}
                    <span className="text-[#374151]">{notice.strategySuggestion}</span>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}

          {notice.secondaryFilterJudged && notice.secondaryFilterReasons.length > 0 ? (
            <>
              <div className="mb-1.5 text-[15px] font-extrabold">
                공고 원문 정밀 판정
              </div>
              {infoInsufficientCount > 0 ? (
                <div className="mb-2.5 flex items-center justify-between gap-2.5 rounded bg-primary-soft px-3 py-2 text-[12.5px]">
                  <span>
                    [정보부족] 항목은 기업 프로필(매출액·상시근로자 수·기업규모·
                    사업자유형 등)이 비어 있어 판정 근거가 부족했던 항목이에요.
                    프로필을 채우면 더 정확한 결과를 볼 수 있어요.
                  </span>
                  <button
                    type="button"
                    className="shrink-0 cursor-pointer whitespace-nowrap rounded border-none bg-primary px-2.5 py-1.5 text-[12px] font-semibold text-white"
                    onClick={() =>
                      navigate(PATHS.COMPANY_PROFILE, {
                        state: { from: location.pathname + location.search },
                      })
                    }
                  >
                    프로필 채우기
                  </button>
                </div>
              ) : null}
              <div className="mb-[26px] flex flex-col gap-2 text-[12.5px] leading-[1.6]">
                {notice.secondaryFilterReasons.map((reason, index) => (
                  <div
                    className={
                      reason.status === '미충족'
                        ? 'border-l-2 border-danger pl-2.5'
                        : reason.status === '충족'
                          ? 'border-l-2 border-success pl-2.5'
                          : 'border-l-2 border-faint pl-2.5'
                    }
                    key={index}
                  >
                    <span
                      className={
                        reason.status === '미충족'
                          ? 'font-semibold text-danger'
                          : reason.status === '충족'
                            ? 'font-semibold text-success'
                            : 'font-semibold text-faint'
                      }
                    >
                      [{secondaryReasonGroupLabel(reason)} · {reason.status}]
                    </span>{' '}
                    <span className="text-[#374151]">{reason.criterion}</span>
                    {reason.evidence ? (
                      <span className="text-faint"> — {reason.evidence}</span>
                    ) : null}
                  </div>
                ))}
              </div>
            </>
          ) : null}

          {otherNotices.length > 0 ? (
            <>
              <div className="mb-1.5 text-[15px] font-extrabold">다른 추천 공고와 비교</div>
              <div className="overflow-hidden rounded-md border border-border text-[12.5px]">
                <div className="grid grid-cols-[1fr_56px_64px_60px] bg-surface-subtle font-bold text-muted">
                  <div className="px-3 py-[11px]">공고</div>
                  <div className="px-3 py-[11px]">적합</div>
                  <div className="px-3 py-[11px]">규모</div>
                  <div className="px-3 py-[11px]">마감</div>
                </div>
                <div className="grid grid-cols-[1fr_56px_64px_60px] border-t border-[#eef0f2] bg-[#f5f9ff]">
                  <div className="px-3 py-[11px] font-bold">{notice.title}</div>
                  <div className="px-3 py-[11px] font-bold text-success">
                    {notice.score ?? '-'}
                  </div>
                  <div className="px-3 py-[11px] font-bold">{notice.amountLabel ?? '-'}</div>
                  <div className="px-3 py-[11px] font-bold">{notice.deadlineLabel}</div>
                </div>
                {otherNotices.map((item) => (
                  <div
                    className="grid cursor-pointer grid-cols-[1fr_56px_64px_60px] border-t border-[#eef0f2] hover:bg-surface-subtle"
                    key={item.id}
                    onClick={() => onCompareClick(item.id)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onCompareClick(item.id)
                      }
                    }}
                    role="button"
                    tabIndex={0}
                  >
                    <div className="px-3 py-[11px]">{item.title}</div>
                    <div
                      className={
                        item.scoreLevel === 'medium' || item.scoreLevel === 'low'
                          ? 'px-3 py-[11px] font-extrabold text-warning'
                          : 'px-3 py-[11px] font-extrabold text-success'
                      }
                    >
                      {item.score ?? '-'}
                    </div>
                    <div className="px-3 py-[11px]">{item.amountLabel ?? '-'}</div>
                    <div className="px-3 py-[11px]">{item.deadlineLabel}</div>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          <div className="mb-1.5 text-[15px] font-extrabold" style={{ marginTop: 26 }}>
            신청 전 체크리스트
          </div>
          <div className="flex flex-col gap-[10px]">
            {APPLICATION_CHECKLIST.map((label) => {
              const checked = checkedItems.has(label)
              return (
                <label
                  className="flex cursor-pointer items-center gap-[9px] text-[13px]"
                  key={label}
                >
                  <input
                    type="checkbox"
                    className="sr-only"
                    checked={checked}
                    onChange={() => toggleChecklistItem(label)}
                  />
                  <span
                    className={
                      checked
                        ? 'flex h-4 w-4 flex-shrink-0 items-center justify-center rounded-[3px] border border-primary bg-primary text-[10px] leading-none text-white'
                        : 'h-4 w-4 flex-shrink-0 rounded-[3px] border border-[#c8cdd3]'
                    }
                  >
                    {checked ? '✓' : ''}
                  </span>
                  <span className={checked ? 'text-faint line-through' : ''}>
                    {label}
                  </span>
                </label>
              )
            })}
          </div>

          <div className="mt-6 rounded-md bg-surface-subtle px-4 py-3.5 text-xs leading-[1.6] text-muted">
            본 적합도는 AI 분석 결과이며 실제 선정 여부를 보장하지 않습니다.
            자격요건은 원문 공고를 반드시 확인하세요.
          </div>
        </div>
      </div>
    </div>
  )
}
