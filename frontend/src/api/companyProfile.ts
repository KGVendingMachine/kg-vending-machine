import { apiFetch } from './client'

/** 서버에 저장된 기업 프로필(본인). 아직 다루는 컬럼만 담는다. */
export interface CompanyProfile {
  id: number
  representative_name: string | null
  business_registration_number: string | null
  company_size: string | null
  employee_count: number | null
}

/** 부분 갱신 요청. 담은 필드만 저장되고 나머지는 그대로 유지된다. */
export interface CompanyProfileUpdate {
  representative_name?: string
  business_registration_number?: string
  company_size?: string
  employee_count?: number
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
