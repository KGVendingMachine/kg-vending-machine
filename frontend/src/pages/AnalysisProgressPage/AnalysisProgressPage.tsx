import { Fragment, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import {
  getBusinessPlanAnalysisStatus,
  startBusinessPlanAnalysis,
} from '../../api/businessPlanAnalysis'
import type { AnalysisStatus } from '../../api/businessPlanAnalysis'
import styles from './AnalysisProgressPage.module.css'

// 백엔드가 아직 처리하는 단계(OCR 추출 → 정규화)만 노출한다. 매칭·결과 생성은
// 미구현이라 완료 시 결과 페이지로 이동하는 것으로 대신한다.
// 문구는 비개발자 사용자 기준 — "추출/정규화/스키마" 같은 용어를 쓰지 않는다.
const STEP_LABELS = ['문서 읽기', '내용 정리']

const POLL_INTERVAL_MS = 2000
// 일시적 네트워크 오류 1회로 실패 처리하지 않도록, 상태 조회(GET)가 연속으로
// 이 횟수 실패했을 때만 실패 UI로 전환한다 (사이에 성공하면 카운트 리셋).
const MAX_CONSECUTIVE_POLL_ERRORS = 3
// 폴링 상한. 잡 도중 서버가 죽으면 DB에 processing이 박제되므로 무한 폴링을
// 막는다. 백엔드 stale 기준(10분)과 맞춰, 초과 시 실패 UI를 띄우고 "다시
// 시도"(POST 재호출)가 서버의 stale 재선점으로 이어지게 한다.
const MAX_POLL_DURATION_MS = 10 * 60 * 1000

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
      return [{ text: '→ 올려주신 문서를 읽고 있어요…', active: true }]
    case 'normalizing':
      return [
        { text: '✓ 문서 읽기 완료', active: false },
        { text: '→ 사업 내용을 항목별로 정리하고 있어요…', active: true },
      ]
    case 'completed':
      return [
        { text: '✓ 문서 읽기 완료', active: false },
        { text: '✓ 사업 내용 정리 완료', active: false },
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
  // "다시 시도" 버튼이 증가시켜 effect를 다시 태운다. 0이면 첫 진입(현재
  // 상태 조회부터), 1 이상이면 명시적 재시도(바로 POST).
  const [attempt, setAttempt] = useState(0)

  useEffect(() => {
    // 업로드를 거치지 않고 직접 들어오면 분석할 대상이 없다 → 업로드로 되돌린다.
    if (businessPlanId == null) {
      navigate(PATHS.UPLOAD, { replace: true })
      return
    }
    const planId = businessPlanId

    // cleanup으로 취소 플래그를 세워, 언마운트 후 setState/추가 폴링을 막는다.
    // (StrictMode 이중 실행으로 POST가 두 번 나가도 서버가 멱등 처리한다.)
    let cancelled = false
    let timer: ReturnType<typeof setTimeout> | undefined
    const pollingStartedAt = Date.now()
    let consecutiveErrors = 0

    function fail(message: string) {
      setPhase('failed')
      setError(message)
    }

    /** 응답을 화면 국면에 반영하고, 종료 상태(완료/실패)면 true를 돌려준다. */
    function applyStatus(status: AnalysisStatus): boolean {
      if (status.status === 'completed') {
        setPhase('completed')
        return true
      }
      if (status.status === 'failed') {
        fail(status.error_message ?? '분석에 실패했어요.')
        return true
      }
      // pending | processing → 단계 표시 후 계속 폴링
      setPhase(status.step === 'normalizing' ? 'normalizing' : 'extracting')
      return false
    }

    const poll = async () => {
      if (cancelled) return
      if (Date.now() - pollingStartedAt > MAX_POLL_DURATION_MS) {
        fail('분석이 예상보다 오래 걸리고 있어요. 다시 시도해 주세요.')
        return
      }
      try {
        const status = await getBusinessPlanAnalysisStatus(planId)
        if (cancelled) return
        consecutiveErrors = 0
        if (applyStatus(status)) return
      } catch {
        if (cancelled) return
        consecutiveErrors += 1
        if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          fail('진행 상황을 확인하지 못했어요. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.')
          return
        }
      }
      timer = setTimeout(poll, POLL_INTERVAL_MS)
    }

    async function run() {
      try {
        if (attempt === 0) {
          // 첫 진입: 서버에 남아 있는 상태부터 확인한다. 새로고침·재접속 시
          // 이미 진행 중이면 POST 없이 폴링만 이어붙고, 완료면 바로 완료 UI.
          const current = await getBusinessPlanAnalysisStatus(planId)
          if (cancelled) return
          if (current.status != null) {
            if (applyStatus(current)) return
            timer = setTimeout(poll, POLL_INTERVAL_MS)
            return
          }
          // status null → 아직 분석 이력이 없는 plan → 아래에서 시작
        }
        // 미시작 첫 진입이거나 "다시 시도" → 분석 시작 요청(서버가 멱등 처리)
        const started = await startBusinessPlanAnalysis(planId)
        if (cancelled) return
        if (applyStatus(started)) return
        timer = setTimeout(poll, POLL_INTERVAL_MS)
      } catch {
        if (cancelled) return
        fail('분석을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.')
      }
    }

    run()

    return () => {
      cancelled = true
      if (timer) clearTimeout(timer)
    }
  }, [businessPlanId, navigate, attempt])

  function handleRetry() {
    setPhase('starting')
    setError(null)
    setAttempt((current) => current + 1)
  }

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
            <span className={styles.logTitle}>진행 상황</span>
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
            연결이 잠시 끊겨도 자동으로 다시 확인해요. 분석이 실패하면 다시
            시도 버튼이 나타나요.
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
          <div className={styles.failedActions}>
            <button
              type="button"
              className={styles.resultButton}
              onClick={handleRetry}
            >
              다시 시도
            </button>
            <button
              type="button"
              className={styles.secondaryButton}
              onClick={() => navigate(PATHS.UPLOAD)}
            >
              다시 업로드하기
            </button>
          </div>
        ) : null}
      </div>
    </div>
  )
}
