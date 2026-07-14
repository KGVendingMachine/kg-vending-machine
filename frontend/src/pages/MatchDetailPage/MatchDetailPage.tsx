import { useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { SecondaryFilteringLogPanel } from '../../components/SecondaryFilteringLogPanel/SecondaryFilteringLogPanel'
import { getMyCompanyProfile } from '../../api/companyProfile'
import type { CompanyProfile } from '../../api/companyProfile'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import { PATHS } from '../../routes/paths'
import { toggleBookmark } from '../../api/bookmarks'

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
    .map((node) => (node.textContent ?? '').replace(/ /g, ' ').trim())
    .filter(Boolean)
}

function targetCompanyLabel(profile: CompanyProfile | null): string | null {
  if (!profile) return null
  const parts = [profile.company_size, profile.region_name]
  if (profile.founded_date) {
    parts.push(`${new Date(profile.founded_date).getFullYear()} 설립`)
  }
  const label = parts.filter(Boolean).join(' · ')
  return label || null
}

export function MatchDetailPage() {
  const { noticeId: noticeIdParam } = useParams<{ noticeId: string }>()
  const noticeId = noticeIdParam ? Number(noticeIdParam) : null
  const [searchParams] = useSearchParams()
  const matchLogIdParam = searchParams.get('matchLogId')
  const matchLogId = matchLogIdParam ? Number(matchLogIdParam) : null

  const navigate = useNavigate()
  const { matchedNotices, loading } = useMatchedNotices(matchLogId)
  const { data: profile } = useFetchOnMount<CompanyProfile | null>(
    () => getMyCompanyProfile(),
    [],
  )
  // 별표 상태는 결과에서 온 bookmarkId를 로컬로 들고 토글마다 갱신한다.
  const [bookmarkId, setBookmarkId] = useState<number | null>(null)
  const [bookmarkBusy, setBookmarkBusy] = useState(false)

  useEffect(() => {
    const found = matchedNotices.find((item) => item.id === noticeId)
    setBookmarkId(found?.bookmarkId ?? null)
  }, [matchedNotices, noticeId])

  if (noticeId == null || Number.isNaN(noticeId) || matchLogId == null) {
    return <Navigate to={PATHS.RESULTS} replace />
  }

  const notice = matchedNotices.find((item) => item.id === noticeId)

  if (!notice) {
    if (loading) {
      return (
        <div className="flex flex-1 flex-col">
          <AppHeader />
          <div className="flex items-center gap-8 border-b border-[#eef0f2] bg-white px-10 py-7">
            매칭 상세 정보를 불러오는 중이에요…
          </div>
        </div>
      )
    }
    return <Navigate to={`${PATHS.RESULTS}?matchLogId=${matchLogId}`} replace />
  }

  const otherNotices = matchedNotices.filter((item) => item.id !== notice.id)
  const bookmarked = bookmarkId != null
  const targetLabel = targetCompanyLabel(profile)

  async function handleToggleBookmark() {
    if (bookmarkBusy || !notice) return
    setBookmarkBusy(true)
    try {
      const nextBookmarkId = await toggleBookmark({
        bookmarkId,
        matchResultId: notice.matchResultId,
        noticeId: notice.id,
      })
      setBookmarkId(nextBookmarkId)
    } catch {
      // 실패하면 상태를 그대로 두어 다시 시도할 수 있게 한다.
    } finally {
      setBookmarkBusy(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <AppHeader />

      <div className="flex h-14 items-center gap-[14px] border-b border-[#eef0f2] bg-white px-6">
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-primary"
          onClick={() => navigate(`${PATHS.RESULTS}?matchLogId=${matchLogId}`)}
        >
          ← 추천 결과
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
          onClick={handleToggleBookmark}
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

      <SecondaryFilteringLogPanel matchLogId={matchLogId} />

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
                      [{reason.status}]
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
                    className="grid grid-cols-[1fr_56px_64px_60px] border-t border-[#eef0f2]"
                    key={item.id}
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
            {APPLICATION_CHECKLIST.map((label) => (
              <label className="flex items-center gap-[9px] text-[13px]" key={label}>
                <span className="h-4 w-4 flex-shrink-0 rounded-[3px] border border-[#c8cdd3]" />
                {label}
              </label>
            ))}
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
