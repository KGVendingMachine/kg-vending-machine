import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMe, logout, withdrawAccount, type AuthUser } from '../../api/auth'
import { ApiError } from '../../api/client'
import {
  getMyCompanyProfile,
  type CompanyProfile,
} from '../../api/companyProfile'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { PATHS } from '../../routes/paths'

const EMPTY = '—'

const WITHDRAW_ERROR_FALLBACK =
  '탈퇴 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'

interface MyPageData {
  profile: CompanyProfile | null
  user: AuthUser | null
}

export function MyPage() {
  const navigate = useNavigate()
  const [showWithdrawConfirm, setShowWithdrawConfirm] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)

  // 마운트 시 본인 유저·기업 프로필을 조회한다. 인증 쿠키가 없으면 apiFetch가
  // refresh 실패 후 로그인 페이지로 보낸다(여기서 별도 처리 불필요).
  const { data, loading } = useFetchOnMount<MyPageData>(async () => {
    const [profileData, userData] = await Promise.all([
      getMyCompanyProfile().catch(() => null),
      getMe()
        .then((data) => {
          console.log('getMe() 응답:', data)
          return data
        })
        .catch((err) => {
          console.log('getMe() 실패:', err)
          return null
        }),
    ])
    return { profile: profileData, user: userData }
  }, [])
  const profile = data?.profile ?? null
  const user = data?.user ?? null

  async function handleLogout(): Promise<void> {
    // 서버가 인증 쿠키를 삭제하게 한다. 실패하더라도(이미 만료 등) 사용자
    // 의도는 로그아웃이므로 어느 경우든 루트 페이지로 보낸다.
    try {
      await logout()
    } catch {
      // 무시하고 이동한다.
    } finally {
      navigate(PATHS.LANDING)
    }
  }

  async function handleWithdraw(): Promise<void> {
    setWithdrawing(true)
    setWithdrawError(null)
    try {
      await withdrawAccount()
      navigate(PATHS.LANDING)
    } catch (error) {
      const message =
        error instanceof ApiError && typeof error.body === 'object'
          ? ((error.body as { detail?: string } | null)?.detail ?? null)
          : null
      setWithdrawError(message ?? WITHDRAW_ERROR_FALLBACK)
      setWithdrawing(false)
    }
  }

  const employeeCount =
    profile?.employee_count != null ? `${profile.employee_count}명` : EMPTY

  return (
    <div className="flex flex-1 flex-col">
      <div className="mx-auto box-border w-full max-w-[480px] p-10">
        <div className="mb-7 flex items-center gap-3.5">
          <span className="h-12 w-12 flex-shrink-0 rounded-full bg-[#e9edf2]" />
          <div>
            <div className="text-lg font-extrabold">
              {profile?.representative_name ?? user?.nickname ?? '내 기업 프로필'}
            </div>
            <div className="mt-0.5 text-[13px] text-muted">
              {user?.nickname ? `${user.nickname} · ` : ''}카카오 계정으로 로그인됨
            </div>
          </div>
        </div>

        <div className="mb-6 divide-y divide-border overflow-hidden rounded-md border border-border">
          <div className="flex justify-between px-4 py-3.5 text-sm">
            <span className="text-muted">대표자명</span>
            <span className="font-semibold">
              {loading ? '…' : (profile?.representative_name ?? EMPTY)}
            </span>
          </div>
          <div className="flex justify-between px-4 py-3.5 text-sm">
            <span className="text-muted">사업자등록번호</span>
            <span className="font-semibold">
              {loading ? '…' : (profile?.business_registration_number ?? EMPTY)}
            </span>
          </div>
          <div className="flex justify-between px-4 py-3.5 text-sm">
            <span className="text-muted">기업 규모</span>
            <span className="font-semibold">
              {loading ? '…' : (profile?.company_size ?? EMPTY)}
            </span>
          </div>
          <div className="flex justify-between px-4 py-3.5 text-sm">
            <span className="text-muted">상시근로자 수</span>
            <span className="font-semibold">{loading ? '…' : employeeCount}</span>
          </div>
          <button
            type="button"
            className="block w-full cursor-pointer border-0 bg-transparent p-3 text-center text-sm font-semibold text-primary"
            onClick={() => navigate(PATHS.COMPANY_PROFILE)}
          >
            정보 수정
          </button>
        </div>

        <div className="mt-6 flex items-center justify-between gap-3">
          <button
            type="button"
            className="cursor-pointer border-0 bg-transparent p-1 text-xs text-faint underline underline-offset-2"
            onClick={() => setShowWithdrawConfirm(true)}
          >
            회원탈퇴
          </button>
          <button
            type="button"
            className="h-[46px] flex-1 cursor-pointer rounded border border-border-strong bg-white text-sm font-semibold text-muted"
            onClick={handleLogout}
          >
            로그아웃
          </button>
        </div>
      </div>

      {showWithdrawConfirm && (
        <div className="fixed inset-0 z-[100] flex items-center justify-center bg-black/40 p-6">
          <div className="w-[360px] max-w-full rounded-[10px] bg-white px-6 pt-7 pb-6 shadow-[0_8px_24px_rgba(0,0,0,0.15)]">
            <div className="text-[17px] font-extrabold">정말 탈퇴하시겠어요?</div>
            <div className="mt-2.5 text-[13px] leading-[1.6] text-muted">
              탈퇴 시 카카오 계정 연결이 해제되고 개인정보가 삭제됩니다.
              <br />
              작성한 기업 프로필과 매칭 기록은 복구할 수 없습니다.
            </div>
            {withdrawError && (
              <div className="mt-3.5 rounded-md bg-danger-soft px-3 py-2.5 text-xs leading-normal text-danger">
                {withdrawError}
              </div>
            )}
            <div className="mt-[22px] flex gap-2">
              <button
                type="button"
                className="h-11 flex-1 cursor-pointer rounded-md border border-border-strong bg-white text-sm font-semibold text-muted disabled:cursor-default disabled:opacity-60"
                onClick={() => {
                  setShowWithdrawConfirm(false)
                  setWithdrawError(null)
                }}
                disabled={withdrawing}
              >
                취소
              </button>
              <button
                type="button"
                className="h-11 flex-1 cursor-pointer rounded-md border-0 bg-danger text-sm font-bold text-white disabled:cursor-default disabled:opacity-60"
                onClick={handleWithdraw}
                disabled={withdrawing}
              >
                {withdrawing ? '탈퇴 처리 중…' : '탈퇴하기'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
