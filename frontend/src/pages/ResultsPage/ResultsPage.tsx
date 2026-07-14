import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { ComparisonReport } from '../../components/ComparisonReport/ComparisonReport'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { getMatchLog, formatMatchLogDate } from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { toggleBookmark } from '../../api/bookmarks'
import { getMyCompanyProfile } from '../../api/companyProfile'
import type { CompanyProfile } from '../../api/companyProfile'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import type { MatchedNotice } from '../../types/notice'
import { PATHS } from '../../routes/paths'
import { DEADLINE_FILTERS } from '../../constants/resultsFilters'
import {
  reportFileTitle,
  printWithFilename,
  PRINT_DESTINATION_HINT,
} from '../../utils/reportFilename'

export function ResultsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 어느 매칭 실행(match_log)의 결과인지. 분석 페이지에서 새 매칭을 돌리거나
  // 매칭 기록을 클릭하면 ?matchLogId= 쿼리로 넘어온다.
  const matchLogIdParam = searchParams.get('matchLogId')
  const matchLogId = matchLogIdParam ? Number(matchLogIdParam) : null
  const validLogId =
    matchLogId != null && !Number.isNaN(matchLogId) ? matchLogId : null

  const [selectedId, setSelectedId] = useState<number | null>(null)
  // 공고 상세와 매칭 점수를 합친 표시용 모델(MatchedNotice)을 가져온다 —
  // MatchDetailPage/BookmarksPage와 동일한 훅으로, 목록/상세 화면 전체가
  // 같은 모델을 쓰게 통일한다.
  const { matchedNotices, loading, error, applyBookmark } =
    useMatchedNotices(validLogId)
  const [bookmarkBusyIds, setBookmarkBusyIds] = useState<Set<number>>(new Set())

  async function handleToggleBookmark(notice: MatchedNotice) {
    if (bookmarkBusyIds.has(notice.id)) return
    setBookmarkBusyIds((current) => new Set(current).add(notice.id))
    try {
      const nextBookmarkId = await toggleBookmark({
        bookmarkId: notice.bookmarkId,
        matchResultId: notice.matchResultId,
        noticeId: notice.id,
      })
      applyBookmark(notice.id, nextBookmarkId)
    } catch {
      // 실패하면 상태를 그대로 두어 사용자가 다시 시도할 수 있게 한다.
    } finally {
      setBookmarkBusyIds((current) => {
        const next = new Set(current)
        next.delete(notice.id)
        return next
      })
    }
  }

  // 실행 정보 배너는 부가 정보라 실패해도 결과 화면은 그대로 보여준다.
  const { data: matchLog } = useFetchOnMount<MatchLog>(
    () => (validLogId == null ? null : getMatchLog(validLogId)),
    [validLogId],
  )
  // 비교 리포트 머리말의 "대상 기업" 표기에만 쓰인다. 실패해도 리포트는
  // 사업계획서 제목만으로 그대로 생성된다.
  const { data: profile } = useFetchOnMount<CompanyProfile | null>(
    () => getMyCompanyProfile(),
    [],
  )

  // 상위 3건 비교 리포트를 브라우저 인쇄(→ "PDF로 저장")로 내려받는다.
  // 인쇄 시에는 화면(.no-print)이 숨겨지고 리포트(.print-only)만 출력된다.
  const handleDownloadReport = () => {
    printWithFilename(reportFileTitle('추천공고_비교리포트'))
  }

  // 결과가 (다시) 로드되면 첫 번째 공고를 기본 선택한다.
  useEffect(() => {
    setSelectedId(matchedNotices[0]?.id ?? null)
  }, [matchedNotices])

  const list = matchedNotices
  const selected = list.find((notice) => notice.id === selectedId)

  const fieldFilters = useMemo(() => {
    const counts = new Map<string, number>()
    for (const notice of list) {
      const label = notice.category ?? '기타'
      counts.set(label, (counts.get(label) ?? 0) + 1)
    }
    return [...counts.entries()].map(([label, count], index) => ({
      label,
      count,
      checked: index === 0,
    }))
  }, [list])

  // matchLogId 없이 진입(직접 URL 입력 등)하면 보여줄 결과가 없다.
  if (validLogId == null) {
    return (
      <div className="flex flex-1 flex-col min-h-0">
        <AppHeader />
        <div className="flex flex-1 flex-col items-center justify-center gap-2.5 px-6 py-[60px] text-center">
          <div className="text-lg font-extrabold">표시할 매칭 결과가 없어요</div>
          <div className="text-sm leading-[1.6] text-muted">
            사업계획서를 분석하고 공고 매칭을 실행하면 결과를 볼 수 있어요.
            <br />
            분석 페이지의 매칭 기록에서 지난 결과를 다시 열 수도 있어요.
          </div>
          <button
            type="button"
            className="mt-3 h-11 cursor-pointer rounded border-none bg-primary px-6 text-sm font-bold text-white"
            onClick={() => navigate(PATHS.UPLOAD)}
          >
            사업계획서 분석하러 가기 →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col min-h-0">
      <div className="no-print flex flex-1 flex-col min-h-0">
      <AppHeader />
      {matchLog ? (
        <div className="flex items-center gap-2.5 border-b border-[#eef0f2] bg-primary-soft px-6 py-2.5 text-[13px]">
          <span className="font-extrabold">
            {matchLog.business_plan_title ?? '사업계획서'}
          </span>
          <span className="text-muted">
            {formatMatchLogDate(matchLog.created_at)} 매칭 결과
          </span>
        </div>
      ) : null}

      {loading ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2.5 px-6 py-[60px] text-center">
          <div className="text-sm leading-[1.6] text-muted">매칭 결과를 불러오는 중…</div>
        </div>
      ) : list.length === 0 ? (
        <div className="flex flex-1 flex-col items-center justify-center gap-2.5 px-6 py-[60px] text-center">
          <div className="text-lg font-extrabold">
            {error ? '결과를 불러오지 못했어요' : '이 매칭에는 저장된 결과가 없어요'}
          </div>
          <div className="text-sm leading-[1.6] text-muted">
            {error
              ? '매칭 결과를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.'
              : '공고 데이터가 없던 시점의 실행이거나, 결과 생성에 실패한 실행이에요.'}
          </div>
        </div>
      ) : (
        <div className="grid flex-1 min-h-0 grid-cols-[230px_1fr_380px]">
          <aside className="overflow-auto border-r border-[#eef0f2] px-5 py-6">
            <div className="mb-[18px] text-[13px] font-extrabold">필터</div>

            <div className="mb-2.5 text-xs font-bold text-muted">분야</div>
            <div className="mb-[22px] flex flex-col gap-[9px] text-[13px]">
              {fieldFilters.map((filter) => (
                <label className="flex items-center gap-2" key={filter.label}>
                  <span
                    className={
                      filter.checked
                        ? 'h-[15px] w-[15px] shrink-0 rounded-[3px] border border-primary bg-primary'
                        : 'h-[15px] w-[15px] shrink-0 rounded-[3px] border border-[#c8cdd3]'
                    }
                  />
                  {filter.label} ({filter.count})
                </label>
              ))}
            </div>

            <div className="mb-2.5 text-xs font-bold text-muted">마감</div>
            <div className="mb-[22px] flex flex-col gap-[9px] text-[13px]">
              {DEADLINE_FILTERS.map((label) => (
                <label className="flex items-center gap-2" key={label}>
                  <span className="h-[15px] w-[15px] shrink-0 rounded-[3px] border border-[#c8cdd3]" />
                  {label}
                </label>
              ))}
            </div>
          </aside>

          <div className="overflow-auto bg-surface-subtle px-6 py-[22px]">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-[15px] font-bold">
                맞춤 공고 <span className="text-primary">{list.length}</span>건
              </div>
              <div className="flex items-center gap-3">
                <button
                  type="button"
                  className="h-8 cursor-pointer rounded border border-border-strong bg-white px-3 text-[13px] font-semibold text-muted"
                  onClick={handleDownloadReport}
                  title={PRINT_DESTINATION_HINT}
                >
                  ⬇ 상위 3건 비교 리포트
                </button>
                <span className="text-[13px] text-muted">적합도순 ▾</span>
              </div>
            </div>

            <div className="mb-4 -mt-1.5 text-[11px] leading-[1.5] text-faint">
              ⓘ {PRINT_DESTINATION_HINT}
            </div>

            {list.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={notice.id === selectedId}
                onClick={() => setSelectedId(notice.id)}
                onToggleBookmark={() => handleToggleBookmark(notice)}
                bookmarkBusy={bookmarkBusyIds.has(notice.id)}
              />
            ))}
          </div>

          <div className="overflow-auto border-l border-[#eef0f2] p-6">
            {selected ? (
              <>
                <span className="inline-block rounded-[3px] bg-primary-soft px-2 py-[3px] text-[11px] font-bold text-primary">
                  {selected.category} · {selected.deadlineLabel}
                </span>
                <div className="mt-3 text-lg font-extrabold leading-[1.4]">{selected.title}</div>
                <div className="mt-1 text-[13px] text-muted">{selected.org}</div>

                {selected.score != null ? (
                  <div className="my-5 flex items-center gap-3 rounded-md bg-success-soft p-4">
                    <ScoreGauge score={selected.score} size={72} />
                    <div className="text-[13px] leading-[1.5] text-[#15803d]">
                      적합도{' '}
                      {selected.scoreLevel === 'high' ? '매우 높음' : '보통'}
                      <br />
                      <span className="text-muted">
                        {selected.score >= 90 ? '상위 3% 추천' : '적합도 순위 반영'}
                      </span>
                    </div>
                  </div>
                ) : null}

                <div className="mb-2.5 text-[13px] font-extrabold">왜 추천했나요?</div>
                <div className="flex flex-col gap-2.5 text-[13px] leading-[1.6] text-[#374151]">
                  {selected.strengths.map((reason) => (
                    <div className="border-l-2 border-success pl-2.5" key={reason}>
                      {reason}
                    </div>
                  ))}
                  {selected.weaknesses.map((reason) => (
                    <div className="border-l-2 border-warning pl-2.5" key={reason}>
                      {reason}
                    </div>
                  ))}
                </div>

                {selected.scoreBreakdown ? (
                  <>
                    <div className="mb-2.5 mt-[22px] text-[13px] font-extrabold">
                      점수 구성
                    </div>
                    <div className="mt-[22px] flex flex-col gap-2.5">
                      {selected.scoreBreakdown.map((item) => (
                        <div key={item.key}>
                          <div className="mb-1 flex justify-between text-xs">
                            <span>{item.label}</span>
                            <span>
                              {item.score}/{item.max}
                            </span>
                          </div>
                          <div className="h-[5px] rounded-[3px] bg-border">
                            <div
                              className={
                                item.score < item.max / 2
                                  ? 'h-full rounded-[3px] bg-warning'
                                  : 'h-full rounded-[3px] bg-success'
                              }
                              style={{ width: `${(item.score / item.max) * 100}%` }}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </>
                ) : null}

                <div className="mt-6 flex flex-col gap-2">
                  {selected.sourceUrl ? (
                    <a
                      className="flex h-11 items-center justify-center rounded border border-border-strong bg-white text-sm font-semibold text-ink no-underline"
                      href={selected.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      원문 공고 보기 ↗
                    </a>
                  ) : (
                    <button
                      type="button"
                      className="h-11 cursor-not-allowed rounded border border-border bg-surface-subtle text-sm font-semibold text-faint"
                      disabled
                    >
                      원문 공고 보기 ↗
                    </button>
                  )}
                  {/* 상세 분석 페이지는 아직 목데이터 기반이라 실제 공고 id로는
                      열 수 없다. match_result 연동 후 버튼을 되살린다. */}
                </div>
              </>
            ) : (
              <div className="mt-[60px] text-center text-[13px] text-faint">공고를 선택해주세요</div>
            )}
          </div>
        </div>
      )}
      </div>

      <ComparisonReport notices={list} matchLog={matchLog} profile={profile} />
    </div>
  )
}
