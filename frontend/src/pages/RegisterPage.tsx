import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Grid,
  IconButton,
  InputAdornment,
  Link as MuiLink,
  Step,
  StepLabel,
  Stepper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import AccountCircle from '@mui/icons-material/AccountCircle'
import CheckCircle from '@mui/icons-material/CheckCircle'
import Email from '@mui/icons-material/Email'
import Lock from '@mui/icons-material/Lock'
import Phone from '@mui/icons-material/Phone'
import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'

import AuthScreen from '@/components/layout/AuthScreen'
import ConsentCheckboxes, { type ConsentOption } from '@/components/ConsentCheckboxes'
import PrivacyPolicyDialog from '@/components/PrivacyPolicyDialog'
import { buildConsentPayload, type ConsentType } from '@/constants/consent'
import { checkPasswordStrength } from '@/utils/passwordPolicy'
import { RootState, AppDispatch } from '@/store/store'
import { clearError, register, sendRegisterCode } from '@/store/slices/authSlice'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { useTranslation } from 'react-i18next'

const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
const PHONE_PATTERN = /^1[3-9]\d{9}$/

function trimOrEmpty(value: string) {
  return value.trim()
}

export default function RegisterPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { isLoading, error } = useSelector((state: RootState) => state.auth)

  const steps = [t('register.stepInfo'), t('register.stepEmail'), t('register.stepDone')]

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [activeStep, setActiveStep] = useState(0)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  // P1-3.8：两步注册第二步——邮箱验证码输入与重发倒计时（后端返回的 resend_in 驱动）
  const [verificationCode, setVerificationCode] = useState('')
  const [resendSeconds, setResendSeconds] = useState(0)
  const [sendingCode, setSendingCode] = useState(false)
  // 短信抢占：提交前先查手机号占用；已占用才进入短信验码流程（未占用直绑不发短信）
  const [phoneOccupied, setPhoneOccupied] = useState<boolean | null>(null)
  const [phoneCode, setPhoneCode] = useState('')
  const [phoneResendSeconds, setPhoneResendSeconds] = useState(0)
  const [phoneCodeSending, setPhoneCodeSending] = useState(false)
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    phone: '',
    password: '',
    confirmPassword: '',
  })
  // P2-5.2：条款勾选状态——未勾选的项不会传给后端，后端也不会代为记录
  const [consentChecked, setConsentChecked] = useState<Partial<Record<ConsentType, boolean>>>({})
  // P2-5.5 修订：《隐私政策》页内弹窗开关（就地查阅，避免新标签页导致已填内容"丢失"）
  const [privacyDialogOpen, setPrivacyDialogOpen] = useState(false)

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }))

    if (formErrors[name]) {
      setFormErrors((prev) => ({
        ...prev,
        [name]: '',
      }))
    }

    if (name === 'phone' && phoneOccupied !== null) {
      // 手机号变更：作废占用结论与已输入的短信码，需重新检查
      setPhoneOccupied(null)
      setPhoneCode('')
      setPhoneResendSeconds(0)
    }

    if (error) {
      dispatch(clearError())
    }
  }

  const handleCodeChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    // 只保留数字，最长 6 位（后端验证码为 6 位数字）
    setVerificationCode(e.target.value.replace(/\D/g, '').slice(0, 6))
    if (error) {
      dispatch(clearError())
    }
  }

  // 重发倒计时：到 0 后才允许再次发送验证码（与后端重发间隔对齐）
  useEffect(() => {
    if (resendSeconds <= 0) return
    const timer = window.setTimeout(() => setResendSeconds((prev) => prev - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [resendSeconds])

  // 短信码重发倒计时（与后端重发间隔对齐）
  useEffect(() => {
    if (phoneResendSeconds <= 0) return
    const timer = window.setTimeout(() => setPhoneResendSeconds((prev) => prev - 1), 1000)
    return () => window.clearTimeout(timer)
  }, [phoneResendSeconds])

  const sendCodeToEmail = async () => {
    const email = trimOrEmpty(formData.email).toLowerCase()
    setSendingCode(true)
    try {
      const response = await dispatch(sendRegisterCode(email)).unwrap()
      setResendSeconds(response.resend_in)
      return true
    } catch {
      // 错误文案已由 sendRegisterCode.rejected 写入 state.error
      return false
    } finally {
      setSendingCode(false)
    }
  }

  // 短信抢占：失焦即查占用——未占用直绑不发短信；已占用展示短信验码入口（申诉绑定）
  const handleCheckPhoneOccupied = async () => {
    const phone = trimOrEmpty(formData.phone)
    if (!phone || !PHONE_PATTERN.test(phone) || phoneOccupied !== null) return
    try {
      const response = await apiClient.phoneCheckStatus(phone)
      setPhoneOccupied(response.data?.occupied ?? false)
    } catch (checkError) {
      // 占用查询失败不阻断填写，提交时后端会再次校验并统一兜底
      const message = await extractApiErrorMessage(checkError, t('register.errorPhoneCheck'))
      setFormErrors((prev) => ({ ...prev, phone: message }))
    }
  }

  const handleSendPhoneCode = async () => {
    const phone = trimOrEmpty(formData.phone)
    if (!phone || phoneResendSeconds > 0 || phoneCodeSending) return
    setPhoneCodeSending(true)
    try {
      const response = await apiClient.phoneSendCode({ phone, purpose: 'takeover' })
      setPhoneResendSeconds(response.data?.resend_in || 60)
    } catch (sendError) {
      const message = await extractApiErrorMessage(sendError, t('register.errorPhoneCodeSend'))
      setFormErrors((prev) => ({ ...prev, phone: message }))
    } finally {
      setPhoneCodeSending(false)
    }
  }

  // P2-5.2：注册需勾选的条款。填了手机号（敏感个人信息）时额外要求手机号收集同意；
  // 合规修订：建号必须勾选"年满 14 周岁"自我声明（age_eligibility），
  // 未勾选的项不会出现在提交给后端的 consent 里，后端也不会代为记录。
  const phoneProvided = Boolean(trimOrEmpty(formData.phone))
  const consentOptions: ConsentOption[] = [
    {
      type: 'privacy_policy',
      required: true,
      // P2-5.5 修订：政策正文页内弹窗查阅，不打断勾选流程也不丢失已填内容
      label: (
        <>
          {t('register.consentPrivacyPrefix')}
          <MuiLink
            component="button"
            type="button"
            onClick={(e: React.MouseEvent) => {
              // 阻止冒泡/默认行为，避免连带触发外层勾选框
              e.preventDefault()
              e.stopPropagation()
              setPrivacyDialogOpen(true)
            }}
            sx={{ mx: 0.4 }}
          >
            {t('register.consentPrivacyLink')}
          </MuiLink>
        </>
      ),
    },
    { type: 'age_eligibility', required: true, label: t('register.consentAge') },
    ...(phoneProvided
      ? [
          {
            type: 'phone_collection' as ConsentType,
            required: true,
            label: t('register.consentPhone'),
          },
        ]
      : []),
  ]

  const validateCurrentStep = () => {
    const username = trimOrEmpty(formData.username)
    const email = trimOrEmpty(formData.email).toLowerCase()
    const phone = trimOrEmpty(formData.phone)
    const errors: Record<string, string> = {}

    if (username.length < 2 || username.length > 50) {
      errors.username = t('register.errorUsername')
    }

    if (!EMAIL_PATTERN.test(email)) {
      errors.email = t('register.errorEmail')
    }

    if (phone && !PHONE_PATTERN.test(phone)) {
      errors.phone = t('register.errorPhone')
    }

    // P2-4.6：与后端策略同源（utils/passwordPolicy.ts 与 app/core/password_policy.py 同规则）；
    // 密码强度错误文案走 i18n passwordPolicy.message
    const passwordError = checkPasswordStrength(formData.password)
    if (passwordError) {
      errors.password = t('passwordPolicy.message')
    }

    if (formData.confirmPassword !== formData.password) {
      errors.confirmPassword = t('register.errorMismatch')
    }

    // P2-5.2：必选条款未勾选不放行（与后端校验同语义：未同意不处理个人信息）
    if (consentOptions.some((option) => option.required && !consentChecked[option.type])) {
      errors.consent = t('register.errorConsent')
    }

    setFormErrors(errors)
    return Object.keys(errors).length === 0
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()

    if (activeStep === 0) {
      if (!validateCurrentStep()) {
        return
      }

      // 短信抢占：提交前确保完成占用检查——已占用必须输入 6 位短信码才可主张号码所有权
      const phone = trimOrEmpty(formData.phone)
      if (phone && PHONE_PATTERN.test(phone)) {
        let occupied = phoneOccupied
        if (occupied === null) {
          try {
            const response = await apiClient.phoneCheckStatus(phone)
            occupied = response.data?.occupied ?? false
            setPhoneOccupied(occupied)
          } catch (checkError) {
            const message = await extractApiErrorMessage(checkError, t('register.errorPhoneCheck'))
            setFormErrors((prev) => ({ ...prev, phone: message }))
            return
          }
        }
        if (occupied && phoneCode.length !== 6) {
          setFormErrors((prev) => ({
            ...prev,
            phone: t('register.errorPhoneOccupied'),
          }))
          return
        }
      }

      // P1-3.8：第一步校验通过后先发验证码，发送成功才进入验证码输入步；失败停留原步展示错误
      const sent = await sendCodeToEmail()
      if (sent) {
        setActiveStep(1)
      }
      return
    }

    if (activeStep !== 1) {
      return
    }

    if (verificationCode.length !== 6) {
      setFormErrors((prev) => ({ ...prev, code: t('register.errorCodeFormat') }))
      return
    }

    const payload = {
      username: trimOrEmpty(formData.username),
      email: trimOrEmpty(formData.email).toLowerCase(),
      password: formData.password,
      code: verificationCode,
      ...(trimOrEmpty(formData.phone) ? { phone: trimOrEmpty(formData.phone) } : {}),
      // 短信抢占：已占用且验码通过时携带短信码，后端据此转移号码绑定权
      ...(phoneOccupied && phoneCode.length === 6 ? { phone_code: phoneCode } : {}),
      // P2-5.2：只提交用户实际勾选的条款，未勾选的项后端不记录
      consent: buildConsentPayload(consentChecked),
    }

    const result = await dispatch(register(payload))
    if (register.fulfilled.match(result)) {
      setActiveStep(2)
      window.setTimeout(() => {
        navigate('/home')
      }, 1200)
    }
  }

  const handleResendCode = async () => {
    if (resendSeconds > 0 || sendingCode) return
    await sendCodeToEmail()
  }

  const isStepValid =
    trimOrEmpty(formData.username) &&
    trimOrEmpty(formData.email) &&
    formData.password &&
    formData.confirmPassword

  return (
    <AuthScreen title={t('register.title')} subtitle={t('register.subtitle')} maxWidth="md">
      <Stepper activeStep={activeStep} sx={{ mb: 4, '& .MuiStepLabel-label': { color: 'primary.main' } }}>
        {steps.map((label) => (
          <Step key={label}>
            <StepLabel>{label}</StepLabel>
          </Step>
        ))}
      </Stepper>

      {error ? (
        <Alert severity="error" onClose={() => dispatch(clearError())} sx={{ mb: 3 }}>
          {error}
        </Alert>
      ) : null}

      <Box component="form" onSubmit={handleSubmit} noValidate>
        {activeStep === 0 && (
          <Grid container spacing={3}>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label={t('register.usernameLabel')}
                name="username"
                value={formData.username}
                onChange={handleChange}
                required
                autoComplete="nickname"
                error={!!formErrors.username}
                helperText={formErrors.username || t('register.usernameHint')}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <AccountCircle sx={{ color: 'text.secondary' }} />
                    </InputAdornment>
                  ),
                }}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label={t('register.emailLabel')}
                name="email"
                type="email"
                value={formData.email}
                onChange={handleChange}
                required
                autoComplete="email"
                error={!!formErrors.email}
                helperText={formErrors.email || t('register.emailHint')}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Email sx={{ color: 'text.secondary' }} />
                    </InputAdornment>
                  ),
                }}
              />
            </Grid>
            <Grid item xs={12}>
              <TextField
                fullWidth
                label={t('register.phoneLabel')}
                name="phone"
                type="tel"
                value={formData.phone}
                onChange={handleChange}
                autoComplete="tel"
                onBlur={() => void handleCheckPhoneOccupied()}
                error={!!formErrors.phone}
                helperText={
                  formErrors.phone ||
                  (phoneOccupied
                    ? t('register.phoneOccupiedHint')
                    : t('register.phoneHintOptional'))
                }
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Phone sx={{ color: 'text.secondary' }} />
                    </InputAdornment>
                  ),
                }}
              />
            </Grid>
            {phoneOccupied && (
              <Grid item xs={12}>
                <Alert severity="info" sx={{ mb: 1.5 }}>
                  {t('register.phoneOccupiedAlert')}
                </Alert>
                <Stack direction={{ xs: 'column', sm: 'row' }} spacing={1.5}>
                  <TextField
                    fullWidth
                    label={t('register.smsCodeLabel')}
                    value={phoneCode}
                    onChange={(e) => setPhoneCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                    autoComplete="one-time-code"
                    inputProps={{ inputMode: 'numeric', maxLength: 6 }}
                    helperText={t('register.smsCodeHint')}
                    InputProps={{
                      startAdornment: (
                        <InputAdornment position="start">
                          <Phone sx={{ color: 'text.secondary' }} />
                        </InputAdornment>
                      ),
                    }}
                  />
                  <Button
                    variant="outlined"
                    onClick={() => void handleSendPhoneCode()}
                    disabled={phoneCodeSending || phoneResendSeconds > 0}
                    sx={{
                      whiteSpace: 'nowrap',
                      borderColor: 'primary.main',
                      color: 'primary.main',
                      minWidth: 150,
                      py: 1.4,
                    }}
                  >
                    {phoneCodeSending
                      ? t('register.sending')
                      : phoneResendSeconds > 0
                        ? t('register.phoneResendCountdown', { seconds: phoneResendSeconds })
                        : t('register.phoneSendCode')}
                  </Button>
                </Stack>
              </Grid>
            )}
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label={t('register.passwordLabel')}
                name="password"
                type={showPassword ? 'text' : 'password'}
                value={formData.password}
                onChange={handleChange}
                required
                autoComplete="new-password"
                error={!!formErrors.password}
                helperText={formErrors.password || t('register.passwordHint')}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Lock sx={{ color: 'text.secondary' }} />
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
              />
            </Grid>
            <Grid item xs={12} sm={6}>
              <TextField
                fullWidth
                label={t('register.confirmPasswordLabel')}
                name="confirmPassword"
                type={showConfirmPassword ? 'text' : 'password'}
                value={formData.confirmPassword}
                onChange={handleChange}
                required
                autoComplete="new-password"
                error={!!formErrors.confirmPassword}
                helperText={formErrors.confirmPassword || t('register.confirmPasswordHint')}
                InputProps={{
                  startAdornment: (
                    <InputAdornment position="start">
                      <Lock sx={{ color: 'text.secondary' }} />
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
              />
            </Grid>

            {/* P2-5.2：条款勾选——只提交用户实际勾选的项 */}
            <Grid item xs={12}>
              <ConsentCheckboxes
                options={consentOptions}
                checked={consentChecked}
                onChange={(type, isChecked) => {
                  setConsentChecked((prev) => ({ ...prev, [type]: isChecked }))
                  if (formErrors.consent) {
                    setFormErrors((prev) => ({ ...prev, consent: '' }))
                  }
                }}
                error={formErrors.consent}
              />
            </Grid>
          </Grid>
        )}

        {activeStep === 1 && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Box
              sx={{
                width: 120,
                height: 120,
                mx: 'auto',
                mb: 3,
                borderRadius: '50%',
                bgcolor: 'primary.light',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <Email sx={{ fontSize: 60, color: 'primary.main' }} />
            </Box>
            <Typography variant="h6" fontWeight="bold" sx={{ mb: 1 }}>
              {t('register.emailStepTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
              {t('register.emailSentHint', { email: trimOrEmpty(formData.email).toLowerCase() })}
            </Typography>
            <TextField
              fullWidth
              label={t('register.emailCodeLabel')}
              name="code"
              value={verificationCode}
              onChange={handleCodeChange}
              required
              autoComplete="one-time-code"
              inputProps={{ inputMode: 'numeric', maxLength: 6 }}
              error={!!formErrors.code}
              helperText={formErrors.code || t('register.emailCodeHint')}
              InputProps={{
                startAdornment: (
                  <InputAdornment position="start">
                    <Lock sx={{ color: 'text.secondary' }} />
                  </InputAdornment>
                ),
              }}
              sx={{ mb: 2 }}
            />
            <Button
              size="small"
              onClick={() => void handleResendCode()}
              disabled={resendSeconds > 0 || sendingCode}
              sx={{ color: 'primary.main', fontWeight: 'bold' }}
            >
              {sendingCode
                ? t('register.sending')
                : resendSeconds > 0
                  ? t('register.resendCountdown', { seconds: resendSeconds })
                  : t('register.resend')}
            </Button>
          </Box>
        )}

        {activeStep === 2 && (
          <Box sx={{ textAlign: 'center', py: 4 }}>
            <Box
              sx={{
                width: 120,
                height: 120,
                mx: 'auto',
                mb: 3,
                borderRadius: '50%',
                bgcolor: 'primary.light',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              <CheckCircle sx={{ fontSize: 60, color: 'primary.main' }} />
            </Box>
            <Typography variant="h5" fontWeight="bold" sx={{ mb: 1 }}>
              {t('register.successTitle')}
            </Typography>
            <Typography variant="body1" color="text.secondary">
              {t('register.successHint')}
            </Typography>
          </Box>
        )}

        {activeStep < 2 && (
          <Box sx={{ display: 'flex', gap: 2, mt: 4 }}>
            {activeStep > 0 && (
              <Button
                fullWidth
                variant="outlined"
                onClick={() => setActiveStep((prev) => prev - 1)}
                disabled={isLoading}
                sx={{
                  py: 1.8,
                  borderRadius: 2,
                  fontSize: '1rem',
                  fontWeight: 'bold',
                  borderColor: 'primary.main',
                  color: 'primary.main',
                }}
              >
                {t('register.stepperBack')}
              </Button>
            )}
            <Button
              fullWidth
              variant="contained"
              type="submit"
              size="large"
              disabled={
                isLoading ||
                sendingCode ||
                phoneCodeSending ||
                (activeStep === 0 && !isStepValid) ||
                (activeStep === 1 && verificationCode.length !== 6)
              }
              sx={{
                py: 1.8,
                borderRadius: 2,
                fontSize: '1rem',
                fontWeight: 'bold',
              }}
            >
              {isLoading || sendingCode || phoneCodeSending
                ? t('register.submitting')
                : activeStep === 0
                  ? t('register.stepperNext')
                  : t('register.submit')}
            </Button>
          </Box>
        )}
      </Box>

      {activeStep === 0 && (
        <Box sx={{ mt: 3, textAlign: 'center' }}>
          <Typography variant="body2" color="text.secondary">
            {t('register.hasAccount')}{' '}
            <MuiLink
              component={RouterLink}
              to="/login"
              sx={{
                color: 'primary.main',
                textDecoration: 'none',
                fontWeight: 'bold',
              }}
            >
              {t('register.goLogin')}
            </MuiLink>
          </Typography>
        </Box>
      )}

      {/* P2-5.5 修订：页内弹窗查阅隐私政策，关闭后表单填写内容原样保留 */}
      <PrivacyPolicyDialog open={privacyDialogOpen} onClose={() => setPrivacyDialogOpen(false)} />
    </AuthScreen>
  )
}
