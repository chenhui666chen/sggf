import { useEffect, useState } from 'react'
import type { TFunction } from 'i18next'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Link,
  Paper,
  Stack,
  Typography,
} from '@mui/material'

import ConsentCheckboxes, { type ConsentOption } from '@/components/ConsentCheckboxes'
import PrivacyPolicyDialog from '@/components/PrivacyPolicyDialog'
import { buildConsentPayload, type ConsentType } from '@/constants/consent'
import { apiClient } from '@/services/api'
import { AppDispatch } from '@/store/store'
import { alipayLogin, confirmOAuthRegistration, wechatLogin } from '@/store/slices/authSlice'
import { clearOAuthContext, getStoredOAuthContext } from '@/utils/auth'

// P2-5.2：第三方建号需同意隐私政策 + 资料同步 + 年满 14 周岁声明；绑定仅需资料同步
// P2-5.5 修订：《隐私政策》页内弹窗查阅，不打断勾选流程也不丢失已填内容；
// 因 label 需要打开弹窗的回调，改为工厂函数由组件内构造。
function buildRegistrationConsents(t: TFunction, onOpenPrivacy: () => void): ConsentOption[] {
  return [
    {
      type: 'privacy_policy',
      required: true,
      label: (
        <>
          {t('loginCallback.agreePrefix')}
          <Link
            component="button"
            type="button"
            onClick={(e: React.MouseEvent) => {
              // 阻止冒泡/默认行为，避免连带触发外层勾选框
              e.preventDefault()
              e.stopPropagation()
              onOpenPrivacy()
            }}
            sx={{ mx: 0.4 }}
          >
            {t('loginCallback.privacyPolicy')}
          </Link>
        </>
      ),
    },
    { type: 'oauth_sync', required: true, label: t('loginCallback.oauthSync') },
    { type: 'age_eligibility', required: true, label: t('loginCallback.ageEligibility') },
  ]
}

function buildBindConsents(t: TFunction): ConsentOption[] {
  return [{ type: 'oauth_sync', required: true, label: t('loginCallback.oauthSync') }]
}

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
  const { t } = useTranslation()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const [searchParams] = useSearchParams()
  const [error, setError] = useState<string | null>(null)
  // P1-3.2：第三方首次登录返回注册票据时，等待用户确认建号（不自动创建账户）
  const [pendingTicket, setPendingTicket] = useState<string | null>(null)
  // P2-4.2：绑定意图同样等待用户确认（P2-5.2：需先勾选资料同步同意）
  const [pendingBindTicket, setPendingBindTicket] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  // P2-5.2：条款勾选状态——未勾选的项不传给后端，后端不代为记录
  const [consentChecked, setConsentChecked] = useState<Partial<Record<ConsentType, boolean>>>({})
  const [consentError, setConsentError] = useState('')
  // P2-5.5 修订：《隐私政策》页内弹窗开关与条款选项（弹窗就地查阅，不丢失已填上下文）
  const [privacyDialogOpen, setPrivacyDialogOpen] = useState(false)
  const registrationConsents = buildRegistrationConsents(t, () => setPrivacyDialogOpen(true))
  const bindConsents = buildBindConsents(t)

  useEffect(() => {
    const handleCallback = async () => {
      const oauthError = searchParams.get('error_description') || searchParams.get('error')
      if (oauthError) {
        clearOAuthContext()
        setError(oauthError)
        return
      }

      // 支付宝网关回传参数名为 auth_code（微信为 code），两者都需兼容
      const code = searchParams.get('code') || searchParams.get('auth_code')
      const callbackState = searchParams.get('state')
      const { provider, state: storedState } = getStoredOAuthContext()

      if (!code) {
        clearOAuthContext()
        setError(t('loginCallback.missingCode'))
        return
      }

      if (!provider) {
        clearOAuthContext()
        setError(t('loginCallback.missingContext'))
        return
      }

      if (provider !== 'alipay' && provider !== 'wechat') {
        clearOAuthContext()
        setError(t('loginCallback.invalidProvider'))
        return
      }

      if (!callbackState || !storedState || callbackState !== storedState) {
        clearOAuthContext()
        setError(t('loginCallback.stateMismatch'))
        return
      }

      try {
        const oauthState = callbackState as string
        const result =
          provider === 'alipay'
            ? await dispatch(alipayLogin({ code, state: oauthState })).unwrap()
            : await dispatch(wechatLogin({ code, state: oauthState })).unwrap()

        // P2-4.2：绑定意图（intent=bind）——已登录用户绑定第三方登录，
        // 票据由登录态 /auth/bind/confirm 消费后回用户中心安全页
        if (result.status === 'bind_pending') {
          if (!result.bindTicket) {
            clearOAuthContext()
            setError(t('loginCallback.missingBindTicket'))
            return
          }
          // P2-5.2：绑定需用户勾选资料同步同意，先进入确认页（不再无感自动绑定）
          setPendingBindTicket(result.bindTicket)
          return
        }

        clearOAuthContext()

        // P1-3.2：新用户不自动建号，进入确认页等待用户同意后才创建账户
        if (result.status === 'new_user') {
          if (!result.registrationTicket) {
            setError(t('loginCallback.missingRegTicket'))
            return
          }
          setPendingTicket(result.registrationTicket)
          return
        }

        navigate('/home', { replace: true })
      } catch (err) {
        clearOAuthContext()
        setError(normalizeCallbackError(err, t('loginCallback.loginFailed')))
      }
    }

    handleCallback()
  }, [dispatch, navigate, searchParams])

  const handleConfirmRegistration = async () => {
    if (!pendingTicket || confirming) return
    // P2-5.2：必选条款未勾选不放行
    if (registrationConsents.some((option) => option.required && !consentChecked[option.type])) {
      setConsentError(t('loginCallback.mustCheckConsents'))
      return
    }
    setConsentError('')
    setConfirming(true)
    try {
      await dispatch(
        confirmOAuthRegistration({
          ticket: pendingTicket,
          action: 'confirm',
          // 只提交用户实际勾选的项
          consent: buildConsentPayload(consentChecked),
        }),
      ).unwrap()
      navigate('/home', { replace: true })
    } catch (err) {
      setPendingTicket(null)
      setError(normalizeCallbackError(err, t('loginCallback.regConfirmFailed')))
    } finally {
      setConfirming(false)
    }
  }

  const handleConfirmBind = async () => {
    if (!pendingBindTicket || confirming) return
    if (bindConsents.some((option) => option.required && !consentChecked[option.type])) {
      setConsentError(t('loginCallback.mustCheckSync'))
      return
    }
    setConsentError('')
    setConfirming(true)
    try {
      await apiClient.bindConfirm(pendingBindTicket, buildConsentPayload(consentChecked))
      clearOAuthContext()
      navigate('/user-center?tab=security', { replace: true })
    } catch (bindError) {
      clearOAuthContext()
      setError(normalizeCallbackError(bindError, t('loginCallback.bindFailed')))
    } finally {
      setConfirming(false)
    }
  }

  const handleCancelRegistration = async () => {
    if (!pendingTicket || confirming) return
    setConfirming(true)
    try {
      // 取消也消费票据（一次性），避免票据残留被复用
      await dispatch(confirmOAuthRegistration({ ticket: pendingTicket, action: 'cancel' }))
    } finally {
      setConfirming(false)
      navigate('/login', { replace: true })
    }
  }

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
            <a href="/login" style={{ color: 'var(--sg-accent)' }}>
              {t('loginCallback.backToLogin')}
            </a>
          </Typography>
        </Box>
      </Container>
    )
  }

  if (pendingBindTicket) {
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
          <Paper elevation={4} sx={{ p: 4, borderRadius: 3, width: '100%' }}>
            <Typography variant="h6" fontWeight="bold" sx={{ mb: 1.5 }}>
              {t('loginCallback.bindTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {t('loginCallback.bindHint')}
            </Typography>
            <Box sx={{ mb: 2 }}>
              <ConsentCheckboxes
                options={bindConsents}
                checked={consentChecked}
                onChange={(type, isChecked) => {
                  setConsentChecked((prev) => ({ ...prev, [type]: isChecked }))
                  if (consentError) setConsentError('')
                }}
                error={consentError}
                disabled={confirming}
              />
            </Box>
            <Stack direction="row" spacing={2}>
              <Button
                fullWidth
                variant="contained"
                onClick={() => void handleConfirmBind()}
                disabled={confirming}
                startIcon={confirming ? <CircularProgress size={16} color="inherit" /> : undefined}
              >
                {confirming ? t('loginCallback.processing') : t('loginCallback.confirmBind')}
              </Button>
              <Button
                fullWidth
                variant="outlined"
                disabled={confirming}
                onClick={() => {
                  clearOAuthContext()
                  navigate('/user-center?tab=security', { replace: true })
                }}
              >
                {t('action.cancel')}
              </Button>
            </Stack>
          </Paper>
        </Box>
      </Container>
    )
  }

  if (pendingTicket) {
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
          <Paper elevation={4} sx={{ p: 4, borderRadius: 3, width: '100%' }}>
            <Typography variant="h6" fontWeight="bold" sx={{ mb: 1.5 }}>
              {t('loginCallback.firstLoginTitle')}
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              {t('loginCallback.firstLoginHint')}
            </Typography>
            {/* P2-5.2：条款勾选——未勾选的项不会传给后端 */}
            <Box sx={{ mb: 2 }}>
              <ConsentCheckboxes
                options={registrationConsents}
                checked={consentChecked}
                onChange={(type, isChecked) => {
                  setConsentChecked((prev) => ({ ...prev, [type]: isChecked }))
                  if (consentError) setConsentError('')
                }}
                error={consentError}
                disabled={confirming}
              />
            </Box>
            <Stack direction="row" spacing={2}>
              <Button
                fullWidth
                variant="contained"
                onClick={() => void handleConfirmRegistration()}
                disabled={confirming}
                startIcon={confirming ? <CircularProgress size={16} color="inherit" /> : undefined}
              >
                {confirming ? t('loginCallback.processing') : t('loginCallback.confirmCreate')}
              </Button>
              <Button fullWidth variant="outlined" onClick={() => void handleCancelRegistration()} disabled={confirming}>
                {t('action.cancel')}
              </Button>
            </Stack>
          </Paper>
          {/* P2-5.5 修订：页内弹窗查阅隐私政策，关闭后勾选状态原样保留 */}
          <PrivacyPolicyDialog open={privacyDialogOpen} onClose={() => setPrivacyDialogOpen(false)} />
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
          {t('loginCallback.loggingIn')}
        </Typography>
        <Typography variant="body2" color="text.secondary">
          {t('loginCallback.verifying')}
        </Typography>
      </Box>
    </Container>
  )
}
