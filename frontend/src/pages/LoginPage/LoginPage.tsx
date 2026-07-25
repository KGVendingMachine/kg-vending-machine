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
    <div className="flex flex-1 items-center justify-center bg-[linear-gradient(180deg,#fafbfc,#fff)] p-6">
      <div className="relative w-[440px] max-w-full overflow-hidden rounded-2xl border border-[#e6e9ed] bg-white px-10 py-12 text-center shadow-[0_20px_50px_rgba(20,30,50,0.08)]">
        <div className="absolute inset-x-0 top-0 h-1 bg-[linear-gradient(90deg,#2f6df6,#7aa4ff)]" />

        <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-xl bg-[#15181c] text-xl font-extrabold text-white">
          K
        </div>
        <div className="text-[22px] font-extrabold tracking-[-0.5px]">
          KGVendingMachine
        </div>
        <div className="mt-2 text-[14px] leading-relaxed text-muted">
          사업계획서 한 장이면
          <br />
          맞는 정부지원사업을 찾아드려요
        </div>

        {errorMessage && (
          <div className="mt-5 flex items-start gap-2 rounded-lg bg-danger-soft px-4 py-3 text-left text-[13px] leading-normal text-danger">
            <span className="mt-px font-bold">!</span>
            <span>{errorMessage}</span>
          </div>
        )}

        <div className="my-8 flex items-center gap-3">
          <div className="h-px flex-1 bg-[#eef0f2]" />
          <span className="text-[11px] font-medium text-faint">간편 로그인</span>
          <div className="h-px flex-1 bg-[#eef0f2]" />
        </div>

        <button
          type="button"
          className="flex h-[52px] w-full cursor-pointer items-center justify-center gap-2 rounded-xl bg-kakao text-base font-bold text-kakao-ink shadow-[0_2px_8px_rgba(254,229,0,0.5)] transition hover:brightness-[0.97] active:scale-[0.99]"
          onClick={redirectToBackendKakaoLogin}
        >
          <span className="inline-block h-5 w-5 rounded-md bg-kakao-ink opacity-85" />
          카카오로 시작하기
        </button>
        <div className="mt-4 text-xs leading-[1.6] text-faint">
          카카오 계정으로만 가입·로그인합니다.
          <br />
          최초 로그인 시 자동으로 회원가입돼요.
        </div>

        <div className="mt-8 text-[11px] text-[#b0b5bb]">
          로그인 시 <u>이용약관</u> 및 <u>개인정보처리방침</u>에 동의합니다
        </div>
      </div>
    </div>
  )
}
