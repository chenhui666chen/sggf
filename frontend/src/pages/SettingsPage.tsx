import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  Card,
  CardContent,
  Button,
  TextField,
  Typography,
  Alert,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import SaveIcon from '@mui/icons-material/Save'
import { RootState, AppDispatch } from '@/store/store'
import { logout } from '@/store/slices/authSlice'
import { apiClient, extractApiErrorMessage } from '@/services/api'

export default function SettingsPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { user } = useSelector((state: RootState) => state.auth)
  const [passwordData, setPasswordData] = useState({
    old_password: '',
    new_password: '',
    confirm_password: '',
  })
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null)
  const [isLoading, setIsLoading] = useState(false)

  const handleChangePassword = async () => {
    if (passwordData.new_password !== passwordData.confirm_password) {
      setMessage({ type: 'error', text: '两次输入的新密码不一致' })
      return
    }

    if (passwordData.new_password.length < 6) {
      setMessage({ type: 'error', text: '新密码长度不能少于 6 个字符' })
      return
    }

    setIsLoading(true)
    try {
      const response = await apiClient.changePassword({
        old_password: passwordData.old_password,
        new_password: passwordData.new_password,
      })
      setMessage({ type: 'success', text: response.data?.message || '密码修改成功' })
      setPasswordData({ old_password: '', new_password: '', confirm_password: '' })
    } catch (error) {
      setMessage({ type: 'error', text: await extractApiErrorMessage(error, '密码修改失败') })
    } finally {
      setIsLoading(false)
    }
  }

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  return (
    <Container maxWidth="md" sx={{ py: 4 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
        >
          返回
        </Button>
        <Typography variant="h5">账户设置</Typography>
      </Box>

      {message && (
        <Alert severity={message.type} onClose={() => setMessage(null)} sx={{ mb: 2 }}>
          {message.text}
        </Alert>
      )}

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            账户信息
          </Typography>
          <Box sx={{ mt: 2 }}>
            <Typography variant="body2" color="textSecondary">
              用户名：<strong>{user?.username}</strong>
            </Typography>
            <Typography variant="body2" color="textSecondary">
              邮箱：<strong>{user?.email}</strong>
            </Typography>
            <Typography variant="body2" color="textSecondary">
              显示名称：<strong>{user?.full_name || '未设置'}</strong>
            </Typography>
          </Box>
        </CardContent>
      </Card>

      <Card sx={{ mb: 3 }}>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            修改密码
          </Typography>
          <TextField
            fullWidth
            label="当前密码"
            type="password"
            value={passwordData.old_password}
            onChange={(e) => setPasswordData({ ...passwordData, old_password: e.target.value })}
            margin="normal"
          />
          <TextField
            fullWidth
            label="新密码"
            type="password"
            value={passwordData.new_password}
            onChange={(e) => setPasswordData({ ...passwordData, new_password: e.target.value })}
            margin="normal"
          />
          <TextField
            fullWidth
            label="确认新密码"
            type="password"
            value={passwordData.confirm_password}
            onChange={(e) => setPasswordData({ ...passwordData, confirm_password: e.target.value })}
            margin="normal"
          />
          <Button
            variant="contained"
            color="primary"
            startIcon={<SaveIcon />}
            onClick={handleChangePassword}
            disabled={isLoading}
            sx={{ mt: 2 }}
          >
            {isLoading ? '提交中...' : '更新密码'}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardContent>
          <Typography variant="h6" gutterBottom>
            退出登录
          </Typography>
          <Typography variant="body2" color="textSecondary" sx={{ mb: 2 }}>
            点击下方按钮即可退出当前账号。
          </Typography>
          <Button
            variant="outlined"
            color="error"
            onClick={handleLogout}
          >
            退出登录
          </Button>
        </CardContent>
      </Card>
    </Container>
  )
}
