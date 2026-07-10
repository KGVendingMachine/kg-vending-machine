import { Fragment, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import {
  getBusinessPlanAnalysisStatus,
  startBusinessPlanAnalysis,
} from '../../api/businessPlanAnalysis'
import styles from './AnalysisProgressPage.module.css'

// 백엔드가 아직 처리하는 단계(OCR 추출 → 정규화)만 노출한다. 매칭·결과 생성은
// 미구현이라 완료 시 결과 페이지로 이동하는 것으로 대신한다.
const STEP_LABELS = ['문서 추출', '내용 정규화']

const POLL_INTERVAL_MS = 2000

// 화면 진행 국면. 백엔드 status/step을 이 값으로 매핑한다.
type Phase = 'starting' | 'extracting' | 'normalizing' | 'completed' | 'failed'

const PHASE_PERCENT: Record<Phase, number> = {
  starting: 5,
  extracting: 30,
  normalizing: 70,
  completed: 100,
  failed: 100,
}

interface LogLine {
  text: string
  active: boolean
}

function buildLogLines(phase: Phase): LogLine[] {
  switch (phase) {
    case 'starting':
      return [{ text: '→ 분석을 준비하고 있어요…', active: true }]
    case 'extracting':
      return [{ text: '→ 문서에서 텍스트를 추출하고 있어요…', active: true }]
    case 'normalizing':
      return [
        { text: '✓ 문서 텍스트 추출 완료', active: false },
        { text: '→ 표준 스키마로 정규화하고 있어요…', active: true },
      ]
    case 'completed':
      return [
        { text: '✓ 문서 텍스트 추출 완료', active: false },
        { text: '✓ 표준 스키마 정규화 완료', active: false },
      ]
    case 'failed':
      return []
  }
}

export function AnalysisProgressPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const businessPlanId = (
    location.state as { businessPlanId?: number } | null
  )?.businessPlanId

  const [phase, setPhase] = useState<Phase>('starting')
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    // 업로드를 거치지 않고 직접 들어오면 분석할 대상이 없다 → 업로드로 되돌린다.
    if (businessPlanId == null) {
      navigate(PATHS.UPLOAD, { replace: true })
      return
    }

    // cleanup으로 취소 플래그를 세워, 언마운트 후 setState/추가 폴링을 막는다.
    // (개발 중 StrictMode에서는 effect가 두 번 실행돼 분석 요청이 두 번 나갈 수
    //  있는데, 이는 개발 전용 동작이라 운영 빌드에서는 한 번만 실행된다.)
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function run() {
      try {
        const { job_id } = await startBusinessPlanAnalysis(businessPlanId!)

        const poll = async () => {
          if (cancelled) return
          try {
            const status = await getBusinessPlanAnalysisStatus(
              businessPlanId!,
              job_id,
            )
            if (cancelled) return

            if (status.status === 'completed') {
              setPhase('completed')
              return
            }
            if (status.status === 'failed') {
              setPhase('failed')
              setError(status.error_message ?? '분석에 실패했어요.')
              return
            }
            // pending | processing → 단계 표시 후 다시 폴링
            setPhase(status.step === 'normalizing' ? 'normalizing' : 'extracting')
            timer = setTimeout(poll, POLL_INTERVAL_MS)
          } catch {
            if (cancelled) return
            setPhase('failed')
            setError('분석 상태를 불러오지 못했어요.')
          }
        }

        await poll()
      } catch {
        if (cancelled) return
        setPhase('failed')
        setError('분석을 시작하지 못했어요.')
      }
    }

    run()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [businessPlanId, navigate])

  const complete = phase === 'completed'
  const failed = phase === 'failed'
  const progress = PHASE_PERCENT[phase]
  const activeIndex = phase === 'normalizing' ? 1 : 0
  const logLines = buildLogLines(phase)

  function stepStatus(stepIndex: number): 'done' | 'active' | 'pending' {
    if (complete) return 'done'
    if (stepIndex < activeIndex) return 'done'
    if (stepIndex === activeIndex) return 'active'
    return 'pending'
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>
          {complete
            ? '분석이 완료됐어요'
            : failed
              ? '분석 중 문제가 발생했어요'
              : '사업계획서를 분석하고 있어요'}
        </div>
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
            {failed ? (
              <div className={styles.logLine}>{error}</div>
            ) : (
              logLines.map((line) => (
                <div
                  key={line.text}
                  className={line.active ? styles.logLineActive : styles.logLine}
                >
                  {line.text}
                </div>
              ))
            )}
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
        {failed ? (
          <button
            type="button"
            className={styles.resultButton}
            onClick={() => navigate(PATHS.UPLOAD)}
          >
            다시 업로드하기 →
          </button>
        ) : null}
      </div>
    </div>
  )
}
