const KAKAO_AUTHORIZE_URL = 'https://kauth.kakao.com/oauth/authorize'

/**
 * 브라우저를 카카오 로그인 페이지로 이동시킨다.
 * 로그인·동의가 끝나면 카카오가 VITE_KAKAO_REDIRECT_URI로 인가 코드를
 * 붙여 되돌려 보낸다(그 경로는 AuthCallbackPage가 처리).
 */
export function redirectToKakaoLogin(): void {
  const params = new URLSearchParams({
    client_id: import.meta.env.VITE_KAKAO_CLIENT_ID ?? '',
    redirect_uri: import.meta.env.VITE_KAKAO_REDIRECT_URI ?? '',
    response_type: 'code',
  })
  window.location.href = `${KAKAO_AUTHORIZE_URL}?${params.toString()}`
}
