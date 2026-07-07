import { useEffect, useRef } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { loginWithKakao } from '../../api/authApi'
import { PATHS } from '../../routes/paths'
import { consumeOAuthState } from '../../utils/kakaoAuth'
import { saveTokens } from '../../utils/token'
import styles from './AuthCallbackPage.module.css'

/**
 * 카카오가 redirect_uri로 되돌려 보낸 인가 코드를 받아 백엔드에 로그인
 * 요청을 보내고, 발급받은 토큰을 저장한 뒤 다음 화면으로 이동한다.
 */
export function AuthCallbackPage() {
  const navigate = useNavigate()
  const [searchParams] = useSearchParams()
  const handledRef = useRef(false)

  useEffect(() => {
    // 인가 코드는 일회용이라, StrictMode의 effect 이중 실행으로 두 번
    // 교환하지 않도록 한 번만 처리하도록 가드한다.
    if (handledRef.current) return
    handledRef.current = true

    const code = searchParams.get('code')
    const returnedState = searchParams.get('state')
    const savedState = consumeOAuthState()

    // CSRF 방지: 카카오가 돌려준 state가 우리가 보내며 저장해둔 값과
    // 일치해야 한다. code가 없거나 state가 어긋나면 위조된 콜백으로 보고
    // 로그인 화면으로 되돌린다.
    if (!code || !returnedState || returnedState !== savedState) {
      navigate(PATHS.LOGIN, { replace: true })
      return
    }

    loginWithKakao(code)
      .then((tokens) => {
        saveTokens(tokens.access_token, tokens.refresh_token)
        navigate(PATHS.COMPANY_PROFILE, { replace: true })
      })
      .catch(() => {
        navigate(PATHS.LOGIN, { replace: true })
      })
  }, [navigate, searchParams])

  return (
    <div className={styles.page}>
      <div className={styles.spinner} />
      <p className={styles.text}>로그인 처리 중...</p>
    </div>
  )
}
