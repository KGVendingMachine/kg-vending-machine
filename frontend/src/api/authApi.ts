const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

export interface TokenResponse {
  access_token: string
  refresh_token: string
  token_type: string
}

/**
 * 카카오 인가 코드를 백엔드로 보내 자체 JWT 토큰 쌍을 발급받는다.
 * 백엔드가 카카오 토큰 교환·유저 upsert·JWT 발급을 모두 처리한다.
 */
export async function loginWithKakao(code: string): Promise<TokenResponse> {
  const response = await fetch(`${API_BASE_URL}/api/auth/kakao`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ code }),
  })

  if (!response.ok) {
    let detail = ''
    try {
      detail = (await response.json()).detail
    } catch {
      // 응답 본문이 JSON이 아닐 수 있음
    }
    throw new Error(detail || `로그인에 실패했습니다 (${response.status})`)
  }

  return (await response.json()) as TokenResponse
}
