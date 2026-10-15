import { ReactNode } from 'react'
import { Navigate } from 'react-router-dom'
import { useSelector } from 'react-redux'
import { Box, CircularProgress } from '@mui/material'
import { RootState } from '@/store/store'
import type { SessionStatus } from '@/store/slices/authSlice'

interface ProtectedRouteProps {
  children: ReactNode
}

export type ProtectedRouteAction = 'pending' | 'grant' | 'redirect'

// 会话恢复落定前不做任何判定：令牌只在 httpOnly cookie 里，启动时 isAuthenticated 恒为 false，
// 立刻重定向会把硬刷新的已登录用户弹到登录页（恢复完成后 /me 已证实会话有效）。
export function resolveProtectedRouteDecision({
  sessionStatus,
  isAuthenticated,
}: {
  sessionStatus: SessionStatus
  isAuthenticated: boolean
}): ProtectedRouteAction {
  if (sessionStatus === 'checking') return 'pending'
  return isAuthenticated ? 'grant' : 'redirect'
}

export function SessionPendingFallback() {
  return (
    <Box
      sx={{
        display: 'flex',
        justifyContent: 'center',
        alignItems: 'center',
        minHeight: '100vh',
      }}
    >
      <CircularProgress size={28} />
    </Box>
  )
}

export default function ProtectedRoute({ children }: ProtectedRouteProps) {
  const { isAuthenticated, sessionStatus } = useSelector((state: RootState) => state.auth)

  const decision = resolveProtectedRouteDecision({ sessionStatus, isAuthenticated })

  if (decision === 'pending') {
    return <SessionPendingFallback />
  }

  if (decision === 'redirect') {
    return <Navigate to="/login" replace />
  }

  return <>{children}</>
}
