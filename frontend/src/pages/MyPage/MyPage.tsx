import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { apiFetch } from '../../api/client'
import {
  getMyCompanyProfile,
  type CompanyProfile,
} from '../../api/companyProfile'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { PATHS } from '../../routes/paths'
import styles from './MyPage.module.css'

const EMPTY = '—'

export function MyPage() {
  const navigate = useNavigate()
  const [profile, setProfile] = useState<CompanyProfile | null>(null)
  const [loading, setLoading] = useState(true)

  // 마운트 시 본인 기업 프로필을 조회한다. 인증 쿠키가 없으면 apiFetch가
  // refresh 실패 후 로그인 페이지로 보낸다(여기서 별도 처리 불필요).
  useEffect(() => {
    let active = true
    getMyCompanyProfile()
      .then((data) => {
        if (active) setProfile(data)
      })
      .catch(() => {
        // 조회 실패 시 프로필 없음으로 둔다.
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
      await apiFetch('/api/auth/logout', { method: 'POST' })
    } catch {
      // 무시하고 이동한다.
    } finally {
      navigate(PATHS.LANDING)
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
              {profile?.representative_name ?? '내 기업 프로필'}
            </div>
            <div className={styles.subtext}>카카오 계정으로 로그인됨</div>
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

        <button
          type="button"
          className={styles.logoutButton}
          onClick={handleLogout}
        >
          로그아웃
        </button>
      </div>
    </div>
  )
}
