/**
 * 账户菜单：顶栏右侧的用户身份入口 + 下拉（用户中心 / 积分中心 / 退出登录）。
 *
 * 从 CreationModulePage 的内联用户菜单抽取而来，供 AppShell 顶栏复用。两处关键改造：
 * 1. 写死的中文与 hex（#667eea/#d32f2f/rgba 白…）换成 i18n 键与 theme token，
 *    这样它进了 AppShell 才能跟着明暗模式反相、跟着语言切换；
 * 2. 组件做成展示组件——user 与回调走 props 注入，不在内部摸 redux/router，
 *    因此能沿用项目既有的 renderToStaticMarkup 测试范式（无需 Provider/MemoryRouter）。
 *
 * 「从 user 派生展示身份」这段真正的逻辑抽成纯函数 resolveUserAccountIdentity，
 * 口径与 LanguageSwitcher 的 buildLanguageOptions 一致：菜单展开内容在静态渲染里
 * 是关着的，逻辑必须能脱离渲染单独验。
 */
import { useState } from 'react'
import {
  Avatar,
  Box,
  Button,
  Chip,
  Divider,
  ListItemIcon,
  ListItemText,
  Menu,
  MenuItem,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import LogoutIcon from '@mui/icons-material/Logout'
import ManageAccountsOutlinedIcon from '@mui/icons-material/ManageAccountsOutlined'
import StarsOutlinedIcon from '@mui/icons-material/StarsOutlined'
import { useTranslation } from 'react-i18next'

import { withAlpha } from '@/theme'

/** 账户菜单需要的最小用户形状；authSlice 的 User 结构化兼容它（ISP，不反向耦合 store）。 */
export interface UserAccountSource {
  readonly username: string
  readonly email: string | null
  readonly full_name?: string | null
  readonly avatar_url?: string | null
  readonly roles?: readonly { readonly code: string }[] | null
}

export interface UserAccountIdentity {
  /** full_name(去空白) → username → null；null 表示交给调用方套 i18n 兜底名。 */
  readonly displayName: string | null
  /** email → username → null；null 同上。 */
  readonly identity: string | null
  readonly avatarSrc: string | null
  readonly isAdmin: boolean
}

/** 管理员判定同时认 admin 与 super_admin，口径与原 CreationModulePage 一致。 */
const ADMIN_ROLE_CODES: readonly string[] = ['admin', 'super_admin']

export function resolveUserAccountIdentity(
  user: UserAccountSource | null,
): UserAccountIdentity {
  if (!user) {
    return { displayName: null, identity: null, avatarSrc: null, isAdmin: false }
  }

  const fullName = user.full_name?.trim() ?? ''
  const username = user.username?.trim() ?? ''
  const displayName = fullName || username || null
  const identity = user.email || username || null
  const isAdmin = user.roles?.some((role) => ADMIN_ROLE_CODES.includes(role.code)) ?? false

  return {
    displayName,
    identity,
    avatarSrc: user.avatar_url || null,
    isAdmin,
  }
}

export interface UserAccountMenuProps {
  /** 当前登录用户；null 时退回 i18n 兜底身份（受保护路由里不该出现，但要能安全渲染）。 */
  readonly user: UserAccountSource | null
  /** 由 AppShell 注入的导航（router navigate）；组件自身不碰 react-router。 */
  readonly onNavigate: (path: string) => void
  /** 由 AppShell 注入的登出（redux performLogout + 跳登录）；组件自身不碰 store。 */
  readonly onLogout: () => void
}

const MENU_ID = 'app-shell-account-menu'
const USER_CENTER_PATH = '/user-center'
const POINTS_CENTER_PATH = '/user-center?tab=points'

/**
 * 顶栏账户菜单。展示组件：身份走 resolveUserAccountIdentity，导航/登出走 props 注入，
 * 因此能用 renderToStaticMarkup 静态渲染（MUI Menu 关闭时不入标记，只渲染触发按钮）。
 *
 * 颜色一律走 theme token（primary 黄铜 / secondary 墨青 / error），随明暗反相；
 * 文案一律走 shell.account.* i18n 键，随语言切换——这正是它相对 CreationModulePage
 * 内联版本的两处硬改造。
 */
export default function UserAccountMenu({ user, onNavigate, onLogout }: UserAccountMenuProps) {
  const { t } = useTranslation()
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)

  const { displayName, identity, avatarSrc, isAdmin } = resolveUserAccountIdentity(user)
  const resolvedName = displayName ?? t('shell.account.fallbackName')
  const resolvedIdentity = identity ?? t('shell.account.fallbackIdentity')
  const avatarFallback = resolvedName.slice(0, 1).toUpperCase()
  const subtitle = isAdmin
    ? t('shell.account.subtitleAdmin')
    : t('shell.account.subtitleUser')

  const open = anchorEl !== null
  const close = () => setAnchorEl(null)
  // 先关菜单再跳转/登出，避免 Menu 悬着盖住新页面。
  const navigateTo = (path: string) => () => {
    close()
    onNavigate(path)
  }
  const handleLogout = () => {
    close()
    onLogout()
  }

  return (
    <>
      <Button
        variant="outlined"
        size="small"
        onClick={(event) => setAnchorEl(event.currentTarget)}
        aria-haspopup="true"
        aria-expanded={open}
        aria-controls={open ? MENU_ID : undefined}
        sx={{
          minHeight: 44,
          px: { xs: 1, sm: 1.25 },
          textTransform: 'none',
          gap: 1,
          borderColor: 'divider',
          color: 'text.primary',
          '&:hover': {
            borderColor: 'primary.main',
            backgroundColor: 'action.hover',
          },
        }}
      >
        <Avatar
          src={avatarSrc ?? undefined}
          sx={{
            width: 28,
            height: 28,
            fontSize: '0.875rem',
            fontWeight: 700,
            bgcolor: 'primary.main',
            color: 'primary.contrastText',
          }}
        >
          {avatarFallback}
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
              color: 'text.primary',
              width: '100%',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {resolvedName}
          </Typography>
          <Typography
            sx={{
              fontSize: '0.72rem',
              lineHeight: 1.15,
              color: 'text.secondary',
              width: '100%',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}
          >
            {subtitle}
          </Typography>
        </Box>
        <ExpandMoreIcon sx={{ fontSize: 18, color: 'text.secondary', opacity: 0.82 }} />
      </Button>

      <Menu
        id={MENU_ID}
        anchorEl={anchorEl}
        open={open}
        onClose={close}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'right' }}
        transformOrigin={{ vertical: 'top', horizontal: 'right' }}
        PaperProps={{
          sx: { mt: 1, minWidth: 300, borderRadius: 3, overflow: 'hidden' },
        }}
      >
        <Box
          sx={(theme) => ({
            display: 'flex',
            alignItems: 'center',
            gap: 1.5,
            px: 2,
            py: 1.75,
            // 黄铜→墨青的极淡渐变，替代原来写死的紫色带；两种模式下都由 token 反相。
            background: `linear-gradient(135deg, ${withAlpha(theme.palette.primary.main, 0.1)} 0%, ${withAlpha(theme.palette.secondary.main, 0.06)} 100%)`,
          })}
        >
          <Avatar
            src={avatarSrc ?? undefined}
            sx={{
              width: 44,
              height: 44,
              fontWeight: 700,
              bgcolor: 'primary.main',
              color: 'primary.contrastText',
            }}
          >
            {avatarFallback}
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
              {resolvedName}
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
              {resolvedIdentity}
            </Typography>
            <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 0.9 }}>
              <Chip
                size="small"
                label={
                  isAdmin
                    ? t('shell.account.badgeAdmin')
                    : t('shell.account.badgeCreator')
                }
                sx={{
                  height: 22,
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  backgroundColor: 'secondary.light',
                  color: 'secondary.main',
                }}
              />
              <Chip
                size="small"
                label={t('shell.account.badgePoints')}
                sx={{
                  height: 22,
                  fontSize: '0.7rem',
                  fontWeight: 600,
                  backgroundColor: 'primary.light',
                  color: 'primary.main',
                }}
              />
            </Box>
          </Box>
        </Box>

        <Divider />

        <MenuItem onClick={navigateTo(USER_CENTER_PATH)}>
          <ListItemIcon>
            <ManageAccountsOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary={t('shell.account.userCenter')}
            secondary={t('shell.account.userCenterHint')}
          />
        </MenuItem>

        <MenuItem onClick={navigateTo(POINTS_CENTER_PATH)}>
          <ListItemIcon>
            <StarsOutlinedIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary={t('shell.account.pointsCenter')}
            secondary={t('shell.account.pointsCenterHint')}
          />
        </MenuItem>

        <Divider />

        <MenuItem onClick={handleLogout} sx={{ color: 'error.main' }}>
          <ListItemIcon sx={{ color: 'inherit' }}>
            <LogoutIcon fontSize="small" />
          </ListItemIcon>
          <ListItemText
            primary={t('shell.account.logout')}
            secondary={t('shell.account.logoutHint')}
          />
        </MenuItem>
      </Menu>
    </>
  )
}
