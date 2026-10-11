/**
 * 外观切换按钮：单击轮换 浅色 → 深色 → 跟随系统。
 *
 * 轮换而不是弹菜单，是 themeMode.ts 的 nextThemeMode 早就定下的口径——三档用
 * 一个图标按钮就能覆盖，不必为"跟随系统"单开一个下拉。
 *
 * 图标与 aria-label 都跟着**用户选的那一档**走，而不是 resolvedMode：选了 system
 * 却报"深色"的话，用户会以为这个按钮决定当前明暗，点下去却发现跳到了浅色。
 * 至于系统此刻解析成什么，整个页面已经告诉他了，不需要按钮再说一遍。
 */
import BrightnessAutoIcon from '@mui/icons-material/BrightnessAuto'
import DarkModeIcon from '@mui/icons-material/DarkMode'
import LightModeIcon from '@mui/icons-material/LightMode'
import { IconButton, Tooltip, type IconButtonProps } from '@mui/material'
import { useTranslation } from 'react-i18next'

import { useThemeMode } from '@/theme'
import type { ThemeMode } from '@/theme'

/**
 * 写成 Record<ThemeMode, …> 是刻意的：漏掉任何一档都会在编译期红掉，
 * 而不是等用户轮到那一档时看见一个空按钮。
 */
const MODE_ICONS: Record<ThemeMode, typeof LightModeIcon> = {
  light: LightModeIcon,
  dark: DarkModeIcon,
  system: BrightnessAutoIcon,
}

export interface ThemeModeToggleProps {
  readonly size?: IconButtonProps['size']
  /** 默认 inherit：放进 AppBar 时跟着栏内文字色，不必每处再指定。 */
  readonly color?: IconButtonProps['color']
}

export default function ThemeModeToggle({
  size = 'medium',
  color = 'inherit',
}: ThemeModeToggleProps) {
  const { mode, cycleMode } = useThemeMode()
  const { t } = useTranslation()

  const Icon = MODE_ICONS[mode]
  const modeLabel = t(`theme.${mode}`)

  return (
    <Tooltip title={modeLabel}>
      <IconButton
        onClick={cycleMode}
        size={size}
        color={color}
        aria-label={t('theme.toggleAria', { mode: modeLabel })}
      >
        <Icon />
      </IconButton>
    </Tooltip>
  )
}
