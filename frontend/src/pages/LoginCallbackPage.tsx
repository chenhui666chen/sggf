import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import { Alert, Box, CircularProgress, Container, Typography } from '@mui/material'

import { AppDispatch } from '@/store/store'
import { alipayLogin, wechatLogin } from '@/store/slices/authSlice'
import { clearOAuthContext, getStoredOAuthContext } from '@/utils/auth'

function normalizeCallbackError(error: unknown, fallback: string): string {
  if (typeof error === 'string' && error.trim()) {
    return error
  }

  if (error instanceof Error && error.message.trim()) {
    return error.message
  }

  return fallback
}

export default function LoginCallbackPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const handleCallback = async () => {
      const oauthError = searchParams.get('error_description') || searchParams.get('error')
      if (oauthError) {
        clearOAuthContext()
        setError(oauthError)
        return
      }

      const code = searchParams.get('code')
      const callbackState = searchParams.get('state')
      const { provider, state: storedState } = getStoredOAuthContext()

      if (!code) {
        clearOAuthContext()
        setError('缺少授权码')
        return
      }

      if (!provider) {
        clearOAuthContext()
        setError('缺少登录上下文，请重新发起登录')
        return
      }

      if (provider !== 'alipay' && provider !== 'wechat') {
        clearOAuthContext()
        setError('无效的登录提供方，请重新尝试')
        return
      }

      if (!callbackState || !storedState || callbackState !== storedState) {
        clearOAuthContext()
        setError('登录状态校验失败，请重新尝试')
        return
      }

      try {
        if (provider === 'alipay') {
          await dispatch(alipayLogin(code)).unwrap()
        } else {
          await dispatch(wechatLogin(code)).unwrap()
        }

        clearOAuthContext()
        navigate('/home', { replace: true })
      } catch (err) {
        clearOAuthContext()
        setError(normalizeCallbackError(err, '登录失败'))
      }
    }

    handleCallback()
  }, [dispatch, navigate, searchParams])

  if (error) {
    return (
      <Container maxWidth="sm">
        <Box
          sx={{
            display: 'flex',
            flexDirection: 'column',
            justifyContent: 'center',
            alignItems: 'center',
            minHeight: '100vh',
          }}
        >
          <Alert severity="error" sx={{ mb: 2 }}>
            {error}
          </Alert>
          <Typography variant="body2" color="text.secondary">
            <a href="/login" style={{ color: '#1976d2' }}>
              返回登录页面
            </a>
          </Typography>
        </Box>
      </Container>
    )
  }

  return (
    <Container maxWidth="sm">
      <Box
        sx={{
          display: 'flex',
          flexDirection: 'column',
          justifyContent: 'center',
          alignItems: 'center',
          minHeight: '100vh',
        }}
      >
        <CircularProgress size={60} sx={{ mb: 3 }} />
        <Typography variant="h6" gutterBottom>
          正在登录...
        </Typography>
        <Typography variant="body2" color="text.secondary">
          请稍候，我们正在校验您的身份
        </Typography>
      </Box>
    </Container>
  )
}
