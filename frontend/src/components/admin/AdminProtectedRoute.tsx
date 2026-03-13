import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useSelector } from 'react-redux'
import { RootState } from '@/store/store'

interface AdminProtectedRouteProps {
  children: ReactNode
  requiredRole?: 'admin' | 'super_admin'
}

export default function AdminProtectedRoute({ 
  children, 
  requiredRole = 'admin' 
}: AdminProtectedRouteProps) {
  const { isAuthenticated, user } = useSelector((state: RootState) => state.auth)

  if (!isAuthenticated) {
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
