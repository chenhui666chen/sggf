/**
 * 认证页共享外壳的展示层：整屏 token wash + 右上角控件簇 + 居中卡片
 * （拾光字标 + 标题/副标题 + children 表单体）。
 *
 * 与 AppShellView 同理——纯展示、零 router/redux，可被 renderToStaticMarkup 静态测。
 * 登录/注册/找回三页共用它，把重复 chrome 收敛到一处（DRY），明暗双模式统一由 token
 * 反相：不再有旧紫渐变 + 白磨砂卡在暗色下破相的问题。
 *
 * title 省略时（登录页）以拾光字标本身作 h1；给了 title（注册/找回）则字标降为品牌锚点、
 * title 作 h1——两条路径都保证每屏有且仅有一个 h1 主标题地标。
 *
 * 刻意不加 overflow:hidden：注册页表单在移动端可能高于视口，minHeight:100dvh 让盒子随
 * 内容增高、body 自然滚动，避免"居中 + 定高 + 裁切"导致顶部够不着。入场动效属 P4 打磨。
 */
import type { ReactNode } from 'react'
import { Box, Container, Paper, Typography, alpha } from '@mui/material'

import BrandWordmark from '@/components/common/BrandWordmark'
import ControlCluster from '@/components/common/ControlCluster'

export interface AuthScreenProps {
  /** 页面主标题（h1）。省略时以拾光字标作为 h1（登录页）。 */
  readonly title?: ReactNode
  /** 标题下的一行说明。 */
  readonly subtitle?: ReactNode
  /** 卡片主体（表单）。 */
  readonly children: ReactNode
  /** 卡片最大宽度：登录/找回 sm，注册 md。 */
  readonly maxWidth?: 'sm' | 'md'
}

export default function AuthScreen({ title, subtitle, children, maxWidth = 'sm' }: AuthScreenProps) {
  return (
    <Box
      sx={(theme) => ({
        minHeight: '100dvh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        position: 'relative',
        padding: { xs: 2, sm: 3, md: 4 },
        // 与 /home hero 同一套 token wash：画布底 + 黄铜/墨青极淡渐变，双模式由 token 反相。
        backgroundColor: theme.palette.background.default,
        backgroundImage: `linear-gradient(160deg, ${alpha(theme.palette.primary.main, 0.1)} 0%, ${alpha(theme.palette.secondary.main, 0.07)} 100%)`,
        // 控件簇两个原语都 color="inherit"，这里给 token 前景色让它明暗都站得住。
        color: theme.palette.text.primary,
      })}
    >
      {/* 控件簇挂右上角：认证页是整屏居中卡片，卡内没有它的位置，而语言/外观切换必须首屏可达。 */}
      <Box sx={{ position: 'absolute', top: { xs: 2, sm: 3 }, right: { xs: 2, sm: 3 }, zIndex: 2 }}>
        <ControlCluster />
      </Box>

      <Container maxWidth={maxWidth} sx={{ position: 'relative', zIndex: 1, width: '100%' }}>
        <Paper
          elevation={12}
          sx={{
            p: { xs: 3, sm: 4, md: 5 },
            borderRadius: { xs: 3, sm: 4 },
            bgcolor: 'background.paper',
            mx: { xs: 1, sm: 0 },
          }}
        >
          <Box sx={{ textAlign: 'center', mb: { xs: 3, sm: 4 } }}>
            {title ? (
              <>
                <Box sx={{ display: 'flex', justifyContent: 'center', mb: { xs: 1.5, sm: 2 } }}>
                  <BrandWordmark size="md" />
                </Box>
                <Typography
                  component="h1"
                  variant="h4"
                  fontWeight={700}
                  sx={{
                    color: 'text.primary',
                    mb: 1,
                    fontSize: { xs: '1.5rem', sm: '1.75rem', md: '2rem' },
                  }}
                >
                  {title}
                </Typography>
              </>
            ) : (
              <Box
                component="h1"
                sx={{ display: 'flex', justifyContent: 'center', mb: { xs: 1.5, sm: 2 } }}
              >
                <BrandWordmark size="lg" />
              </Box>
            )}
            {subtitle ? (
              <Typography variant="body2" color="text.secondary">
                {subtitle}
              </Typography>
            ) : null}
          </Box>

          {children}
        </Paper>
      </Container>
    </Box>
  )
}
