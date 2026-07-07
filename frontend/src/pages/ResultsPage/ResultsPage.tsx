import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { NoticeCard } from '../../components/NoticeCard/NoticeCard'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { NOTICE_CATEGORIES } from '../../mock/categories'
import { notices } from '../../mock/notices'
import { resultDetailPath } from '../../routes/paths'
import styles from './ResultsPage.module.css'

const FIELD_FILTERS = NOTICE_CATEGORIES.map((category) => ({
  label: category,
  count: notices.filter((notice) => notice.category === category).length,
  checked: category === notices[0].category,
}))

const DEADLINE_FILTERS = ['7일 이내', '30일 이내', '상시 모집']

export function ResultsPage() {
  const navigate = useNavigate()
  const [selectedId, setSelectedId] = useState(notices[0].id)
  const selected = notices.find((notice) => notice.id === selectedId)

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.layout}>
        <aside className={styles.sidebar}>
          <div className={styles.sidebarTitle}>필터</div>

          <div className={styles.filterGroupTitle}>분야</div>
          <div className={styles.filterOptions}>
            {FIELD_FILTERS.map((filter) => (
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

          <div className={styles.filterGroupTitle}>지원규모</div>
          <div className={styles.rangeTrack}>
            <div className={styles.rangeFill} />
          </div>
          <div className={styles.rangeLabel}>~5천만원 · 5천만~3억</div>
        </aside>

        <div className={styles.list}>
          <div className={styles.listHeader}>
            <div className={styles.listCount}>
              맞춤 공고 <span>{notices.length}</span>건
            </div>
            <div className={styles.sortLabel}>적합도순 ▾</div>
          </div>

          {notices.map((notice) => (
            <NoticeCard
              key={notice.id}
              notice={notice}
              selected={notice.id === selectedId}
              onClick={() => setSelectedId(notice.id)}
            />
          ))}
          <div className={styles.moreLink}>+ 20건 더보기</div>
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
                <button type="button" className={styles.disabledAction} disabled>
                  원문 공고 보기 ↗
                </button>
                <button
                  type="button"
                  className={styles.secondaryAction}
                  onClick={() => navigate(resultDetailPath(selected.id))}
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
