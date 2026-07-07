import { useNavigate } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'
import { mockCompany } from '../../mock/company'
import { PATHS } from '../../routes/paths'
import styles from './MyPage.module.css'

export function MyPage() {
  const navigate = useNavigate()

  return (
    <div className={styles.page}>
      <AppHeader />
      <div className={styles.body}>
        <div className={styles.profile}>
          <span className={styles.avatar} />
          <div>
            <div className={styles.name}>{mockCompany.name}</div>
            <div className={styles.subtext}>카카오 계정으로 로그인됨</div>
          </div>
        </div>

        <div className={styles.infoList}>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>업종</span>
            <span className={styles.infoValue}>{mockCompany.industry}</span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>지역</span>
            <span className={styles.infoValue}>{mockCompany.region}</span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>설립연도</span>
            <span className={styles.infoValue}>{mockCompany.foundedYear}</span>
          </div>
          <div className={styles.infoRow}>
            <span className={styles.infoLabel}>기업 규모</span>
            <span className={styles.infoValue}>{mockCompany.size}</span>
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
          onClick={() => navigate(PATHS.LANDING)}
        >
          로그아웃
        </button>
      </div>
    </div>
  )
}
