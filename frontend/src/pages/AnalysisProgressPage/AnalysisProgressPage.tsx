import { Fragment, useEffect, useRef, useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { PATHS, resultsPath } from '../../routes/paths'
import {
  getBusinessPlanAnalysisStatus,
  startBusinessPlanAnalysis,
} from '../../api/businessPlanAnalysis'
import type { AnalysisStatus } from '../../api/businessPlanAnalysis'
import { createMatchLog, getActiveMatchLog, getMatchLog } from '../../api/matchLogs'
import { ApiError } from '../../api/client'
import { STEP_LABELS } from '../../constants/analysisSteps'

const POLL_INTERVAL_MS = 2000
// 일시적 네트워크 오류 1회로 실패 처리하지 않도록, 상태 조회(GET)가 연속으로
// 이 횟수 실패했을 때만 실패 UI로 전환한다 (사이에 성공하면 카운트 리셋).
const MAX_CONSECUTIVE_POLL_ERRORS = 3
// 폴링 상한. 잡 도중 서버가 죽으면 DB에 processing이 박제되므로 무한 폴링을
// 막는다. 백엔드 stale 기준(10분)과 맞춰, 초과 시 실패 UI를 띄우고 "다시
// 시도"(POST 재호출)가 서버의 stale 재선점으로 이어지게 한다.
const MAX_POLL_DURATION_MS = 10 * 60 * 1000

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
        { text: '→ 아래 버튼으로 결과를 확인할 수 있어요', active: true },
      ]
    case 'failed':
      return []
  }
}

type StepState = 'done' | 'active' | 'pending'

const CIRCLE_STATE_CLASS: Record<StepState, string> = {
  done: 'bg-success text-white',
  active: 'border-[3px] border-primary border-t-transparent animate-spin',
  pending: 'border-2 border-border-strong text-[#c8cdd3]',
}

const STEP_STATUS_TEXT_CLASS: Record<StepState, string> = {
  done: 'text-success',
  active: 'text-primary',
  pending: 'text-[#b0b5bb]',
}

function apiErrorDetail(error: unknown): string | null {
  if (error instanceof ApiError && error.body && typeof error.body === 'object') {
    const detail = (error.body as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  }
  return null
}

// 백그라운드 탭은 브라우저가 setTimeout을 스로틀링해 폴링이 실제로는 몇 분씩
// 밀릴 수 있다 — 탭이 다시 보이는 순간엔 대기를 끊고 바로 재확인하게 한다.
function waitForNextPoll(ms: number): Promise<void> {
  return new Promise((resolve) => {
    const timer = setTimeout(finish, ms)
    function onVisible() {
      if (document.visibilityState === 'visible') finish()
    }
    function finish() {
      clearTimeout(timer)
      document.removeEventListener('visibilitychange', onVisible)
      resolve()
    }
    document.addEventListener('visibilitychange', onVisible)
  })
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
  const [matchError, setMatchError] = useState<string | null>(null)
  // 방금 실행으로 만들어진 매칭 로그 id. 매칭 완료 시 "결과 보기" 버튼이
  // 이 id 기준으로 결과 페이지로 보낸다.
  const [matchedLogId, setMatchedLogId] = useState<number | null>(null)

  // handleStartMatch는 useEffect가 아니라 버튼 클릭으로 시작하는 긴 폴링
  // 루프라, 언마운트(페이지 이탈) 후에도 setState가 계속 불리는 걸 막으려면
  // 별도 취소 플래그가 필요하다.
  const matchCancelledRef = useRef(false)
  useEffect(() => {
    // 마운트마다 false로 되돌린다 — StrictMode(dev)는 마운트 → cleanup →
    // 재마운트로 도는데 ref는 재마운트에도 보존되므로, 리셋이 없으면 cleanup이
    // 세운 true가 그대로 남아 이후 매칭 폴링이 첫 줄에서 조용히 빠져나가
    // 화면이 '매칭 중'에 영구히 멈춘다.
    matchCancelledRef.current = false
    return () => {
      matchCancelledRef.current = true
    }
  }, [])

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

    // 백그라운드 탭에서 setTimeout이 스로틀링되는 동안 화면이 멈춰 보이는 걸
    // 막는다 — 탭이 다시 보이면 예약된 타이머를 끊고 바로 재확인한다.
    function onVisible() {
      if (document.visibilityState !== 'visible' || cancelled || timer == null) return
      clearTimeout(timer)
      poll()
    }
    document.addEventListener('visibilitychange', onVisible)

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
      document.removeEventListener('visibilitychange', onVisible)
    }
  }, [businessPlanId, navigate, attempt])

  function handleRetry() {
    setPhase('starting')
    setError(null)
    setAttempt((current) => current + 1)
  }

  function matchFail(message: string) {
    if (matchCancelledRef.current) return
    // 매칭 실행 실패는 분석 실패와 달리 완료 화면으로 되돌려 다시 시도하게 한다.
    setPhase('analyzed')
    setMatchError(message)
  }

  // 매칭 로그가 completed/failed가 될 때까지 폴링하고 화면 국면을 갱신한다.
  // 새 실행(handleStartMatch)과 새로고침 후 복구(아래 useEffect)가 공유한다 —
  // logId는 방금 만든 실행이거나 서버에서 복구한 진행 중 실행이다.
  //
  // 매칭(OCR·정규화·임베딩·LLM 판정)은 실측 몇 분까지 걸려(2026-07-15) 서버가
  // 즉시 processing으로 응답하고 백그라운드에서 계속 돈다 —
  // getBusinessPlanAnalysisStatus 폴링과 같은 패턴으로 완료를 기다린다.
  async function pollMatchLog(logId: number) {
    const startedAt = Date.now()
    let consecutiveErrors = 0
    for (;;) {
      if (matchCancelledRef.current) return
      if (Date.now() - startedAt > MAX_POLL_DURATION_MS) {
        matchFail('매칭이 예상보다 오래 걸리고 있어요. 다시 시도해 주세요.')
        return
      }

      let current
      try {
        current = await getMatchLog(logId)
        consecutiveErrors = 0
      } catch {
        if (matchCancelledRef.current) return
        consecutiveErrors += 1
        if (consecutiveErrors >= MAX_CONSECUTIVE_POLL_ERRORS) {
          matchFail(
            '진행 상황을 확인하지 못했어요. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.',
          )
          return
        }
        await waitForNextPoll(POLL_INTERVAL_MS)
        continue
      }

      if (matchCancelledRef.current) return
      if (current.run_status === 'completed') break
      if (current.run_status === 'failed') {
        matchFail('매칭에 실패했어요. 잠시 후 다시 시도해 주세요.')
        return
      }
      await waitForNextPoll(POLL_INTERVAL_MS)
    }

    if (matchCancelledRef.current) return
    setMatchedLogId(logId)
    setPhase('matched')
  }

  async function handleStartMatch() {
    if (businessPlanId == null || phase === 'matching') return
    setPhase('matching')
    setMatchError(null)

    try {
      // 같은 계획서로 이미 매칭이 도는 중이면 서버가 새 잡을 만들지 않고 그
      // 진행 중 로그를 그대로 돌려준다(멱등) — 그 id를 폴링에 이어붙인다.
      const log = await createMatchLog(businessPlanId)
      console.log('공고 매칭 로그 (match_log):', log)
      await pollMatchLog(log.id)
    } catch (err) {
      matchFail(
        apiErrorDetail(err) ?? '매칭을 시작하지 못했어요. 잠시 후 다시 시도해 주세요.',
      )
    }
  }

  // 새로고침·재접속으로 화면 state가 초기화되면 분석 완료(analyzed) 시점으로
  // 되돌아온다. 그때 서버에 이 계획서로 진행 중인 매칭이 있으면(백엔드가 유저당
  // 1건으로 제한) 그 로그를 폴링에 이어붙여 '매칭 중' 화면으로 복구한다 — 새
  // 잡을 만들지 않으므로 임베딩·LLM 호출이 중복 실행되지 않는다.
  useEffect(() => {
    if (phase !== 'analyzed' || businessPlanId == null) return
    let cancelled = false
    void (async () => {
      try {
        const active = await getActiveMatchLog(businessPlanId)
        // cancelled: StrictMode 이중 실행/이탈 가드. 첫 실행의 cleanup이
        // 세운 cancelled를 보고 빠져, 폴링 루프가 두 개 뜨지 않게 한다.
        if (cancelled || matchCancelledRef.current || active == null) return
        if (active.run_status === 'processing') {
          setPhase('matching')
          void pollMatchLog(active.id)
        }
      } catch {
        // 복구용 조회 실패는 조용히 무시한다 — 사용자가 버튼으로 직접 매칭을
        // 시작하면 되고, 복구는 어디까지나 편의 기능이다.
      }
    })()
    return () => {
      cancelled = true
    }
  }, [phase, businessPlanId])

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
    <div className="flex flex-1 flex-col">
      <div className="mx-auto box-border w-full max-w-[1000px] px-15 py-12">
        <div className="text-[22px] font-extrabold tracking-[-0.5px]">
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
        <div className="mt-1.5 text-sm text-muted">
          {analyzed
            ? '공고 매칭을 시작해보세요. 지난 매칭 기록은 상단 "이전 기록" 메뉴에서 볼 수 있어요.'
            : phase === 'matched'
              ? '공고 매칭이 완료됐어요. 아래 버튼으로 결과를 확인하세요.'
              : '보통 1~2분 정도 걸려요. 창을 닫아도 분석은 계속됩니다.'}
        </div>

        <div className="mt-11 flex items-center">
          {STEP_LABELS.map((label, index) => {
            const status = stepStatus(index)
            return (
              <Fragment key={label}>
                <div className="flex w-[140px] shrink-0 flex-col items-center gap-2.5">
                  <div
                    className={`flex h-11 w-11 items-center justify-center rounded-full font-bold ${CIRCLE_STATE_CLASS[status]}`}
                  >
                    {status === 'done'
                      ? '✓'
                      : status === 'active'
                        ? ''
                        : index + 1}
                  </div>
                  <div
                    className={
                      status === 'active'
                        ? 'text-[13px] font-bold text-primary'
                        : status === 'pending'
                          ? 'text-[13px] font-bold text-faint'
                          : 'text-[13px] font-bold'
                    }
                  >
                    {label}
                  </div>
                  <div className={`text-[11px] ${STEP_STATUS_TEXT_CLASS[status]}`}>
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
                        ? 'h-0.5 flex-1 bg-success'
                        : 'h-0.5 flex-1 bg-border'
                    }
                  />
                ) : null}
              </Fragment>
            )
          })}
        </div>

        <div className="mt-11 rounded-md border border-border bg-surface-subtle px-6 py-5">
          <div className="mb-3.5 flex items-center justify-between">
            <span className="text-[13px] font-bold text-muted">진행 상황</span>
            <span className="text-[13px] font-bold text-primary">{progress}%</span>
          </div>
          <div className="mb-4 h-1.5 overflow-hidden rounded-[3px] bg-border">
            <div
              className="h-full bg-primary transition-[width] duration-200 ease-linear"
              style={{ width: `${progress}%` }}
            />
          </div>
          <div className="text-[13px] text-muted">
            {failed ? (
              <div className="py-0.5">{error}</div>
            ) : (
              logLines.map((line) => (
                <div
                  key={line.text}
                  className={line.active ? 'py-0.5 font-semibold text-primary' : 'py-0.5'}
                >
                  {line.text}
                </div>
              ))
            )}
          </div>
          <div className="mt-4 text-xs text-faint">
            연결이 잠시 끊겨도 자동으로 다시 확인해요. 분석이 실패하면 다시
            시도 버튼이 나타나요.
          </div>
        </div>

        {matchStage ? (
          <>
            {matchError ? (
              <div className="mt-5 rounded-md border border-[#fecaca] bg-[#fef2f2] px-4 py-3 text-[13px] text-[#b91c1c]">
                {matchError}
              </div>
            ) : null}
            <button
              type="button"
              className={
                phase === 'matched'
                  ? 'h-12 cursor-pointer rounded border border-border-strong bg-white px-7 text-[15px] font-semibold text-muted'
                  : 'mt-7 h-12 cursor-pointer rounded bg-primary px-7 text-[15px] font-bold text-white'
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

            {phase === 'matched' && matchedLogId != null ? (
              <button
                type="button"
                className="ml-3 h-12 cursor-pointer rounded border-0 bg-primary px-7 text-[15px] font-bold text-white"
                onClick={() => navigate(resultsPath(matchedLogId))}
              >
                결과 보기 →
              </button>
            ) : null}
          </>
        ) : null}
        {failed ? (
          <div className="mt-7 flex gap-3">
            <button
              type="button"
              className="h-12 cursor-pointer rounded bg-primary px-7 text-[15px] font-bold text-white"
              onClick={handleRetry}
            >
              다시 시도
            </button>
            <button
              type="button"
              className="h-12 cursor-pointer rounded border border-border-strong bg-white px-7 text-[15px] font-semibold text-muted"
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
