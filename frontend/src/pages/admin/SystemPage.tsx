import { useEffect, useState } from 'react'
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  Button,
  CircularProgress,
  Alert,
  Chip,
  LinearProgress,
  Paper,
} from '@mui/material'
import {
  Storage as StorageIcon,
  Memory as MemoryIcon,
  Dns as DnsIcon,
  CheckCircle as CheckCircleIcon,
  Error as ErrorIcon,
  Refresh as RefreshIcon,
} from '@mui/icons-material'
import { useSelector } from 'react-redux'
import { apiClient } from '@/services/api'
import { RootState } from '@/store/store'

interface SystemHealth {
  database: string
  timestamp: string
}

export default function SystemPage() {
  const { user } = useSelector((state: RootState) => state.auth)
  const isSuperAdmin = (user as any)?.roles?.some((r: any) => r.code === 'super_admin')
  
  const [health, setHealth] = useState<SystemHealth | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)

  useEffect(() => {
    fetchSystemHealth()
  }, [])

  const fetchSystemHealth = async () => {
    try {
      setRefreshing(true)
      const response = await apiClient.get('/api/v1/admin/stats/system/health')
      setHealth(response.data)
      setError(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || '获取系统状态失败')
    } finally {
      setLoading(false)
      setRefreshing(false)
    }
  }

  const getHealthStatus = (status: string) => {
    if (status === 'healthy') {
      return { icon: <CheckCircleIcon color="success" />, label: '正常', color: 'success' as const }
    }
    return { icon: <ErrorIcon color="error" />, label: '异常', color: 'error' as const }
  }

  if (!isSuperAdmin) {
    return (
      <Box>
        <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
          系统配置
        </Typography>
        <Alert severity="warning">
          您没有权限访问此页面，仅超级管理员可查看系统配置。
        </Alert>
      </Box>
    )
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  const dbStatus = health ? getHealthStatus(health.database) : null

  return (
    <Box>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
        <Typography variant="h4">
          系统配置
        </Typography>
        <Button
          variant="outlined"
          startIcon={refreshing ? <CircularProgress size={20} /> : <RefreshIcon />}
          onClick={fetchSystemHealth}
          disabled={refreshing}
        >
          刷新状态
        </Button>
      </Box>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }} onClose={() => setError(null)}>
          {error}
        </Alert>
      )}

      <Grid container spacing={3}>
        {/* 系统健康状态 */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <DnsIcon /> 系统健康状态
              </Typography>
              <Box sx={{ mt: 2 }}>
                <Paper variant="outlined" sx={{ p: 2, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 2 }}>
                    <StorageIcon sx={{ fontSize: 40, color: 'primary.main' }} />
                    <Box>
                      <Typography variant="subtitle1">数据库连接</Typography>
                      <Typography variant="body2" color="text.secondary">
                        PostgreSQL
                      </Typography>
                    </Box>
                  </Box>
                  {dbStatus && (
                    <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                      {dbStatus.icon}
                      <Chip label={dbStatus.label} color={dbStatus.color} size="small" />
                    </Box>
                  )}
                </Paper>
              </Box>
              {health && (
                <Typography variant="caption" color="text.secondary" sx={{ mt: 2, display: 'block' }}>
                  最后检查时间: {new Date(health.timestamp).toLocaleString('zh-CN')}
                </Typography>
              )}
            </CardContent>
          </Card>
        </Grid>

        {/* 存储空间 */}
        <Grid item xs={12} md={6}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <StorageIcon /> 存储空间
              </Typography>
              <Box sx={{ mt: 2 }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  已使用空间
                </Typography>
                <LinearProgress 
                  variant="determinate" 
                  value={45} 
                  sx={{ height: 10, borderRadius: 5, mb: 1 }}
                />
                <Typography variant="body2" color="text.secondary">
                  4.5 GB / 10 GB (45%)
                </Typography>
              </Box>
              <Box sx={{ mt: 3 }}>
                <Typography variant="body2" color="text.secondary" gutterBottom>
                  文件统计
                </Typography>
                <Grid container spacing={2}>
                  <Grid item xs={6}>
                    <Paper variant="outlined" sx={{ p: 1.5, textAlign: 'center' }}>
                      <Typography variant="h5" color="primary">1,234</Typography>
                      <Typography variant="caption" color="text.secondary">项目文件</Typography>
                    </Paper>
                  </Grid>
                  <Grid item xs={6}>
                    <Paper variant="outlined" sx={{ p: 1.5, textAlign: 'center' }}>
                      <Typography variant="h5" color="secondary">567</Typography>
                      <Typography variant="caption" color="text.secondary">音频文件</Typography>
                    </Paper>
                  </Grid>
                </Grid>
              </Box>
            </CardContent>
          </Card>
        </Grid>

        {/* 系统信息 */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                <MemoryIcon /> 系统信息
              </Typography>
              <Grid container spacing={2} sx={{ mt: 1 }}>
                <Grid item xs={12} sm={6} md={3}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="body2" color="text.secondary">系统版本</Typography>
                    <Typography variant="h6">v1.0.0</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="body2" color="text.secondary">API 版本</Typography>
                    <Typography variant="h6">v1</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="body2" color="text.secondary">Python 版本</Typography>
                    <Typography variant="h6">3.11.x</Typography>
                  </Paper>
                </Grid>
                <Grid item xs={12} sm={6} md={3}>
                  <Paper variant="outlined" sx={{ p: 2 }}>
                    <Typography variant="body2" color="text.secondary">数据库版本</Typography>
                    <Typography variant="h6">PostgreSQL 15</Typography>
                  </Paper>
                </Grid>
              </Grid>
            </CardContent>
          </Card>
        </Grid>

        {/* 功能配置 */}
        <Grid item xs={12}>
          <Card>
            <CardContent>
              <Typography variant="h6" gutterBottom>
                功能配置
              </Typography>
              <Alert severity="info" sx={{ mt: 2 }}>
                系统配置功能正在开发中，敬请期待。后续将支持：
                <ul style={{ margin: '8px 0', paddingLeft: '20px' }}>
                  <li>API 密钥管理</li>
                  <li>邮件服务配置</li>
                  <li>存储空间管理</li>
                  <li>系统参数调整</li>
                </ul>
              </Alert>
            </CardContent>
          </Card>
        </Grid>
      </Grid>
    </Box>
  )
}
