import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { getMatchLog, formatMatchLogDate, listMatchLogs } from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { getMatchResults, matchResultToNotice } from '../../api/matchResults'
import type { Notice } from '../../types/notice'
import { PATHS } from '../../routes/paths'
import styles from './ResultsPage.module.css'

const DEADLINE_FILTERS = ['7일 이내', '30일 이내', '상시 모집']

export function ResultsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 어느 매칭 실행(match_log)의 결과인지. 분석 페이지에서 새 매칭을 돌리거나
  // 매칭 기록을 클릭하면 ?matchLogId= 쿼리로 넘어온다.
  const matchLogIdParam = searchParams.get('matchLogId')
  const matchLogId = matchLogIdParam ? Number(matchLogIdParam) : null
  const validLogId =
    matchLogId != null && !Number.isNaN(matchLogId) ? matchLogId : null

  const [matchLog, setMatchLog] = useState<MatchLog | null>(null)
  // null = 로딩 중. 로딩이 끝나면 (빈 배열 포함) 배열.
  const [results, setResults] = useState<Notice[] | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  useEffect(() => {
    if (validLogId == null) {
      setMatchLog(null)
      return
    }
    let cancelled = false
    getMatchLog(validLogId)
      .then((log) => {
        if (!cancelled) setMatchLog(log)
      })
      .catch(() => {
        // 실행 정보 배너는 부가 정보라 실패해도 결과 화면은 그대로 보여준다.
        if (!cancelled) setMatchLog(null)
      })
    return () => {
      cancelled = true
    }
  }, [validLogId])

  useEffect(() => {
    if (validLogId == null) {
      setResults([])
      return
    }
    let cancelled = false
    setResults(null)
    setLoadError(null)
    getMatchResults(validLogId)
      .then((rows) => {
        if (cancelled) return
        const list = rows.map(matchResultToNotice)
        setResults(list)
        setSelectedId(list[0]?.id ?? null)
      })
      .catch(() => {
        if (cancelled) return
        setResults([])
        setLoadError('매칭 결과를 불러오지 못했어요. 잠시 후 다시 시도해 주세요.')
      })
    return () => {
      cancelled = true
    }
  }, [validLogId])

  const list = results ?? []
  const selected = list.find((notice) => notice.id === selectedId)

  const fieldFilters = useMemo(() => {
    const counts = new Map<string, number>()
    for (const notice of results ?? []) {
      counts.set(notice.category, (counts.get(notice.category) ?? 0) + 1)
    }
    return [...counts.entries()].map(([label, count], index) => ({
      label,
      count,
      checked: index === 0,
    }))
  }, [results])

  // matchLogId 없이 진입(직접 URL 입력 등)하면 보여줄 결과가 없다.
  if (validLogId == null) {
    return (
      <div className={styles.page}>
        <AppHeader />
        <div className={styles.stateWrap}>
          <div className={styles.stateTitle}>표시할 매칭 결과가 없어요</div>
          <div className={styles.stateText}>
            사업계획서를 분석하고 공고 매칭을 실행하면 결과를 볼 수 있어요.
            <br />
            분석 페이지의 매칭 기록에서 지난 결과를 다시 열 수도 있어요.
          </div>
          <button
            type="button"
            className={styles.stateButton}
            onClick={() => navigate(PATHS.UPLOAD)}
          >
            사업계획서 분석하러 가기 →
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      {matchLog ? (
        <div className={styles.runBanner}>
          <span className={styles.runBannerTitle}>
            {matchLog.business_plan_title ?? '사업계획서'}
          </span>
          <span className={styles.runBannerDate}>
            {formatMatchLogDate(matchLog.created_at)} 매칭 결과
          </span>
        </div>
      ) : null}

      {results == null ? (
        <div className={styles.stateWrap}>
          <div className={styles.stateText}>매칭 결과를 불러오는 중…</div>
        </div>
      ) : list.length === 0 ? (
        <div className={styles.stateWrap}>
          <div className={styles.stateTitle}>
            {loadError ? '결과를 불러오지 못했어요' : '이 매칭에는 저장된 결과가 없어요'}
          </div>
          <div className={styles.stateText}>
            {loadError ?? '공고 데이터가 없던 시점의 실행이거나, 결과 생성에 실패한 실행이에요.'}
          </div>
        </div>
      ) : (
        <div className={styles.layout}>
          <aside className={styles.sidebar}>
            <div className={styles.sidebarTitle}>필터</div>

            <div className={styles.filterGroupTitle}>분야</div>
            <div className={styles.filterOptions}>
              {fieldFilters.map((filter) => (
                <label className={styles.filterLabel} key={filter.label}>
                  <span
                    className={
                      filter.checked
                        ? `${styles.checkbox} ${styles.checked}`
                        : styles.checkbox
                    }
                  />
                  {filter.label} ({filter.count})
                </label>
              ))}
            </div>

            <div className={styles.filterGroupTitle}>마감</div>
            <div className={styles.filterOptions}>
              {DEADLINE_FILTERS.map((label) => (
                <label className={styles.filterLabel} key={label}>
                  <span className={styles.checkbox} />
                  {label}
                </label>
              ))}
            </div>
          </aside>

          <div className={styles.list}>
            <div className={styles.listHeader}>
              <div className={styles.listCount}>
                맞춤 공고 <span>{list.length}</span>건
              </div>
              <div className={styles.sortLabel}>적합도순 ▾</div>
            </div>

            {list.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={notice.id === selectedId}
                onClick={() => setSelectedId(notice.id)}
              />
            ))}
          </div>

          <div className={styles.detail}>
            {selected ? (
              <>
                <span className={styles.detailBadge}>
                  {selected.category} · {selected.deadlineLabel}
                </span>
                <div className={styles.detailTitle}>{selected.title}</div>
                <div className={styles.detailOrg}>{selected.org}</div>

                <div className={styles.gaugeBanner}>
                  <ScoreGauge score={selected.score} size={72} />
                  <div className={styles.gaugeBannerText}>
                    적합도{' '}
                    {selected.scoreLevel === 'high' ? '매우 높음' : '보통'}
                    <br />
                    <span>
                      {selected.score >= 90 ? '상위 3% 추천' : '적합도 순위 반영'}
                    </span>
                  </div>
                </div>

                <div className={styles.detailSectionTitle}>왜 추천했나요?</div>
                <div className={styles.reasons}>
                  {selected.reasons.map((reason) => (
                    <div
                      className={
                        reason.tone === 'warn'
                          ? `${styles.reasonItem} ${styles.warn}`
                          : styles.reasonItem
                      }
                      key={reason.detail}
                    >
                      {reason.detail}
                    </div>
                  ))}
                </div>

                <div className={styles.detailSectionTitle} style={{ marginTop: 22 }}>
                  점수 구성
                </div>
                <div className={styles.breakdown}>
                  {selected.scoreBreakdown.map((item) => (
                    <div key={item.label}>
                      <div className={styles.breakdownRow}>
                        <span>{item.label}</span>
                        <span>
                          {item.score}/{item.max}
                        </span>
                      </div>
                      <div className={styles.breakdownTrack}>
                        <div
                          className={
                            item.status === 'warn'
                              ? `${styles.breakdownFill} ${styles.warn}`
                              : styles.breakdownFill
                          }
                          style={{ width: `${(item.score / item.max) * 100}%` }}
                        />
                      </div>
                    </div>
                  ))}
                </div>

                <div className={styles.detailActions}>
                  {selected.sourceUrl ? (
                    <a
                      className={styles.linkAction}
                      href={selected.sourceUrl}
                      target="_blank"
                      rel="noreferrer"
                    >
                      원문 공고 보기 ↗
                    </a>
                  ) : (
                    <button type="button" className={styles.disabledAction} disabled>
                      원문 공고 보기 ↗
                    </button>
                  )}
                  {/* 상세 분석 페이지는 아직 목데이터 기반이라 실제 공고 id로는
                      열 수 없다. match_result 연동 후 버튼을 되살린다. */}
                </div>
              </>
            ) : (
              <div className={styles.emptyDetail}>공고를 선택해주세요</div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
