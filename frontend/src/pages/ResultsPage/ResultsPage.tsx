import { useMemo, useState } from 'react'
import type { Dispatch, SetStateAction } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { ComparisonReport } from '../../components/ComparisonReport/ComparisonReport'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { getMatchLog, formatMatchLogDate, listMatchLogs } from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { toggleBookmark } from '../../api/bookmarks'
import { getMyCompanyProfile } from '../../api/companyProfile'
import type { CompanyProfile } from '../../api/companyProfile'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import { PATHS, resultDetailPath, resultsPath } from '../../routes/paths'
import { CATEGORY_FILTERS, DEADLINE_FILTERS } from '../../constants/resultsFilters'
import type { CategoryFilterValue } from '../../constants/resultsFilters'
import type { MatchedNotice } from '../../types/notice'
import {
  reportFileTitle,
  printWithFilename,
  PRINT_DESTINATION_HINT,
} from '../../utils/reportFilename'

/** application_end_date 기준 남은 일수. null이면 상시 모집(또는 날짜 없음). */
function daysRemaining(notice: MatchedNotice): number | null {
  if (!notice.applicationEndDate) return null
  const end = new Date(`${notice.applicationEndDate}T00:00:00`)
  if (Number.isNaN(end.getTime())) return null
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  return Math.round((end.getTime() - today.getTime()) / 86_400_000)
}

function matchesDeadlineFilter(
  notice: MatchedNotice,
  selectedDeadlines: Set<string>,
): boolean {
  if (selectedDeadlines.size === 0) return true
  const days = daysRemaining(notice)
  return [...selectedDeadlines].some((label) => {
    if (label === '상시 모집') return days == null
    if (days == null || days < 0) return false
    if (label === '7일 이내') return days <= 7
    if (label === '30일 이내') return days <= 30
    return false
  })
}

export function ResultsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 어느 매칭 실행(match_log)의 결과인지. 분석 페이지에서 새 매칭을 돌리거나
  // 매칭 기록을 클릭하면 ?matchLogId= 쿼리로 넘어온다.
  const matchLogIdParam = searchParams.get('matchLogId')
  const matchLogId = matchLogIdParam ? Number(matchLogIdParam) : null
  const validLogId =
    matchLogId != null && !Number.isNaN(matchLogId) ? matchLogId : null

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

  // matchLogId 없이 진입("추천 결과" 탭 클릭 등)하면 최신 매칭 실행으로
  // 리다이렉트한다 — "추천 결과"는 항상 마지막 분석 결과를 보여주고, 지난
  // 기록은 이전 매칭 기록 페이지에서 고른다.
  const { data: latestLogs, loading: loadingLatest } = useFetchOnMount<MatchLog[]>(
    () => (validLogId == null ? listMatchLogs(1, 0) : null),
    [validLogId],
  )

  const list = matchedNotices

  // 분야는 전체/자금/R&D 중 하나만 고를 수 있는 단일 선택. 마감은 체크된 게
  // 없으면 "전체 보임"으로 취급한다(최초 상태에서 목록이 통째로 사라지면
  // 안 되므로).
  const [selectedCategory, setSelectedCategory] =
    useState<CategoryFilterValue>('all')
  const [selectedDeadlines, setSelectedDeadlines] = useState<Set<string>>(
    new Set(),
  )

  function toggleSetValue(
    setState: Dispatch<SetStateAction<Set<string>>>,
    value: string,
  ) {
    setState((current) => {
      const next = new Set(current)
      if (next.has(value)) next.delete(value)
      else next.add(value)
      return next
    })
  }

  const categoryCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const notice of list) {
      const label = notice.category ?? '기타'
      counts.set(label, (counts.get(label) ?? 0) + 1)
    }
    return counts
  }, [list])

  const filteredList = useMemo(
    () =>
      list.filter((notice) => {
        const categoryOk =
          selectedCategory === 'all' || notice.category === selectedCategory
        return categoryOk && matchesDeadlineFilter(notice, selectedDeadlines)
      }),
    [list, selectedCategory, selectedDeadlines],
  )

  // matchLogId 없이 진입("추천 결과" 탭 클릭 등)하면 최신 매칭 실행으로
  // 리다이렉트한다. 매칭 기록 자체가 없는 유저에게만 안내 화면을 보여준다.
  if (validLogId == null) {
    if (loadingLatest) {
      return (
        <div className="flex flex-1 flex-col min-h-0">
          <div className="flex flex-1 flex-col items-center justify-center gap-2.5 px-6 py-[60px] text-center">
            <div className="text-sm leading-[1.6] text-muted">최근 매칭 결과를 불러오는 중…</div>
          </div>
        </div>
      )
    }
    if (latestLogs && latestLogs.length > 0) {
      return <Navigate to={resultsPath(latestLogs[0].id)} replace />
    }
    return (
      <div className="flex flex-1 flex-col min-h-0">
        <div className="flex flex-1 flex-col items-center justify-center gap-2.5 px-6 py-[60px] text-center">
          <div className="text-lg font-extrabold">표시할 매칭 결과가 없어요</div>
          <div className="text-sm leading-[1.6] text-muted">
            사업계획서를 분석하고 공고 매칭을 실행하면 결과를 볼 수 있어요.
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
    <>
      <div className="no-print flex flex-1 flex-col min-h-0">
      {matchLog ? (
        <div className="flex items-center gap-2.5 border-b border-[#eef0f2] bg-primary-soft px-6 py-2.5 text-[13px]">
          <span className="font-extrabold">
            {matchLog.business_plan_title ?? '사업계획서'}
          </span>
          <span className="text-muted">
            {formatMatchLogDate(matchLog.created_at)} 매칭 결과
          </span>
          <button
            type="button"
            className="ml-auto cursor-pointer border-0 bg-transparent p-0 text-[13px] font-semibold text-primary underline-offset-2 hover:underline"
            onClick={() => navigate(PATHS.MATCH_HISTORY)}
          >
            이전 매칭 기록 보기 →
          </button>
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
        <div className="grid flex-1 min-h-0 grid-cols-[230px_1fr]">
          <aside className="overflow-auto border-r border-[#eef0f2] px-5 py-6">
            <div className="mb-[18px] text-[13px] font-extrabold">필터</div>

            <div className="mb-2.5 text-xs font-bold text-muted">분야</div>
            <div className="mb-[22px] flex flex-col gap-[9px] text-[13px]">
              {CATEGORY_FILTERS.map((filter) => {
                const checked = selectedCategory === filter.value
                const count =
                  filter.value === 'all'
                    ? list.length
                    : (categoryCounts.get(filter.value) ?? 0)
                return (
                  <label
                    className="flex cursor-pointer items-center gap-2"
                    key={filter.value}
                  >
                    <input
                      type="radio"
                      name="category-filter"
                      className="sr-only"
                      checked={checked}
                      onChange={() => setSelectedCategory(filter.value)}
                    />
                    <span
                      className={
                        checked
                          ? 'h-[15px] w-[15px] shrink-0 rounded-full border border-primary bg-primary'
                          : 'h-[15px] w-[15px] shrink-0 rounded-full border border-[#c8cdd3]'
                      }
                    />
                    {filter.label} ({count})
                  </label>
                )
              })}
            </div>

            <div className="mb-2.5 text-xs font-bold text-muted">마감</div>
            <div className="mb-[22px] flex flex-col gap-[9px] text-[13px]">
              {DEADLINE_FILTERS.map((label) => {
                const checked = selectedDeadlines.has(label)
                return (
                  <label className="flex cursor-pointer items-center gap-2" key={label}>
                    <input
                      type="checkbox"
                      className="sr-only"
                      checked={checked}
                      onChange={() => toggleSetValue(setSelectedDeadlines, label)}
                    />
                    <span
                      className={
                        checked
                          ? 'h-[15px] w-[15px] shrink-0 rounded-[3px] border border-primary bg-primary'
                          : 'h-[15px] w-[15px] shrink-0 rounded-[3px] border border-[#c8cdd3]'
                      }
                    />
                    {label}
                  </label>
                )
              })}
            </div>
            {selectedCategory !== 'all' || selectedDeadlines.size > 0 ? (
              <button
                type="button"
                className="cursor-pointer border-0 bg-transparent p-0 text-xs font-semibold text-primary underline-offset-2 hover:underline"
                onClick={() => {
                  setSelectedCategory('all')
                  setSelectedDeadlines(new Set())
                }}
              >
                필터 초기화
              </button>
            ) : null}
          </aside>

          <div className="overflow-auto bg-surface-subtle px-6 py-[22px]">
            <div className="mb-4 flex items-center justify-between">
              <div className="text-[15px] font-bold">
                맞춤 공고 <span className="text-primary">{filteredList.length}</span>건
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

            {filteredList.length === 0 ? (
              <div className="rounded-lg border border-dashed border-border-strong px-6 py-12 text-center text-[13.5px] leading-[1.6] text-faint">
                선택한 조건에 맞는 공고가 없어요.
              </div>
            ) : (
              filteredList.map((notice) => (
                <NoticeCard
                  key={notice.id}
                  notice={notice}
                  selected={false}
                  onClick={() => navigate(resultDetailPath(notice.id, validLogId))}
                  onToggleBookmark={() => handleToggleBookmark(notice)}
                  bookmarkBusy={bookmarkBusyIds.has(notice.id)}
                />
              ))
            )}
          </div>
        </div>
      )}
      </div>

      <ComparisonReport notices={list} matchLog={matchLog} profile={profile} />
    </>
  )
}
