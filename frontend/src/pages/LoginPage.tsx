import { useState } from 'react'
import { useNavigate, Link } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Paper,
  TextField,
  Button,
  Box,
  Typography,
  Alert,
  Divider,
  IconButton,
} from '@mui/material'
import {
  AccountCircle,
  Lock,
  Chat,
  Payment,
} from '@mui/icons-material'
import { RootState, AppDispatch } from '@/store/store'
import { login, clearError } from '@/store/slices/authSlice'

export default function LoginPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { isLoading, error } = useSelector((state: RootState) => state.auth)
  const [formData, setFormData] = useState({
    username: '',
    password: '',
  })

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }))
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    const result = await dispatch(login(formData))
    if (login.fulfilled.match(result)) {
      navigate('/home')
    }
  }

  const handleAlipayLogin = async () => {
    try {
      localStorage.setItem('oauth_provider', 'alipay')
      const redirectUri = `${window.location.origin}/login/callback`
      const response = await fetch('/api/v1/auth/alipay/auth-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          redirect_uri: redirectUri,
        }),
      })
      const data = await response.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch (error) {
      console.error('Alipay login error:', error)
    }
  }

  const handleWechatLogin = async () => {
    try {
      localStorage.setItem('oauth_provider', 'wechat')
      const redirectUri = `${window.location.origin}/login/callback`
      const response = await fetch('/api/v1/auth/wechat/auth-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          redirect_uri: redirectUri,
        }),
      })
      const data = await response.json()
      if (data.auth_url) {
        window.location.href = data.auth_url
      }
    } catch (error) {
      console.error('WeChat login error:', error)
    }
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
          py: 4,
        }}
      >
        <Paper elevation={3} sx={{ p: 4, width: '100%' }}>
          <Typography variant="h4" component="h1" gutterBottom align="center" fontWeight="bold">
            拾光工坊
          </Typography>
          <Typography variant="body2" color="textSecondary" align="center" sx={{ mb: 3 }}>
            登录您的账户
          </Typography>

          {error && (
            <Alert severity="error" onClose={() => dispatch(clearError())} sx={{ mb: 2 }}>
              {error}
            </Alert>
          )}

          <Box component="form" onSubmit={handleSubmit} sx={{ mt: 2 }}>
            <TextField
              fullWidth
              label="用户名"
              name="username"
              value={formData.username}
              onChange={handleChange}
              margin="normal"
              required
              InputProps={{
                startAdornment: (
                  <AccountCircle sx={{ color: 'text.secondary', mr: 1 }} />
                ),
              }}
            />
            <TextField
              fullWidth
              label="密码"
              name="password"
              type="password"
              value={formData.password}
              onChange={handleChange}
              margin="normal"
              required
              InputProps={{
                startAdornment: (
                  <Lock sx={{ color: 'text.secondary', mr: 1 }} />
                ),
              }}
            />
            <Button
              fullWidth
              variant="contained"
              color="primary"
              type="submit"
              sx={{ mt: 3, py: 1.5 }}
              disabled={isLoading}
            >
              {isLoading ? '登录中...' : '登录'}
            </Button>
          </Box>

          <Divider sx={{ my: 3 }}>或</Divider>

          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'center' }}>
            <Button
              variant="outlined"
              startIcon={<Payment />}
              onClick={handleAlipayLogin}
              sx={{
                flex: 1,
                py: 1.5,
                borderColor: '#1677FF',
                color: '#1677FF',
                '&:hover': {
                  borderColor: '#1677FF',
                  backgroundColor: 'rgba(22, 119, 255, 0.04)',
                },
              }}
            >
              支付宝登录
            </Button>
            <Button
              variant="outlined"
              startIcon={<Chat />}
              onClick={handleWechatLogin}
              sx={{
                flex: 1,
                py: 1.5,
                borderColor: '#07C160',
                color: '#07C160',
                '&:hover': {
                  borderColor: '#07C160',
                  backgroundColor: 'rgba(7, 193, 96, 0.04)',
                },
              }}
            >
              微信登录
            </Button>
          </Box>

          <Box sx={{ mt: 3, textAlign: 'center' }}>
            <Typography variant="body2">
              还没有账户？{' '}
              <Link to="/register" style={{ color: '#1976d2', textDecoration: 'none' }}>
                注册
              </Link>
            </Typography>
          </Box>
        </Paper>
      </Box>
    </Container>
  )
}

