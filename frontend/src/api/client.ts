import { PATHS } from '../routes/paths'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

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
  init: RequestInit = {},
): Promise<T> {
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
      window.location.href = PATHS.LOGIN
      throw error
    }
    return request<T>(path, init)
  }
}
