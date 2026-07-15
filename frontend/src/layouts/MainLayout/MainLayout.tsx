import { Outlet } from 'react-router-dom'
import { AppHeader } from '../../components/AppHeader/AppHeader'

/** 랜딩 페이지를 제외한 모든 내부 페이지에 헤더를 공통으로 노출한다. */
export function MainLayout() {
  return (
    <>
      <AppHeader />
      <Outlet />
    </>
  )
}
