import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Container,
  Grid,
  IconButton,
  Snackbar,
  Tooltip,
  Typography,
  alpha,
} from '@mui/material'
import PermMediaOutlinedIcon from '@mui/icons-material/PermMediaOutlined'
import AutoStoriesIcon from '@mui/icons-material/AutoStories'
import HeadphonesIcon from '@mui/icons-material/Headphones'
import MovieIcon from '@mui/icons-material/Movie'
import AutoFixHighIcon from '@mui/icons-material/AutoFixHigh'
import HubIcon from '@mui/icons-material/Hub'
import { useSelector } from 'react-redux'
import { RootState } from '@/store/store'
import BookParserUploadDialog from '@/components/BookParserUploadDialog'
import type { BookSource } from '@/services/bookParserApi'

const headerActionButtonSx = {
  color: 'text.primary',
  borderColor: 'divider',
  minHeight: { xs: 44, sm: 36 },
  fontSize: { xs: '0.875rem', sm: '0.875rem' },
  '&:hover': {
    borderColor: 'primary.main',
    backgroundColor: 'action.hover',
  },
}

const BrokenBookIcon = () => (
  <svg
    width="24"
    height="24"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <path d="M2.75 4.5h5.75c2.2 0 3.5 1.05 3.5 3v14.25c-.65-.55-1.6-.9-2.75-.9H2.75V4.5z" />
    <path d="M21.25 4.5h-5.75c-2.2 0-3.5 1.05-3.5 3v14.25c.65-.55 1.6-.9 2.75-.9h6.5V4.5z" />
    <path d="M12 7.75l-1 1.4 1 1.4-1 1.4 1 1.4-1 1.4 1 1.4-1 1.4 1 1.4" />
    <path d="M15.2 9.4h3.3" />
    <path d="M15.2 12h3.3" />
    <path d="M15.2 14.6h3.3" />
  </svg>
)

type CreationModule = {
  id: string
  title: string
  subtitle: string
  description: string
  icon: typeof AutoStoriesIcon
  color: string
  available: boolean
  path: string
  adminOnly?: boolean
  badge?: string
}

export default function CreationModulePage() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const { user } = useSelector((state: RootState) => state.auth)
  const [bookUploadDialogOpen, setBookUploadDialogOpen] = useState(false)
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string }>({ open: false, message: '' })

  // 模块卡片（组件内构造以支持 i18n）
  const modules: CreationModule[] = [
    {
      id: 'novel',
      title: t('creationModule.novel.title'),
      subtitle: t('creationModule.novel.subtitle'),
      description: t('creationModule.novel.description'),
      icon: AutoStoriesIcon,
      color: '#1976d2', // sg-color-fixed: 灵感方舟模块签名色（模块身份色，数据非主题 chrome）
      available: true,
      path: '/dashboard',
    },
    {
      id: 'audiobook',
      title: t('creationModule.audiobook.title'),
      subtitle: t('creationModule.audiobook.subtitle'),
      description: t('creationModule.audiobook.description'),
      icon: HeadphonesIcon,
      color: '#9c27b0', // sg-color-fixed: 耳畔星河模块签名色
      available: true,
      path: '/audiobook-dashboard',
    },
    {
      id: 'drama',
      title: t('creationModule.drama.title'),
      subtitle: t('creationModule.drama.subtitle'),
      description: t('creationModule.drama.description'),
      icon: MovieIcon,
      color: '#f57c00', // sg-color-fixed: 织梦映心模块签名色
      available: true,
      adminOnly: true,
      path: '/drama',
      badge: t('creationModule.drama.badge'),
    },
    {
      id: 'ai-detect',
      title: t('creationModule.aiTrace.title'),
      subtitle: t('creationModule.aiTrace.subtitle'),
      description: t('creationModule.aiTrace.description'),
      icon: AutoFixHighIcon,
      color: '#2e7d32', // sg-color-fixed: 织文无迹模块签名色
      available: true,
      path: '/ai-trace',
    },
  ]

  // 仅保留模块卡片的 adminOnly 门控（如「织梦映心」）所需；用户身份/账户菜单已上移到
  // AppShell 的 UserAccountMenu，此处不再重复。
  const hasAdminRole = user?.roles?.some((role) => role.code === 'admin' || role.code === 'super_admin') ?? false

  const handleModuleClick = (module: CreationModule) => {
    const isAdminOnly = module.adminOnly && !hasAdminRole
    const isAvailable = module.available && !isAdminOnly

    if (isAvailable) {
      navigate(module.path)
    }
  }

  const handleBookUploadSuccess = (book: BookSource) => {
    setSnackbar({
      open: true,
      message: t('creationModule.bookUploaded', { title: book.title }),
    })
  }

  return (
    <Box
      sx={(theme) => ({
        // 原写死紫色渐变（不随暗色反相）→「墨与光」token：画布底 + 黄铜/墨青极淡渐变，
        // 双模式都由 token 反相；flex:1 填满 AppShell 的 <main>，不再自撑 100dvh 造成双滚动。
        flex: 1,
        backgroundColor: theme.palette.background.default,
        backgroundImage: `linear-gradient(160deg, ${alpha(theme.palette.primary.main, 0.1)} 0%, ${alpha(theme.palette.secondary.main, 0.07)} 100%)`,
        py: { xs: 2, sm: 3, md: 4 },
        px: { xs: 1, sm: 2 },
        display: 'flex',
        flexDirection: 'column',
      })}
    >
      <Container
        maxWidth="lg"
        sx={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          px: { xs: 0, sm: 2 },
        }}
      >
        <Box
          sx={{
            display: 'flex',
            flexDirection: { xs: 'column', sm: 'row' },
            justifyContent: 'space-between',
            alignItems: { xs: 'flex-start', sm: 'center' },
            mb: { xs: 2, sm: 3 },
            gap: { xs: 1.5, sm: 0 },
          }}
        >
          <Box>
            <Typography
              variant="h4"
              sx={{
                color: 'text.primary',
                fontWeight: 700,
                mb: 0.5,
                fontSize: { xs: '1.5rem', sm: '1.75rem', md: '2rem' },
              }}
            >
              {t('creationModule.title')}
            </Typography>
            <Typography
              variant="body1"
              sx={{
                color: 'text.secondary',
                fontSize: { xs: '0.875rem', sm: '1rem' },
              }}
            >
              {t('creationModule.subtitle')}
            </Typography>
          </Box>

          <Box
            sx={{
              display: 'flex',
              gap: { xs: 1, sm: 1.5 },
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            <Button
              variant="outlined"
              size="small"
              startIcon={<PermMediaOutlinedIcon />}
              onClick={() => navigate('/asset-studio')}
              sx={headerActionButtonSx}
            >
              {t('creationModule.assetStudio')}
            </Button>

            <Button
              variant="outlined"
              size="small"
              startIcon={<HubIcon />}
              onClick={() => navigate('/model-catalog')}
              sx={headerActionButtonSx}
            >
              {t('creationModule.modelCatalog')}
            </Button>
          </Box>
        </Box>

        <Grid container spacing={{ xs: 1.5, sm: 2, md: 2.5 }} sx={{ flex: 1 }}>
          {modules.map((module) => {
            const IconComponent = module.icon
            const isNovel = module.id === 'novel'
            const isAdminOnly = module.adminOnly && !hasAdminRole
            const isAvailable = module.available && !isAdminOnly

            return (
              <Grid item xs={12} sm={6} md={6} key={module.id}>
                <Card
                  sx={{
                    height: '100%',
                    minHeight: { xs: 140, sm: 180, md: 200 },
                    borderRadius: { xs: 2, sm: 3 },
                    transition: 'all 0.3s ease',
                    opacity: isAvailable ? 1 : 0.6,
                    position: 'relative',
                    boxShadow: 4,
                    '&:hover': {
                      transform: isAvailable ? 'translateY(-3px)' : 'none',
                      boxShadow: isAvailable ? 8 : 4,
                    },
                  }}
                >
                  {isNovel && (
                    <Tooltip title={t('creationModule.bookParserTooltip')} placement="top" arrow>
                      <IconButton
                        onClick={(event) => {
                          event.stopPropagation()
                          setBookUploadDialogOpen(true)
                        }}
                        sx={(theme) => ({
                          position: 'absolute',
                          top: { xs: 6, sm: 8 },
                          right: { xs: 6, sm: 8 },
                          zIndex: 10,
                          width: { xs: 36, sm: 40 },
                          height: { xs: 36, sm: 40 },
                          // 拆书工具按钮走 info token：柔色底 + info 前景，hover 加深，随主题反相（原 teal 在暗底几乎不可见）。
                          backgroundColor: alpha(theme.palette.info.main, 0.1),
                          color: theme.palette.info.main,
                          transition: 'all 0.3s ease',
                          '&:hover': {
                            backgroundColor: alpha(theme.palette.info.main, 0.2),
                            transform: 'scale(1.1) rotate(-5deg)',
                          },
                        })}
                      >
                        <BrokenBookIcon />
                      </IconButton>
                    </Tooltip>
                  )}

                  <CardActionArea onClick={() => handleModuleClick(module)} disabled={!isAvailable} sx={{ height: '100%' }}>
                    <CardContent
                      sx={{
                        display: 'flex',
                        flexDirection: 'column',
                        alignItems: 'center',
                        gap: { xs: 1, sm: 1.25, md: 1.5 },
                        p: { xs: 2, sm: 2.5, md: 3 },
                        textAlign: 'center',
                        height: '100%',
                        justifyContent: 'center',
                      }}
                    >
                      <Box
                        sx={{
                          width: { xs: 56, sm: 64, md: 68 },
                          height: { xs: 56, sm: 64, md: 68 },
                          borderRadius: '50%',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          backgroundColor: alpha(module.color, 0.1),
                          flexShrink: 0,
                        }}
                      >
                        <IconComponent sx={{ fontSize: { xs: 28, sm: 32, md: 36 }, color: module.color }} />
                      </Box>

                      <Box sx={{ width: '100%' }}>
                        <Typography
                          variant="h6"
                          sx={{
                            fontWeight: 700,
                            mb: 0.2,
                            color: module.color,
                            fontSize: { xs: '1.05rem', sm: '1.15rem', md: '1.2rem' },
                            lineHeight: 1.3,
                          }}
                        >
                          {module.title}
                        </Typography>

                        <Typography
                          variant="caption"
                          sx={{
                            color: 'text.secondary',
                            display: 'block',
                            mb: 0.6,
                            fontSize: { xs: '0.78rem', sm: '0.82rem' },
                          }}
                        >
                          {module.subtitle}
                        </Typography>

                        <Box sx={{ display: 'flex', gap: 0.6, flexWrap: 'wrap', mb: 0.8, justifyContent: 'center' }}>
                          {module.badge ? (
                            <Chip
                              label={module.badge}
                              size="small"
                              sx={{
                                backgroundColor: alpha(module.color, 0.1),
                                color: module.color,
                                fontSize: { xs: '0.68rem', sm: '0.72rem' },
                                height: { xs: 22, sm: 24 },
                              }}
                            />
                          ) : null}

                          {!isAvailable && module.adminOnly ? (
                            <Chip
                              label={t('creationModule.adminOnly')}
                              size="small"
                              sx={{
                                backgroundColor: 'action.disabledBackground',
                                color: 'text.disabled',
                                fontSize: { xs: '0.68rem', sm: '0.72rem' },
                                height: { xs: 22, sm: 24 },
                              }}
                            />
                          ) : null}

                          {!isAvailable && !module.adminOnly ? (
                            <Chip
                              label={t('creationModule.comingSoon')}
                              size="small"
                              sx={{
                                backgroundColor: 'action.disabledBackground',
                                fontSize: { xs: '0.68rem', sm: '0.72rem' },
                                height: { xs: 22, sm: 24 },
                              }}
                            />
                          ) : null}
                        </Box>

                        <Typography
                          variant="body2"
                          color="text.secondary"
                          sx={{
                            fontSize: { xs: '0.8rem', sm: '0.85rem', md: '0.875rem' },
                            lineHeight: 1.55,
                            display: '-webkit-box',
                            overflow: 'hidden',
                            WebkitLineClamp: { xs: 2, sm: 2 },
                            WebkitBoxOrient: 'vertical',
                          }}
                        >
                          {module.description}
                        </Typography>
                      </Box>
                    </CardContent>
                  </CardActionArea>
                </Card>
              </Grid>
            )
          })}
        </Grid>
      </Container>

      {/* 书籍上传对话框 */}
      <BookParserUploadDialog
        open={bookUploadDialogOpen}
        onClose={() => setBookUploadDialogOpen(false)}
        onUploadSuccess={handleBookUploadSuccess}
      />

      {/* 提示消息 */}
      <Snackbar
        open={snackbar.open}
        autoHideDuration={3000}
        onClose={() => setSnackbar({ ...snackbar, open: false })}
        message={snackbar.message}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      />
    </Box>
  )
}
