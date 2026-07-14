import { Fragment, useState } from 'react'
import {
  getSecondaryFilteringLog,
  type SecondaryFilteringNoticeLog,
} from '../../api/matchLogs'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'

const SKIP_REASON_LABEL: Record<string, string> = {
  no_text: '원문 텍스트 없음',
  embedding_failed: '임베딩 호출 실패',
}

const STATUS_LABEL: Record<string, string> = {
  충족: '충족',
  미충족: '미충족',
  정보부족: '정보부족',
}

const STATUS_CLASS: Record<string, string> = {
  충족: 'text-success',
  미충족: 'text-danger',
  정보부족: 'text-faint',
}

/** 판정 근거(reasons)를 펼쳐볼 수 있는 행. LLM 판정을 안 거친 공고는 이 행을
 * 렌더링하지 않는다(reasons가 비어 있어 펼쳐도 보여줄 게 없음). */
function ReasonsRow({ notice }: { notice: SecondaryFilteringNoticeLog }) {
  const [expanded, setExpanded] = useState(false)
  if (!notice.llm_judged || !notice.reasons?.length) return null

  return (
    <tr className="border-t border-[#eef0f2] bg-surface-subtle/40">
      <td colSpan={5} className="px-3 py-1.5">
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 text-faint underline-offset-2 hover:underline"
          onClick={() => setExpanded((current) => !current)}
        >
          판정 근거 {notice.reasons.length}건 {expanded ? '접기 ▴' : '보기 ▾'}
        </button>
        {expanded ? (
          <ul className="mt-1.5 list-none space-y-1">
            {notice.reasons.map((reason, index) => (
              <li key={index} className="flex gap-2">
                <span
                  className={`shrink-0 font-semibold ${STATUS_CLASS[reason.status] ?? ''}`}
                >
                  [{STATUS_LABEL[reason.status] ?? reason.status}]
                </span>
                <span>
                  {reason.criterion}
                  {reason.evidence ? (
                    <span className="text-faint"> — {reason.evidence}</span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </td>
    </tr>
  )
}

interface SecondaryFilteringLogPanelProps {
  matchLogId: number
}

/**
 * 2차 필터링(docs/matching-pipeline.md 4단계 — 공고 PDF·사업계획서 원문
 * 임베딩 유사도 + 유사도 상위 후보 LLM 판정, docs/secondary-filtering-llm-judge-guide.md)
 * 실행 로그를 보여준다. 이 매칭 실행이 이 기능 도입 이전에 만들어졌으면
 * 로그가 없어(getSecondaryFilteringLog가 null 반환) 아무것도 렌더링하지 않는다.
 */
export function SecondaryFilteringLogPanel({
  matchLogId,
}: SecondaryFilteringLogPanelProps) {
  const [expanded, setExpanded] = useState(false)
  const { data: log, loading } = useFetchOnMount(
    () => getSecondaryFilteringLog(matchLogId),
    [matchLogId],
  )

  if (loading || !log) return null

  return (
    <div className="border-b border-[#eef0f2] bg-white px-6 py-2.5 text-[12.5px]">
      <button
        type="button"
        className="flex w-full cursor-pointer items-center gap-2 border-0 bg-transparent p-0 text-left"
        onClick={() => setExpanded((current) => !current)}
      >
        <span className="font-bold text-ink">2차 필터링 로그</span>
        <span className="text-muted">
          후보 {log.candidate_count}건 중 임베딩 검색 {log.embedded_count}건
          {log.judged_count ? ` · LLM 판정 ${log.judged_count}건` : ''}
          {log.score_stats
            ? ` · 점수 ${log.score_stats.min}~${log.score_stats.max} (평균 ${log.score_stats.avg})`
            : ''}
        </span>
        <span className="ml-auto text-faint">{expanded ? '접기 ▴' : '펼치기 ▾'}</span>
      </button>

      {expanded ? (
        <div className="mt-2.5 max-h-[220px] overflow-auto rounded border border-border">
          <table className="w-full border-collapse text-left">
            <thead>
              <tr className="bg-surface-subtle text-muted">
                <th className="px-3 py-2 font-semibold">공고</th>
                <th className="px-3 py-2 font-semibold">임베딩</th>
                <th className="px-3 py-2 font-semibold">LLM 판정</th>
                <th className="px-3 py-2 font-semibold">2차 필터링 점수</th>
                <th className="px-3 py-2 font-semibold">스킵 사유</th>
              </tr>
            </thead>
            <tbody>
              {log.notices.map((notice) => (
                <Fragment key={notice.notice_id}>
                  <tr className="border-t border-[#eef0f2]">
                    <td className="max-w-[280px] truncate px-3 py-2" title={notice.title ?? ''}>
                      {notice.title ?? `#${notice.notice_id}`}
                    </td>
                    <td className="px-3 py-2">
                      {notice.embedded ? (
                        <span className="font-semibold text-success">✓</span>
                      ) : (
                        <span className="text-faint">–</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {notice.llm_judged ? (
                        <span className="font-semibold text-success">✓</span>
                      ) : (
                        <span className="text-faint">–</span>
                      )}
                    </td>
                    <td className="px-3 py-2">
                      {notice.secondary_filter_score != null
                        ? notice.secondary_filter_score.toFixed(2)
                        : '–'}
                      {notice.excluded ? (
                        <span className="ml-1.5 rounded bg-danger/10 px-1 py-0.5 text-[11px] font-semibold text-danger">
                          제외요건 확정
                        </span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 text-faint">
                      {notice.skip_reason
                        ? (SKIP_REASON_LABEL[notice.skip_reason] ?? notice.skip_reason)
                        : '–'}
                    </td>
                  </tr>
                  <ReasonsRow notice={notice} />
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
