import { ApiError } from './client'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

/** 사업계획서 파일 업로드 결과. 생성된 business_plan row의 id를 돌려받는다. */
export interface BusinessPlanUploadResult {
  id: number
}

/**
 * 사업계획서 파일을 업로드해 서버에 business_plan row를 생성한다.
 *
 * 파일 업로드는 multipart라 JSON 기반 공용 래퍼(apiFetch)를 타지 않고 직접
 * fetch한다. Content-Type을 지정하지 않아야 브라우저가 multipart 경계(boundary)를
 * 포함해 자동 설정한다. 인증 쿠키는 credentials로 실어 보낸다.
 *
 * OCR·정규화·매칭 같은 무거운 분석은 이 요청에서 하지 않는다(파일만 저장하고
 * id를 빠르게 반환). 분석은 이후 별도의 백그라운드 잡으로 돌린다.
 */
export async function uploadBusinessPlan(
  file: File,
): Promise<BusinessPlanUploadResult> {
  const formData = new FormData()
  formData.append('file', file)

  const res = await fetch(`${API_BASE_URL}/api/business-plans`, {
    method: 'POST',
    credentials: 'include',
    body: formData,
  })

  if (!res.ok) {
    const text = await res.text()
    let body: unknown = text
    try {
      body = JSON.parse(text)
    } catch {
      // 본문이 JSON이 아니면 원문 텍스트를 그대로 담는다.
    }
    throw new ApiError(res.status, body)
  }

  return (await res.json()) as BusinessPlanUploadResult
}
