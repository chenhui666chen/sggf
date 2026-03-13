import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Alert,
  Box,
  Button,
  Container,
  Fade,
  Grid,
  IconButton,
  InputAdornment,
  Paper,
  Step,
  StepLabel,
  Stepper,
  TextField,
  Typography,
  Zoom,
} from '@mui/material'
import {
  AccountCircle,
  CheckCircle,
  Email,
  Lock,
  Phone,
  RocketLaunch,
  Visibility,
  VisibilityOff,
} from '@mui/icons-material'

import { RootState, AppDispatch } from '@/store/store'
import { clearError, register } from '@/store/slices/authSlice'

const EMAIL_PATTERN = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
const PHONE_PATTERN = /^1[3-9]\d{9}$/

const steps = ['填写信息', '确认提交', '完成']

function trimOrEmpty(value: string) {
  return value.trim()
}

export default function RegisterPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { isLoading, error } = useSelector((state: RootState) => state.auth)

  const [showPassword, setShowPassword] = useState(false)
  const [showConfirmPassword, setShowConfirmPassword] = useState(false)
  const [activeStep, setActiveStep] = useState(0)
  const [formErrors, setFormErrors] = useState<Record<string, string>>({})
  const [formData, setFormData] = useState({
    username: '',
    email: '',
    phone: '',
    password: '',
    confirmPassword: '',
  })

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

    if (error) {
      dispatch(clearError())
    }
  }

  const validateCurrentStep = () => {
    const username = trimOrEmpty(formData.username)
    const email = trimOrEmpty(formData.email).toLowerCase()
    const phone = trimOrEmpty(formData.phone)
    const errors: Record<string, string> = {}

    if (username.length < 2 || username.length > 50) {
      errors.username = '用户名长度必须在 2-50 个字符之间'
    }

    if (!EMAIL_PATTERN.test(email)) {
      errors.email = '请输入有效的邮箱地址'
    }

    if (phone && !PHONE_PATTERN.test(phone)) {
      errors.phone = '请输入有效的手机号'
    }

    if (formData.password.length < 6 || formData.password.length > 50) {
      errors.password = '密码长度必须在 6-50 个字符之间'
    }

    if (formData.confirmPassword !== formData.password) {
      errors.confirmPassword = '两次输入的密码不一致'
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

      setActiveStep(1)
      return
    }

    if (activeStep !== 1) {
      return
    }

    const payload = {
      username: trimOrEmpty(formData.username),
      email: trimOrEmpty(formData.email).toLowerCase(),
      password: formData.password,
      ...(trimOrEmpty(formData.phone) ? { phone: trimOrEmpty(formData.phone) } : {}),
    }

    const result = await dispatch(register(payload))
    if (register.fulfilled.match(result)) {
      setActiveStep(2)
      window.setTimeout(() => {
        navigate('/home')
      }, 1200)
    }
  }

  const isStepValid =
    trimOrEmpty(formData.username) &&
    trimOrEmpty(formData.email) &&
    formData.password &&
    formData.confirmPassword

  return (
    <Box
      sx={{
        minHeight: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        position: 'relative',
        overflow: 'hidden',
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
          width: '600px',
          height: '600px',
          borderRadius: '50%',
          background: 'rgba(255, 255, 255, 0.1)',
          top: '-200px',
          right: '-200px',
          zIndex: 0,
        }}
      />
      <Box
        sx={{
          position: 'absolute',
          width: '400px',
          height: '400px',
          borderRadius: '50%',
          background: 'rgba(255, 255, 255, 0.08)',
          bottom: '-100px',
          left: '-100px',
          zIndex: 0,
        }}
      />

      <Zoom in timeout={1000}>
        <Container maxWidth="md" sx={{ position: 'relative', zIndex: 1, px: 3 }}>
          <Fade in timeout={1500}>
            <Paper
              elevation={24}
              sx={{
                p: { xs: 4, sm: 5 },
                borderRadius: 4,
                backdropFilter: 'blur(10px)',
                backgroundColor: 'rgba(255, 255, 255, 0.95)',
                boxShadow: '0 20px 60px rgba(0, 0, 0, 0.3)',
              }}
            >
              <Box sx={{ textAlign: 'center', mb: 4 }}>
                <Zoom in timeout={2000}>
                  <Box
                    sx={{
                      width: 80,
                      height: 80,
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
                    <RocketLaunch sx={{ fontSize: 40, color: '#fff' }} />
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
                  }}
                >
                  创建账户
                </Typography>
                <Typography variant="body2" color="text.secondary">
                  加入拾光工坊，开启创作之旅
                </Typography>
              </Box>

              <Stepper activeStep={activeStep} sx={{ mb: 4, '& .MuiStepLabel-label': { color: '#667eea' } }}>
                {steps.map((label) => (
                  <Step key={label}>
                    <StepLabel>{label}</StepLabel>
                  </Step>
                ))}
              </Stepper>

              <Fade in={!!error}>
                <Box>
                  <Alert severity="error" onClose={() => dispatch(clearError())} sx={{ mb: 3 }}>
                    {error}
                  </Alert>
                </Box>
              </Fade>

              <Box component="form" onSubmit={handleSubmit} noValidate>
                {activeStep === 0 && (
                  <Fade in timeout={800}>
                    <Grid container spacing={3}>
                      <Grid item xs={12}>
                        <TextField
                          fullWidth
                          label="用户名"
                          name="username"
                          value={formData.username}
                          onChange={handleChange}
                          required
                          autoComplete="nickname"
                          error={!!formErrors.username}
                          helperText={formErrors.username || '用于登录和系统内展示'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <AccountCircle sx={{ color: '#667eea' }} />
                              </InputAdornment>
                            ),
                          }}
                        />
                      </Grid>
                      <Grid item xs={12}>
                        <TextField
                          fullWidth
                          label="邮箱"
                          name="email"
                          type="email"
                          value={formData.email}
                          onChange={handleChange}
                          required
                          autoComplete="email"
                          error={!!formErrors.email}
                          helperText={formErrors.email || '邮箱也可用于登录'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <Email sx={{ color: '#667eea' }} />
                              </InputAdornment>
                            ),
                          }}
                        />
                      </Grid>
                      <Grid item xs={12}>
                        <TextField
                          fullWidth
                          label="手机号（可选）"
                          name="phone"
                          type="tel"
                          value={formData.phone}
                          onChange={handleChange}
                          autoComplete="tel"
                          error={!!formErrors.phone}
                          helperText={formErrors.phone || '手机号也可用于登录'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <Phone sx={{ color: '#667eea' }} />
                              </InputAdornment>
                            ),
                          }}
                        />
                      </Grid>
                      <Grid item xs={12} sm={6}>
                        <TextField
                          fullWidth
                          label="密码"
                          name="password"
                          type={showPassword ? 'text' : 'password'}
                          value={formData.password}
                          onChange={handleChange}
                          required
                          autoComplete="new-password"
                          error={!!formErrors.password}
                          helperText={formErrors.password || '长度必须在 6-50 个字符之间'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <Lock sx={{ color: '#667eea' }} />
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
                          label="确认密码"
                          name="confirmPassword"
                          type={showConfirmPassword ? 'text' : 'password'}
                          value={formData.confirmPassword}
                          onChange={handleChange}
                          required
                          autoComplete="new-password"
                          error={!!formErrors.confirmPassword}
                          helperText={formErrors.confirmPassword || '请再次输入密码'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <Lock sx={{ color: '#667eea' }} />
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
                    </Grid>
                  </Fade>
                )}

                {activeStep === 1 && (
                  <Fade in timeout={800}>
                    <Box sx={{ textAlign: 'center', py: 4 }}>
                      <Zoom in timeout={1000}>
                        <Box
                          sx={{
                            width: 120,
                            height: 120,
                            mx: 'auto',
                            mb: 3,
                            borderRadius: '50%',
                            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            boxShadow: '0 8px 24px rgba(102, 126, 234, 0.4)',
                          }}
                        >
                          <CheckCircle sx={{ fontSize: 60, color: '#fff' }} />
                        </Box>
                      </Zoom>
                      <Typography variant="h6" fontWeight="bold" sx={{ mb: 2 }}>
                        确认提交信息
                      </Typography>
                      <Box
                        sx={{
                          mt: 3,
                          p: 3,
                          borderRadius: 2,
                          backgroundColor: 'rgba(102, 126, 234, 0.05)',
                          border: '1px solid rgba(102, 126, 234, 0.2)',
                        }}
                      >
                        <Grid container spacing={2}>
                          <Grid item xs={6} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              用户名
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {trimOrEmpty(formData.username)}
                            </Typography>
                          </Grid>
                          <Grid item xs={6} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              邮箱
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {trimOrEmpty(formData.email).toLowerCase()}
                            </Typography>
                          </Grid>
                          <Grid item xs={12} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              手机号
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {trimOrEmpty(formData.phone) || '未填写'}
                            </Typography>
                          </Grid>
                          <Grid item xs={12} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              密码
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {'*'.repeat(formData.password.length)}
                            </Typography>
                          </Grid>
                        </Grid>
                      </Box>
                    </Box>
                  </Fade>
                )}

                {activeStep === 2 && (
                  <Fade in timeout={800}>
                    <Box sx={{ textAlign: 'center', py: 4 }}>
                      <Zoom in timeout={1000}>
                        <Box
                          sx={{
                            width: 120,
                            height: 120,
                            mx: 'auto',
                            mb: 3,
                            borderRadius: '50%',
                            background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                            display: 'flex',
                            alignItems: 'center',
                            justifyContent: 'center',
                            boxShadow: '0 8px 24px rgba(102, 126, 234, 0.4)',
                          }}
                        >
                          <CheckCircle sx={{ fontSize: 60, color: '#fff' }} />
                        </Box>
                      </Zoom>
                      <Typography variant="h5" fontWeight="bold" sx={{ mb: 1 }}>
                        注册成功
                      </Typography>
                      <Typography variant="body1" color="text.secondary">
                        正在跳转到首页...
                      </Typography>
                    </Box>
                  </Fade>
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
                          borderColor: '#667eea',
                          color: '#667eea',
                        }}
                      >
                        上一步
                      </Button>
                    )}
                    <Button
                      fullWidth
                      variant="contained"
                      type="submit"
                      size="large"
                      disabled={isLoading || (activeStep === 0 && !isStepValid)}
                      sx={{
                        py: 1.8,
                        borderRadius: 2,
                        fontSize: '1rem',
                        fontWeight: 'bold',
                        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                        boxShadow: '0 4px 14px rgba(102, 126, 234, 0.4)',
                        '&:hover': {
                          boxShadow: '0 6px 20px rgba(102, 126, 234, 0.6)',
                          transform: 'translateY(-2px)',
                        },
                        '&:disabled': {
                          background: 'rgba(0, 0, 0, 0.12)',
                          color: 'rgba(0, 0, 0, 0.26)',
                        },
                      }}
                    >
                      {isLoading ? '提交中...' : activeStep === 0 ? '下一步' : '确认注册'}
                    </Button>
                  </Box>
                )}
              </Box>

              {activeStep === 0 && (
                <Fade in timeout={1800}>
                  <Box sx={{ mt: 3, textAlign: 'center' }}>
                    <Typography variant="body2" color="text.secondary">
                      已有账户？{' '}
                      <Link
                        to="/login"
                        style={{
                          color: '#667eea',
                          textDecoration: 'none',
                          fontWeight: 'bold',
                        }}
                      >
                        立即登录
                      </Link>
                    </Typography>
                  </Box>
                </Fade>
              )}
            </Paper>
          </Fade>
        </Container>
      </Zoom>
    </Box>
  )
}
