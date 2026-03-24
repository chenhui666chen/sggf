import { useState, type MouseEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import {
  Avatar,
  Box,
  Button,
  Card,
  CardActionArea,
  CardContent,
  Chip,
  Container,
  Divider,
  Grid,
  IconButton,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
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
import LogoutIcon from '@mui/icons-material/Logout'
import ManageAccountsOutlinedIcon from '@mui/icons-material/ManageAccountsOutlined'
import StarsOutlinedIcon from '@mui/icons-material/StarsOutlined'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import HubIcon from '@mui/icons-material/Hub'
import { useDispatch, useSelector } from 'react-redux'
import { logout } from '@/store/slices/authSlice'
import { AppDispatch, RootState } from '@/store/store'
import BookParserUploadDialog from '@/components/BookParserUploadDialog'
import type { BookSource } from '@/services/bookParserApi'

const headerActionButtonSx = {
  color: 'white',
  borderColor: 'rgba(255,255,255,0.5)',
  minHeight: { xs: 44, sm: 36 },
  fontSize: { xs: '0.875rem', sm: '0.875rem' },
  '&:hover': {
    borderColor: 'white',
    backgroundColor: 'rgba(255,255,255,0.1)',
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

const modules: CreationModule[] = [
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
    available: true,
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
    adminOnly: true,
    path: '/drama',
    badge: '内测',
  },
  {
    id: 'ai-detect',
    title: '织文无迹',
    subtitle: 'AI 痕迹降低',
    description: '检测与降低 AI 痕迹，让创作更自然流畅',
    icon: AutoFixHighIcon,
    color: '#2e7d32',
    available: true,
    path: '/ai-trace',
  },
]

export default function CreationModulePage() {
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const { user } = useSelector((state: RootState) => state.auth)
  const [userMenuAnchorEl, setUserMenuAnchorEl] = useState<null | HTMLElement>(null)
  const [bookUploadDialogOpen, setBookUploadDialogOpen] = useState(false)
  const [snackbar, setSnackbar] = useState<{ open: boolean; message: string }>({ open: false, message: '' })

  const hasAdminRole = user?.roles?.some((role) => role.code === 'admin' || role.code === 'super_admin') ?? false
  const userDisplayName = user?.full_name?.trim() || user?.username || '创作者'
  const userIdentity = user?.email || user?.username || '欢迎回来'
  const userAvatarFallback = userDisplayName.slice(0, 1).toUpperCase()
  const userCenterSubtitle = hasAdminRole ? '管理员 · 用户中心' : '用户中心'
  const userMenuId = 'creation-module-user-center-menu'
  const userMenuOpen = Boolean(userMenuAnchorEl)

  const handleModuleClick = (module: CreationModule) => {
    const isAdminOnly = module.adminOnly && !hasAdminRole
    const isAvailable = module.available && !isAdminOnly

    if (isAvailable) {
      navigate(module.path)
    }
  }

  const handleOpenUserMenu = (event: MouseEvent<HTMLElement>) => {
    setUserMenuAnchorEl(event.currentTarget)
  }

  const handleCloseUserMenu = () => {
    setUserMenuAnchorEl(null)
  }

  const handleOpenSettings = () => {
    handleCloseUserMenu()
    navigate('/user-center')
  }

  const handleLogout = () => {
    handleCloseUserMenu()
    dispatch(logout())
    navigate('/login')
  }

  const handleBookUploadSuccess = (book: BookSource) => {
    setSnackbar({
      open: true,
      message: `书籍《${book.title}》已上传、完成拆书分析并自动导入灵感方舟，请在灵感方舟中查看`,
    })
  }

  return (
    <Box
      sx={{
        minHeight: '100dvh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        py: { xs: 2, sm: 3, md: 4 },
        px: { xs: 1, sm: 2 },
        display: 'flex',
        flexDirection: 'column',
      }}
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
                color: 'white',
                fontWeight: 700,
                mb: 0.5,
                fontSize: { xs: '1.5rem', sm: '1.75rem', md: '2rem' },
              }}
            >
              创作工坊
            </Typography>
            <Typography
              variant="body1"
              sx={{
                color: 'rgba(255,255,255,0.8)',
                fontSize: { xs: '0.875rem', sm: '1rem' },
              }}
            >
              选择你的创作模式，开启智能创作之旅
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
              资产生成
            </Button>

            <Button
              variant="outlined"
              size="small"
              startIcon={<HubIcon />}
              onClick={() => navigate('/model-catalog')}
              sx={headerActionButtonSx}
            >
              模型中心
            </Button>

            <Button
              variant="outlined"
              size="small"
              onClick={handleOpenUserMenu}
              aria-controls={userMenuOpen ? userMenuId : undefined}
              aria-haspopup="true"
              aria-expanded={userMenuOpen ? 'true' : undefined}
              sx={{
                ...headerActionButtonSx,
                minHeight: { xs: 44, sm: 44 },
                px: { xs: 1, sm: 1.2 },
                textTransform: 'none',
                gap: 1,
              }}
            >
              <Avatar
                src={user?.avatar_url || undefined}
                sx={{
                  width: 28,
                  height: 28,
                  fontSize: '0.875rem',
                  fontWeight: 700,
                  bgcolor: 'rgba(255,255,255,0.2)',
                }}
              >
                {userAvatarFallback}
              </Avatar>
              <Box
                sx={{
                  display: 'flex',
                  flexDirection: 'column',
                  alignItems: 'flex-start',
                  minWidth: 0,
                  maxWidth: { xs: 120, sm: 156 },
                }}
              >
                <Typography
                  sx={{
                    fontSize: '0.875rem',
                    fontWeight: 700,
                    lineHeight: 1.15,
                    color: 'inherit',
                    width: '100%',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {userDisplayName}
                </Typography>
                <Typography
                  sx={{
                    fontSize: '0.72rem',
                    lineHeight: 1.15,
                    color: 'rgba(255,255,255,0.78)',
                    width: '100%',
                    whiteSpace: 'nowrap',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                  }}
                >
                  {userCenterSubtitle}
                </Typography>
              </Box>
              <ExpandMoreIcon sx={{ fontSize: 18, opacity: 0.82 }} />
            </Button>
          </Box>
        </Box>

        <Menu
          id={userMenuId}
          anchorEl={userMenuAnchorEl}
          open={userMenuOpen}
          onClose={handleCloseUserMenu}
          anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
          transformOrigin={{ vertical: 'top', horizontal: 'right' }}
          PaperProps={{
            sx: {
              mt: 1,
              minWidth: 300,
              borderRadius: 3,
              overflow: 'hidden',
              boxShadow: '0 18px 40px rgba(16, 24, 40, 0.18)',
            },
          }}
        >
          <Box
            sx={{
              display: 'flex',
              alignItems: 'center',
              gap: 1.5,
              px: 2,
              py: 1.75,
              background: 'linear-gradient(135deg, rgba(102, 126, 234, 0.12) 0%, rgba(118, 75, 162, 0.12) 100%)',
            }}
          >
            <Avatar
              src={user?.avatar_url || undefined}
              sx={{
                width: 44,
                height: 44,
                fontWeight: 700,
                bgcolor: '#667eea',
              }}
            >
              {userAvatarFallback}
            </Avatar>
            <Box sx={{ minWidth: 0, flex: 1 }}>
              <Typography
                sx={{
                  fontSize: '0.95rem',
                  fontWeight: 700,
                  color: 'text.primary',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {userDisplayName}
              </Typography>
              <Typography
                sx={{
                  mt: 0.2,
                  fontSize: '0.78rem',
                  color: 'text.secondary',
                  whiteSpace: 'nowrap',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                }}
              >
                {userIdentity}
              </Typography>
              <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 0.9 }}>
                <Chip
                  size="small"
                  label={hasAdminRole ? '管理员账户' : '创作者账户'}
                  sx={{
                    height: 22,
                    fontSize: '0.7rem',
                    backgroundColor: 'rgba(102, 126, 234, 0.12)',
                    color: '#5b64d6',
                  }}
                />
                <Chip
                  size="small"
                  label="积分系统规划中"
                  sx={{
                    height: 22,
                    fontSize: '0.7rem',
                    backgroundColor: 'rgba(255, 193, 7, 0.14)',
                    color: '#8a6700',
                  }}
                />
              </Box>
            </Box>
          </Box>

          <Divider />

          <MenuItem onClick={handleOpenSettings}>
            <ListItemIcon>
              <ManageAccountsOutlinedIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="用户中心" secondary="查看创作概览、资产规划、账户与安全设置" />
          </MenuItem>

          <MenuItem disabled>
            <ListItemIcon>
              <StarsOutlinedIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="积分中心" secondary="后续接入积分、权益与消耗明细" />
          </MenuItem>

          <Divider />

          <MenuItem onClick={handleLogout} sx={{ color: '#d32f2f' }}>
            <ListItemIcon sx={{ color: 'inherit' }}>
              <LogoutIcon fontSize="small" />
            </ListItemIcon>
            <ListItemText primary="退出登录" secondary="从当前设备安全退出账户" />
          </MenuItem>
        </Menu>

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
                    boxShadow: '0 12px 28px rgba(19, 22, 52, 0.12)',
                    '&:hover': {
                      transform: isAvailable ? 'translateY(-3px)' : 'none',
                      boxShadow: isAvailable ? '0 18px 34px rgba(17, 24, 39, 0.18)' : '0 12px 28px rgba(19, 22, 52, 0.12)',
                    },
                  }}
                >
                  {isNovel && (
                    <Tooltip title="拆书工具 - 智能分析书籍结构" placement="top" arrow>
                      <IconButton
                        onClick={(event) => {
                          event.stopPropagation()
                          setBookUploadDialogOpen(true)
                        }}
                        sx={{
                          position: 'absolute',
                          top: { xs: 6, sm: 8 },
                          right: { xs: 6, sm: 8 },
                          zIndex: 10,
                          width: { xs: 36, sm: 40 },
                          height: { xs: 36, sm: 40 },
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
                              label="管理员专属"
                              size="small"
                              sx={{
                                backgroundColor: '#f5f5f5',
                                color: '#757575',
                                fontSize: { xs: '0.68rem', sm: '0.72rem' },
                                height: { xs: 22, sm: 24 },
                              }}
                            />
                          ) : null}

                          {!isAvailable && !module.adminOnly ? (
                            <Chip
                              label="敬请期待"
                              size="small"
                              sx={{
                                backgroundColor: '#f5f5f5',
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
