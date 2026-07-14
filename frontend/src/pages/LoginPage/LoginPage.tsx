import { useSearchParams } from 'react-router-dom'
import { API_BASE_URL } from '../../api/client'
import { KAKAO_AUTH_ERROR_MESSAGES } from '../../constants/authErrors'

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
    ? KAKAO_AUTH_ERROR_MESSAGES[errorCode] ?? '로그인에 실패했습니다. 다시 시도해주세요.'
    : null

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <div className="flex w-[460px] max-w-full flex-col items-center rounded-lg border border-border bg-white px-11 py-14 text-center shadow-[0_1px_3px_rgba(0,0,0,0.06)]">
        <div className="mb-6 flex h-14 w-14 items-center justify-center rounded-lg border-2 border-ink text-[22px] font-extrabold">
          K
        </div>
        <div className="text-2xl font-extrabold tracking-[-0.5px]">
          KGVendingMachine
        </div>
        <div className="mt-2.5 text-[15px] leading-normal text-muted">
          사업계획서 한 장이면
          <br />
          맞는 정부지원사업을 찾아드려요
        </div>

        {errorMessage && (
          <div className="mt-5 w-full rounded-md bg-[#fdecec] px-4 py-3 text-[13px] leading-normal text-[#c0392b]">
            {errorMessage}
          </div>
        )}

        <div className="my-9 h-px w-full bg-[#eef0f2]" />

        <button
          type="button"
          className="flex h-[52px] w-full cursor-pointer items-center justify-center gap-2 rounded-lg bg-kakao text-base font-bold text-kakao-ink"
          onClick={redirectToBackendKakaoLogin}
        >
          <span className="inline-block h-5 w-5 rounded bg-kakao-ink opacity-85" />
          카카오로 시작하기
        </button>
        <div className="mt-4 text-xs leading-[1.6] text-faint">
          카카오 계정으로만 가입·로그인합니다.
          <br />
          최초 로그인 시 자동으로 회원가입돼요.
        </div>

        <div className="mt-auto pt-8 text-[11px] text-[#b0b5bb]">
          로그인 시 <u>이용약관</u> 및 <u>개인정보처리방침</u>에 동의합니다
        </div>
      </div>
    </div>
  )
}
