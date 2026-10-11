/**
 * 字体栈与字阶。
 *
 * 排版的两条硬约束：
 * 1. 拉丁字体自托管（@fontsource，不走 CDN，适配中国大陆网络），CJK 一律走
 *    系统本地字体栈。加载思源/Noto 的 CJK webfont 会给 dist 增加数 MB 到数十 MB，
 *    而各平台的本地中文字体（苹方、雅黑、思源）质量已足够高。
 * 2. textTransform 全部 none。uppercase 对中文是空操作，对英文品牌标签是错误，
 *    MUI 的默认值在双语产品里没有任何一档是想要的。
 */

import type { TypographyOptions } from '@mui/material/styles/createTypography'

export interface FontFamilies {
  /** 衬线：品牌标题 */
  display: string
  /** 人文无衬线：正文与界面 */
  sans: string
  /** 等宽：代码、ID、数字对齐 */
  mono: string
}

export const fontFamilies: FontFamilies = {
  display:
    "'Fraunces Variable', 'Songti SC', 'Source Han Serif SC', 'Noto Serif CJK SC', 'STSong', 'SimSun', serif",
  sans:
    "'Schibsted Grotesk Variable', 'PingFang SC', 'HarmonyOS Sans SC', 'Microsoft YaHei', 'Source Han Sans SC', 'Noto Sans CJK SC', 'Hiragino Sans GB', sans-serif",
  mono:
    "'IBM Plex Mono', 'SFMono-Regular', 'JetBrains Mono', 'Cascadia Mono', Consolas, 'Courier New', monospace",
}

export interface TypeScaleTokens {
  /** 根字号；MUI 默认 14px，对中文正文偏小。 */
  rootFontSize: number
  /** 中文方块字在 1.7 以下会显得拥挤。 */
  bodyLineHeight: number
  bodySmallLineHeight: number
  /** 标题行高比正文紧，避免多行标题松散。 */
  headingLineHeight: number
  /** 紧凑标题（h4-h6、副标题）行高。 */
  subheadingLineHeight: number
}

export const typeScaleTokens: TypeScaleTokens = {
  rootFontSize: 15,
  bodyLineHeight: 1.75,
  bodySmallLineHeight: 1.65,
  headingLineHeight: 1.28,
  subheadingLineHeight: 1.45,
}

/**
 * 生成 MUI 的 typography 配置。
 *
 * 字号以 px 数值给出，由 MUI 统一换算成 rem，从而保留用户浏览器字号缩放的偏好。
 * 衬线只用于 h1-h3：中文衬线在 h4 以下的小字号里笔画发糊，衬线只在大标题上
 * 承担品牌感，其余一律人文无衬线。
 */
export function createTypography(): TypographyOptions {
  return {
    fontFamily: fontFamilies.sans,
    fontSize: typeScaleTokens.rootFontSize,
    // htmlFontSize 保持浏览器默认 16，rem 换算基准因此不受影响。
    htmlFontSize: 16,

    h1: {
      fontFamily: fontFamilies.display,
      fontSize: 32,
      lineHeight: typeScaleTokens.headingLineHeight,
      fontWeight: 600,
      // 衬线大字号需要收紧字距；中文在这个幅度下不会显得挤。
      letterSpacing: '-0.02em',
    },
    h2: {
      fontFamily: fontFamilies.display,
      fontSize: 26,
      lineHeight: typeScaleTokens.headingLineHeight,
      fontWeight: 600,
      letterSpacing: '-0.018em',
    },
    h3: {
      fontFamily: fontFamilies.display,
      fontSize: 22,
      lineHeight: typeScaleTokens.headingLineHeight,
      fontWeight: 600,
      letterSpacing: '-0.014em',
    },
    h4: {
      fontFamily: fontFamilies.sans,
      fontSize: 19,
      lineHeight: typeScaleTokens.subheadingLineHeight,
      fontWeight: 600,
      letterSpacing: '-0.006em',
    },
    h5: {
      fontFamily: fontFamilies.sans,
      fontSize: 17,
      lineHeight: typeScaleTokens.subheadingLineHeight,
      fontWeight: 600,
      letterSpacing: '-0.004em',
    },
    h6: {
      fontFamily: fontFamilies.sans,
      fontSize: 15,
      lineHeight: typeScaleTokens.subheadingLineHeight,
      fontWeight: 600,
      letterSpacing: '0em',
    },

    subtitle1: {
      fontFamily: fontFamilies.sans,
      fontSize: 15,
      lineHeight: typeScaleTokens.subheadingLineHeight,
      fontWeight: 500,
      letterSpacing: '0em',
    },
    subtitle2: {
      fontFamily: fontFamilies.sans,
      fontSize: 13,
      lineHeight: typeScaleTokens.subheadingLineHeight,
      fontWeight: 500,
      letterSpacing: '0.004em',
    },

    body1: {
      fontFamily: fontFamilies.sans,
      fontSize: 15,
      lineHeight: typeScaleTokens.bodyLineHeight,
      fontWeight: 400,
      letterSpacing: '0.006em',
    },
    body2: {
      fontFamily: fontFamilies.sans,
      fontSize: 13,
      lineHeight: typeScaleTokens.bodySmallLineHeight,
      fontWeight: 400,
      letterSpacing: '0.008em',
    },

    button: {
      fontFamily: fontFamilies.sans,
      fontSize: 14,
      lineHeight: 1.4,
      fontWeight: 500,
      letterSpacing: '0.012em',
      textTransform: 'none',
    },
    caption: {
      fontFamily: fontFamilies.sans,
      fontSize: 12,
      lineHeight: 1.5,
      fontWeight: 400,
      letterSpacing: '0.02em',
    },
    overline: {
      fontFamily: fontFamilies.sans,
      fontSize: 11,
      lineHeight: 1.4,
      fontWeight: 500,
      // 小字号标签需要字距，但仍不做大小写变换。
      letterSpacing: '0.08em',
      textTransform: 'none',
    },
  }
}
