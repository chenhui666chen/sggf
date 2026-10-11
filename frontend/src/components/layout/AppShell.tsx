/**
 * 全站共享外壳的连接层：把 redux 的 user、router 的 navigate / Outlet、登出动作灌进
 * 展示层 AppShellView。
 *
 * 这层是纯 glue，且 import authSlice（模块加载即读 localStorage），故按项目约定
 * （AdminLayout 亦然）不做静态单测，由 tsc + build + 浏览器验收兜底；可静态测的骨架
 * 契约都落在 AppShellView 上。
 *
 * 目前只做 full 变体（顶栏常驻）。沉浸页需要的 slim 浮动变体等真有页面消费时再加
 * （YAGNI）——现在加只是无法验证的投机代码。
 */
import { Outlet, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'

import AppShellView from './AppShellView'
import { performLogout } from '@/store/slices/authSlice'
import { AppDispatch, RootState } from '@/store/store'

export default function AppShell() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { user } = useSelector((state: RootState) => state.auth)

  const handleLogout = () => {
    dispatch(performLogout())
    navigate('/login')
  }

  return (
    <AppShellView user={user} onNavigate={(path) => navigate(path)} onLogout={handleLogout}>
      <Outlet />
    </AppShellView>
  )
}
