import { useEffect, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import { Container, Box, Typography, CircularProgress, Alert } from '@mui/material'
import { AppDispatch } from '@/store/store'
import { alipayLogin, wechatLogin } from '@/store/slices/authSlice'

export default function LoginCallbackPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const handleCallback = async () => {
      const code = searchParams.get('code')
      const provider = localStorage.getItem('oauth_provider')

      if (!code) {
        setError('缺少授权码')
        return
      }

      if (!provider) {
        setError('缺少登录提供商信息')
        return
      }

      try {
        let result
        if (provider === 'alipay') {
          result = await dispatch(alipayLogin(code))
        } else if (provider === 'wechat') {
          result = await dispatch(wechatLogin(code))
        } else {
          setError('无效的登录提供商')
          return
        }

        if (alipayLogin.fulfilled.match(result) || wechatLogin.fulfilled.match(result)) {
          localStorage.removeItem('oauth_provider')
          navigate('/home')
        } else {
          setError(result.error?.message || '登录失败')
        }
      } catch (err) {
        setError(err instanceof Error ? err.message : '登录失败')
      }
    }

    handleCallback()
  }, [searchParams, navigate, dispatch])

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
          <Typography variant="body2" color="textSecondary">
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
        <Typography variant="body2" color="textSecondary">
          请稍候，我们正在验证您的身份
        </Typography>
      </Box>
    </Container>
  )
}
