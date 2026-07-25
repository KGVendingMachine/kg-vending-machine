import { NavLink, useNavigate } from 'react-router-dom'
import { getMe } from '../../api/auth'
import { useFetchOnMount } from '../../hooks/useFetchOnMount'
import { PATHS } from '../../routes/paths'

function tabClassName({ isActive }: { isActive: boolean }): string {
  return isActive
    ? 'text-sm font-semibold text-ink no-underline'
    : 'text-sm text-faint no-underline'
}

export function AppHeader() {
  const navigate = useNavigate()
  // 로그인 정보 표시는 부가 기능이라 실패해도(error 무시) 헤더 자체는 그대로 보여준다.
  const { data: user } = useFetchOnMount(() => getMe(), [])
  const displayName = user?.nickname ?? user?.name ?? null

  function handleLogoClick() {
    navigate(user ? PATHS.UPLOAD : PATHS.LANDING)
  }

  return (
    <header className="flex h-14 flex-shrink-0 items-center gap-7 border-b border-border bg-white px-6">
      <button
        type="button"
        className="cursor-pointer border-0 bg-transparent p-0 text-base font-extrabold"
        onClick={handleLogoClick}
      >
        KGVendingMachine
      </button>
      <NavLink to={PATHS.UPLOAD} className={tabClassName}>
        새 분석
      </NavLink>
      <NavLink to={PATHS.RESULTS} className={tabClassName}>
        추천 결과
      </NavLink>
      <NavLink to={PATHS.MATCH_HISTORY} className={tabClassName}>
        이전 기록
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
