import { useEffect, useState } from 'react'
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  CircularProgress,
} from '@mui/material'
import AdminIcon from '@mui/icons-material/AdminPanelSettings'
import FolderIcon from '@mui/icons-material/Folder'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import PeopleIcon from '@mui/icons-material/People'
import { useFormats } from '@/i18n'
import { useTranslation } from 'react-i18next'
import { apiClient } from '@/services/api'

interface StatsOverview {
  total_users: number
  new_users_today: number
  active_users_30d: number
  total_projects: number
  active_projects: number
  total_audiobook_tasks: number
  admin_operations_today: number
}

export default function AdminDashboardPage() {
  // 必须放在下面两个 early return（loading / error）之前，否则 hook 调用数会随渲染路径变。
  const { t } = useTranslation()
  const { formatNumber } = useFormats()
  const [stats, setStats] = useState<StatsOverview | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchStats()
  }, [])

  const fetchStats = async () => {
    try {
      setLoading(true)
      const response = await apiClient.get('/api/v1/admin/stats/overview')
      setStats(response.data)
    } catch (err: any) {
      setError(err.response?.data?.detail || t('admin.dashboard.messages.fetchFailed'))
    } finally {
      setLoading(false)
    }
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '50vh' }}>
        <CircularProgress />
      </Box>
    )
  }

  if (error) {
    return (
      <Box sx={{ p: 3 }}>
        <Typography color="error">{error}</Typography>
      </Box>
    )
  }

  const statCards = [
    {
      title: t('admin.dashboard.statCards.totalUsers'),
      value: stats?.total_users || 0,
      subValue: t('admin.dashboard.statCards.newToday', { count: stats?.new_users_today || 0 }),
      icon: <PeopleIcon sx={{ fontSize: 40 }} />,
      color: '#1976d2', // sg-color-fixed: 统计卡身份色（颜色即数据）
    },
    {
      title: t('admin.dashboard.statCards.activeUsers30d'),
      value: stats?.active_users_30d || 0,
      icon: <PeopleIcon sx={{ fontSize: 40 }} />,
      color: '#2e7d32', // sg-color-fixed: 统计卡身份色（颜色即数据）
    },
    {
      title: t('admin.dashboard.statCards.totalProjects'),
      value: stats?.total_projects || 0,
      subValue: t('admin.dashboard.statCards.inProgress', { count: stats?.active_projects || 0 }),
      icon: <FolderIcon sx={{ fontSize: 40 }} />,
      color: '#ed6c02', // sg-color-fixed: 统计卡身份色（颜色即数据）
    },
    {
      title: t('admin.dashboard.statCards.audiobookTasks'),
      value: stats?.total_audiobook_tasks || 0,
      icon: <HeadphonesIcon sx={{ fontSize: 40 }} />,
      color: '#9c27b0', // sg-color-fixed: 统计卡身份色（颜色即数据）
    },
    {
      title: t('admin.dashboard.statCards.adminOpsToday'),
      value: stats?.admin_operations_today || 0,
      icon: <AdminIcon sx={{ fontSize: 40 }} />,
      color: '#dc004e', // sg-color-fixed: 统计卡身份色（颜色即数据）
    },
  ]

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
        {t('admin.dashboard.title')}
      </Typography>
      
      <Grid container spacing={3}>
        {statCards.map((card, index) => (
          <Grid item xs={12} sm={6} md={4} key={index}>
            <Card sx={{ height: '100%' }}>
              <CardContent>
                <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
                  <Box>
                    <Typography color="textSecondary" gutterBottom variant="body2">
                      {card.title}
                    </Typography>
                    <Typography variant="h4" component="div" sx={{ fontWeight: 'bold', color: card.color }}>
                      {formatNumber(card.value)}
                    </Typography>
                    {card.subValue && (
                      <Typography variant="body2" color="textSecondary" sx={{ mt: 1 }}>
                        {card.subValue}
                      </Typography>
                    )}
                  </Box>
                  <Box sx={{ color: card.color, opacity: 0.7 }}>
                    {card.icon}
                  </Box>
                </Box>
              </CardContent>
            </Card>
          </Grid>
        ))}
      </Grid>
    </Box>
  )
}
