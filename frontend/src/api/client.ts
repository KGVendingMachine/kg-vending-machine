import { PATHS } from '../routes/paths'

// API 호출의 베이스 URL. 프로덕션(Vercel)에서는 빈 문자열('')로 두어 요청이
// 같은 오리진(Vercel 도메인)으로 나가게 하고, vercel.json의 rewrite가 이를
// 백엔드로 프록시한다 → 브라우저는 HTTPS 오리진만 보므로 mixed content가 없다.
// 로컬 개발에서만 localhost:8000 백엔드를 직접 가리킨다. VITE_API_BASE_URL을
// 명시하면 항상 그 값을 쓴다(빈 문자열도 유효한 값으로 취급).
export const API_BASE_URL =
  import.meta.env.VITE_API_BASE_URL ??
  (import.meta.env.DEV ? 'http://localhost:8000' : '')

const REFRESH_PATH = '/api/auth/refresh'

/**
 * API 요청 실패(2xx가 아님)를 나타낸다. status로 분기하고, 파싱된 응답 본문은
 * body에 담아 호출부가 서버의 detail 메시지 등을 쓸 수 있게 한다.
 */
export class ApiError extends Error {
  readonly status: number
  readonly body: unknown

  constructor(status: number, body: unknown) {
    super(`API ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.body = body
  }
}

async function parseBody(res: Response): Promise<unknown> {
  if (res.status === 204) return undefined
  const text = await res.text()
  if (!text) return undefined
  try {
    return JSON.parse(text)
  } catch {
    return text
  }
}

async function request<T>(path: string, init: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    // 인증 쿠키(httpOnly)를 브라우저가 자동으로 실어 보내게 한다. 이 래퍼를
    // 거치면 매 요청마다 신경 쓸 필요가 없다.
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...init.headers,
    },
  })

  const body = await parseBody(res)
  if (!res.ok) throw new ApiError(res.status, body)
  return body as T
}

interface ApiFetchOptions extends RequestInit {
  /**
   * refresh까지 실패했을 때 로그인 페이지로 강제 이동할지 여부(기본 true).
   * 비로그인 상태에서도 도는 백그라운드 조회(북마크 목록 등)는 false로 두어
   * 방문자를 로그인 페이지로 쫓아내지 않는다.
   */
  redirectOn401?: boolean
}

/**
 * 인증 쿠키를 자동 전송하는 공용 API 호출 래퍼.
 *
 * 401을 받으면 쿠키 기반 refresh를 1회 시도하고, 성공하면 원래 요청을 다시
 * 보낸다(브라우저가 새 access_token 쿠키를 자동 전송). refresh도 실패하면
 * 로그인 페이지로 보낸다. refresh 요청 자체는 이 재시도 로직을 타지 않는다
 * (무한 루프 방지).
 */
export async function apiFetch<T>(
  path: string,
  options: ApiFetchOptions = {},
): Promise<T> {
  const { redirectOn401 = true, ...init } = options
  try {
    return await request<T>(path, init)
  } catch (error) {
    if (
      !(error instanceof ApiError) ||
      error.status !== 401 ||
      path === REFRESH_PATH
    ) {
      throw error
    }

    // access token 만료 추정 → 쿠키로 재발급 시도.
    try {
      await request<unknown>(REFRESH_PATH, { method: 'POST' })
    } catch {
      // 이미 로그인 페이지라면 다시 보낼 필요가 없다 — 헤더가 모든 페이지에
      // 떠 있어 로그인 페이지에서도 getMe()가 호출되는데, 여기서 무조건
      // 리다이렉트하면 새로고침이 반복되는 루프가 생긴다.
      if (window.location.pathname !== PATHS.LOGIN) {
        window.location.href = PATHS.LOGIN
      }
      throw error
    }
    return request<T>(path, init)
  }
}
