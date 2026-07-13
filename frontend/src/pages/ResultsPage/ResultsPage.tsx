import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { getMatchLog, formatMatchLogDate, listMatchLogs } from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import { NOTICE_CATEGORIES } from '../../mock/categories'
import { resultDetailPath } from '../../routes/paths'
import styles from './ResultsPage.module.css'

export function ResultsPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()

  // 어느 매칭 실행(match_log)의 결과인지. 분석 페이지에서 새 매칭을 돌리거나
  // 이전 기록을 클릭하면 ?matchLogId= 쿼리로 넘어온다. 쿼리가 없으면(직접
  // 진입) 가장 최근 실행 기록을 대신 불러온다.
  const matchLogIdParam = searchParams.get('matchLogId')
  const [matchLogId, setMatchLogId] = useState<number | null>(
    matchLogIdParam ? Number(matchLogIdParam) : null,
  )

  useEffect(() => {
    if (matchLogIdParam) {
      setMatchLogId(Number(matchLogIdParam))
      return
    }
    let cancelled = false
    listMatchLogs(1, 0)
      .then((logs) => {
        if (!cancelled) setMatchLogId(logs[0]?.id ?? null)
      })
      .catch(() => {
        if (!cancelled) setMatchLogId(null)
      })
    return () => {
      cancelled = true
    }
  }, [matchLogIdParam])

  const [matchLog, setMatchLog] = useState<MatchLog | null>(null)

  useEffect(() => {
    if (matchLogId == null) {
      setMatchLog(null)
      return
    }
    let cancelled = false
    getMatchLog(matchLogId)
      .then((log) => {
        if (!cancelled) setMatchLog(log)
      })
      .catch(() => {
        // 실행 정보 표시는 부가 기능이라 실패해도 결과 화면은 그대로 보여준다.
        if (!cancelled) setMatchLog(null)
      })
    return () => {
      cancelled = true
    }
  }, [matchLogId])

  const { matchedNotices, loading, error } = useMatchedNotices(matchLogId)

  const [selectedId, setSelectedId] = useState<number | null>(null)
  useEffect(() => {
    setSelectedId(matchedNotices[0]?.id ?? null)
  }, [matchedNotices])
  const selected = matchedNotices.find((notice) => notice.id === selectedId)

  const fieldFilters = useMemo(
    () =>
      NOTICE_CATEGORIES.map((category) => ({
        label: category,
        count: matchedNotices.filter((notice) => notice.category === category).length,
      })),
    [matchedNotices],
  )

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
      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <div className={styles.sidebarTitle}>필터</div>

          <div className={styles.filterGroupTitle}>분야</div>
          <div className={styles.filterOptions}>
            {fieldFilters.map((filter) => (
              <label className={styles.filterLabel} key={filter.label}>
                <span className={styles.checkbox} />
                {filter.label} ({filter.count})
              </label>
            ))}
          </div>
        </aside>

        <div className={styles.list}>
          <div className={styles.listHeader}>
            <div className={styles.listCount}>
              맞춤 공고 <span>{matchedNotices.length}</span>건
            </div>
            <div className={styles.sortLabel}>적합도순 ▾</div>
          </div>

          {loading ? (
            <div className={styles.emptyDetail}>매칭 결과를 불러오는 중이에요…</div>
          ) : error ? (
            <div className={styles.emptyDetail}>
              매칭 결과를 불러오지 못했어요. 잠시 후 다시 시도해주세요.
            </div>
          ) : matchedNotices.length === 0 ? (
            <div className={styles.emptyDetail}>
              아직 매칭 결과가 없어요. 사업계획서를 분석해 공고 매칭을 실행해주세요.
            </div>
          ) : (
            matchedNotices.map((notice) => (
              <NoticeCard
                key={notice.id}
                notice={notice}
                selected={notice.id === selectedId}
                onClick={() => setSelectedId(notice.id)}
              />
            ))
          )}
        </div>

        <div className={styles.detail}>
          {selected ? (
            <>
              <span className={styles.detailBadge}>
                {selected.category ?? '분류 없음'} · {selected.deadlineLabel}
              </span>
              <div className={styles.detailTitle}>{selected.title}</div>
              <div className={styles.detailOrg}>{selected.org}</div>

              {selected.score != null ? (
                <div className={styles.gaugeBanner}>
                  <ScoreGauge score={selected.score} size={72} />
                  <div className={styles.gaugeBannerText}>
                    적합도{' '}
                    {selected.scoreLevel === 'high'
                      ? '매우 높음'
                      : selected.scoreLevel === 'medium'
                        ? '보통'
                        : '낮음'}
                    <br />
                    <span>
                      {selected.score >= 90 ? '상위권 추천' : '적합도 순위 반영'}
                    </span>
                  </div>
                </div>
              ) : null}

              {selected.strengths.length > 0 ? (
                <>
                  <div className={styles.detailSectionTitle}>왜 추천했나요?</div>
                  <div className={styles.reasons}>
                    {selected.strengths.map((reason) => (
                      <div className={styles.reasonItem} key={reason}>
                        {reason}
                      </div>
                    ))}
                    {selected.weaknesses.map((reason) => (
                      <div className={`${styles.reasonItem} ${styles.warn}`} key={reason}>
                        {reason}
                      </div>
                    ))}
                  </div>
                </>
              ) : null}

              {selected.scoreBreakdown ? (
                <>
                  <div className={styles.detailSectionTitle} style={{ marginTop: 22 }}>
                    점수 구성
                  </div>
                  <div className={styles.breakdown}>
                    {selected.scoreBreakdown.map((item) => (
                      <div key={item.key}>
                        <div className={styles.breakdownRow}>
                          <span>{item.label}</span>
                          <span>
                            {item.score}/{item.max}
                          </span>
                        </div>
                        <div className={styles.breakdownTrack}>
                          <div
                            className={
                              item.score < 50
                                ? `${styles.breakdownFill} ${styles.warn}`
                                : styles.breakdownFill
                            }
                            style={{ width: `${(item.score / item.max) * 100}%` }}
                          />
                        </div>
                      </div>
                    ))}
                  </div>
                </>
              ) : null}

              <div className={styles.detailActions}>
                {selected.sourceUrl ? (
                  <a
                    className={styles.secondaryAction}
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
                <button
                  type="button"
                  className={styles.secondaryAction}
                  onClick={() =>
                    matchLogId != null &&
                    navigate(resultDetailPath(selected.id, matchLogId))
                  }
                >
                  상세 분석 보기
                </button>
              </div>
            </>
          ) : (
            <div className={styles.emptyDetail}>공고를 선택해주세요</div>
          )}
        </div>
      </div>
    </div>
  )
}
