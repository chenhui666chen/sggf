import { useNavigate } from 'react-router-dom'
import {
  Container,
  Box,
  Typography,
  Card,
  CardContent,
  CardActionArea,
  Grid,
  Button,
  Chip,
  alpha,
  IconButton,
  Tooltip,
} from '@mui/material'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import MovieIcon from '@mui/icons-material/Movie'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import LogoutIcon from '@mui/icons-material/Logout'
import { useDispatch } from 'react-redux'
import { logout } from '@/store/slices/authSlice'

// 破碎书册 SVG 图标（拆书工具入口）
const BrokenBookIcon = () => (
  <svg width="24" height="24" viewBox="0 0 24 24" fill="currentColor">
    {/* 左半本书 */}
    <path d="M3 4v14c0 1.1.9 2 2 2h4V2H5c-1.1 0-2 .9-2 2z" opacity="0.9" />
    {/* 右半本书（破碎效果） */}
    <path d="M13 2v6l2-1.5 2 1.5V2h2c1.1 0 2 .9 2 2v10l-3-2-3 2V6l-2 1.5L11 6v12h4l1 2h3c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2h-6z" opacity="0.7" />
    {/* 裂缝效果 */}
    <path d="M10 2h1v20h-1z" fill="#fff" opacity="0.3" />
    <path d="M11.5 8l1-2 1 3-1 2-1-3z" fill="#fff" opacity="0.5" />
  </svg>
)

// 模块配置
const modules = [
  {
    id: 'novel',
    title: '灵感方舟',
    subtitle: '小说创作',
    description: '智能小说创作工作流，从构思到成稿一站式完成',
    icon: AutoStoriesIcon,
    color: '#1976d2',
    available: true,
    path: '/dashboard',
  },
  {
    id: 'audiobook',
    title: '耳畔星河',
    subtitle: '有声小说创作',
    description: '将文字作品转化为有声读物，支持多种音色选择',
    icon: HeadphonesIcon,
    color: '#9c27b0',
    available: true, // 启用
    path: '/audiobook-dashboard',
  },
  {
    id: 'drama',
    title: '织梦映心',
    subtitle: '短剧创作',
    description: '短视频剧本创作，快速生成短剧内容（当前为模拟线路）',
    icon: MovieIcon,
    color: '#f57c00',
    available: true,
    path: '/drama',
    badge: '内测',
  },
  {
    id: 'ai-detect',
    title: '织文无迹',
    subtitle: 'AI痕迹降低',
    description: '检测与降低AI痕迹，让创作更自然流畅',
    icon: AutoFixHighIcon,
    color: '#2e7d32',
    available: true,
    path: '/ai-trace',
  },
]

export default function CreationModulePage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()

  const handleModuleClick = (module: typeof modules[0]) => {
    if (module.available) {
      navigate(module.path)
    }
  }

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  return (
    <Box
      sx={{
        height: '100vh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        py: 3,
        display: 'flex',
        flexDirection: 'column',
      }}
    >
      <Container maxWidth="lg" sx={{ flex: 1, display: 'flex', flexDirection: 'column' }}>
        {/* 头部 */}
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 3 }}>
          <Box>
            <Typography variant="h4" sx={{ color: 'white', fontWeight: 700, mb: 0.5 }}>
              创作工坊
            </Typography>
            <Typography variant="body1" sx={{ color: 'rgba(255,255,255,0.8)' }}>
              选择你的创作模式，开启智能创作之旅
            </Typography>
          </Box>
          <Button
            variant="outlined"
            size="small"
            startIcon={<LogoutIcon />}
            onClick={handleLogout}
            sx={{
              color: 'white',
              borderColor: 'rgba(255,255,255,0.5)',
              '&:hover': {
                borderColor: 'white',
                backgroundColor: 'rgba(255,255,255,0.1)',
              },
            }}
          >
            退出登录
          </Button>
        </Box>

        {/* 模块卡片网格 */}
        <Grid container spacing={2.5} sx={{ flex: 1 }}>
          {modules.map((module) => {
            const IconComponent = module.icon
            const isNovel = module.id === 'novel' // 灵感方舟模块
            return (
              <Grid item xs={12} sm={6} md={6} key={module.id}>
                <Card
                  sx={{
                    height: '100%',
                    borderRadius: 3,
                    transition: 'all 0.3s ease',
                    opacity: module.available ? 1 : 0.7,
                    position: 'relative', // 用于拆书入口定位
                    '&:hover': {
                      transform: module.available ? 'translateY(-4px)' : 'none',
                      boxShadow: module.available ? '0 12px 24px rgba(0,0,0,0.15)' : 'none',
                    },
                  }}
                >
                  {/* 灵感方舟卡片右上角的拆书入口 */}
                  {isNovel && (
                    <Tooltip title="拆书工具 - 智能分析书籍结构" placement="top" arrow>
                      <IconButton
                        onClick={(e) => {
                          e.stopPropagation()
                          navigate('/book-parser', { state: { from: '/home' } })
                        }}
                        sx={{
                          position: 'absolute',
                          top: 8,
                          right: 8,
                          zIndex: 10,
                          width: 40,
                          height: 40,
                          backgroundColor: 'rgba(0, 131, 143, 0.1)',
                          color: '#00838f',
                          transition: 'all 0.3s ease',
                          '&:hover': {
                            backgroundColor: 'rgba(0, 131, 143, 0.2)',
                            transform: 'scale(1.1) rotate(-5deg)',
                          },
                        }}
                      >
                        <BrokenBookIcon />
                      </IconButton>
                    </Tooltip>
                  )}
                  <CardActionArea
                    onClick={() => handleModuleClick(module)}
                    disabled={!module.available}
                    sx={{ height: '100%', p: 2 }}
                  >
                    <CardContent sx={{ textAlign: 'center', py: 1 }}>
                      {/* 图标 */}
                      <Box
                        sx={{
                          width: 64,
                          height: 64,
                          borderRadius: '50%',
                          mx: 'auto',
                          mb: 1.5,
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          backgroundColor: alpha(module.color, 0.1),
                        }}
                      >
                        <IconComponent sx={{ fontSize: 32, color: module.color }} />
                      </Box>
                      {/* 标题 */}
                      <Typography variant="h6" sx={{ fontWeight: 600, mb: 0.3, color: module.color }}>
                        {module.title}
                      </Typography>
                      {/* 副标题 */}
                      <Typography variant="caption" sx={{ color: 'text.secondary', display: 'block', mb: 0.5 }}>
                        {module.subtitle}
                      </Typography>
                      {/* 状态标签 */}
                      {module.badge && (
                        <Chip
                          label={module.badge}
                          size="small"
                          sx={{ mb: 1, backgroundColor: alpha(module.color, 0.1), color: module.color }}
                        />
                      )}
                      {!module.available && (
                        <Chip label="敬请期待" size="small" sx={{ mb: 1, backgroundColor: '#f5f5f5' }} />
                      )}
                      {/* 描述 */}
                      <Typography variant="body2" color="text.secondary">
                        {module.description}
                      </Typography>
                    </CardContent>
                  </CardActionArea>
                </Card>
              </Grid>
            )
          })}
        </Grid>
      </Container>
    </Box>
  )
}
