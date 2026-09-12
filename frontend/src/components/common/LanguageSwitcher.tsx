/**
 * 语言切换菜单。
 *
 * 用菜单而不是"点一下切到另一语"的按钮：SUPPORTED_LANGUAGES 是可以继续加的，
 * 两语时按钮看着利落，但加到第三门语言就得整个换掉。
 *
 * 菜单里的语言名一律用**母语自称**（简体中文 / English），而不是当前界面语言下
 * 的译名：看不懂中文的人，正是最需要一眼找到 "English" 的那个人。englishLabel
 * 放在第二行兜底，两种写法都不认识时还有一条出路。
 */
import { useState } from 'react'
import CheckIcon from '@mui/icons-material/Check'
import LanguageIcon from '@mui/icons-material/Language'
import {
  Box,
  IconButton,
  ListItemIcon,
  Menu,
  MenuItem,
  Tooltip,
  Typography,
  type IconButtonProps,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

import { SUPPORTED_LANGUAGES, getLanguageDescriptor, useAppLanguage } from '@/i18n'
import type { AppLanguage, LanguageDescriptor } from '@/i18n'

export interface LanguageOption {
  readonly code: AppLanguage
  readonly nativeLabel: string
  readonly englishLabel: string
  readonly selected: boolean
}

/**
 * 菜单的视图模型。
 *
 * languages 可注入，因此"当前语言不在清单里"这条边界才测得到；生产路径用缺省的
 * SUPPORTED_LANGUAGES，那时不会有任何一项被选中，而不是抛错或随便选一个。
 */
export function buildLanguageOptions(
  current: AppLanguage,
  languages: readonly LanguageDescriptor[] = SUPPORTED_LANGUAGES,
): LanguageOption[] {
  return languages.map((entry) => ({
    code: entry.code,
    nativeLabel: entry.nativeLabel,
    englishLabel: entry.englishLabel,
    selected: entry.code === current,
  }))
}

export interface LanguageSwitcherProps {
  readonly size?: IconButtonProps['size']
  /** 默认 inherit：放进 AppBar 时跟着栏内文字色，与 ThemeModeToggle 一致。 */
  readonly color?: IconButtonProps['color']
}

export default function LanguageSwitcher({
  size = 'medium',
  color = 'inherit',
}: LanguageSwitcherProps) {
  const { language, setLanguage } = useAppLanguage()
  const { t } = useTranslation()
  const [anchorEl, setAnchorEl] = useState<HTMLElement | null>(null)

  const options = buildLanguageOptions(language)
  const open = anchorEl !== null

  const close = () => setAnchorEl(null)

  const choose = (code: AppLanguage) => {
    // 先关菜单再切：非事实源语言要现拉 chunk，菜单一直悬着会显得点了没反应。
    close()

    if (code === language) {
      return
    }

    // setLanguage 内部先持久化再切换，所以 chunk 拉不到时用户的选择也已经记下，
    // 下次加载会重试。这里只留日志：失败时按钮仍显示原语言，"什么都没变"本身
    // 就是反馈；再叠一个错误提示条属于 P4 的打磨范围。
    void setLanguage(code).catch((error: unknown) => {
      console.error('[i18n] 语言切换失败', error)
    })
  }

  return (
    <>
      <Tooltip title={t('language.label')}>
        <IconButton
          onClick={(event) => setAnchorEl(event.currentTarget)}
          size={size}
          color={color}
          aria-label={t('language.switchAria', {
            language: getLanguageDescriptor(language).nativeLabel,
          })}
          aria-haspopup="menu"
          aria-expanded={open}
        >
          <LanguageIcon />
        </IconButton>
      </Tooltip>
      <Menu anchorEl={anchorEl} open={open} onClose={close}>
        {options.map((option) => (
          <MenuItem
            key={option.code}
            selected={option.selected}
            onClick={() => choose(option.code)}
          >
            {/* 未选中时也占住这一格，否则勾选出现时整行文字会横跳一下。 */}
            <ListItemIcon>{option.selected ? <CheckIcon fontSize="small" /> : null}</ListItemIcon>
            <Box>
              <Typography variant="body2">{option.nativeLabel}</Typography>
              <Typography variant="caption" color="text.secondary">
                {option.englishLabel}
              </Typography>
            </Box>
          </MenuItem>
        ))}
      </Menu>
    </>
  )
}
