import { useEffect, useState } from 'react'
import { Link as RouterLink, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Divider,
  IconButton,
  InputAdornment,
  Link,
  TextField,
  Typography,
} from '@mui/material'
import Chat from '@mui/icons-material/Chat'
import Email from '@mui/icons-material/Email'
import Lock from '@mui/icons-material/Lock'
import Payment from '@mui/icons-material/Payment'
import Visibility from '@mui/icons-material/Visibility'
import VisibilityOff from '@mui/icons-material/VisibilityOff'
import { useTranslation } from 'react-i18next'

import AuthScreen from '@/components/layout/AuthScreen'
import { apiClient, extractApiErrorMessage } from '@/services/api'
import { RootState, AppDispatch } from '@/store/store'
import { clearError, login } from '@/store/slices/authSlice'
import {
  clearOAuthContext,
  generateOAuthState,
  getRequiredOAuthOrigin,
  navigateToOAuthTarget,
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
  const { t } = useTranslation()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { isLoading, error } = useSelector((state: RootState) => state.auth)

  const [showPassword, setShowPassword] = useState(false)
  // 存的是**已翻译的文案**而不是 i18n key：下面还有一路是后端返回的原始错误串
  // （extractApiErrorMessage），两者混在同一个 state 里就没法统一存 key。
  // 代价是错误显示期间切语言，这条文案会停在旧语言——但用户一敲键盘
  // handleChange 就把它清了，影响很小。彻底解法属于 P3：后端 detail → i18n key
  // 的映射表建起来后一起改。
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
      setFormError(t('login.errorInvalidIdentifier'))
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
    // 平台回调白名单仅登记单一域名：当前域名不匹配时先跳转授权域名，
    // 用 autostart 参数在目标域名上自动重新发起（localStorage 按源隔离，不能跨域传递 state）
    const requiredOrigin = getRequiredOAuthOrigin(provider)
    if (requiredOrigin && window.location.origin !== requiredOrigin) {
      window.location.href = `${requiredOrigin}/login?autostart=${provider}`
      return
    }
    try {
      clearOAuthContext()
      const state = generateOAuthState()
      const redirectUri = `${window.location.origin}/login/callback`
      const response =
        provider === 'alipay'
          ? await apiClient.getAlipayAuthUrl({ redirect_uri: redirectUri, state })
          : await apiClient.getWechatAuthUrl({ redirect_uri: redirectUri, state })

      const authUrl = response.data?.auth_url
      // 服务端生成并返回 state（P0-2.3）。未返回 state 时直接失败，不做静默回退
      // （回退到前端 state 会导致回调时与 Redis 中记录不一致而必失败）
      const serverState = response.data?.state
      if (!authUrl || !serverState) {
        clearOAuthContext()
        setFormError(t('login.errorMissingOAuthUrl'))
        return
      }

      storeOAuthContext(provider, serverState)
      // 支付宝在移动端唤起 App（免扫码）并在未安装时降级；微信手机浏览器无法唤起，沿用原授权页
      navigateToOAuthTarget(authUrl, provider)
    } catch (oauthError) {
      clearOAuthContext()
      setFormError(await extractApiErrorMessage(oauthError, t('login.errorOAuthStartFailed')))
    }
  }

  // 从授权域名跳转回来时（?autostart=alipay|wechat），自动发起对应登录；非法值忽略并清理参数
  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const autostart = params.get('autostart')
    if (!autostart) return
    params.delete('autostart')
    const query = params.toString()
    window.history.replaceState(null, '', `/login${query ? `?${query}` : ''}`)
    if (autostart === 'alipay' || autostart === 'wechat') {
      startOAuthLogin(autostart)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AuthScreen subtitle={t('login.subtitle')} maxWidth="sm">
      {(error || formError) ? (
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
      ) : null}

      <Box component="form" onSubmit={handleSubmit} noValidate>
        <TextField
          fullWidth
          label={t('login.identifierLabel')}
          name="username"
          value={formData.username}
          onChange={handleChange}
          required
          autoComplete="username"
          placeholder={t('login.identifierPlaceholder')}
          error={!!formError}
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Email sx={{ color: 'text.secondary', fontSize: { xs: 20, sm: 24 } }} />
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
                borderColor: 'primary.main',
              },
              '&.Mui-focused fieldset': {
                borderColor: 'primary.main',
              },
            },
          }}
        />

        <TextField
          fullWidth
          label={t('login.passwordLabel')}
          name="password"
          type={showPassword ? 'text' : 'password'}
          value={formData.password}
          onChange={handleChange}
          required
          autoComplete="current-password"
          InputProps={{
            startAdornment: (
              <InputAdornment position="start">
                <Lock sx={{ color: 'text.secondary', fontSize: { xs: 20, sm: 24 } }} />
              </InputAdornment>
            ),
            endAdornment: (
              <InputAdornment position="end">
                <IconButton
                  onClick={() => setShowPassword((prev) => !prev)}
                  edge="end"
                  size="medium"
                  aria-label={
                    showPassword ? t('login.hidePassword') : t('login.showPassword')
                  }
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
                borderColor: 'primary.main',
              },
              '&.Mui-focused fieldset': {
                borderColor: 'primary.main',
              },
            },
          }}
        />

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
            minHeight: { xs: 48, sm: 56 },
          }}
        >
          {isLoading ? t('login.submitting') : t('login.submit')}
        </Button>

        <Box sx={{ textAlign: 'right', mb: { xs: 2, sm: 3 } }}>
          <Link
            component={RouterLink}
            to="/forgot-password"
            sx={{
              color: 'primary.main',
              textDecoration: 'none',
              fontWeight: 'bold',
              fontSize: '0.875rem',
            }}
          >
            {t('login.forgotPassword')}
          </Link>
        </Box>
      </Box>

      <Divider
        sx={{
          my: { xs: 2, sm: 3 },
          '&::before, &::after': {
            borderColor: 'divider',
          },
        }}
      >
        <Typography variant="caption" sx={{ color: 'text.secondary', fontWeight: 'medium' }}>
          {t('login.oauthDivider')}
        </Typography>
      </Divider>

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
            borderColor: '#1677FF', // sg-color-fixed: 支付宝品牌蓝（OAuth 品牌色）
            color: '#1677FF', // sg-color-fixed: 支付宝品牌蓝（OAuth 品牌色）
            minHeight: { xs: 48, sm: 52 },
            '&:hover': {
              borderColor: '#1677FF', // sg-color-fixed: 支付宝品牌蓝（OAuth 品牌色）
              backgroundColor: 'rgba(22, 119, 255, 0.08)', // sg-color-fixed: 支付宝品牌蓝 hover 底（OAuth 品牌色）
            },
          }}
        >
          {t('login.oauthAlipay')}
        </Button>
        <Button
          fullWidth
          variant="outlined"
          startIcon={<Chat />}
          onClick={() => void startOAuthLogin('wechat')}
          sx={{
            py: { xs: 1.2, sm: 1.5 },
            borderRadius: 2,
            borderColor: '#07C160', // sg-color-fixed: 微信品牌绿（OAuth 品牌色）
            color: '#07C160', // sg-color-fixed: 微信品牌绿（OAuth 品牌色）
            minHeight: { xs: 48, sm: 52 },
            '&:hover': {
              borderColor: '#07C160', // sg-color-fixed: 微信品牌绿（OAuth 品牌色）
              backgroundColor: 'rgba(7, 193, 96, 0.08)', // sg-color-fixed: 微信品牌绿 hover 底（OAuth 品牌色）
            },
          }}
        >
          {t('login.oauthWechat')}
        </Button>
      </Box>

      <Box sx={{ textAlign: 'center' }}>
        <Typography variant="body2" color="text.secondary">
          {t('login.noAccount')}{' '}
          <Link
            component={RouterLink}
            to="/register"
            sx={{
              color: 'primary.main',
              textDecoration: 'none',
              fontWeight: 'bold',
            }}
          >
            {t('login.register')}
          </Link>
        </Typography>
      </Box>
    </AuthScreen>
  )
}
