import { NavLink } from 'react-router-dom'
import { mockCompany } from '../../mock/company'
import { PATHS } from '../../routes/paths'
import styles from './AppHeader.module.css'

function tabClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.tab} ${styles.active}` : styles.tab
}

export function AppHeader() {
  return (
    <header className={styles.header}>
      <span className={styles.logo}>KGVendingMachine</span>
      <NavLink to={PATHS.UPLOAD} className={tabClassName}>
        새 분석
      </NavLink>
      <NavLink to={PATHS.RESULTS} className={tabClassName}>
        추천 결과
      </NavLink>
      <NavLink to={PATHS.BOOKMARKS} className={tabClassName}>
        북마크
      </NavLink>
      <NavLink to={PATHS.MYPAGE} className={styles.right}>
        <span className={styles.company}>{mockCompany.name}</span>
        <span className={styles.avatar} />
      </NavLink>
    </header>
  )
}
