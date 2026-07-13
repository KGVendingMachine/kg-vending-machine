import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { getMe, logout, withdrawAccount, type AuthUser } from '../../api/auth'
import { ApiError } from '../../api/client'
import {
  getMyCompanyProfile,
  type CompanyProfile,
} from '../../api/companyProfile'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import styles from './MyPage.module.css'

const EMPTY = '—'

const WITHDRAW_ERROR_FALLBACK =
  '탈퇴 처리 중 문제가 발생했습니다. 잠시 후 다시 시도해주세요.'

export function MyPage() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState<CompanyProfile | null>(null)
  const [user, setUser] = useState<AuthUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [showWithdrawConfirm, setShowWithdrawConfirm] = useState(false)
  const [withdrawing, setWithdrawing] = useState(false)
  const [withdrawError, setWithdrawError] = useState<string | null>(null)

  // 마운트 시 본인 유저·기업 프로필을 조회한다. 인증 쿠키가 없으면 apiFetch가
  // refresh 실패 후 로그인 페이지로 보낸다(여기서 별도 처리 불필요).
  useEffect(() => {
    let active = true
    Promise.all([
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
      .then(([profileData, userData]) => {
        if (!active) return
        setProfile(profileData)
        setUser(userData)
      })
      .finally(() => {
        if (active) setLoading(false)
      })
    return () => {
      active = false
    }
  }, [])

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
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.profile}>
          <span className={styles.avatar} />
          <div>
            <div className={styles.name}>
              {profile?.representative_name ?? user?.nickname ?? '내 기업 프로필'}
            </div>
            <div className={styles.subtext}>
              {user?.nickname ? `${user.nickname} · ` : ''}카카오 계정으로 로그인됨
            </div>
          </div>
        </div>

        <div className={styles.infoList}>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>대표자명</span>
            <span className={styles.infoValue}>
              {loading ? '…' : (profile?.representative_name ?? EMPTY)}
            </span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>사업자등록번호</span>
            <span className={styles.infoValue}>
              {loading ? '…' : (profile?.business_registration_number ?? EMPTY)}
            </span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>기업 규모</span>
            <span className={styles.infoValue}>
              {loading ? '…' : (profile?.company_size ?? EMPTY)}
            </span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>상시근로자 수</span>
            <span className={styles.infoValue}>
              {loading ? '…' : employeeCount}
            </span>
          </div>
          <button
            type="button"
            className={styles.editLink}
            onClick={() => navigate(PATHS.COMPANY_PROFILE)}
          >
            정보 수정
          </button>
        </div>

        <div className={styles.actions}>
          <button
            type="button"
            className={styles.withdrawLink}
            onClick={() => setShowWithdrawConfirm(true)}
          >
            회원탈퇴
          </button>
          <button
            type="button"
            className={styles.logoutButton}
            onClick={handleLogout}
          >
            로그아웃
          </button>
        </div>
      </div>

      {showWithdrawConfirm && (
        <div className={styles.overlay}>
          <div className={styles.confirmCard}>
            <div className={styles.confirmTitle}>정말 탈퇴하시겠어요?</div>
            <div className={styles.confirmBody}>
              탈퇴 시 카카오 계정 연결이 해제되고 개인정보가 삭제됩니다.
              <br />
              작성한 기업 프로필과 매칭 기록은 복구할 수 없습니다.
            </div>
            {withdrawError && (
              <div className={styles.confirmError}>{withdrawError}</div>
            )}
            <div className={styles.confirmActions}>
              <button
                type="button"
                className={styles.cancelButton}
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
                className={styles.confirmWithdrawButton}
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
