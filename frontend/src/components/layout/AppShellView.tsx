/**
 * AppShell 的展示层：顶栏（拾光字标 + 控件簇 + 账户菜单）+ <main> 路由出口。
 *
 * 只吃 props（user / onNavigate / onLogout / children），既不碰 redux、router，也
 * 刻意不 import 任何带浏览器副作用的模块——正因如此它能被 renderToStaticMarkup
 * 静态测。连接层 AppShell 会 import authSlice，而 authSlice 在模块加载时就读
 * localStorage，在 node 测试环境里会直接抛错，所以展示层必须与它物理隔离。
 */
import type { ReactNode } from 'react'
import { AppBar, Box, ButtonBase, Toolbar } from '@mui/material'
import { useTranslation } from 'react-i18next'

import BrandWordmark from '@/components/common/BrandWordmark'
import ControlCluster from '@/components/common/ControlCluster'
import UserAccountMenu, { type UserAccountSource } from '@/components/common/UserAccountMenu'

export interface AppShellViewProps {
  /** 当前登录用户；连接层从 redux 灌入，展示层不碰 store。 */
  readonly user: UserAccountSource | null
  /** 路由跳转（字标回首页、账户菜单导航都走它）；展示层不碰 react-router。 */
  readonly onNavigate: (path: string) => void
  /** 登出（连接层做 performLogout + 跳登录）；展示层不碰 store。 */
  readonly onLogout: () => void
  /** 路由出口内容；连接层传 <Outlet/>，测试传哨兵节点。 */
  readonly children?: ReactNode
}

export default function AppShellView({ user, onNavigate, onLogout, children }: AppShellViewProps) {
  const { t } = useTranslation()

  return (
    <Box
      sx={{
        minHeight: '100dvh',
        display: 'flex',
        flexDirection: 'column',
        bgcolor: 'background.default',
      }}
    >
      <AppBar
        position="sticky"
        elevation={0}
        color="default"
        sx={(theme) => ({
          // 显式钉死表面/文字 token，不吃 MUI 各版本对 color="default" 的映射差异。
          bgcolor: theme.palette.background.paper,
          color: theme.palette.text.primary,
          borderBottom: `1px solid ${theme.palette.divider}`,
        })}
      >
        <Toolbar sx={{ gap: { xs: 0.5, sm: 1 } }}>
          <ButtonBase
            onClick={() => onNavigate('/home')}
            aria-label={t('shell.brandHomeAria')}
            sx={{ borderRadius: 2, px: 0.5, py: 0.25 }}
          >
            <BrandWordmark size="md" />
          </ButtonBase>

          <Box sx={{ flexGrow: 1 }} />

          <ControlCluster />

          <UserAccountMenu user={user} onNavigate={onNavigate} onLogout={onLogout} />
        </Toolbar>
      </AppBar>

      <Box
        component="main"
        sx={{ flexGrow: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}
      >
        {children}
      </Box>
    </Box>
  )
}
