import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  Container,
  Fade,
  IconButton,
  InputAdornment,
  Paper,
  TextField,
  Typography,
  Zoom,
} from '@mui/material'
import Badge from '@mui/icons-material/Badge'
import LockReset from '@mui/icons-material/LockReset'
import MarkEmailUnread from '@mui/icons-material/MarkEmailUnread'
import Password from '@mui/icons-material/Password'
import RocketLaunch from '@mui/icons-material/RocketLaunch'
import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'

import { apiClient, extractApiErrorMessage } from '@/services/api'

const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
const PHONE_PATTERN = /^1[3-9]\d{9}$/

function isValidIdentity(value: string) {
  const trimmed = value.trim()
  return (
    EMAIL_PATTERN.test(trimmed) ||
    PHONE_PATTERN.test(trimmed) ||
    (trimmed.length >= 2 && trimmed.length <= 50)
  )
}

export default function ForgotPasswordPage() {
  const navigate = useNavigate()
  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [sendingCode, setSendingCode] = useState(false)
  const [submitting, setSubmitting] = useState(false)
  const [countdown, setCountdown] = useState(0)
  const [codeExpiresIn, setCodeExpiresIn] = useState(600)
  const [codeRequested, setCodeRequested] = useState(false)
  const [error, setError] = useState('')
  const [success, setSuccess] = useState('')
  const [formData, setFormData] = useState({
    account: '',
    code: '',
    newPassword: '',
    confirmPassword: '',
  })

  useEffect(() => {
    if (countdown <= 0) {
      return
    }

    const timer = window.setInterval(() => {
      setCountdown((prev) => (prev > 1 ? prev - 1 : 0))
    }, 1000)

    return () => {
      window.clearInterval(timer)
    }
  }, [countdown])

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }))

    if (name === 'account' && codeRequested) {
      setCodeRequested(false)
      setCountdown(0)
    }

    if (error) {
      setError('')
    }

    if (success) {
      setSuccess('')
    }
  }

  const handleRequestCode = async () => {
    const account = formData.account.trim()
    if (!isValidIdentity(account)) {
      setError('请输入有效的账号信息，支持用户名、邮箱或手机号')
      return
    }

    setSendingCode(true)
    try {
      const response = await apiClient.requestPasswordResetCode({ account })
      const message = response.data?.message || '如果账号存在且已绑定本地密码，验证码将发送到注册邮箱'
      const devCode = response.data?.dev_code
      const expiresIn = Number(response.data?.expires_in || 600)
      const resendIn = Number(response.data?.resend_in || 60)
      const expiresMinutes = Math.max(1, Math.ceil(expiresIn / 60))
      setCodeExpiresIn(expiresIn)
      setSuccess(devCode ? `${message} 验证码 ${expiresMinutes} 分钟内有效。开发模式验证码：${devCode}` : `${message} 验证码 ${expiresMinutes} 分钟内有效。`)
      setCodeRequested(true)
      setCountdown(resendIn)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, '验证码发送失败'))
    } finally {
      setSendingCode(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const account = formData.account.trim()
    const code = formData.code.trim()

    if (!isValidIdentity(account)) {
      setError('请输入有效的账号信息，支持用户名、邮箱或手机号')
      return
    }

    if (!code) {
      setError('请输入验证码')
      return
    }

    if (!/^\d{6}$/.test(code)) {
      setError('请输入 6 位数字验证码')
      return
    }

    if (formData.newPassword.length < 6 || formData.newPassword.length > 50) {
      setError('新密码长度必须在 6-50 个字符之间')
      return
    }

    if (formData.newPassword !== formData.confirmPassword) {
      setError('两次输入的新密码不一致')
      return
    }

    setSubmitting(true)
    try {
      const response = await apiClient.resetPassword({
        account,
        code,
        new_password: formData.newPassword,
      })
      setSuccess(response.data?.message || '密码重置成功，请返回登录页继续')
      setTimeout(() => {
        navigate('/login')
      }, 1200)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, '密码重置失败'))
    } finally {
      setSubmitting(false)
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
      }}
    >
      <Zoom in timeout={900}>
        <Container maxWidth="sm" sx={{ position: 'relative', zIndex: 1 }}>
          <Fade in timeout={1200}>
            <Paper
              elevation={24}
              sx={{
                p: { xs: 3, sm: 4, md: 5 },
                borderRadius: 4,
                backdropFilter: 'blur(10px)',
                backgroundColor: 'rgba(255, 255, 255, 0.95)',
              }}
            >
              <Box sx={{ textAlign: 'center', mb: 4 }}>
                <Box
                  sx={{
                    width: 76,
                    height: 76,
                    mx: 'auto',
                    mb: 2,
                    borderRadius: 3,
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: '0 8px 24px rgba(102, 126, 234, 0.4)',
                  }}
                >
                  <RocketLaunch sx={{ fontSize: 38, color: '#fff' }} />
                </Box>
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
                  }}
                >
                  找回密码
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  先发送验证码到绑定邮箱，再输入验证码重置本地密码
                </Typography>
              </Box>

              <Fade in={!!error || !!success}>
                <Box>
                  {error ? (
                    <Alert severity="error" sx={{ mb: 3 }}>
                      {error}
                    </Alert>
                  ) : null}
                  {success ? (
                    <Alert severity="success" sx={{ mb: 3 }}>
                      {success}
                    </Alert>
                  ) : null}
                </Box>
              </Fade>

              <Box component="form" onSubmit={handleSubmit} noValidate>
                <TextField
                  fullWidth
                  label="账号"
                  name="account"
                  value={formData.account}
                  onChange={handleChange}
                  placeholder="用户名、邮箱或手机号"
                  helperText="验证码会发送到该账号绑定的邮箱"
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <Badge sx={{ color: '#667eea' }} />
                      </InputAdornment>
                    ),
                  }}
                  sx={{ mb: 2 }}
                />

                <Button
                  fullWidth
                  variant="outlined"
                  onClick={() => void handleRequestCode()}
                  disabled={sendingCode || countdown > 0}
                  startIcon={<MarkEmailUnread />}
                  sx={{
                    mb: 2,
                    py: 1.4,
                    borderRadius: 2,
                    borderColor: '#667eea',
                    color: '#667eea',
                  }}
                >
                  {sendingCode
                    ? '发送中...'
                    : countdown > 0
                      ? `${countdown}s 后可重新发送`
                      : codeRequested
                        ? '重新发送验证码'
                        : '发送验证码'}
                </Button>

                <TextField
                  fullWidth
                  label="邮箱验证码"
                  name="code"
                  value={formData.code}
                  onChange={handleChange}
                  placeholder="请输入 6 位数字验证码"
                  helperText={`验证码有效期 ${Math.max(1, Math.ceil(codeExpiresIn / 60))} 分钟`}
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <LockReset sx={{ color: '#667eea' }} />
                      </InputAdornment>
                    ),
                  }}
                  sx={{ mb: 2 }}
                />

                <TextField
                  fullWidth
                  label="新密码"
                  name="newPassword"
                  type={showPassword ? 'text' : 'password'}
                  value={formData.newPassword}
                  onChange={handleChange}
                  helperText="长度必须在 6-50 个字符之间"
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <Password sx={{ color: '#667eea' }} />
                      </InputAdornment>
                    ),
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowPassword((prev) => !prev)} edge="end">
                          {showPassword ? <VisibilityOff /> : <Visibility />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                  sx={{ mb: 2 }}
                />

                <TextField
                  fullWidth
                  label="确认新密码"
                  name="confirmPassword"
                  type={showConfirmPassword ? 'text' : 'password'}
                  value={formData.confirmPassword}
                  onChange={handleChange}
                  InputProps={{
                    startAdornment: (
                      <InputAdornment position="start">
                        <Password sx={{ color: '#667eea' }} />
                      </InputAdornment>
                    ),
                    endAdornment: (
                      <InputAdornment position="end">
                        <IconButton onClick={() => setShowConfirmPassword((prev) => !prev)} edge="end">
                          {showConfirmPassword ? <VisibilityOff /> : <Visibility />}
                        </IconButton>
                      </InputAdornment>
                    ),
                  }}
                  sx={{ mb: 3 }}
                />

                <Button
                  fullWidth
                  variant="contained"
                  type="submit"
                  disabled={submitting}
                  sx={{
                    py: 1.6,
                    borderRadius: 2,
                    fontWeight: 'bold',
                    background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                  }}
                >
                  {submitting ? '重置中...' : '重置密码'}
                </Button>
              </Box>

              <Box sx={{ textAlign: 'center', mt: 3 }}>
                <Typography variant="body2" color="text.secondary">
                  想起密码了？{' '}
                  <Link
                    to="/login"
                    style={{
                      color: '#667eea',
                      textDecoration: 'none',
                      fontWeight: 'bold',
                    }}
                  >
                    返回登录
                  </Link>
                </Typography>
              </Box>
            </Paper>
          </Fade>
        </Container>
      </Zoom>
    </Box>
  )
}
