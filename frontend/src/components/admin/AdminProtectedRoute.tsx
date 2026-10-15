import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useSelector } from 'react-redux'
import { RootState } from '@/store/store'
import { SessionPendingFallback, resolveProtectedRouteDecision } from '@/components/ProtectedRoute'

interface AdminProtectedRouteProps {
  children: ReactNode
  requiredRole?: 'admin' | 'super_admin'
}

export default function AdminProtectedRoute({ 
  children, 
  requiredRole = 'admin' 
}: AdminProtectedRouteProps) {
  const { isAuthenticated, user, sessionStatus } = useSelector((state: RootState) => state.auth)

  // 与 ProtectedRoute 共用恢复期判定：角色信息也是 /me 回来后才可用，
  // 提前判定会把硬刷新的管理员弹回登录页
  const decision = resolveProtectedRouteDecision({ sessionStatus, isAuthenticated })

  if (decision === 'pending') {
    return <SessionPendingFallback />
  }

  if (decision === 'redirect') {
    return <Navigate to="/login" replace />
  }

  const userRoles = (user as any)?.roles?.map((r: any) => r.code) || []
  const hasAdminRole = userRoles.includes('admin') || userRoles.includes('super_admin')
  const hasSuperAdminRole = userRoles.includes('super_admin')

  if (!hasAdminRole) {
    return <Navigate to="/" replace />
  }

  if (requiredRole === 'super_admin' && !hasSuperAdminRole) {
    return <Navigate to="/admin" replace />
  }

  return <>{children}</>
}
