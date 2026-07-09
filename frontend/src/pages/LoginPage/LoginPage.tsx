import { useSearchParams } from 'react-router-dom'
import styles from './LoginPage.module.css'

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://localhost:8000'

const ERROR_MESSAGES: Record<string, string> = {
  kakao_auth_failed: '카카오 인증에 실패했습니다. 다시 시도해주세요.',
  inactive_account: '비활성화된 계정입니다. 고객센터에 문의해주세요.',
  invalid_state: '로그인 요청이 만료되었습니다. 다시 시도해주세요.',
  no_code: '카카오 로그인이 취소되었습니다.',
}

/**
 * 백엔드가 카카오 인가 요청을 직접 시작하도록 넘긴다. 백엔드가 로그인·
 * 토큰 발급을 모두 마치고 쿠키를 심은 뒤 이 앱의 /company-profile로
 * 리다이렉트한다(실패 시 이 페이지로 ?error=...와 함께 되돌아온다).
 */
function redirectToBackendKakaoLogin(): void {
  window.location.href = `${API_BASE_URL}/api/auth/kakao/login`
}

export function LoginPage() {
  const [searchParams] = useSearchParams()
  const errorCode = searchParams.get('error')
  const errorMessage = errorCode
    ? ERROR_MESSAGES[errorCode] ?? '로그인에 실패했습니다. 다시 시도해주세요.'
    : null

  return (
    <div className={styles.page}>
      <div className={styles.card}>
        <div className={styles.mark}>K</div>
        <div className={styles.title}>KGVendingMachine</div>
        <div className={styles.tagline}>
          사업계획서 한 장이면
          <br />
          맞는 정부지원사업을 찾아드려요
        </div>

        {errorMessage && <div className={styles.error}>{errorMessage}</div>}

        <div className={styles.divider} />

        <button
          type="button"
          className={styles.kakaoButton}
          onClick={redirectToBackendKakaoLogin}
        >
          <span className={styles.kakaoDot} />
          카카오로 시작하기
        </button>
        <div className={styles.notice}>
          카카오 계정으로만 가입·로그인합니다.
          <br />
          최초 로그인 시 자동으로 회원가입돼요.
        </div>

        <div className={styles.footnote}>
          로그인 시 <u>이용약관</u> 및 <u>개인정보처리방침</u>에 동의합니다
        </div>
      </div>
    </div>
  )
}
