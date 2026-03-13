import { useEffect, useState } from 'react'
import {
  Box,
  Card,
  CardContent,
  Typography,
  Grid,
  CircularProgress,
} from '@mui/material'
import {
  People as PeopleIcon,
  Folder as FolderIcon,
  Headphones as HeadphonesIcon,
  AdminPanelSettings as AdminIcon,
} from '@mui/icons-material'
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
      setError(err.response?.data?.detail || '获取统计数据失败')
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
      title: '总用户数',
      value: stats?.total_users || 0,
      subValue: `今日新增: ${stats?.new_users_today || 0}`,
      icon: <PeopleIcon sx={{ fontSize: 40 }} />,
      color: '#1976d2',
    },
    {
      title: '活跃用户（30天）',
      value: stats?.active_users_30d || 0,
      icon: <PeopleIcon sx={{ fontSize: 40 }} />,
      color: '#2e7d32',
    },
    {
      title: '总项目数',
      value: stats?.total_projects || 0,
      subValue: `进行中: ${stats?.active_projects || 0}`,
      icon: <FolderIcon sx={{ fontSize: 40 }} />,
      color: '#ed6c02',
    },
    {
      title: '有声书任务',
      value: stats?.total_audiobook_tasks || 0,
      icon: <HeadphonesIcon sx={{ fontSize: 40 }} />,
      color: '#9c27b0',
    },
    {
      title: '今日管理操作',
      value: stats?.admin_operations_today || 0,
      icon: <AdminIcon sx={{ fontSize: 40 }} />,
      color: '#dc004e',
    },
  ]

  return (
    <Box>
      <Typography variant="h4" gutterBottom sx={{ mb: 3 }}>
        数据仪表盘
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
                      {card.value.toLocaleString()}
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
