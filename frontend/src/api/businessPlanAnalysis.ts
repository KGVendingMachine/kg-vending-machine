import { apiFetch } from './client'

/** 분석 잡 상태. null이면 아직 분석을 시작한 적 없는 plan. */
export type JobStatus = 'pending' | 'processing' | 'completed' | 'failed'
/** processing 중 현재 단계 (OCR 추출 / 정규화). */
export type AnalysisStep = 'extracting' | 'normalizing'

/**
 * POST/GET .../analysis 공통 응답. 상태가 business_plan 행에 저장되므로
 * job_id 없이 plan id만으로 조회하고, 창을 닫았다 다시 들어와도 복구된다.
 */
export interface AnalysisStatus {
  business_plan_id: number
  status: JobStatus | null
  step: AnalysisStep | null
  analysis_json: unknown | null
  analyzed_at: string | null
  error_message: string | null
}

/**
 * 사업계획서 분석(OCR + 정규화)을 백그라운드로 시작한다.
 * 이미 진행 중이면 서버가 새 잡을 만들지 않고 현재 상태를 돌려준다(멱등).
 */
export function startBusinessPlanAnalysis(
  businessPlanId: number,
): Promise<AnalysisStatus> {
  return apiFetch<AnalysisStatus>(
    `/api/business-plans/${businessPlanId}/analysis`,
    { method: 'POST' },
  )
}

/** 분석 작업 상태·결과를 조회한다(폴링용). */
export function getBusinessPlanAnalysisStatus(
  businessPlanId: number,
): Promise<AnalysisStatus> {
  return apiFetch<AnalysisStatus>(
    `/api/business-plans/${businessPlanId}/analysis`,
  )
}
