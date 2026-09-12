import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
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

export default function AICreationPlatformPage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const [showcaseTab, setShowcaseTab] = useState(0)

  // 示例作品数据（组件内构造以支持 i18n）
  const showcaseWorks = [
    { id: 1, title: t('aiPlatform.work1.title'), description: t('aiPlatform.work1.description'), coverImage: 'https://picsum.photos/seed/scifi1/800/600', tags: [t('aiPlatform.tabScifi'), t('aiPlatform.tagAdventure'), t('aiPlatform.tagDynamicComic')], views: t('aiPlatform.work1.views') },
    { id: 2, title: t('aiPlatform.work2.title'), description: t('aiPlatform.work2.description'), coverImage: 'https://picsum.photos/seed/historical2/800/600', tags: [t('aiPlatform.tabHistory'), t('aiPlatform.tagDrama'), t('aiPlatform.tagDynamicComic')], views: t('aiPlatform.work2.views') },
    { id: 3, title: t('aiPlatform.work3.title'), description: t('aiPlatform.work3.description'), coverImage: 'https://picsum.photos/seed/fantasy3/800/600', tags: [t('aiPlatform.tabFantasy'), t('aiPlatform.tagUrban'), t('aiPlatform.tagDynamicComic')], views: t('aiPlatform.work3.views') },
    { id: 4, title: t('aiPlatform.work4.title'), description: t('aiPlatform.work4.description'), coverImage: 'https://picsum.photos/seed/wuxia4/800/600', tags: [t('aiPlatform.tabWuxia'), t('aiPlatform.tagAction'), t('aiPlatform.tagDynamicComic')], views: t('aiPlatform.work4.views') },
  ]

  // 功能特性（组件内构造以支持 i18n）
  const features = [
    { icon: PsychologyIcon, title: t('aiPlatform.featureScript.title'), description: t('aiPlatform.featureScript.description'), color: '#6366f1' },
    { icon: PaletteIcon, title: t('aiPlatform.featureImage.title'), description: t('aiPlatform.featureImage.description'), color: '#ec4899' },
    { icon: MovieCreationIcon, title: t('aiPlatform.featureComic.title'), description: t('aiPlatform.featureComic.description'), color: '#8b5cf6' },
    { icon: AutoFixHighIcon, title: t('aiPlatform.featureOptimize.title'), description: t('aiPlatform.featureOptimize.description'), color: '#14b8a6' },
  ]

  // 创作步骤（组件内构造以支持 i18n）
  const creationSteps = [
    { step: 1, title: t('aiPlatform.step1.title'), description: t('aiPlatform.step1.description') },
    { step: 2, title: t('aiPlatform.step2.title'), description: t('aiPlatform.step2.description') },
    { step: 3, title: t('aiPlatform.step3.title'), description: t('aiPlatform.step3.description') },
    { step: 4, title: t('aiPlatform.step4.title'), description: t('aiPlatform.step4.description') },
    { step: 5, title: t('aiPlatform.step5.title'), description: t('aiPlatform.step5.description') },
  ]

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
              {/* 常暗着陆页：返回按钮钉白叠色，避免浅色模式继承 text.primary 深字压墨底不可见（方案 A）。 */}
              <Button color="inherit" onClick={() => navigate('/home')} sx={{ color: 'rgba(255,255,255,0.85)' }}>
                {t('aiPlatform.backToModules')}
              </Button>
              <Button
                variant="contained"
                startIcon={<RocketLaunchIcon />}
                onClick={handleStartCreation}
              >
                {t('aiPlatform.startCreation')}
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
                    label={t('aiPlatform.heroBadge')}
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
                    {t('aiPlatform.heroTitle1')}
                    <br />
                    {t('aiPlatform.heroTitle2')}
                  </Typography>
                  <Typography
                    variant="h5"
                    sx={{
                      color: 'rgba(255,255,255,0.9)',
                      mb: 4,
                      lineHeight: 1.6,
                    }}
                  >
                    {t('aiPlatform.heroSubtitle')}
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
                      {t('aiPlatform.startNow')}
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
                      {t('aiPlatform.watchDemo')}
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
          {t('aiPlatform.featuresTitle')}
        </Typography>
        <Typography variant="h6" align="center" sx={{ color: 'rgba(255,255,255,0.7)', mb: 6 }}>
          {t('aiPlatform.featuresSubtitle')}
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
            {t('aiPlatform.stepsTitle')}
          </Typography>
          <Typography variant="h6" align="center" sx={{ color: 'rgba(255,255,255,0.7)', mb: 6 }}>
            {t('aiPlatform.stepsSubtitle')}
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
          {t('aiPlatform.worksTitle')}
        </Typography>
        <Typography variant="h6" align="center" sx={{ color: 'rgba(255,255,255,0.7)', mb: 4 }}>
          {t('aiPlatform.worksSubtitle')}
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
          <Tab label={t('aiPlatform.tabAll')} />
          <Tab label={t('aiPlatform.tabScifi')} />
          <Tab label={t('aiPlatform.tabFantasy')} />
          <Tab label={t('aiPlatform.tabHistory')} />
          <Tab label={t('aiPlatform.tabWuxia')} />
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
            {t('aiPlatform.ctaTitle')}
          </Typography>
          <Typography variant="h6" sx={{ color: 'rgba(255,255,255,0.9)', mb: 4 }}>
            {t('aiPlatform.ctaSubtitle')}
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
            {t('aiPlatform.ctaStart')}
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
              <Button sx={{ color: 'rgba(255,255,255,0.7)' }}>{t('aiPlatform.footerTerms')}</Button>
              <Button sx={{ color: 'rgba(255,255,255,0.7)' }}>{t('aiPlatform.footerPrivacy')}</Button>
              <Button sx={{ color: 'rgba(255,255,255,0.7)' }}>{t('aiPlatform.footerContact')}</Button>
            </Box>
          </Box>
        </Container>
      </Box>
    </Box>
  )
}
