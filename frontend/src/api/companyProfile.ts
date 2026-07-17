import { apiFetch } from './client'

/** 서버에 저장된 기업 프로필(본인). 아직 다루는 컬럼만 담는다. */
export interface CompanyProfile {
  id: number
  representative_name: string | null
  business_registration_number: string | null
  company_size: string | null
  employee_count: number | null
  business_type: string | null
  company_stage: string | null
  industry_code: string | null
  region_code: string | null
  region_name: string | null
  founded_date: string | null
  /** 연매출 (원) */
  annual_revenue: number | null
  /** 매칭 전 확인 모달에서 지역·기업형태를 확인한 시각. null이면 모달 표시 대상 */
  matching_confirmed_at: string | null
}

/** 부분 갱신 요청. 담은 필드만 저장되고 나머지는 그대로 유지된다. */
export interface CompanyProfileUpdate {
  representative_name?: string
  business_registration_number?: string
  // company_size는 입력하지 않는다 — 업종·매출에서 서버가 산출한다.
  employee_count?: number
  /** 개인사업자 / 법인사업자 / 예비창업자 */
  business_type?: string
  /** 초기창업 / 중소기업 */
  company_stage?: string
  /** KSIC 대분류 코드 (A~S) */
  industry_code?: string
  /** 시/도 이름. region_code 변환은 서버가 수행한다. */
  region_name?: string
  /** 설립연도. founded_date 변환은 서버가 수행한다. */
  founded_year?: number
  /** 연매출 (원). 억원 입력창 환산은 프론트 담당. */
  annual_revenue?: number
}

/** 본인 기업 프로필 조회. 저장 전이면 null. */
export function getMyCompanyProfile(): Promise<CompanyProfile | null> {
  return apiFetch<CompanyProfile | null>('/api/company-profile/me')
}

/** 본인 기업 프로필 저장(부분 갱신). */
export function saveMyCompanyProfile(
  payload: CompanyProfileUpdate,
): Promise<CompanyProfile> {
  return apiFetch<CompanyProfile>('/api/company-profile/me', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

/**
 * 매칭 전 확인 모달에서 지역·기업형태가 맞다고 확인했음을 기록한다.
 * 기록되면 이후 매칭 시작 시 확인 모달을 건너뛴다.
 */
export function confirmMatchingProfile(): Promise<CompanyProfile> {
  return apiFetch<CompanyProfile>('/api/company-profile/me/matching-confirmation', {
    method: 'POST',
  })
}
