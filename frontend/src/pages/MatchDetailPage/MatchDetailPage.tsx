import { useEffect, useState } from 'react'
import { Navigate, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { getMyCompanyProfile } from '../../api/companyProfile'
import type { CompanyProfile } from '../../api/companyProfile'
import { useMatchedNotices } from '../../hooks/useMatchedNotices'
import { PATHS } from '../../routes/paths'
import { toggleBookmark } from '../../api/bookmarks'
import styles from './MatchDetailPage.module.css'

const APPLICATION_CHECKLIST = [
  '사업자등록증·중소기업 확인서 준비',
  '자부담 자금조달 계획 수립',
  '설비 도입 견적서 확보',
  '온라인 신청서 제출',
]

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
  const [profile, setProfile] = useState<CompanyProfile | null>(null)
  // 별표 상태는 결과에서 온 bookmarkId를 로컬로 들고 토글마다 갱신한다.
  const [bookmarkId, setBookmarkId] = useState<number | null>(null)
  const [bookmarkBusy, setBookmarkBusy] = useState(false)

  useEffect(() => {
    let cancelled = false
    getMyCompanyProfile()
      .then((value) => {
        if (!cancelled) setProfile(value)
      })
      .catch(() => {
        if (!cancelled) setProfile(null)
      })
    return () => {
      cancelled = true
    }
  }, [])

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
        <div className={styles.page}>
          <AppHeader />
          <div className={styles.banner}>매칭 상세 정보를 불러오는 중이에요…</div>
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
    <div className={styles.page}>
      <AppHeader />

      <div className={styles.subnav}>
        <button
          type="button"
          className={styles.backLink}
          onClick={() => navigate(`${PATHS.RESULTS}?matchLogId=${matchLogId}`)}
        >
          ← 추천 결과
        </button>
        <div className={styles.subnavTitle}>매칭 상세 분석</div>
        <button
          type="button"
          className={
            bookmarked
              ? `${styles.bookmarkButton} ${styles.bookmarked}`
              : styles.bookmarkButton
          }
          aria-label={bookmarked ? '북마크 해제' : '북마크 추가'}
          disabled={bookmarkBusy}
          onClick={handleToggleBookmark}
        >
          {bookmarked ? '★ 북마크됨' : '☆ 북마크'}
        </button>
      </div>

      <div className={styles.banner}>
        <div className={styles.bannerMain}>
          <div className={styles.badges}>
            {notice.category ? (
              <span className={styles.category}>{notice.category}</span>
            ) : null}
            <span className={styles.deadline}>
              {notice.deadlineLabel} · {notice.dueDateLabel} 마감
            </span>
          </div>
          <div className={styles.title}>{notice.title}</div>
          <div className={styles.org}>
            {notice.org}
            {notice.amountLabel ? ` · ${notice.amountLabel}` : ''}
          </div>
          {targetLabel ? <div className={styles.target}>대상 기업 {targetLabel}</div> : null}
        </div>
        {notice.score != null ? (
          <div className={styles.gaugeCol}>
            <ScoreGauge score={notice.score} />
            <div className={styles.gaugeLevel}>
              적합도{' '}
              {notice.scoreLevel === 'high'
                ? '매우 높음'
                : notice.scoreLevel === 'medium'
                  ? '보통'
                  : '낮음'}
            </div>
            <div className={styles.gaugeRank}>
              {notice.score >= 90 ? '전체 추천 중 상위권' : '전체 추천 결과 기준'}
            </div>
          </div>
        ) : null}
      </div>

      {notice.summary ? (
        <div className={styles.diagnosis}>
          <div className={styles.diagnosisHeader}>
            <div className={styles.diagnosisHeading}>
              <span className={styles.diagnosisTitle}>공고 요약</span>
              <span className={styles.diagnosisSubtitle}>
                공고 원문에서 핵심 내용만 정리했어요
              </span>
            </div>
          </div>
          <div className={styles.summaryOverview}>{notice.summary}</div>
        </div>
      ) : null}

      <div className={styles.body}>
        <div className={styles.left}>
          {notice.scoreBreakdown ? (
            <>
              <div className={styles.sectionTitle}>점수 구성</div>
              <div className={styles.sectionSubtitle}>
                항목별 가중치 기준으로 합산된 적합도입니다
              </div>

              {notice.scoreBreakdown.map((item) => (
                <div className={styles.scoreItem} key={item.key}>
                  <div className={styles.scoreItemHeader}>
                    <span className={styles.scoreItemLabel}>
                      {item.label}{' '}
                      <span className={styles.scoreItemWeight}>{item.weightLabel}</span>
                    </span>
                    <span
                      className={
                        item.score < 50
                          ? `${styles.scoreItemValue} ${styles.warn}`
                          : styles.scoreItemValue
                      }
                    >
                      {item.score} / {item.max}
                    </span>
                  </div>
                  <div className={styles.scoreTrack}>
                    <div
                      className={
                        item.score < 50
                          ? `${styles.scoreFill} ${styles.warn}`
                          : styles.scoreFill
                      }
                      style={{ width: `${(item.score / item.max) * 100}%` }}
                    />
                  </div>
                </div>
              ))}

              <div className={styles.divider} />
            </>
          ) : null}

          {notice.eligibilityStatus || notice.cautions.length > 0 ? (
            <>
              <div className={styles.sectionTitle}>자격요건 대조</div>
              <div className={styles.requirements}>
                {notice.eligibilityStatus ? (
                  <div className={styles.requirementRow}>
                    <span
                      className={
                        notice.eligibilityStatus === 'eligible'
                          ? `${styles.requirementIcon} ${styles.ok}`
                          : `${styles.requirementIcon} ${styles.warn}`
                      }
                    >
                      {notice.eligibilityStatus === 'eligible' ? '✓' : '!'}
                    </span>
                    <div>
                      <b>자격 상태</b> —{' '}
                      <span className={styles.requirementDetail}>
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
                  <div className={styles.requirementRow} key={caution}>
                    <span className={`${styles.requirementIcon} ${styles.warn}`}>!</span>
                    <div>
                      <span className={styles.requirementDetail}>{caution}</span>
                    </div>
                  </div>
                ))}
              </div>
            </>
          ) : null}
        </div>

        <div className={styles.right}>
          {notice.strengths.length > 0 || notice.weaknesses.length > 0 ? (
            <>
              <div className={styles.sectionTitle}>추천 근거</div>
              <div className={styles.reasonCards}>
                {notice.strengths.map((reason) => (
                  <div className={styles.reasonCard} key={reason}>
                    <div className={styles.reasonCardLabel}>강점</div>
                    <div className={styles.reasonCardDetail}>{reason}</div>
                  </div>
                ))}
                {notice.weaknesses.map((reason) => (
                  <div className={`${styles.reasonCard} ${styles.warn}`} key={reason}>
                    <div className={styles.reasonCardLabel}>주의</div>
                    <div className={styles.reasonCardDetail}>{reason}</div>
                  </div>
                ))}
                {notice.strategySuggestion ? (
                  <div className={styles.reasonCard}>
                    <div className={styles.reasonCardLabel}>제안</div>
                    <div className={styles.reasonCardDetail}>
                      {notice.strategySuggestion}
                    </div>
                  </div>
                ) : null}
              </div>
            </>
          ) : null}

          {otherNotices.length > 0 ? (
            <>
              <div className={styles.sectionTitle}>다른 추천 공고와 비교</div>
              <div className={styles.comparisonTable}>
                <div className={`${styles.comparisonRow} ${styles.comparisonHeaderRow}`}>
                  <div>공고</div>
                  <div>적합</div>
                  <div>규모</div>
                  <div>마감</div>
                </div>
                <div className={`${styles.comparisonRow} ${styles.current}`}>
                  <div>{notice.title}</div>
                  <div className={styles.comparisonScore}>{notice.score ?? '-'}</div>
                  <div>{notice.amountLabel ?? '-'}</div>
                  <div>{notice.deadlineLabel}</div>
                </div>
                {otherNotices.map((item) => (
                  <div className={styles.comparisonRow} key={item.id}>
                    <div>{item.title}</div>
                    <div
                      className={
                        item.scoreLevel === 'medium' || item.scoreLevel === 'low'
                          ? `${styles.comparisonScore} ${styles.warn}`
                          : styles.comparisonScore
                      }
                    >
                      {item.score ?? '-'}
                    </div>
                    <div>{item.amountLabel ?? '-'}</div>
                    <div>{item.deadlineLabel}</div>
                  </div>
                ))}
              </div>
            </>
          ) : null}

          <div className={styles.sectionTitle} style={{ marginTop: 26 }}>
            신청 전 체크리스트
          </div>
          <div className={styles.checklist}>
            {APPLICATION_CHECKLIST.map((label) => (
              <label className={styles.checklistItem} key={label}>
                <span className={styles.checklistBox} />
                {label}
              </label>
            ))}
          </div>

          <div className={styles.disclaimer}>
            본 적합도는 AI 분석 결과이며 실제 선정 여부를 보장하지 않습니다.
            자격요건은 원문 공고를 반드시 확인하세요.
          </div>
        </div>
      </div>
    </div>
  )
}
