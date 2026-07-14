import { NavLink } from 'react-router-dom'
import { getMe } from '../../api/auth'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { PATHS } from '../../routes/paths'

function tabClassName({ isActive }: { isActive: boolean }): string {
  return isActive
    ? 'text-sm font-semibold text-ink no-underline'
    : 'text-sm text-faint no-underline'
}

export function AppHeader() {
  // 로그인 정보 표시는 부가 기능이라 실패해도(error 무시) 헤더 자체는 그대로 보여준다.
  const { data: user } = useFetchOnMount(() => getMe(), [])
  const displayName = user?.nickname ?? user?.name ?? null

  return (
    <header className="flex h-14 flex-shrink-0 items-center gap-7 border-b border-border bg-white px-6">
      <span className="text-base font-extrabold">지원핏</span>
      <NavLink to={PATHS.UPLOAD} className={tabClassName}>
        새 분석
      </NavLink>
      <NavLink to={PATHS.RESULTS} className={tabClassName}>
        추천 결과
      </NavLink>
      <NavLink to={PATHS.BOOKMARKS} className={tabClassName}>
        북마크
      </NavLink>
      <NavLink
        to={PATHS.MYPAGE}
        className="ml-auto flex cursor-pointer items-center gap-2.5 no-underline"
      >
        <span className="text-[13px] text-muted">{displayName ?? '내 정보'}</span>
        <span className="h-8 w-8 rounded-full bg-[#e9edf2]" />
      </NavLink>
    </header>
  )
}
