/**
 * 拾光字标：一枚「透镜收光」的标记 + 品牌名。
 *
 * 设计扣住「墨与光」：外圈透镜走墨色（text.primary），收束出的那点光走黄铜主色
 * （primary.main），两者都取自当前主题，因此明暗模式下自动反相——暗色下是亮黄铜
 * 的一点光落在暖白透镜里，浅色下是暗铜落在墨黑透镜里，绝不会出现死沉的一块。
 *
 * 刻意保持为纯展示组件：不碰 router、不碰 redux。要不要包成回首页的链接，由外层
 * （AppShell / 认证页）决定，这样它才能被 renderToStaticMarkup 直接测。
 *
 * SVG 的 fill/stroke 走**直接属性**而不是 emotion 的 sx：一来颜色是标记语义的一部分，
 * 二来 sx 生成的样式不会进静态标记，测试也就断言不到色值。
 */
import { Box, Typography, useTheme } from '@mui/material'
import { useTranslation } from 'react-i18next'

import { fontFamilies } from '@/theme'

export type BrandWordmarkSize = 'sm' | 'md' | 'lg'

export interface BrandWordmarkProps {
  /** 顶栏用 md，认证页主视觉用 lg，紧凑处用 sm。 */
  readonly size?: BrandWordmarkSize
}

interface SizeSpec {
  /** SVG 边长（px）。 */
  readonly glyph: number
  /** 品牌名字号（px）。 */
  readonly fontSize: number
  /** 字距：中文方块字与英文品牌标签都需要一点 tracking 才显精致。 */
  readonly letterSpacing: string
}

const SIZE_SPECS: Record<BrandWordmarkSize, SizeSpec> = {
  sm: { glyph: 18, fontSize: 15, letterSpacing: '0.02em' },
  md: { glyph: 24, fontSize: 19, letterSpacing: '0.04em' },
  lg: { glyph: 44, fontSize: 32, letterSpacing: '0.08em' },
}

export default function BrandWordmark({ size = 'md' }: BrandWordmarkProps) {
  const theme = useTheme()
  const { t } = useTranslation()
  const spec = SIZE_SPECS[size]

  const ink = theme.palette.text.primary
  const light = theme.palette.primary.main

  return (
    <Box
      component="span"
      sx={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: `${Math.round(spec.glyph * 0.34)}px`,
        lineHeight: 1,
      }}
    >
      <svg
        viewBox="0 0 24 24"
        width={spec.glyph}
        height={spec.glyph}
        aria-hidden="true"
        focusable="false"
      >
        {/* 透镜：两道对称弧线收束成一只拾光的眼 */}
        <path
          d="M2.6 12C6.1 6.9 17.9 6.9 21.4 12C17.9 17.1 6.1 17.1 2.6 12Z"
          fill="none"
          stroke={ink}
          strokeWidth={1.5}
          strokeLinejoin="round"
        />
        {/* 收束成的那点光 */}
        <circle cx="12" cy="12" r="3.2" fill={light} />
      </svg>
      <Typography
        component="span"
        sx={{
          fontFamily: fontFamilies.display,
          fontSize: spec.fontSize,
          fontWeight: 600,
          letterSpacing: spec.letterSpacing,
          color: 'text.primary',
          whiteSpace: 'nowrap',
        }}
      >
        {t('app.name')}
      </Typography>
    </Box>
  )
}
