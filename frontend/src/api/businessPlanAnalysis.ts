import { apiFetch } from './client'

export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed'
/** processing 중 현재 단계 (OCR 추출 / 정규화). */
export type AnalysisStep = 'extracting' | 'normalizing'

/** POST .../analysis 응답 (202). 백그라운드 작업의 job_id를 돌려받는다. */
export interface AnalysisJobAccepted {
  business_plan_id: number
  job_id: string
  status: JobStatus
}

/** GET .../analysis/{job_id} 폴링 응답. */
export interface AnalysisStatus {
  business_plan_id: number
  job_id: string
  status: JobStatus
  step: AnalysisStep | null
  analysis_json: unknown | null
  analyzed_at: string | null
  error_message: string | null
}

/** 사업계획서 분석(OCR + 정규화)을 백그라운드로 시작한다. */
export function startBusinessPlanAnalysis(
  businessPlanId: number,
): Promise<AnalysisJobAccepted> {
  return apiFetch<AnalysisJobAccepted>(
    `/api/business-plans/${businessPlanId}/analysis`,
    { method: 'POST' },
  )
}

/** 분석 작업 상태·결과를 조회한다(폴링용). */
export function getBusinessPlanAnalysisStatus(
  businessPlanId: number,
  jobId: string,
): Promise<AnalysisStatus> {
  return apiFetch<AnalysisStatus>(
    `/api/business-plans/${businessPlanId}/analysis/${jobId}`,
  )
}
