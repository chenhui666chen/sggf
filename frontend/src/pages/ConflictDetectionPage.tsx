import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import {
  Box,
  Container,
  Typography,
  Button,
  Card,
  CardContent,
  IconButton,
  Breadcrumbs,
  Link,
} from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import HomeIcon from '@mui/icons-material/Home'
import ConflictDetector from '@/components/ConflictDetector'
import { apiClient } from '@/services/api'

interface Project {
  id: number
  title: string
  description?: string
}

export default function ConflictDetectionPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const [project, setProject] = useState<Project | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (projectId) {
      loadProject()
    }
  }, [projectId])

  const loadProject = async () => {
    try {
      setLoading(true)
      const response = await apiClient.getProject(Number(projectId))
      setProject(response.data)
    } catch (error) {
      console.error('加载项目失败:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleBack = () => {
    navigate(`/knowledge-base/${projectId}`)
  }

  const handleGoHome = () => {
    navigate('/home')
  }

  const handleSelectItem = (itemId: number) => {
    // 跳转到知识库页面并定位到该项
    navigate(`/knowledge-base/${projectId}?item=${itemId}`)
  }

  if (loading) {
    return (
      <Container maxWidth="lg" sx={{ mt: 4 }}>
        <Typography>加载中...</Typography>
      </Container>
    )
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: 'background.default', py: 3 }}>
      <Container maxWidth="lg">
        {/* 面包屑导航 */}
        <Box sx={{ mb: 3 }}>
          <Breadcrumbs aria-label="breadcrumb">
            <Link
              component="button"
              variant="body2"
              onClick={handleGoHome}
              sx={{ display: 'flex', alignItems: 'center', cursor: 'pointer' }}
            >
              <HomeIcon sx={{ mr: 0.5 }} fontSize="small" />
              首页
            </Link>
            {project && (
              <Link
                component="button"
                variant="body2"
                onClick={handleBack}
                sx={{ cursor: 'pointer' }}
              >
                {project.title}
              </Link>
            )}
            <Typography color="text.primary">冲突检测</Typography>
          </Breadcrumbs>
        </Box>

        {/* 页面标题 */}
        <Box sx={{ mb: 3, display: 'flex', alignItems: 'center', gap: 2 }}>
          <IconButton onClick={handleBack} size="small">
            <ArrowBackIcon />
          </IconButton>
          <Typography variant="h4" component="h1" sx={{ flexGrow: 1 }}>
            冲突检测
          </Typography>
          <Button variant="outlined" onClick={handleBack}>
            返回知识库
          </Button>
        </Box>

        {/* 冲突检测器组件 */}
        <Card>
          <CardContent>
            {projectId && (
              <ConflictDetector
                projectId={Number(projectId)}
                onSelectItem={handleSelectItem}
                title="设定冲突检测"
              />
            )}
          </CardContent>
        </Card>
      </Container>
    </Box>
  )
}
