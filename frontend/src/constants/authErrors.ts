/** 백엔드 카카오 OAuth 콜백 에러 코드 → 화면 표시 메시지 */
export const KAKAO_AUTH_ERROR_MESSAGES: Record<string, string> = {
  kakao_auth_failed: '카카오 인증에 실패했습니다. 다시 시도해주세요.',
  inactive_account: '비활성화된 계정입니다. 고객센터에 문의해주세요.',
  invalid_state: '로그인 요청이 만료되었습니다. 다시 시도해주세요.',
  no_code: '카카오 로그인이 취소되었습니다.',
}
