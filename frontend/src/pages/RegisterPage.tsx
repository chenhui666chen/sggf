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
  InputAdornment,
  IconButton,
  Fade,
  Zoom,
  Grid,
  Step,
  StepLabel,
  Stepper,
} from '@mui/material'
import {
  AccountCircle,
  Lock,
  Email,
  Phone,
  Visibility,
  VisibilityOff,
  RocketLaunch,
  CheckCircle,
} from '@mui/icons-material'
import { RootState, AppDispatch } from '@/store/store'
import { register, clearError } from '@/store/slices/authSlice'

export default function RegisterPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { isLoading, error } = useSelector((state: RootState) => state.auth)
  const [showPassword, setShowPassword] = useState(false)
  const [activeStep, setActiveStep] = useState(0)
  const [formData, setFormData] = useState({
    username: '', // 昵称
    email: '',
    phone: '',
    password: '',
  })
  const [formErrors, setFormErrors] = useState<{[key: string]: string}>({})

  const steps = ['填写信息', '确认提交', '完成']

  const validateEmail = (email: string) => {
    const re = /^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$/
    return re.test(email)
  }

  const validatePhone = (phone: string) => {
    if (!phone) return true // 手机号可选
    const re = /^1[3-9]\d{9}$/
    return re.test(phone)
  }

  const validateNickname = (nickname: string) => {
    return nickname.length >= 2 && nickname.length <= 50
  }

  const validatePassword = (password: string) => {
    return password.length >= 6 && password.length <= 50
  }

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }))
    // 清除对应字段的错误
    if (formErrors[name]) {
      setFormErrors((prev) => ({
        ...prev,
        [name]: '',
      }))
    }
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    
    if (activeStep === 0) {
      // 验证表单
      const errors: {[key: string]: string} = {}
      
      if (!validateNickname(formData.username)) {
        errors.username = '昵称长度必须在 2-50 个字符之间'
      }
      
      if (!validateEmail(formData.email)) {
        errors.email = '请输入有效的邮箱地址'
      }
      
      if (!validatePhone(formData.phone)) {
        errors.phone = '请输入有效的手机号码（可选）'
      }
      
      if (!validatePassword(formData.password)) {
        errors.password = '密码长度必须在 6-50 个字符之间'
      }
      
      if (Object.keys(errors).length > 0) {
        setFormErrors(errors)
        return
      }
      
      setActiveStep(1)
    } else if (activeStep === 1) {
      const result = await dispatch(register({
        ...formData,
        full_name: formData.username, // full_name 设置为昵称
      }))
      if (register.fulfilled.match(result)) {
        setActiveStep(2)
        setTimeout(() => {
          navigate('/home')
        }, 1500)
      }
    }
  }

  const handleBack = () => {
    setActiveStep((prev) => prev - 1)
    setFormErrors({})
  }

  const isStepValid = () => {
    if (activeStep === 0) {
      return formData.username && formData.email && formData.password && validateEmail(formData.email) && validatePhone(formData.phone)
    }
    return true
  }

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
          top: 0,
          left: 0,
          right: 0,
          bottom: 0,
          background: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='0.05' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
          opacity: 0.3,
        },
      }}
    >
      {/* 装饰性圆形背景 */}
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
              {/* Logo 和标题 */}
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

              {/* 步骤指示器 */}
              <Stepper
                activeStep={activeStep}
                sx={{ mb: 4, '& .MuiStepLabel-label': { color: '#667eea' } }}
              >
                {steps.map((label) => (
                  <Step key={label}>
                    <StepLabel>{label}</StepLabel>
                  </Step>
                ))}
              </Stepper>

              {/* 错误提示 */}
              <Fade in={!!error}>
                <Box>
                  <Alert
                    severity="error"
                    onClose={() => dispatch(clearError())}
                    sx={{ mb: 3 }}
                  >
                    {error}
                  </Alert>
                </Box>
              </Fade>

              {/* 注册表单 */}
              <Box component="form" onSubmit={handleSubmit} noValidate>
                {activeStep === 0 && (
                  <Fade in timeout={800}>
                    <Grid container spacing={3}>
                      <Grid item xs={12}>
                        <TextField
                          fullWidth
                          label="昵称"
                          name="username"
                          value={formData.username}
                          onChange={handleChange}
                          required
                          autoComplete="nickname"
                          error={!!formErrors.username}
                          helperText={formErrors.username || '用于在系统内展示您的身份'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <AccountCircle sx={{ color: '#667eea' }} />
                              </InputAdornment>
                            ),
                          }}
                          sx={{
                            '& .MuiOutlinedInput-root': {
                              borderRadius: 2,
                              '&:hover fieldset': {
                                borderColor: '#667eea',
                              },
                              '&.Mui-focused fieldset': {
                                borderColor: '#667eea',
                              },
                            },
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
                          helperText={formErrors.email || '将作为您的登录账号'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <Email sx={{ color: '#667eea' }} />
                              </InputAdornment>
                            ),
                          }}
                          sx={{
                            '& .MuiOutlinedInput-root': {
                              borderRadius: 2,
                              '&:hover fieldset': {
                                borderColor: '#667eea',
                              },
                              '&.Mui-focused fieldset': {
                                borderColor: '#667eea',
                              },
                            },
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
                          helperText={formErrors.phone || '也可作为登录账号'}
                          InputProps={{
                            startAdornment: (
                              <InputAdornment position="start">
                                <Phone sx={{ color: '#667eea' }} />
                              </InputAdornment>
                            ),
                          }}
                          sx={{
                            '& .MuiOutlinedInput-root': {
                              borderRadius: 2,
                              '&:hover fieldset': {
                                borderColor: '#667eea',
                              },
                              '&.Mui-focused fieldset': {
                                borderColor: '#667eea',
                              },
                            },
                          }}
                        />
                      </Grid>
                      <Grid item xs={12}>
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
                                <IconButton
                                  onClick={() => setShowPassword(!showPassword)}
                                  edge="end"
                                >
                                  {showPassword ? <VisibilityOff /> : <Visibility />}
                                </IconButton>
                              </InputAdornment>
                            ),
                          }}
                          sx={{
                            '& .MuiOutlinedInput-root': {
                              borderRadius: 2,
                              '&:hover fieldset': {
                                borderColor: '#667eea',
                              },
                              '&.Mui-focused fieldset': {
                                borderColor: '#667eea',
                              },
                            },
                          }}
                        />
                      </Grid>
                    </Grid>
                  </Fade>
                )}

                {activeStep === 1 && (
                  <Fade in timeout={800}>
                    <Box
                      sx={{
                        textAlign: 'center',
                        py: 4,
                      }}
                    >
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
                              昵称
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {formData.username}
                            </Typography>
                          </Grid>
                          <Grid item xs={6} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              邮箱
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {formData.email}
                            </Typography>
                          </Grid>
                          <Grid item xs={12} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              手机号
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {formData.phone || '未填写'}
                            </Typography>
                          </Grid>
                          <Grid item xs={12} sx={{ textAlign: 'left' }}>
                            <Typography variant="body2" color="text.secondary">
                              密码
                            </Typography>
                            <Typography variant="body1" fontWeight="medium">
                              {'•'.repeat(formData.password.length)}
                            </Typography>
                          </Grid>
                        </Grid>
                      </Box>
                    </Box>
                  </Fade>
                )}

                {activeStep === 2 && (
                  <Fade in timeout={800}>
                    <Box
                      sx={{
                        textAlign: 'center',
                        py: 4,
                      }}
                    >
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
                            animation: 'pulse 1.5s ease-in-out infinite',
                            '@keyframes pulse': {
                              '0%, 100%': {
                                transform: 'scale(1)',
                              },
                              '50%': {
                                transform: 'scale(1.1)',
                              },
                            },
                          }}
                        >
                          <CheckCircle sx={{ fontSize: 60, color: '#fff' }} />
                        </Box>
                      </Zoom>
                      <Typography variant="h5" fontWeight="bold" sx={{ mb: 1 }}>
                        注册成功！
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
                      <Fade in timeout={600}>
                        <Button
                          fullWidth
                          variant="outlined"
                          onClick={handleBack}
                          disabled={isLoading}
                          sx={{
                            py: 1.8,
                            borderRadius: 2,
                            fontSize: '1rem',
                            fontWeight: 'bold',
                            borderColor: '#667eea',
                            color: '#667eea',
                            '&:hover': {
                              borderColor: '#764ba2',
                              backgroundColor: 'rgba(102, 126, 234, 0.08)',
                            },
                            transition: 'all 0.3s ease',
                          }}
                        >
                          上一步
                        </Button>
                      </Fade>
                    )}
                    <Fade in timeout={600}>
                      <Button
                        fullWidth
                        variant="contained"
                        type="submit"
                        size="large"
                        disabled={isLoading || !isStepValid()}
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
                          transition: 'all 0.3s ease',
                        }}
                      >
                        {isLoading
                          ? '提交中...'
                          : activeStep === 0
                            ? '下一步'
                            : '确认注册'}
                      </Button>
                    </Fade>
                  </Box>
                )}
              </Box>

              {/* 登录链接 */}
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
                          transition: 'color 0.2s',
                        }}
                        onMouseEnter={(e) => (e.currentTarget.style.color = '#764ba2')}
                        onMouseLeave={(e) => (e.currentTarget.style.color = '#667eea')}
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
