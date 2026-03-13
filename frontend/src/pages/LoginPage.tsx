import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Container,
  Divider,
  Fade,
  IconButton,
  InputAdornment,
  Paper,
  TextField,
  Typography,
  Zoom,
} from '@mui/material'
import {
  Chat,
  Email,
  Lock,
  Payment,
  RocketLaunch,
  Visibility,
  VisibilityOff,
} from '@mui/icons-material'

import { apiClient, extractApiErrorMessage } from '@/services/api'
import { RootState, AppDispatch } from '@/store/store'
import { clearError, login } from '@/store/slices/authSlice'
import {
  clearOAuthContext,
  generateOAuthState,
  storeOAuthContext,
  type OAuthProvider,
} from '@/utils/auth'

const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
const PHONE_PATTERN = /^1[3-9]\d{9}$/

function isValidLoginIdentifier(value: string) {
  const trimmed = value.trim()
  return (
    EMAIL_PATTERN.test(trimmed) ||
    PHONE_PATTERN.test(trimmed) ||
    (trimmed.length >= 2 && trimmed.length <= 50)
  )
}

export default function LoginPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { isLoading, error } = useSelector((state: RootState) => state.auth)

  const [showPassword, setShowPassword] = useState(false)
  const [formError, setFormError] = useState('')
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

    if (formError) {
      setFormError('')
    }

    if (error) {
      dispatch(clearError())
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const username = formData.username.trim()
    if (!isValidLoginIdentifier(username)) {
      setFormError('请输入有效的用户名、邮箱或手机号')
      return
    }

    const result = await dispatch(
      login({
        username,
        password: formData.password,
      }),
    )

    if (login.fulfilled.match(result)) {
      navigate('/home')
    }
  }

  const startOAuthLogin = async (provider: OAuthProvider) => {
    try {
      clearOAuthContext()
      const state = generateOAuthState()
      const redirectUri = `${window.location.origin}/login/callback`
      const response =
        provider === 'alipay'
          ? await apiClient.getAlipayAuthUrl({ redirect_uri: redirectUri, state })
          : await apiClient.getWechatAuthUrl({ redirect_uri: redirectUri, state })

      const authUrl = response.data?.auth_url
      if (!authUrl) {
        setFormError('未获取到有效的第三方登录地址')
        return
      }

      storeOAuthContext(provider, state)
      window.location.href = authUrl
    } catch (oauthError) {
      clearOAuthContext()
      setFormError(await extractApiErrorMessage(oauthError, '第三方登录初始化失败'))
    }
  }

  return (
    <Box
      sx={{
        minHeight: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        position: 'relative',
        overflow: 'hidden',
        padding: { xs: 2, sm: 3, md: 4 },
        '&::before': {
          content: '""',
          position: 'absolute',
          inset: 0,
          background:
            'url("data:image/svg+xml,%3Csvg width=\'60\' height=\'60\' viewBox=\'0 0 60 60\' xmlns=\'http://www.w3.org/2000/svg\'%3E%3Cg fill=\'none\' fill-rule=\'evenodd\'%3E%3Cg fill=\'%23ffffff\' fill-opacity=\'0.05\'%3E%3Cpath d=\'M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z\'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")',
          opacity: 0.3,
        },
      }}
    >
      <Box
        sx={{
          position: 'absolute',
          width: { xs: '300px', sm: '400px', md: '600px' },
          height: { xs: '300px', sm: '400px', md: '600px' },
          borderRadius: '50%',
          background: 'rgba(255, 255, 255, 0.1)',
          top: { xs: '-100px', md: '-200px' },
          right: { xs: '-100px', md: '-200px' },
          zIndex: 0,
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          width: { xs: '200px', sm: '300px', md: '400px' },
          height: { xs: '200px', sm: '300px', md: '400px' },
          borderRadius: '50%',
          background: 'rgba(255, 255, 255, 0.08)',
          bottom: { xs: '-50px', md: '-100px' },
          left: { xs: '-50px', md: '-100px' },
          zIndex: 0,
        }}
      />

      <Zoom in timeout={1000}>
        <Container
          maxWidth="sm"
          sx={{
            position: 'relative',
            zIndex: 1,
            px: { xs: 0, sm: 3 },
            width: '100%',
            maxWidth: { xs: '100%', sm: '600px' },
          }}
        >
          <Fade in timeout={1500}>
            <Paper
              elevation={24}
              sx={{
                p: { xs: 3, sm: 4, md: 5 },
                borderRadius: { xs: 3, sm: 4 },
                backdropFilter: 'blur(10px)',
                backgroundColor: 'rgba(255, 255, 255, 0.95)',
                boxShadow: {
                  xs: '0 10px 30px rgba(0, 0, 0, 0.2)',
                  md: '0 20px 60px rgba(0, 0, 0, 0.3)',
                },
                mx: { xs: 1, sm: 0 },
              }}
            >
              <Box sx={{ textAlign: 'center', mb: { xs: 3, sm: 4 } }}>
                <Zoom in timeout={2000}>
                  <Box
                    sx={{
                      width: { xs: 60, sm: 70, md: 80 },
                      height: { xs: 60, sm: 70, md: 80 },
                      mx: 'auto',
                      mb: { xs: 1.5, sm: 2 },
                      borderRadius: { xs: 2, sm: 3 },
                      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      boxShadow: '0 8px 24px rgba(102, 126, 234, 0.4)',
                    }}
                  >
                    <RocketLaunch sx={{ fontSize: { xs: 30, sm: 35, md: 40 }, color: '#fff' }} />
                  </Box>
                </Zoom>
                <Typography
                  variant="h4"
                  component="h1"
                  fontWeight="bold"
                  sx={{
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    backgroundClip: 'text',
                    WebkitBackgroundClip: 'text',
                    WebkitTextFillColor: 'transparent',
                    mb: 1,
                    fontSize: { xs: '1.75rem', sm: '2rem', md: '2.25rem' },
                  }}
                >
                  拾光工坊
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  欢迎回来，请登录您的账户
                </Typography>
              </Box>

              <Fade in={!!error || !!formError}>
                <Box>
                  <Alert
                    severity="error"
                    onClose={() => {
                      dispatch(clearError())
                      setFormError('')
                    }}
                    sx={{ mb: { xs: 2, sm: 3 } }}
                  >
                    {error || formError}
                  </Alert>
                </Box>
              </Fade>

              <Box component="form" onSubmit={handleSubmit} noValidate>
                <Fade in timeout={1000}>
                  <TextField
                    fullWidth
                    label="用户名 / 邮箱 / 手机号"
                    name="username"
                    value={formData.username}
                    onChange={handleChange}
                    required
                    autoComplete="username"
                    placeholder="请输入用户名、邮箱或手机号"
                    error={!!formError}
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <Email sx={{ color: '#667eea', fontSize: { xs: 20, sm: 24 } }} />
                        </InputAdornment>
                      ),
                    }}
                    sx={{
                      mb: { xs: 1.5, sm: 2 },
                      '& .MuiOutlinedInput-root': {
                        borderRadius: 2,
                        fontSize: { xs: '0.9375rem', sm: '1rem' },
                        minHeight: { xs: 48, sm: 56 },
                        '&:hover fieldset': {
                          borderColor: '#667eea',
                        },
                        '&.Mui-focused fieldset': {
                          borderColor: '#667eea',
                        },
                      },
                    }}
                  />
                </Fade>

                <Fade in timeout={1200}>
                  <TextField
                    fullWidth
                    label="密码"
                    name="password"
                    type={showPassword ? 'text' : 'password'}
                    value={formData.password}
                    onChange={handleChange}
                    required
                    autoComplete="current-password"
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <Lock sx={{ color: '#667eea', fontSize: { xs: 20, sm: 24 } }} />
                        </InputAdornment>
                      ),
                      endAdornment: (
                        <InputAdornment position="end">
                          <IconButton
                            onClick={() => setShowPassword((prev) => !prev)}
                            edge="end"
                            size="medium"
                            sx={{ padding: { xs: 1, sm: 1.5 } }}
                          >
                            {showPassword ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
                          </IconButton>
                        </InputAdornment>
                      ),
                    }}
                    sx={{
                      mb: { xs: 2, sm: 3 },
                      '& .MuiOutlinedInput-root': {
                        borderRadius: 2,
                        fontSize: { xs: '0.9375rem', sm: '1rem' },
                        minHeight: { xs: 48, sm: 56 },
                        '&:hover fieldset': {
                          borderColor: '#667eea',
                        },
                        '&.Mui-focused fieldset': {
                          borderColor: '#667eea',
                        },
                      },
                    }}
                  />
                </Fade>

                <Fade in timeout={1400}>
                  <Button
                    fullWidth
                    variant="contained"
                    type="submit"
                    size="large"
                    disabled={isLoading || !formData.username.trim() || !formData.password}
                    sx={{
                      py: { xs: 1.5, sm: 1.8 },
                      mb: { xs: 2, sm: 3 },
                      borderRadius: 2,
                      fontSize: { xs: '0.9375rem', sm: '1rem' },
                      fontWeight: 'bold',
                      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      boxShadow: '0 4px 14px rgba(102, 126, 234, 0.4)',
                      minHeight: { xs: 48, sm: 56 },
                      '&:hover': {
                        boxShadow: '0 6px 20px rgba(102, 126, 234, 0.6)',
                        transform: 'translateY(-2px)',
                      },
                      '&:disabled': {
                        background: 'rgba(0, 0, 0, 0.12)',
                        color: 'rgba(0, 0, 0, 0.26)',
                      },
                      transition: 'all 0.3s ease',
                    }}
                  >
                    {isLoading ? '登录中...' : '登录'}
                  </Button>
                </Fade>

                <Fade in timeout={1500}>
                  <Box sx={{ textAlign: 'right', mb: { xs: 2, sm: 3 } }}>
                    <Link
                      to="/forgot-password"
                      style={{
                        color: '#667eea',
                        textDecoration: 'none',
                        fontWeight: 'bold',
                        fontSize: '0.875rem',
                      }}
                    >
                      找回密码
                    </Link>
                  </Box>
                </Fade>
              </Box>

              <Divider
                sx={{
                  my: { xs: 2, sm: 3 },
                  '&::before, &::after': {
                    borderColor: 'rgba(0, 0, 0, 0.12)',
                  },
                }}
              >
                <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 'medium' }}>
                  或使用以下方式登录
                </Typography>
              </Divider>

              <Fade in timeout={1600}>
                <Box
                  sx={{
                    display: 'flex',
                    gap: { xs: 1.5, sm: 2 },
                    mb: { xs: 2, sm: 3 },
                    flexDirection: { xs: 'column', sm: 'row' },
                  }}
                >
                  <Button
                    fullWidth
                    variant="outlined"
                    startIcon={<Payment />}
                    onClick={() => void startOAuthLogin('alipay')}
                    sx={{
                      py: { xs: 1.2, sm: 1.5 },
                      borderRadius: 2,
                      borderColor: '#1677FF',
                      color: '#1677FF',
                      minHeight: { xs: 48, sm: 52 },
                      '&:hover': {
                        borderColor: '#1677FF',
                        backgroundColor: 'rgba(22, 119, 255, 0.08)',
                        transform: 'translateY(-2px)',
                        boxShadow: '0 4px 12px rgba(22, 119, 255, 0.3)',
                      },
                      transition: 'all 0.3s ease',
                    }}
                  >
                    支付宝
                  </Button>
                  <Button
                    fullWidth
                    variant="outlined"
                    startIcon={<Chat />}
                    onClick={() => void startOAuthLogin('wechat')}
                    sx={{
                      py: { xs: 1.2, sm: 1.5 },
                      borderRadius: 2,
                      borderColor: '#07C160',
                      color: '#07C160',
                      minHeight: { xs: 48, sm: 52 },
                      '&:hover': {
                        borderColor: '#07C160',
                        backgroundColor: 'rgba(7, 193, 96, 0.08)',
                        transform: 'translateY(-2px)',
                        boxShadow: '0 4px 12px rgba(7, 193, 96, 0.3)',
                      },
                      transition: 'all 0.3s ease',
                    }}
                  >
                    微信
                  </Button>
                </Box>
              </Fade>

              <Fade in timeout={1800}>
                <Box sx={{ textAlign: 'center' }}>
                  <Typography variant="body2" color="text.secondary">
                    还没有账户？{' '}
                    <Link
                      to="/register"
                      style={{
                        color: '#667eea',
                        textDecoration: 'none',
                        fontWeight: 'bold',
                      }}
                    >
                      立即注册
                    </Link>
                  </Typography>
                </Box>
              </Fade>
            </Paper>
          </Fade>
        </Container>
      </Zoom>
    </Box>
  )
}
