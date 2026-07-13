import { apiFetch } from './client'

/** backend/app/schemas/auth.py UserResponse (GET /auth/me). 토큰·kakao_id 등은 제외. */
export interface AuthUser {
  id: number
  email: string | null
  name: string | null
  nickname: string | null
  role: string
  status: string
}

/** 현재 로그인한 유저 정보. 인증 쿠키가 없거나 만료되면 apiFetch가 401을 처리
 * (refresh 시도 → 실패 시 로그인 페이지 이동)하므로 호출부는 별도 처리가 필요 없다. */
export function getMe(): Promise<AuthUser> {
  return apiFetch<AuthUser>('/api/auth/me')
}

/** access/refresh 쿠키를 서버가 삭제한다. httpOnly라 JS에서 직접 지울 수 없다. */
export function logout(): Promise<void> {
  return apiFetch<void>('/api/auth/logout', { method: 'POST' })
}

/** 회원탈퇴. 카카오 연결 해제, 딸린 데이터 삭제, 계정 익명화를 서버가 한 번에 처리한다. */
export function withdrawAccount(): Promise<void> {
  return apiFetch<void>('/api/auth/me', { method: 'DELETE' })
}
