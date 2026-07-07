import { Navigate, useNavigate, useParams } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { ScoreGauge } from '../../components/ScoreGauge/ScoreGauge'
import { findNoticeById, notices } from '../../mock/notices'
import { PATHS } from '../../routes/paths'
import { useBookmarks } from '../../store/BookmarkContext'
import styles from './MatchDetailPage.module.css'

const APPLICATION_CHECKLIST = [
  { label: '사업자등록증·중소기업 확인서 준비', checked: true },
  { label: '자부담 자금조달 계획 수립', checked: false },
  { label: '설비 도입 견적서 확보', checked: false },
  { label: '온라인 신청서 제출', checked: false },
]

export function MatchDetailPage() {
  const { noticeId } = useParams<{ noticeId: string }>()
  const navigate = useNavigate()
  const notice = noticeId ? findNoticeById(noticeId) : undefined
  const { isBookmarked, toggleBookmark } = useBookmarks()

  if (!notice) {
    return <Navigate to={PATHS.RESULTS} replace />
  }

  const otherNotices = notices.filter((item) => item.id !== notice.id)
  const bookmarked = isBookmarked(notice.id)

  return (
    <div className={styles.page}>
      <AppHeader />

      <div className={styles.subnav}>
        <button
          type="button"
          className={styles.backLink}
          onClick={() => navigate(PATHS.RESULTS)}
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
          onClick={() => toggleBookmark(notice.id)}
        >
          {bookmarked ? '★ 북마크됨' : '☆ 북마크'}
        </button>
      </div>

      <div className={styles.banner}>
        <div className={styles.bannerMain}>
          <div className={styles.badges}>
            <span className={styles.category}>{notice.category}</span>
            <span className={styles.deadline}>
              {notice.deadlineLabel} · {notice.dueDateLabel} 마감
            </span>
          </div>
          <div className={styles.title}>{notice.title}</div>
          <div className={styles.org}>
            {notice.org} · {notice.amountLabel}
          </div>
          <div className={styles.target}>대상 기업 (주)그린테크 · 제조 · 소기업 · 2021 설립</div>
        </div>
        <div className={styles.gaugeCol}>
          <ScoreGauge score={notice.score} />
          <div className={styles.gaugeLevel}>
            적합도 {notice.scoreLevel === 'high' ? '매우 높음' : '보통'}
          </div>
          <div className={styles.gaugeRank}>
            {notice.score >= 90 ? '전체 추천 중 상위 3%' : '전체 추천 중 상위권'}
          </div>
        </div>
      </div>

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
        <div className={styles.diagnosisGrid}>
          {notice.summaryPoints.map((point) => (
            <div className={styles.summaryCard} key={point.label}>
              <div className={styles.diagnosisCardHeader}>
                <span className={styles.diagnosisLabel}>{point.label}</span>
              </div>
              <div className={styles.diagnosisMessage}>{point.detail}</div>
            </div>
          ))}
        </div>
      </div>

      <div className={styles.body}>
        <div className={styles.left}>
          <div className={styles.sectionTitle}>점수 구성</div>
          <div className={styles.sectionSubtitle}>
            항목별 가중치 기준으로 합산된 적합도입니다
          </div>

          {notice.scoreBreakdown.map((item) => (
            <div className={styles.scoreItem} key={item.label}>
              <div className={styles.scoreItemHeader}>
                <span className={styles.scoreItemLabel}>
                  {item.label} <span className={styles.scoreItemWeight}>{item.weightLabel}</span>
                </span>
                <span
                  className={
                    item.status === 'warn'
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
                    item.status === 'warn'
                      ? `${styles.scoreFill} ${styles.warn}`
                      : styles.scoreFill
                  }
                  style={{ width: `${(item.score / item.max) * 100}%` }}
                />
              </div>
              <div className={styles.scoreItemNote}>{item.note}</div>
            </div>
          ))}

          <div className={styles.divider} />

          <div className={styles.sectionTitle}>자격요건 대조</div>
          <div className={styles.requirements}>
            {notice.requirements.map((requirement) => (
              <div className={styles.requirementRow} key={requirement.label}>
                <span
                  className={
                    requirement.status === 'ok'
                      ? `${styles.requirementIcon} ${styles.ok}`
                      : `${styles.requirementIcon} ${styles.warn}`
                  }
                >
                  {requirement.status === 'ok' ? '✓' : '!'}
                </span>
                <div>
                  <b>{requirement.label}</b> —{' '}
                  <span className={styles.requirementDetail}>
                    {requirement.detail}
                  </span>
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className={styles.right}>
          <div className={styles.sectionTitle}>추천 근거</div>
          <div className={styles.reasonCards}>
            {notice.reasons.map((reason) => (
              <div
                className={
                  reason.tone === 'warn'
                    ? `${styles.reasonCard} ${styles.warn}`
                    : styles.reasonCard
                }
                key={reason.detail}
              >
                <div className={styles.reasonCardLabel}>
                  {reason.tone === 'warn' ? '주의' : '강점'}
                </div>
                <div className={styles.reasonCardDetail}>{reason.detail}</div>
              </div>
            ))}
          </div>

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
              <div className={styles.comparisonScore}>{notice.score}</div>
              <div>{notice.amountLabel.replace('최대 ', '')}</div>
              <div>{notice.deadlineLabel}</div>
            </div>
            {otherNotices.map((item) => (
              <div className={styles.comparisonRow} key={item.id}>
                <div>{item.title}</div>
                <div
                  className={
                    item.scoreLevel === 'medium'
                      ? `${styles.comparisonScore} ${styles.warn}`
                      : styles.comparisonScore
                  }
                >
                  {item.score}
                </div>
                <div>{item.amountLabel.replace('최대 ', '')}</div>
                <div>{item.deadlineLabel}</div>
              </div>
            ))}
          </div>

          <div className={styles.sectionTitle} style={{ marginTop: 26 }}>
            신청 전 체크리스트
          </div>
          <div className={styles.checklist}>
            {APPLICATION_CHECKLIST.map((item) => (
              <label className={styles.checklistItem} key={item.label}>
                <span
                  className={
                    item.checked
                      ? `${styles.checklistBox} ${styles.checked}`
                      : styles.checklistBox
                  }
                />
                {item.label}
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
