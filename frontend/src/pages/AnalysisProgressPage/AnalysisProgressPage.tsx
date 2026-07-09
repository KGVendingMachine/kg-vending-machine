import { Fragment, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import styles from './AnalysisProgressPage.module.css'

const STEP_LABELS = ['문서 추출', '내용 정규화', '매칭 스코어링', '결과 생성']

interface LogStage {
  threshold: number
  text: string
}

const LOG_STAGES: LogStage[] = [
  { threshold: 10, text: '✓ HWP 텍스트 추출 완료 (12,840자)' },
  { threshold: 25, text: '✓ 표준 스키마 정규화 완료 · 분야: 제조' },
  {
    threshold: 40,
    text: '→ 1차 필터링(원본 공고 JSON 기준 유사도) 시작 · 대상 공고 142건',
  },
  {
    threshold: 55,
    text: '✓ 1차 필터링 완료 · 142건 → 38건 통과 (분야·지역·마감 기준)',
  },
  {
    threshold: 65,
    text: '→ 2차 필터링(공고 PDF OCR → 벡터 DB 유사도 검색) 시작 · 38건 대상',
  },
  {
    threshold: 85,
    text: '✓ 2차 필터링 완료 · 38건 → 12건 통과 (사업계획서 유사도 상위)',
  },
  { threshold: 95, text: '→ AI 매칭 스코어링 진행 중… · 12건' },
  { threshold: 100, text: '✓ AI 매칭 스코어링 완료 · 결과 생성 완료' },
]

export function AnalysisProgressPage() {
  const navigate = useNavigate()
  const [progress, setProgress] = useState(0)

  useEffect(() => {
    const interval = setInterval(() => {
      setProgress((current) => {
        if (current >= 100) {
          clearInterval(interval)
          return 100
        }
        return Math.min(current + 4, 100)
      })
    }, 100)
    return () => clearInterval(interval)
  }, [])

  const complete = progress >= 100
  const visibleLogStages = LOG_STAGES.filter(
    (stage) => progress >= stage.threshold,
  )

  function stepStatus(stepIndex: number): 'done' | 'active' | 'pending' {
    if (complete) return 'done'
    if (stepIndex < 2) return 'done'
    if (stepIndex === 2) return 'active'
    return 'pending'
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>사업계획서를 분석하고 있어요</div>
        <div className={styles.subheading}>
          보통 1~2분 정도 걸려요. 창을 닫아도 분석은 계속됩니다.
        </div>

        <div className={styles.stepper}>
          {STEP_LABELS.map((label, index) => {
            const status = stepStatus(index)
            return (
              <Fragment key={label}>
                <div className={styles.step}>
                  <div className={`${styles.circle} ${styles[status]}`}>
                    {status === 'done'
                      ? '✓'
                      : status === 'active'
                        ? ''
                        : index + 1}
                  </div>
                  <div
                    className={
                      status === 'active'
                        ? `${styles.stepLabel} ${styles.activeLabel}`
                        : status === 'pending'
                          ? `${styles.stepLabel} ${styles.pendingLabel}`
                          : styles.stepLabel
                    }
                  >
                    {label}
                  </div>
                  <div className={`${styles.stepStatus} ${styles[status]}`}>
                    {status === 'done'
                      ? '완료'
                      : status === 'active'
                        ? '진행 중…'
                        : '대기'}
                  </div>
                </div>
                {index < STEP_LABELS.length - 1 ? (
                  <div
                    className={
                      stepStatus(index) === 'done'
                        ? `${styles.connector} ${styles.done}`
                        : styles.connector
                    }
                  />
                ) : null}
              </Fragment>
            )
          })}
        </div>

        <div className={styles.log}>
          <div className={styles.logHeader}>
            <span className={styles.logTitle}>진행 로그</span>
            <span className={styles.logPercent}>{progress}%</span>
          </div>
          <div className={styles.progressBar}>
            <div
              className={styles.progressFill}
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className={styles.logText}>
            {visibleLogStages.map((stage, index) => (
              <div
                key={stage.threshold}
                className={
                  index === visibleLogStages.length - 1 && !complete
                    ? styles.logLineActive
                    : styles.logLine
                }
              >
                {stage.text}
              </div>
            ))}
          </div>
          <div className={styles.logFootnote}>
            단계 실패 시 자동 재시도하며, 실패가 지속되면 재시도 버튼이
            표시됩니다.
          </div>
        </div>

        {complete ? (
          <button
            type="button"
            className={styles.resultButton}
            onClick={() => navigate(PATHS.RESULTS)}
          >
            결과 확인하기 →
          </button>
        ) : null}
      </div>
    </div>
  )
}
