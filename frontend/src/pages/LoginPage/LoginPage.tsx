import { redirectToKakaoLogin } from '../../utils/kakaoAuth'
import styles from './LoginPage.module.css'

export function LoginPage() {
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

        <div className={styles.divider} />

        <button
          type="button"
          className={styles.kakaoButton}
          onClick={redirectToKakaoLogin}
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
