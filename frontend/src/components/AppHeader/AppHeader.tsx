import { useEffect, useState } from 'react'
import { NavLink } from 'react-router-dom'
import { getMe } from '../../api/auth'
import { PATHS } from '../../routes/paths'
import styles from './AppHeader.module.css'

function tabClassName({ isActive }: { isActive: boolean }): string {
  return isActive ? `${styles.tab} ${styles.active}` : styles.tab
}

export function AppHeader() {
  const [displayName, setDisplayName] = useState<string | null>(null)

  useEffect(() => {
    let active = true
    getMe()
      .then((user) => {
        if (active) setDisplayName(user.nickname ?? user.name ?? null)
      })
      .catch(() => {
        // 로그인 정보 표시는 부가 기능이라 실패해도 헤더 자체는 그대로 보여준다.
      })
    return () => {
      active = false
    }
  }, [])

  return (
    <header className={styles.header}>
      <span className={styles.logo}>지원핏</span>
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
        <span className={styles.company}>{displayName ?? '내 정보'}</span>
        <span className={styles.avatar} />
      </NavLink>
    </header>
  )
}
