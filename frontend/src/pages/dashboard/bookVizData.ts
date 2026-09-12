/**
 * Dashboard 书卡体裁数据纹理色（颜色即数据）。
 *
 * 每本书卡封面是「深色渐变书封 + 亮色金字」的媒体美术设计：genre 标签色、
 * 封面主/次/强调/文字色、四段渐变全部是封面数据——渲在浅色页面上也刻意
 * 保持深色封面（同 audiobook 黑胶卡），不随主题反相。整文件豁免契约扫描。
 */

export type BookVizPalette = {
  primary: string
  secondary: string
  accent: string
  text: string
  gradient: string
}

/** 题材标签色（书卡内 genre chip / 编辑选单）。 */
export const GENRE_COLORS: Record<string, string> = {
  '修仙': '#e8c46a',
  '玄幻': '#d4a0ff',
  '奇幻': '#72e2a0',
  '都市': '#e8a87c',
  '言情': '#ffb5c8',
  '耐美': '#f9a8d4',
  '悬疑': '#f87171',
  '科幻': '#38bdf8',
  '纯文学': '#c8b99a',
  '浪漫': '#fda4af',
  '惊悚': '#fb923c',
  '其他': '#94a3b8',
}

/** 题材封面调色板（深底浅字数据对）。 */
const BOOK_VIZ_PALETTES: Record<string, BookVizPalette> = {
  '修仙': {
    primary: '#0c1e4a',
    secondary: '#1a3a7a',
    accent: '#e8c46a',
    text: '#fef0c7',
    gradient: 'linear-gradient(160deg, #0c1e4a 0%, #162e68 45%, #1d3d82 75%, #243a6e 100%)',
  },
  '玄幻': {
    primary: '#2d0a4e',
    secondary: '#4a1272',
    accent: '#d4a0ff',
    text: '#f3e4ff',
    gradient: 'linear-gradient(160deg, #1e0535 0%, #2d0a4e 40%, #3f1168 70%, #4a1272 100%)',
  },
  '奇幻': {
    primary: '#0a2e14',
    secondary: '#133d1e',
    accent: '#72e2a0',
    text: '#d4f7e4',
    gradient: 'linear-gradient(160deg, #051a0b 0%, #0a2e14 40%, #0f3d1a 70%, #165226 100%)',
  },
  '都市': {
    primary: '#1a1a2e',
    secondary: '#16213e',
    accent: '#e8a87c',
    text: '#ffeedd',
    gradient: 'linear-gradient(160deg, #12121f 0%, #1a1a2e 40%, #1e2545 70%, #0f3460 100%)',
  },
  '言情': {
    primary: '#3d0b20',
    secondary: '#6b1535',
    accent: '#ffb5c8',
    text: '#ffe4ed',
    gradient: 'linear-gradient(160deg, #2a0716 0%, #3d0b20 40%, #5a1030 70%, #6b1535 100%)',
  },
  '耽美': {
    primary: '#1a0a2e',
    secondary: '#2d1052',
    accent: '#f9a8d4',
    text: '#fce7f3',
    gradient: 'linear-gradient(160deg, #130820 0%, #1a0a2e 40%, #260d42 70%, #2d1052 100%)',
  },
  '悬疑': {
    primary: '#080c14',
    secondary: '#0f172a',
    accent: '#dc2626',
    text: '#fecaca',
    gradient: 'linear-gradient(160deg, #030508 0%, #080c14 40%, #0f172a 70%, #1e2438 100%)',
  },
  '科幻': {
    primary: '#020c1b',
    secondary: '#0a2240',
    accent: '#38bdf8',
    text: '#e0f2fe',
    gradient: 'linear-gradient(160deg, #010810 0%, #020c1b 40%, #0a2240 70%, #0c3060 100%)',
  },
  '纯文学': {
    primary: '#2c2218',
    secondary: '#3d2e20',
    accent: '#c8b99a',
    text: '#f5ede0',
    gradient: 'linear-gradient(160deg, #1c1410 0%, #2c2218 40%, #3d2e20 70%, #4a3828 100%)',
  },
  'Fantasy': {
    primary: '#0a2e14',
    secondary: '#133d1e',
    accent: '#72e2a0',
    text: '#d4f7e4',
    gradient: 'linear-gradient(160deg, #051a0b 0%, #0a2e14 40%, #0f3d1a 70%, #165226 100%)',
  },
}

const BOOK_VIZ_FALLBACK: BookVizPalette = {
  primary: '#1c1a2e',
  secondary: '#2d2a4a',
  accent: '#c4a882',
  text: '#f0e6d3',
  gradient: 'linear-gradient(160deg, #12101e 0%, #1c1a2e 40%, #2d2a4a 70%, #3a3560 100%)',
}

/** 按题材取封面调色板，未登记题材回退默认深墨封面。 */
export function getBookVizPalette(genre: string | undefined): BookVizPalette {
  return BOOK_VIZ_PALETTES[genre || ''] || BOOK_VIZ_FALLBACK
}