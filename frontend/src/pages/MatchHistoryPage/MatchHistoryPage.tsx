import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { formatMatchLogDate, listMatchLogs } from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { PATHS, resultsPath } from '../../routes/paths'

// 한 페이지 크기. "더보기"를 누를 때마다 이만큼 이어붙인다
// (AnalysisProgressPage의 매칭 기록 목록과 동일한 크기).
const PAGE_SIZE = 10

export function MatchHistoryPage() {
  const navigate = useNavigate()
  // null이면 아직 로딩 전/실패.
  const [logs, setLogs] = useState<MatchLog[] | null>(null)
  const [loading, setLoading] = useState(true)
  // 마지막 페이지 응답이 꽉 찼으면(=PAGE_SIZE) 더 있을 수 있다고 보고
  // "더보기"를 노출한다.
  const [hasMore, setHasMore] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)

  useEffect(() => {
    let cancelled = false
    setLoading(true)
    listMatchLogs(PAGE_SIZE, 0)
      .then((result) => {
        if (cancelled) return
        setLogs(result)
        setHasMore(result.length === PAGE_SIZE)
      })
      .catch(() => {
        if (cancelled) return
        setLogs([])
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [])

  async function handleLoadMore() {
    if (logs == null || loadingMore) return
    setLoadingMore(true)
    try {
      const more = await listMatchLogs(PAGE_SIZE, logs.length)
      setLogs([...logs, ...more])
      setHasMore(more.length === PAGE_SIZE)
    } catch {
      // 실패해도 버튼은 남아 있어 다시 누르면 재시도된다.
    } finally {
      setLoadingMore(false)
    }
  }

  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto w-full max-w-[760px] px-10 py-7">
        <div className="text-[22px] font-extrabold tracking-[-0.5px]">
          이전 매칭 기록
        </div>
        <div className="mt-1.5 mb-6 text-[13px] text-muted">
          사업계획서를 분석해 공고 매칭을 실행했던 기록이에요. 클릭하면 그 실행 기준
          추천 결과를 다시 볼 수 있어요.
        </div>

        {loading ? (
          <div className="rounded-lg border border-dashed border-border-strong px-6 py-12 text-center text-[13.5px] leading-[1.6] text-faint">
            불러오는 중이에요…
          </div>
        ) : logs && logs.length > 0 ? (
          <>
            <div className="flex flex-col gap-2">
              {logs.map((log) => (
                <button
                  type="button"
                  key={log.id}
                  className="flex cursor-pointer items-center gap-3.5 rounded-md border border-border bg-white px-[18px] py-3.5 text-left text-[13px] hover:border-primary"
                  onClick={() => navigate(resultsPath(log.id))}
                >
                  <span className="min-w-0 flex-1 truncate font-bold">
                    {log.business_plan_title ?? '사업계획서'}
                  </span>
                  <span className="shrink-0 text-muted">
                    {formatMatchLogDate(log.created_at)}
                  </span>
                  <span className="shrink-0 font-bold text-primary">결과 보기 →</span>
                </button>
              ))}
            </div>
            {hasMore ? (
              <button
                type="button"
                className="mt-2.5 w-full cursor-pointer rounded-md border border-dashed border-border-strong bg-transparent px-0 py-2.5 text-[13px] font-semibold text-muted hover:border-primary hover:text-primary disabled:cursor-default disabled:text-faint"
                onClick={handleLoadMore}
                disabled={loadingMore}
              >
                {loadingMore ? '불러오는 중…' : '+ 더보기'}
              </button>
            ) : null}
          </>
        ) : (
          <div className="rounded-lg border border-dashed border-border-strong px-6 py-12 text-center text-[13.5px] leading-[1.6] text-faint">
            아직 매칭 기록이 없어요. 사업계획서를 분석하고 공고 매칭을 실행해보세요.
            <div className="mt-3">
              <button
                type="button"
                className="cursor-pointer rounded border-none bg-primary px-5 py-2.5 text-[13px] font-bold text-white"
                onClick={() => navigate(PATHS.UPLOAD)}
              >
                사업계획서 분석하러 가기 →
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
