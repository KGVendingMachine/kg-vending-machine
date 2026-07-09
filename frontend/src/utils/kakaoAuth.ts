const KAKAO_AUTHORIZE_URL = 'https://kauth.kakao.com/oauth/authorize'
const OAUTH_STATE_KEY = 'kakaoOAuthState'

/**
 * 브라우저를 카카오 로그인 페이지로 이동시킨다.
 * 로그인·동의가 끝나면 카카오가 VITE_KAKAO_REDIRECT_URI로 인가 코드를
 * 붙여 되돌려 보낸다(그 경로는 AuthCallbackPage가 처리).
 *
 * CSRF 방지를 위해 임의의 state를 만들어 요청에 싣고 sessionStorage에
 * 저장한다. 콜백에서 카카오가 되돌려준 state와 비교해, 우리가 시작하지
 * 않은 위조된 콜백을 걸러낸다.
 */
export function redirectToKakaoLogin(): void {
  const state = crypto.randomUUID()
  sessionStorage.setItem(OAUTH_STATE_KEY, state)

  const params = new URLSearchParams({
    client_id: import.meta.env.VITE_KAKAO_CLIENT_ID ?? '',
    redirect_uri: import.meta.env.VITE_KAKAO_REDIRECT_URI ?? '',
    response_type: 'code',
    state,
  })
  window.location.href = `${KAKAO_AUTHORIZE_URL}?${params.toString()}`
}

/**
 * 저장해둔 state를 반환하고 즉시 삭제한다(1회용). 콜백에서 카카오가
 * 돌려준 state와 비교하는 데 쓴다. 저장된 값이 없으면 null.
 */
export function consumeOAuthState(): string | null {
  const state = sessionStorage.getItem(OAUTH_STATE_KEY)
  sessionStorage.removeItem(OAUTH_STATE_KEY)
  return state
}
