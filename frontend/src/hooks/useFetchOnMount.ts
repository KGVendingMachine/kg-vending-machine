import { useEffect, useState } from 'react'

interface UseFetchOnMountResult<T> {
  data: T | null
  loading: boolean
  error: unknown
}

/**
 * 마운트(또는 deps 변경) 시 fetcher를 호출해 결과를 상태로 관리한다.
 * fetcher가 null을 반환하면 조회를 건너뛰고 data를 비운다(예: 아직 id가 없는 경우).
 * 언마운트되거나 deps가 바뀐 뒤 늦게 도착한 응답은 무시한다.
 */
export function useFetchOnMount<T>(
  fetcher: () => Promise<T> | null,
  deps: unknown[],
): UseFetchOnMountResult<T> {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<unknown>(null)

  useEffect(() => {
    const promise = fetcher()
    if (promise == null) {
      setData(null)
      setError(null)
      setLoading(false)
      return
    }

    let cancelled = false
    setLoading(true)
    setError(null)
    promise
      .then((result) => {
        if (!cancelled) setData(result)
      })
      .catch((err) => {
        if (!cancelled) setError(err)
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  return { data, loading, error }
}
