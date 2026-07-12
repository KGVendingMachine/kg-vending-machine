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
}

/** 부분 갱신 요청. 담은 필드만 저장되고 나머지는 그대로 유지된다. */
export interface CompanyProfileUpdate {
  representative_name?: string
  business_registration_number?: string
  company_size?: string
  employee_count?: number
  /** 개인사업자 / 법인사업자 / 예비창업자 */
  business_type?: string
  /** 예비창업 / 초기창업 / 도약 / 소상공인 */
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
