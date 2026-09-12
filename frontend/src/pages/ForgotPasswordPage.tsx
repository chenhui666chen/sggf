import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import {
  Alert,
  Box,
  Button,
  IconButton,
  InputAdornment,
  Link,
  TextField,
  Typography,
} from '@mui/material'
import Badge from '@mui/icons-material/Badge'
import LockReset from '@mui/icons-material/LockReset'
import MarkEmailUnread from '@mui/icons-material/MarkEmailUnread'
import Password from '@mui/icons-material/Password'
import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'

import AuthScreen from '@/components/layout/AuthScreen'
import { checkPasswordStrength } from '@/utils/passwordPolicy'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
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

  // 双重找回：输入手机号走短信通道，用户名/邮箱走邮件通道（文案随通道切换）
  const accountIsPhone = PHONE_PATTERN.test(formData.account.trim())

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
      setError(t('forgot.errorInvalidAccount'))
      return
    }

    setSendingCode(true)
    try {
      const response = await apiClient.requestPasswordResetCode({ account })
      const fallbackMessage = accountIsPhone
        ? t('forgot.fallbackPhoneSent')
        : t('forgot.fallbackEmailSent')
      const message = response.data?.message || fallbackMessage
      const devCode = response.data?.dev_code
      const expiresIn = Number(response.data?.expires_in || 600)
      const resendIn = Number(response.data?.resend_in || 60)
      const expiresMinutes = Math.max(1, Math.ceil(expiresIn / 60))
      setCodeExpiresIn(expiresIn)
      // 后端返回的 message 是服务端文案，暂透传（与登录页同口径）；
      // 彻底解法归 P3：后端 detail → i18n key 映射表建起来后一起改
      setSuccess(devCode
        ? t('forgot.sentDevHint', { message, minutes: expiresMinutes, code: devCode })
        : t('forgot.sentHint', { message, minutes: expiresMinutes }))
      setCodeRequested(true)
      setCountdown(resendIn)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, t('forgot.errorSendFailed')))
    } finally {
      setSendingCode(false)
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    const account = formData.account.trim()
    const code = formData.code.trim()

    if (!isValidIdentity(account)) {
      setError(t('forgot.errorInvalidAccount'))
      return
    }

    if (!code) {
      setError(t('forgot.errorCodeRequired'))
      return
    }

    if (!/^\d{6}$/.test(code)) {
      setError(t('forgot.errorCodeFormat'))
      return
    }

    // P2-4.6：与后端策略同源（utils/passwordPolicy.ts 与 app/core/password_policy.py 同规则）；
    // 密码强度错误文案走 i18n passwordPolicy.message
    const policyError = checkPasswordStrength(formData.newPassword)
    if (policyError) {
      setError(t('passwordPolicy.message'))
      return
    }

    if (formData.newPassword !== formData.confirmPassword) {
      setError(t('forgot.errorMismatch'))
      return
    }

    setSubmitting(true)
    try {
      const response = await apiClient.resetPassword({
        account,
        code,
        new_password: formData.newPassword,
      })
      setSuccess(response.data?.message || t('forgot.successReset'))
      setTimeout(() => {
        navigate('/login')
      }, 1200)
    } catch (requestError) {
      setError(await extractApiErrorMessage(requestError, t('forgot.errorResetFailed')))
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <AuthScreen
      title={t('forgot.title')}
      subtitle={t('forgot.subtitle')}
      maxWidth="sm"
    >
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

      <Box component="form" onSubmit={handleSubmit} noValidate>
        <TextField
          fullWidth
          label={t('forgot.accountLabel')}
          name="account"
          value={formData.account}
          onChange={handleChange}
          placeholder={t('forgot.accountPlaceholder')}
          helperText={accountIsPhone ? t('forgot.helperPhoneCode') : t('forgot.helperEmailCode')}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Badge sx={{ color: 'text.secondary' }} />
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
            borderColor: 'primary.main',
            color: 'primary.main',
          }}
        >
          {sendingCode
            ? t('forgot.sendingCode')
            : countdown > 0
              ? t('forgot.resendCountdown', { seconds: countdown })
              : codeRequested
                ? t('forgot.resendCode')
                : t('forgot.sendCode')}
        </Button>

        <TextField
          fullWidth
          label={accountIsPhone ? t('forgot.smsCodeLabel') : t('forgot.emailCodeLabel')}
          name="code"
          value={formData.code}
          onChange={handleChange}
          placeholder={t('forgot.codePlaceholder')}
          helperText={t('forgot.codeExpiresHint', { minutes: Math.max(1, Math.ceil(codeExpiresIn / 60)) })}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <LockReset sx={{ color: 'text.secondary' }} />
              </InputAdornment>
            ),
          }}
          sx={{ mb: 2 }}
        />

        <TextField
          fullWidth
          label={t('forgot.newPasswordLabel')}
          name="newPassword"
          type={showPassword ? 'text' : 'password'}
          value={formData.newPassword}
          onChange={handleChange}
          helperText={t('forgot.newPasswordHelper')}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Password sx={{ color: 'text.secondary' }} />
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
          label={t('forgot.confirmPasswordLabel')}
          name="confirmPassword"
          type={showConfirmPassword ? 'text' : 'password'}
          value={formData.confirmPassword}
          onChange={handleChange}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Password sx={{ color: 'text.secondary' }} />
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
          }}
        >
          {submitting ? t('forgot.resetting') : t('forgot.reset')}
        </Button>
      </Box>

      <Box sx={{ textAlign: 'center', mt: 3 }}>
        <Typography variant="body2" color="text.secondary">
          {t('forgot.rememberPassword')}{' '}
          <Link
            component={RouterLink}
            to="/login"
            sx={{
              color: 'primary.main',
              textDecoration: 'none',
              fontWeight: 'bold',
            }}
          >
            {t('forgot.backToLogin')}
          </Link>
        </Typography>
      </Box>
    </AuthScreen>
  )
}
