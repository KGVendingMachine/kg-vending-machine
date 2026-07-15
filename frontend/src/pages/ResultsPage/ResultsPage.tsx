import { useMemo, useState } from 'react'
import { Navigate, useNavigate, useSearchParams } from 'react-router-dom'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { getMatchLog, formatMatchLogDate, listMatchLogs } from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { toggleBookmark } from '../../api/bookmarks'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import { PATHS, resultDetailPath, resultsPath } from '../../routes/paths'
import { DEADLINE_FILTERS } from '../../constants/resultsFilters'
import type { MatchedNotice } from '../../types/notice'

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

  // matchLogId 없이 진입("추천 결과" 탭 클릭 등)하면 최신 매칭 실행으로
  // 리다이렉트한다 — "추천 결과"는 항상 마지막 분석 결과를 보여주고, 지난
  // 기록은 이전 매칭 기록 페이지에서 고른다.
  const { data: latestLogs, loading: loadingLatest } = useFetchOnMount<MatchLog[]>(
    () => (validLogId == null ? listMatchLogs(1, 0) : null),
    [validLogId],
  )

  const list = matchedNotices

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
    <div className="flex flex-1 flex-col min-h-0">
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
              <div className="text-[13px] text-muted">적합도순 ▾</div>
            </div>

            {list.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={false}
                onClick={() => navigate(resultDetailPath(notice.id, validLogId))}
                onToggleBookmark={() => handleToggleBookmark(notice)}
                bookmarkBusy={bookmarkBusyIds.has(notice.id)}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
