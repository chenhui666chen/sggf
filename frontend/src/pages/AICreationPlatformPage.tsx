import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Box,
  Container,
  Typography,
  Button,
  Grid,
  Card,
  CardContent,
  CardMedia,
  Chip,
  Tabs,
  Tab,
  Fade,
} from '@mui/material'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import MovieCreationIcon from '@mui/icons-material/MovieCreation'
import PaletteIcon from '@mui/icons-material/Palette'
import PsychologyIcon from '@mui/icons-material/Psychology'
import RocketLaunchIcon from '@mui/icons-material/RocketLaunch'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'

// 示例作品数据
const showcaseWorks = [
  {
    id: 1,
    title: '星际迷航',
    description: '科幻题材动态漫',
    coverImage: 'https://picsum.photos/seed/scifi1/800/600',
    tags: ['科幻', '冒险', '动态漫'],
    views: '12.5 万',
  },
  {
    id: 2,
    title: '古代传奇',
    description: '历史题材动态漫',
    coverImage: 'https://picsum.photos/seed/historical2/800/600',
    tags: ['历史', '剧情', '动态漫'],
    views: '8.3 万',
  },
  {
    id: 3,
    title: '都市奇幻',
    description: '现代奇幻动态漫',
    coverImage: 'https://picsum.photos/seed/fantasy3/800/600',
    tags: ['奇幻', '都市', '动态漫'],
    views: '15.2 万',
  },
  {
    id: 4,
    title: '武侠世界',
    description: '传统武侠动态漫',
    coverImage: 'https://picsum.photos/seed/wuxia4/800/600',
    tags: ['武侠', '动作', '动态漫'],
    views: '10.8 万',
  },
]

// 功能特性
const features = [
  {
    icon: PsychologyIcon,
    title: '智能剧本创作',
    description: 'AI 辅助构思剧情、人物设定、世界观构建',
    color: '#6366f1',
  },
  {
    icon: PaletteIcon,
    title: 'AI 图片生成',
    description: '自动生成角色立绘、场景背景、道具素材',
    color: '#ec4899',
  },
  {
    icon: MovieCreationIcon,
    title: '动态漫制作',
    description: '一键生成分镜、镜头运动、特效合成',
    color: '#8b5cf6',
  },
  {
    icon: AutoFixHighIcon,
    title: '智能优化',
    description: '自动检测冲突、优化节奏、提升质量',
    color: '#14b8a6',
  },
]

// 创作步骤
const creationSteps = [
  {
    step: 1,
    title: '构思故事',
    description: '输入故事大纲或选择模板',
  },
  {
    step: 2,
    title: '生成角色',
    description: 'AI 生成角色形象和性格设定',
  },
  {
    step: 3,
    title: '创建场景',
    description: '自动生成场景图片和氛围描述',
  },
  {
    step: 4,
    title: '制作分镜',
    description: '智能分镜和镜头设计',
  },
  {
    step: 5,
    title: '合成输出',
    description: '渲染成动态漫视频',
  },
]

export default function AICreationPlatformPage() {
  const navigate = useNavigate()
  const [showcaseTab, setShowcaseTab] = useState(0)

  const handleStartCreation = () => {
    navigate('/drama')
  }

  return (
    <Box sx={{ minHeight: '100vh', bgcolor: '#0a0a0f' }}>
      {/* 导航栏 */}
      <Box
        sx={{
          position: 'fixed',
          top: 0,
          left: 0,
          right: 0,
          zIndex: 1000,
          bgcolor: 'rgba(10,10,15,0.8)',
          backdropFilter: 'blur(10px)',
          borderBottom: '1px solid rgba(255,255,255,0.1)',
        }}
      >
        <Container maxWidth="lg">
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', py: 2 }}>
            <Typography variant="h6" sx={{ fontWeight: 'bold', color: '#fff' }}>
              WandAIGC
            </Typography>
            <Box sx={{ display: 'flex', gap: 2 }}>
              <Button color="inherit" onClick={() => navigate('/home')}>
                返回创作模块
              </Button>
              <Button
                variant="contained"
                startIcon={<RocketLaunchIcon />}
                onClick={handleStartCreation}
              >
                开始创作
              </Button>
            </Box>
          </Box>
        </Container>
      </Box>

      {/* Hero 区域 */}
      <Box
        sx={{
          pt: '120px',
          pb: '80px',
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          position: 'relative',
          overflow: 'hidden',
        }}
      >
        {/* 背景装饰 */}
        <Box
          sx={{
            position: 'absolute',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            opacity: 0.1,
            background: `url("data:image/svg+xml,%3Csvg width='60' height='60' viewBox='0 0 60 60' xmlns='http://www.w3.org/2000/svg'%3E%3Cg fill='none' fill-rule='evenodd'%3E%3Cg fill='%23ffffff' fill-opacity='1'%3E%3Cpath d='M36 34v-4h-2v4h-4v2h4v4h2v-4h4v-2h-4zm0-30V0h-2v4h-4v2h4v4h2V6h4V4h-4zM6 34v-4H4v4H0v2h4v4h2v-4h4v-2H6zM6 4V0H4v4H0v2h4v4h2V6h4V4H6z'/%3E%3C/g%3E%3C/g%3E%3C/svg%3E")`,
          }}
        />

        <Container maxWidth="lg" sx={{ position: 'relative', zIndex: 1 }}>
          <Grid container spacing={4} alignItems="center">
            <Grid item xs={12} md={6}>
              <Fade in timeout={1000}>
                <Box>
                  <Chip
                    label="🎉 全球首个全集 AI 动态漫制作平台"
                    sx={{
                      mb: 2,
                      bgcolor: 'rgba(255,255,255,0.2)',
                      color: '#fff',
                      fontWeight: 'bold',
                    }}
                  />
                  <Typography
                    variant="h2"
                    sx={{
                      color: '#fff',
                      fontWeight: 'bold',
                      mb: 3,
                      fontSize: { xs: '2rem', md: '3.5rem' },
                    }}
                  >
                    从剧本创作
                    <br />
                    到视频制作
                  </Typography>
                  <Typography
                    variant="h5"
                    sx={{
                      color: 'rgba(255,255,255,0.9)',
                      mb: 4,
                      lineHeight: 1.6,
                    }}
                  >
                    一站式 AI 创作工具，让每个人都能成为优秀的创作者
                  </Typography>
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <Button
                      variant="contained"
                      size="large"
                      startIcon={<RocketLaunchIcon />}
                      onClick={handleStartCreation}
                      sx={{
                        bgcolor: '#fff',
                        color: '#667eea',
                        px: 4,
                        py: 1.5,
                        fontSize: '1.1rem',
                        fontWeight: 'bold',
                        '&:hover': {
                          bgcolor: '#f0f0f0',
                        },
                      }}
                    >
                      立即开始
                    </Button>
                    <Button
                      variant="outlined"
                      size="large"
                      startIcon={<PlayArrowIcon />}
                      sx={{
                        color: '#fff',
                        borderColor: 'rgba(255,255,255,0.5)',
                        px: 4,
                        py: 1.5,
                        fontSize: '1.1rem',
                        '&:hover': {
                          borderColor: '#fff',
                          bgcolor: 'rgba(255,255,255,0.1)',
                        },
                      }}
                    >
                      观看演示
                    </Button>
                  </Box>
                </Box>
              </Fade>
            </Grid>
            <Grid item xs={12} md={6}>
              <Fade in timeout={1500}>
                <Box
                  sx={{
                    position: 'relative',
                    borderRadius: 4,
                    overflow: 'hidden',
                    boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
                  }}
                >
                  <Box
                    component="img"
                    src="https://picsum.photos/seed/showcase/1200/800"
                    alt="AI Creation Showcase"
                    sx={{
                      width: '100%',
                      height: 'auto',
                      display: 'block',
                    }}
                  />
                  {/* 播放按钮覆盖层 */}
                  <Box
                    sx={{
                      position: 'absolute',
                      top: 0,
                      left: 0,
                      right: 0,
                      bottom: 0,
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      bgcolor: 'rgba(0,0,0,0.3)',
                      cursor: 'pointer',
                      '&:hover': {
                        bgcolor: 'rgba(0,0,0,0.4)',
                      },
                    }}
                  >
                    <Box
                      sx={{
                        width: 80,
                        height: 80,
                        borderRadius: '50%',
                        bgcolor: 'rgba(255,255,255,0.9)',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        transition: 'transform 0.3s',
                        '&:hover': {
                          transform: 'scale(1.1)',
                        },
                      }}
                    >
                      <PlayArrowIcon sx={{ fontSize: 40, color: '#667eea', ml: 1 }} />
                    </Box>
                  </Box>
                </Box>
              </Fade>
            </Grid>
          </Grid>
        </Container>
      </Box>

      {/* 功能特性 */}
      <Container maxWidth="lg" sx={{ py: 8 }}>
        <Typography variant="h3" align="center" sx={{ color: '#fff', mb: 2, fontWeight: 'bold' }}>
          强大的创作功能
        </Typography>
        <Typography variant="h6" align="center" sx={{ color: 'rgba(255,255,255,0.7)', mb: 6 }}>
          从构思到成品，全流程 AI 辅助
        </Typography>

        <Grid container spacing={4}>
          {features.map((feature, index) => (
            <Grid item xs={12} sm={6} md={3} key={index}>
              <Fade in timeout={500 + index * 100}>
                <Card
                  sx={{
                    height: '100%',
                    bgcolor: 'rgba(255,255,255,0.05)',
                    border: '1px solid rgba(255,255,255,0.1)',
                    transition: 'transform 0.3s, box-shadow 0.3s',
                    '&:hover': {
                      transform: 'translateY(-8px)',
                      boxShadow: '0 12px 40px rgba(0,0,0,0.3)',
                      borderColor: feature.color,
                    },
                  }}
                >
                  <CardContent sx={{ p: 3, textAlign: 'center' }}>
                    <Box
                      sx={{
                        width: 64,
                        height: 64,
                        mx: 'auto',
                        mb: 2,
                        borderRadius: 2,
                        bgcolor: `${feature.color}20`,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                      }}
                    >
                      <feature.icon sx={{ fontSize: 32, color: feature.color }} />
                    </Box>
                    <Typography variant="h6" sx={{ color: '#fff', mb: 1, fontWeight: 'bold' }}>
                      {feature.title}
                    </Typography>
                    <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
                      {feature.description}
                    </Typography>
                  </CardContent>
                </Card>
              </Fade>
            </Grid>
          ))}
        </Grid>
      </Container>

      {/* 创作流程 */}
      <Box sx={{ bgcolor: 'rgba(255,255,255,0.02)', py: 8 }}>
        <Container maxWidth="lg">
          <Typography variant="h3" align="center" sx={{ color: '#fff', mb: 2, fontWeight: 'bold' }}>
            简单的创作流程
          </Typography>
          <Typography variant="h6" align="center" sx={{ color: 'rgba(255,255,255,0.7)', mb: 6 }}>
            5 步完成你的动态漫作品
          </Typography>

          <Box sx={{ display: 'flex', justifyContent: 'space-between', position: 'relative' }}>
            {/* 连接线 */}
            <Box
              sx={{
                position: 'absolute',
                top: 40,
                left: 0,
                right: 0,
                height: 2,
                bgcolor: 'rgba(255,255,255,0.1)',
                zIndex: 0,
                display: { xs: 'none', md: 'block' },
              }}
            />

            {creationSteps.map((step, index) => (
              <Fade in timeout={500 + index * 100} key={index}>
                <Box
                  sx={{
                    position: 'relative',
                    zIndex: 1,
                    textAlign: 'center',
                    flex: 1,
                  }}
                >
                  <Box
                    sx={{
                      width: 80,
                      height: 80,
                      mx: 'auto',
                      mb: 2,
                      borderRadius: '50%',
                      bgcolor: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      color: '#fff',
                      fontSize: '1.5rem',
                      fontWeight: 'bold',
                      border: '4px solid rgba(255,255,255,0.1)',
                    }}
                  >
                    {step.step}
                  </Box>
                  <Typography variant="h6" sx={{ color: '#fff', mb: 1, fontWeight: 'bold' }}>
                    {step.title}
                  </Typography>
                  <Typography sx={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.9rem' }}>
                    {step.description}
                  </Typography>
                </Box>
              </Fade>
            ))}
          </Box>
        </Container>
      </Box>

      {/* 作品展示 */}
      <Container maxWidth="lg" sx={{ py: 8 }}>
        <Typography variant="h3" align="center" sx={{ color: '#fff', mb: 2, fontWeight: 'bold' }}>
          精彩作品展示
        </Typography>
        <Typography variant="h6" align="center" sx={{ color: 'rgba(255,255,255,0.7)', mb: 4 }}>
          看看其他创作者的作品
        </Typography>

        <Tabs
          value={showcaseTab}
          onChange={(_, newValue) => setShowcaseTab(newValue)}
          centered
          sx={{
            mb: 4,
            '& .MuiTab-root': {
              color: 'rgba(255,255,255,0.7)',
              '&.Mui-selected': {
                color: '#fff',
              },
            },
            '& .MuiTabs-indicator': {
              bgcolor: '#667eea',
            },
          }}
        >
          <Tab label="全部" />
          <Tab label="科幻" />
          <Tab label="奇幻" />
          <Tab label="历史" />
          <Tab label="武侠" />
        </Tabs>

        <Grid container spacing={3}>
          {showcaseWorks.map((work, index) => (
            <Grid item xs={12} sm={6} md={3} key={work.id}>
              <Fade in timeout={500 + index * 100}>
                <Card
                  sx={{
                    transition: 'transform 0.3s',
                    '&:hover': {
                      transform: 'scale(1.05)',
                    },
                  }}
                >
                  <Box sx={{ position: 'relative' }}>
                    <CardMedia
                      component="img"
                      height="240"
                      image={work.coverImage}
                      alt={work.title}
                      sx={{ objectFit: 'cover' }}
                    />
                    <Box
                      sx={{
                        position: 'absolute',
                        top: 8,
                        right: 8,
                        bgcolor: 'rgba(0,0,0,0.7)',
                        color: '#fff',
                        px: 1,
                        py: 0.5,
                        borderRadius: 1,
                        fontSize: '0.8rem',
                      }}
                    >
                      👁️ {work.views}
                    </Box>
                  </Box>
                  <CardContent sx={{ p: 2 }}>
                    <Typography variant="h6" sx={{ fontWeight: 'bold', mb: 1 }}>
                      {work.title}
                    </Typography>
                    <Typography variant="body2" sx={{ color: 'text.secondary', mb: 1 }}>
                      {work.description}
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                      {work.tags.map((tag) => (
                        <Chip
                          key={tag}
                          label={tag}
                          size="small"
                          sx={{
                            bgcolor: 'rgba(102,126,234,0.1)',
                            color: '#667eea',
                            fontSize: '0.75rem',
                          }}
                        />
                      ))}
                    </Box>
                  </CardContent>
                </Card>
              </Fade>
            </Grid>
          ))}
        </Grid>
      </Container>

      {/* CTA 区域 */}
      <Box
        sx={{
          py: 8,
          background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
          textAlign: 'center',
        }}
      >
        <Container maxWidth="md">
          <Typography variant="h3" sx={{ color: '#fff', mb: 2, fontWeight: 'bold' }}>
            准备好开始创作了吗？
          </Typography>
          <Typography variant="h6" sx={{ color: 'rgba(255,255,255,0.9)', mb: 4 }}>
            立即加入，开启你的 AI 创作之旅
          </Typography>
          <Button
            variant="contained"
            size="large"
            startIcon={<RocketLaunchIcon />}
            onClick={handleStartCreation}
            sx={{
              bgcolor: '#fff',
              color: '#667eea',
              px: 6,
              py: 2,
              fontSize: '1.2rem',
              fontWeight: 'bold',
              '&:hover': {
                bgcolor: '#f0f0f0',
              },
            }}
          >
            免费开始创作
          </Button>
        </Container>
      </Box>

      {/* 页脚 */}
      <Box sx={{ bgcolor: 'rgba(0,0,0,0.5)', py: 4, borderTop: '1px solid rgba(255,255,255,0.1)' }}>
        <Container maxWidth="lg">
          <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <Typography sx={{ color: 'rgba(255,255,255,0.7)' }}>
              © 2024 WandAIGC. All rights reserved.
            </Typography>
            <Box sx={{ display: 'flex', gap: 2 }}>
              <Button sx={{ color: 'rgba(255,255,255,0.7)' }}>使用条款</Button>
              <Button sx={{ color: 'rgba(255,255,255,0.7)' }}>隐私政策</Button>
              <Button sx={{ color: 'rgba(255,255,255,0.7)' }}>联系我们</Button>
            </Box>
          </Box>
        </Container>
      </Box>
    </Box>
  )
}
