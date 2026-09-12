/**
 * 控件簇：把语言切换与外观切换两个原语分组，供顶栏 full 变体与 slim 浮动变体
 * 共同复用（DRY）。
 *
 * 簇本身不含任何新逻辑，只负责"挨着放、尺寸/颜色一起传"。两个原语都默认
 * color="inherit"，因此整簇丢进 AppBar 就跟着栏内文字色，丢进浮动容器就跟着
 * 容器前景色，调用方不必逐个再指定。
 */
import { Stack, type IconButtonProps } from '@mui/material'

import LanguageSwitcher from './LanguageSwitcher'
import ThemeModeToggle from './ThemeModeToggle'

export interface ControlClusterProps {
  readonly size?: IconButtonProps['size']
  /** 默认 inherit：跟随所在表面（AppBar / 浮动容器）的文字色。 */
  readonly color?: IconButtonProps['color']
}

export default function ControlCluster({
  size = 'medium',
  color = 'inherit',
}: ControlClusterProps) {
  return (
    <Stack direction="row" alignItems="center" spacing={0.25}>
      <LanguageSwitcher size={size} color={color} />
      <ThemeModeToggle size={size} color={color} />
    </Stack>
  )
}
