import { Fragment, useEffect, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS, resultsPath } from '../../routes/paths'
import {
  getBusinessPlanAnalysisStatus,
  startBusinessPlanAnalysis,
} from '../../api/businessPlanAnalysis'
import type { AnalysisStatus } from '../../api/businessPlanAnalysis'
import {
  createMatchLog,
  formatMatchLogDate,
  listMatchLogs,
  listMatchResults,
} from '../../api/matchLogs'
import type { MatchLog } from '../../api/matchLogs'
import { ApiError } from '../../api/client'
import { STEP_LABELS } from '../../constants/analysisSteps'
import styles from './AnalysisProgressPage.module.css'

const POLL_INTERVAL_MS = 2000
// 일시적 네트워크 오류 1회로 실패 처리하지 않도록, 상태 조회(GET)가 연속으로
// 이 횟수 실패했을 때만 실패 UI로 전환한다 (사이에 성공하면 카운트 리셋).
const MAX_CONSECUTIVE_POLL_ERRORS = 3
// 폴링 상한. 잡 도중 서버가 죽으면 DB에 processing이 박제되므로 무한 폴링을
// 막는다. 백엔드 stale 기준(10분)과 맞춰, 초과 시 실패 UI를 띄우고 "다시
// 시도"(POST 재호출)가 서버의 stale 재선점으로 이어지게 한다.
const MAX_POLL_DURATION_MS = 10 * 60 * 1000

// 이전 매칭 기록 한 페이지 크기. "더보기"를 누를 때마다 이만큼 이어붙인다.
const MATCH_LOG_PAGE_SIZE = 5

// 화면 진행 국면. 분석 단계는 백엔드 status/step을 매핑하고, analyzed부터는
// 이 페이지의 매칭 실행 흐름(대기 → 실행 → 완료)이다. 매칭이 끝나도 결과로
// 바로 이동하지 않고, 새 기록이 리스트 맨 위에 추가된 걸 보고 유저가 직접
// 클릭해 결과 페이지로 간다.
type Phase =
  | 'starting'
  | 'extracting'
  | 'normalizing'
  | 'analyzed'
  | 'matching'
  | 'matched'
  | 'failed'

const PHASE_PERCENT: Record<Phase, number> = {
  starting: 5,
  extracting: 20,
  normalizing: 40,
  analyzed: 50,
  matching: 75,
  matched: 100,
  failed: 100,
}

// 매칭 스텁이 즉시 끝나 단계 전환이 안 보이므로, "공고 매칭" 단계를 최소 이
// 시간은 노출한다. 실제 스코어링이 붙으면(폴링 전환) 제거한다.
const MIN_MATCHING_VISIBLE_MS = 1200

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
    case 'analyzed':
      return [
        { text: '✓ 문서 읽기 완료', active: false },
        { text: '✓ 사업 내용 정리 완료', active: false },
        { text: '→ 아래 버튼으로 지원 공고 매칭을 시작할 수 있어요', active: false },
      ]
    case 'matching':
      return [
        { text: '✓ 문서 읽기 완료', active: false },
        { text: '✓ 사업 내용 정리 완료', active: false },
        { text: '→ 사업 내용에 맞는 지원 공고를 찾고 있어요…', active: true },
      ]
    case 'matched':
      return [
        { text: '✓ 문서 읽기 완료', active: false },
        { text: '✓ 사업 내용 정리 완료', active: false },
        { text: '✓ 공고 매칭 완료', active: false },
        { text: '→ 아래 매칭 기록 맨 위에 새 결과가 추가됐어요', active: true },
      ]
    case 'failed':
      return []
  }
}

function apiErrorDetail(error: unknown): string | null {
  if (error instanceof ApiError && error.body && typeof error.body === 'object') {
    const detail = (error.body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return null
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
  // 유저의 이전 매칭 실행 기록. 분석 완료 화면에서 리스트로 보여줘 지난
  // 결과로 바로 이동할 수 있게 한다. null이면 아직 로딩 전/실패.
  const [matchLogs, setMatchLogs] = useState<MatchLog[] | null>(null)
  // 마지막 페이지 응답이 꽉 찼으면(=PAGE_SIZE) 더 있을 수 있다고 보고
  // "더보기"를 노출한다. 개수가 정확히 배수로 끝나면 한 번 더 눌러 빈
  // 응답을 받고서야 사라지는데, 총 개수 API 없이 감수하는 트레이드오프.
  const [hasMoreLogs, setHasMoreLogs] = useState(false)
  const [loadingMoreLogs, setLoadingMoreLogs] = useState(false)
  const [matchError, setMatchError] = useState<string | null>(null)
  // 방금 실행으로 만들어진 로그 id. 리스트 맨 위 항목에 NEW 강조를 붙여
  // 유저가 새 결과가 생겼음을 인지하고 클릭해 이동하게 한다.
  const [newMatchLogId, setNewMatchLogId] = useState<number | null>(null)

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
        console.log('##### 사업계획서 분석 결과 (analysis_json):', status.analysis_json)
        setPhase('analyzed')
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

  useEffect(() => {
    // 이전 매칭 기록은 부가 정보라 실패해도 페이지 흐름을 막지 않는다(무시).
    let cancelled = false
    listMatchLogs(MATCH_LOG_PAGE_SIZE, 0)
      .then((logs) => {
        if (cancelled) return
        setMatchLogs(logs)
        setHasMoreLogs(logs.length === MATCH_LOG_PAGE_SIZE)
      })
      .catch(() => {})
    return () => {
      cancelled = true
    }
  }, [])

  async function handleLoadMoreLogs() {
    if (matchLogs == null || loadingMoreLogs) return
    setLoadingMoreLogs(true)
    try {
      const more = await listMatchLogs(MATCH_LOG_PAGE_SIZE, matchLogs.length)
      setMatchLogs([...matchLogs, ...more])
      setHasMoreLogs(more.length === MATCH_LOG_PAGE_SIZE)
    } catch {
      // 실패해도 버튼은 남아 있어 다시 누르면 재시도된다.
    } finally {
      setLoadingMoreLogs(false)
    }
  }

  function handleRetry() {
    setPhase('starting')
    setError(null)
    setAttempt((current) => current + 1)
  }

  async function handleStartMatch() {
    if (businessPlanId == null || phase === 'matching') return
    setPhase('matching')
    setMatchError(null)
    const startedAt = Date.now()
    try {
      const log = await createMatchLog(businessPlanId)
      console.log('공고 매칭 로그 (match_log):', log)
      const results = await listMatchResults(log.id)
      console.log('공고 매칭 결과 (match_results):', results)
      const remain = MIN_MATCHING_VISIBLE_MS - (Date.now() - startedAt)
      if (remain > 0) {
        await new Promise((resolve) => setTimeout(resolve, remain))
      }
      // 결과 페이지로 바로 이동하지 않는다. 새 로그를 리스트 맨 위에 붙이고
      // NEW로 강조해, 유저가 기록이 생긴 걸 확인하고 직접 클릭해 이동한다.
      setMatchLogs((current) => [log, ...(current ?? [])])
      setNewMatchLogId(log.id)
      setPhase('matched')
    } catch (err) {
      // 매칭 실행 실패는 분석 실패와 달리 완료 화면으로 되돌려 다시 시도하게 한다.
      setPhase('analyzed')
      setMatchError(
        apiErrorDetail(err) ?? '매칭을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.',
      )
    }
  }

  const analyzed = phase === 'analyzed'
  const failed = phase === 'failed'
  // 분석 완료 이후(매칭 대기/실행/완료)에는 매칭 버튼과 기록 리스트를 계속
  // 보여준다 — 매칭 중에도 리스트가 사라지지 않는다.
  const matchStage =
    analyzed || phase === 'matching' || phase === 'matched'
  const progress = PHASE_PERCENT[phase]
  const logLines = buildLogLines(phase)

  function stepStatus(stepIndex: number): 'done' | 'active' | 'pending' {
    if (phase === 'matched') return 'done'
    if (analyzed) return stepIndex < 2 ? 'done' : 'pending'
    if (phase === 'matching') {
      if (stepIndex < 2) return 'done'
      return stepIndex === 2 ? 'active' : 'pending'
    }
    const activeIndex = phase === 'normalizing' ? 1 : 0
    if (stepIndex < activeIndex) return 'done'
    if (stepIndex === activeIndex) return 'active'
    return 'pending'
  }

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.heading}>
          {analyzed
            ? '분석이 완료됐어요'
            : phase === 'matching'
              ? '지원 공고를 매칭하고 있어요'
              : phase === 'matched'
                ? '공고 매칭이 완료됐어요'
                : failed
                  ? '분석 중 문제가 발생했어요'
                  : '사업계획서를 분석하고 있어요'}
        </div>
        <div className={styles.subheading}>
          {analyzed
            ? '공고 매칭을 시작하거나, 이전 매칭 결과를 다시 볼 수 있어요.'
            : phase === 'matched'
              ? '매칭 기록 맨 위에 새 결과가 추가됐어요. 클릭해서 결과를 확인하세요.'
              : '보통 1~2분 정도 걸려요. 창을 닫아도 분석은 계속됩니다.'}
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

        {matchStage ? (
          <>
            {matchError ? (
              <div className={styles.matchError}>{matchError}</div>
            ) : null}
            <button
              type="button"
              className={
                phase === 'matched'
                  ? styles.secondaryButton
                  : styles.resultButton
              }
              onClick={handleStartMatch}
              disabled={phase === 'matching'}
            >
              {phase === 'matching'
                ? '공고 매칭 중…'
                : phase === 'matched'
                  ? '다시 매칭하기'
                  : '공고 매칭 시작하기 →'}
            </button>

            {matchLogs && matchLogs.length > 0 ? (
              <div className={styles.history}>
                <div className={styles.historyTitle}>
                  {phase === 'matched' ? '매칭 기록' : '이전 매칭 기록'}
                </div>
                <div className={styles.historySub}>
                  새로 매칭하지 않아도 지난 결과를 바로 볼 수 있어요.
                </div>
                <div className={styles.historyList}>
                  {matchLogs.map((log) => {
                    const isNew = log.id === newMatchLogId
                    return (
                      <button
                        type="button"
                        key={log.id}
                        className={
                          isNew
                            ? `${styles.historyItem} ${styles.historyItemNew}`
                            : styles.historyItem
                        }
                        onClick={() => navigate(resultsPath(log.id))}
                      >
                        {isNew ? (
                          <span className={styles.newBadge}>NEW</span>
                        ) : null}
                        <span className={styles.historyItemTitle}>
                          {log.business_plan_title ?? '사업계획서'}
                        </span>
                        <span className={styles.historyItemDate}>
                          {formatMatchLogDate(log.created_at)}
                        </span>
                        <span className={styles.historyItemArrow}>
                          결과 보기 →
                        </span>
                      </button>
                    )
                  })}
                </div>
                {hasMoreLogs ? (
                  <button
                    type="button"
                    className={styles.historyMore}
                    onClick={handleLoadMoreLogs}
                    disabled={loadingMoreLogs}
                  >
                    {loadingMoreLogs ? '불러오는 중…' : '+ 더보기'}
                  </button>
                ) : null}
              </div>
            ) : null}
          </>
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
