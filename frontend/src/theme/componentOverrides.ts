/**
 * MUI 组件级覆盖。
 *
 * 三条纪律：
 * 1. 所有颜色、圆角、投影、时长都从 theme.sg 的 token 取，本文件不出现新的
 *    十六进制字面量；
 * 2. 不使用 !important，靠 class key 的天然特异性取胜；
 * 3. 只覆盖"当前代码库真实会渲染到"的表面，不为用不到的组件写样式。
 *
 * 视觉语言：细边框分层 + 低对比投影 + 明确焦点反馈，靠"表面海拔"而不是
 * 靠重投影表达层级，这样深色模式下不会糊成一片。
 */

import { withAlpha } from './contrast'
import { createGlobalStyles } from './globalStyles'
import type { Components, Theme } from '@mui/material/styles'

export function createComponentOverrides(theme: Theme): Components<Theme> {
  const { color, shadow, shape, motion } = theme.sg
  const isDark = theme.palette.mode === 'dark'

  /** 统一的过渡声明，避免每个组件重复拼字符串。 */
  const animate = (properties: string[], duration = motion.durationFast): string =>
    properties.map((property) => `${property} ${duration}ms ${motion.easeStandard}`).join(', ')

  /** 悬停/选中时的中性底：深色需要更高 alpha 才看得见。 */
  const neutralHover = withAlpha(color.textPrimary, isDark ? 0.08 : 0.05)
  const neutralSelected = withAlpha(color.textPrimary, isDark ? 0.14 : 0.09)

  return {
    MuiCssBaseline: {
      styleOverrides: createGlobalStyles(theme),
    },

    MuiButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          borderRadius: shape.radiusSm,
          fontWeight: 500,
          letterSpacing: '0.012em',
          transition: animate(['background-color', 'border-color', 'color', 'box-shadow']),
          '&:focus-visible': {
            outline: `2px solid ${color.focusRing}`,
            outlineOffset: 2,
          },
          // 必须用 &.Mui-disabled 而不是顶层的 disabled 键：后者会被 MUI 的
          // createTheme 在开发环境下清空（traverse 里的 node[key] = {}），
          // 造成"开发无样式、构建后又有样式"的不一致。
          '&.Mui-disabled': {
            color: color.textDisabled,
            borderColor: color.divider,
          },
        },
        sizeSmall: {
          padding: '4px 10px',
          fontSize: '0.8125rem',
        },
        sizeMedium: {
          padding: '7px 16px',
        },
        sizeLarge: {
          padding: '10px 22px',
          fontSize: '0.9375rem',
        },
        // 克制的投影：静止时无投影，悬停时给一档发丝投影，避免满屏浮起。
        contained: {
          boxShadow: 'none',
          '&:hover': {
            boxShadow: shadow.shadow1,
          },
        },
        containedPrimary: {
          backgroundColor: color.primary,
          color: color.onPrimary,
          '&:hover': {
            backgroundColor: color.primaryHover,
          },
          '&:active': {
            backgroundColor: color.primaryActive,
          },
        },
        containedSecondary: {
          backgroundColor: color.secondary,
          color: color.onSecondary,
          '&:hover': {
            backgroundColor: color.secondaryHover,
          },
        },
        outlined: {
          borderWidth: 1,
          borderColor: color.borderStrong,
          color: color.textPrimary,
          '&:hover': {
            borderColor: color.textDisabled,
            backgroundColor: neutralHover,
          },
        },
        outlinedPrimary: {
          borderColor: withAlpha(color.primary, isDark ? 0.5 : 0.4),
          color: color.primary,
          '&:hover': {
            borderColor: color.primary,
            backgroundColor: color.primaryFaint,
          },
        },
        outlinedSecondary: {
          borderColor: withAlpha(color.secondary, isDark ? 0.5 : 0.4),
          color: color.secondary,
          '&:hover': {
            borderColor: color.secondary,
            backgroundColor: color.secondarySoft,
          },
        },
        text: {
          padding: '6px 12px',
          color: color.textSecondary,
          '&:hover': {
            backgroundColor: neutralHover,
            color: color.textPrimary,
          },
        },
        textPrimary: {
          color: color.primary,
          '&:hover': {
            backgroundColor: color.primaryFaint,
            color: isDark ? color.primaryHover : color.primaryActive,
          },
        },
        startIcon: {
          marginLeft: -2,
          marginRight: 6,
        },
        endIcon: {
          marginLeft: 6,
          marginRight: -2,
        },
      },
    },

    MuiIconButton: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusSm,
          color: color.textSecondary,
          transition: animate(['background-color', 'color']),
          '&:hover': {
            backgroundColor: neutralHover,
            color: color.textPrimary,
          },
          '&:disabled': {
            color: color.textDisabled,
          },
        },
        colorPrimary: {
          color: color.primary,
          '&:hover': {
            backgroundColor: color.primaryFaint,
            color: isDark ? color.primaryHover : color.primaryActive,
          },
        },
        sizeSmall: {
          borderRadius: shape.radiusXs,
        },
      },
    },

    MuiFab: {
      styleOverrides: {
        // 投影交给 elevation（默认 6，悬停 8），这里只管颜色。
        primary: {
          backgroundColor: color.primary,
          color: color.onPrimary,
          '&:hover': {
            backgroundColor: color.primaryHover,
          },
        },
      },
    },

    // MUI 在深色模式下会给 Paper 叠一层白色渐变做"海拔提亮"，
    // 那会盖掉我们精心定的 surface 色，因此统一关掉。
    // 投影不在这里写，由 createAppTheme 的 shadows 表按 elevation 供给。
    MuiPaper: {
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
        outlined: {
          borderColor: color.border,
        },
      },
    },

    MuiCard: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusLg,
          border: `1px solid ${color.border}`,
          backgroundColor: color.surface,
          transition: animate(['box-shadow', 'border-color']),
        },
      },
    },

    MuiCardActionArea: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusLg,
          '&:hover': {
            borderColor: color.borderStrong,
          },
          '& .MuiCardActionArea-focusHighlight': {
            backgroundColor: color.primary,
          },
        },
      },
    },

    MuiCardHeader: {
      styleOverrides: {
        root: {
          padding: '16px 20px 12px',
        },
        title: {
          fontWeight: 600,
        },
        subheader: {
          color: color.textSecondary,
        },
      },
    },

    MuiCardContent: {
      styleOverrides: {
        root: {
          padding: '4px 20px 20px',
          '&:last-child': {
            paddingBottom: 20,
          },
        },
      },
    },

    MuiCardActions: {
      styleOverrides: {
        root: {
          padding: '8px 20px 16px',
          gap: 8,
        },
      },
    },

    // 现有 AppBar 多为默认 color="primary"，改 defaultProps 为 default
    // 再覆盖 colorDefault，可让未显式指定颜色的 AppBar 落到纸面配色，
    // 而显式写了 color="primary" 的调用点保持原语义。
    MuiAppBar: {
      defaultProps: {
        color: 'default',
        elevation: 0,
      },
      styleOverrides: {
        root: {
          backgroundImage: 'none',
        },
        colorDefault: {
          backgroundColor: color.surface,
          color: color.textPrimary,
          borderBottom: `1px solid ${color.divider}`,
          boxShadow: shadow.shadow1,
        },
        colorPrimary: {
          backgroundColor: color.primary,
          color: color.onPrimary,
        },
      },
    },

    MuiDrawer: {
      styleOverrides: {
        paper: {
          backgroundColor: color.surface,
          backgroundImage: 'none',
          borderRight: `1px solid ${color.divider}`,
        },
        paperAnchorLeft: {
          borderRight: `1px solid ${color.divider}`,
        },
        paperAnchorRight: {
          borderLeft: `1px solid ${color.divider}`,
          borderRight: 'none',
        },
      },
    },

    MuiPopover: {
      styleOverrides: {
        paper: {
          borderRadius: shape.radiusMd,
          border: `1px solid ${color.divider}`,
          backgroundColor: color.surfaceRaised,
          padding: 4,
        },
      },
    },

    MuiMenu: {
      styleOverrides: {
        paper: {
          borderRadius: shape.radiusMd,
          border: `1px solid ${color.divider}`,
          backgroundColor: color.surfaceRaised,
          padding: 4,
        },
        list: {
          padding: 0,
          gap: 2,
        },
      },
    },

    MuiMenuItem: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusXs,
          fontSize: '0.875rem',
          gap: 10,
          transition: animate(['background-color', 'color']),
          '&:hover': {
            backgroundColor: neutralHover,
          },
          '&.Mui-selected': {
            backgroundColor: neutralSelected,
            '&:hover': {
              backgroundColor: neutralSelected,
            },
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
      },
    },

    MuiDialog: {
      styleOverrides: {
        paper: {
          borderRadius: shape.radiusLg,
          border: `1px solid ${color.divider}`,
          backgroundColor: color.surface,
        },
      },
    },

    MuiDialogTitle: {
      styleOverrides: {
        root: {
          padding: '20px 24px 12px',
          fontSize: '1.125rem',
          fontWeight: 600,
          letterSpacing: '-0.004em',
          lineHeight: 1.4,
        },
      },
    },

    MuiDialogContent: {
      styleOverrides: {
        root: {
          padding: '4px 24px 20px',
        },
      },
    },

    MuiDialogContentText: {
      styleOverrides: {
        root: {
          color: color.textSecondary,
          lineHeight: 1.65,
        },
      },
    },

    MuiDialogActions: {
      styleOverrides: {
        root: {
          padding: '12px 24px 20px',
          gap: 8,
          '& > :not(:first-of-type)': {
            marginLeft: 0,
          },
        },
      },
    },

    MuiBackdrop: {
      styleOverrides: {
        root: {
          // 纸感设计下 MUI 默认的 0.5 黑遮罩太重，浅色再降一档。
          backgroundColor: withAlpha(color.scrim, isDark ? 0.72 : 0.42),
          '&.MuiBackdrop-invisible': {
            backgroundColor: 'transparent',
          },
        },
      },
    },

    MuiTextField: {
      styleOverrides: {
        root: {
          '& .MuiFormHelperText-root': {
            marginTop: 4,
          },
        },
      },
    },

    MuiInputBase: {
      styleOverrides: {
        root: {
          color: color.textPrimary,
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
        input: {
          '&::placeholder': {
            color: color.textDisabled,
            // MUI 已设 1，这里显式重申，避免被第三方样式表覆盖。
            opacity: 1,
          },
          '&::-webkit-outer-spin-button, &::-webkit-inner-spin-button': {
            WebkitAppearance: 'none',
            margin: 0,
          },
        },
        inputSizeSmall: {
          fontSize: '0.875rem',
        },
      },
    },

    // 输入框用内凹表面色，在卡片（surface）上形成"可编辑区域"的暗示。
    MuiOutlinedInput: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusSm,
          backgroundColor: color.surfaceSunken,
          transition: animate(['background-color']),
          '&:hover': {
            backgroundColor: isDark ? color.surfaceSunken : color.bgSubtle,
          },
          '&.Mui-focused': {
            backgroundColor: color.surface,
          },
          '&.Mui-disabled': {
            backgroundColor: color.bgSubtle,
          },
          '&.Mui-error': {
            backgroundColor: color.surfaceSunken,
          },
        },
        notchedOutline: {
          borderColor: color.borderStrong,
          borderWidth: 1,
          transition: animate(['border-color']),
        },
        input: {
          '&:-webkit-autofill': {
            // 浏览器的自动填充黄底在两种模式下都很刺眼，用内阴影压住。
            WebkitBoxShadow: `0 0 0 100px ${color.surfaceSunken} inset`,
            WebkitTextFillColor: color.textPrimary,
            caretColor: color.textPrimary,
          },
        },
      },
    },

    MuiInputLabel: {
      styleOverrides: {
        root: {
          color: color.textSecondary,
          fontWeight: 500,
          '&.Mui-focused': {
            color: color.primary,
          },
          '&.Mui-error': {
            color: color.error,
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
        asterisk: {
          color: color.error,
        },
      },
    },

    MuiFormHelperText: {
      styleOverrides: {
        root: {
          color: color.textSecondary,
          fontSize: '0.75rem',
          letterSpacing: '0.01em',
          '&.Mui-error': {
            color: color.error,
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
      },
    },

    MuiFormLabel: {
      styleOverrides: {
        root: {
          color: color.textSecondary,
          fontWeight: 500,
          '&.Mui-focused': {
            color: color.primary,
          },
          '&.Mui-error': {
            color: color.error,
          },
        },
      },
    },

    MuiSelect: {
      styleOverrides: {
        select: {
          borderRadius: shape.radiusSm,
          '&:focus': {
            // 关掉 MUI 默认聚焦时的灰底，聚焦反馈交给边框。
            backgroundColor: 'transparent',
            borderRadius: shape.radiusSm,
          },
        },
        icon: {
          color: color.textSecondary,
        },
        nativeInput: {
          color: color.textPrimary,
        },
      },
    },

    MuiSwitch: {
      styleOverrides: {
        switchBase: {
          color: color.surfaceRaised,
          '&:hover': {
            backgroundColor: neutralHover,
          },
          '&.Mui-checked': {
            color: color.onPrimary,
            '&:hover': {
              backgroundColor: withAlpha(color.primary, isDark ? 0.16 : 0.1),
            },
            '& + .MuiSwitch-track': {
              backgroundColor: color.primary,
              opacity: 1,
            },
          },
          '&.Mui-disabled': {
            color: color.bgSubtle,
            '& + .MuiSwitch-track': {
              backgroundColor: color.textDisabled,
              opacity: isDark ? 0.3 : 0.2,
            },
          },
        },
        track: {
          backgroundColor: color.textDisabled,
          opacity: isDark ? 0.4 : 0.28,
          borderRadius: shape.radiusPill,
        },
        thumb: {
          boxShadow: shadow.shadow1,
        },
      },
    },

    MuiCheckbox: {
      styleOverrides: {
        root: {
          color: color.borderStrong,
          '&:hover': {
            backgroundColor: withAlpha(color.primary, isDark ? 0.14 : 0.08),
          },
          '&.Mui-checked': {
            color: color.primary,
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
      },
    },

    MuiRadio: {
      styleOverrides: {
        root: {
          color: color.borderStrong,
          '&:hover': {
            backgroundColor: withAlpha(color.primary, isDark ? 0.14 : 0.08),
          },
          '&.Mui-checked': {
            color: color.primary,
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
      },
    },

    MuiToggleButton: {
      styleOverrides: {
        root: {
          textTransform: 'none',
          borderColor: color.border,
          color: color.textSecondary,
          transition: animate(['background-color', 'border-color', 'color']),
          '&:hover': {
            backgroundColor: neutralHover,
            color: color.textPrimary,
          },
          '&.Mui-selected': {
            backgroundColor: color.primarySoft,
            borderColor: withAlpha(color.primary, isDark ? 0.6 : 0.45),
            color: color.primary,
            '&:hover': {
              backgroundColor: color.primarySoft,
            },
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
            borderColor: color.divider,
          },
        },
      },
    },

    // Chip 在本项目里几乎只用于状态标签，因此 color="primary" 等语义色
    // 一律改为"柔色底 + 语义色字"，实心留给 Button。
    MuiChip: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusSm,
          fontWeight: 500,
          fontSize: '0.75rem',
          letterSpacing: '0.01em',
          backgroundColor: color.bgSubtle,
          color: color.textSecondary,
        },
        label: {
          paddingLeft: 8,
          paddingRight: 8,
        },
        outlined: {
          borderColor: color.borderStrong,
        },
        outlinedPrimary: {
          borderColor: withAlpha(color.primary, isDark ? 0.55 : 0.4),
          color: color.primary,
        },
        colorPrimary: {
          backgroundColor: color.primarySoft,
          color: isDark ? color.primaryHover : color.primaryActive,
        },
        colorSecondary: {
          backgroundColor: color.secondarySoft,
          color: color.secondary,
        },
        colorSuccess: {
          backgroundColor: color.successSoft,
          color: color.success,
        },
        colorWarning: {
          backgroundColor: color.warningSoft,
          color: color.warning,
        },
        colorError: {
          backgroundColor: color.errorSoft,
          color: color.error,
        },
        colorInfo: {
          backgroundColor: color.infoSoft,
          color: color.info,
        },
        deleteIcon: {
          color: withAlpha(color.textPrimary, 0.4),
          '&:hover': {
            color: color.textPrimary,
          },
        },
      },
    },

    MuiTabs: {
      styleOverrides: {
        root: {
          minHeight: 44,
        },
        indicator: {
          backgroundColor: color.primary,
          height: 2,
          borderRadius: `${shape.radiusPill}px`,
        },
        scrollButtons: {
          color: color.textSecondary,
        },
        flexContainer: {
          gap: 4,
        },
      },
    },

    MuiTab: {
      styleOverrides: {
        root: {
          // 中文 Tab 标签被 uppercase 处理等于没处理，且会破坏品牌词形。
          textTransform: 'none',
          minHeight: 44,
          paddingTop: 8,
          paddingBottom: 8,
          fontSize: '0.875rem',
          fontWeight: 500,
          letterSpacing: '0.004em',
          color: color.textSecondary,
          borderRadius: shape.radiusSm,
          transition: animate(['color', 'background-color']),
          '&:hover': {
            color: color.textPrimary,
            backgroundColor: neutralHover,
          },
          '&.Mui-selected': {
            color: color.primary,
          },
          '&.Mui-disabled': {
            color: color.textDisabled,
          },
        },
      },
    },

    MuiBreadcrumbs: {
      styleOverrides: {
        root: {
          fontSize: '0.8125rem',
        },
        ol: {
          alignItems: 'center',
          flexWrap: 'nowrap',
        },
        li: {
          color: color.textSecondary,
        },
        separator: {
          color: color.textDisabled,
          marginLeft: 6,
          marginRight: 6,
        },
      },
    },

    MuiLink: {
      defaultProps: {
        // 常驻下划线在中文长段落里噪点太多，改为悬停才出现。
        underline: 'hover',
      },
      styleOverrides: {
        root: {
          color: color.primary,
          fontWeight: 500,
          textUnderlineOffset: '0.2em',
          textDecorationThickness: 1,
          transition: animate(['color']),
          '&:hover': {
            color: isDark ? color.primaryHover : color.primaryActive,
          },
          '&:focus-visible': {
            outline: `2px solid ${color.focusRing}`,
            outlineOffset: 2,
            borderRadius: shape.radiusXs,
          },
        },
      },
    },

    MuiTableHead: {
      styleOverrides: {
        root: {
          backgroundColor: color.bgSubtle,
        },
      },
    },

    MuiTableCell: {
      styleOverrides: {
        root: {
          borderBottom: `1px solid ${color.divider}`,
          fontSize: '0.8125rem',
          padding: '10px 16px',
        },
        head: {
          backgroundColor: color.bgSubtle,
          color: color.textSecondary,
          fontWeight: 600,
          fontSize: '0.75rem',
          letterSpacing: '0.04em',
          borderBottom: `1px solid ${color.dividerStrong}`,
        },
        body: {
          color: color.textPrimary,
        },
        sizeSmall: {
          padding: '6px 12px',
        },
        stickyHeader: {
          backgroundColor: color.bgSubtle,
        },
      },
    },

    MuiTableRow: {
      styleOverrides: {
        root: {
          transition: animate(['background-color']),
          '&:hover': {
            backgroundColor: neutralHover,
          },
          '&.Mui-selected': {
            backgroundColor: withAlpha(color.primary, isDark ? 0.16 : 0.08),
            '&:hover': {
              backgroundColor: withAlpha(color.primary, isDark ? 0.22 : 0.12),
            },
          },
          '&:last-child .MuiTableCell-root': {
            borderBottom: 0,
          },
        },
        head: {
          '&:hover': {
            backgroundColor: 'transparent',
          },
        },
      },
    },

    MuiTableContainer: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusMd,
        },
      },
    },

    MuiList: {
      styleOverrides: {
        root: {
          paddingTop: 4,
          paddingBottom: 4,
        },
      },
    },

    MuiListItemButton: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusXs,
          transition: animate(['background-color', 'color']),
          '&:hover': {
            backgroundColor: neutralHover,
          },
          '&.Mui-selected': {
            backgroundColor: neutralSelected,
            '&:hover': {
              backgroundColor: neutralSelected,
            },
          },
        },
      },
    },

    MuiListItemText: {
      styleOverrides: {
        primary: {
          fontSize: '0.875rem',
          fontWeight: 500,
          color: color.textPrimary,
          lineHeight: 1.45,
        },
        secondary: {
          fontSize: '0.75rem',
          color: color.textSecondary,
          lineHeight: 1.5,
        },
      },
    },

    MuiAccordion: {
      styleOverrides: {
        root: {
          backgroundColor: color.surface,
          border: `1px solid ${color.divider}`,
          borderRadius: `${shape.radiusSm}px !important`,
          boxShadow: 'none',
          backgroundImage: 'none',
          // 我们已用 border 分层，MUI 自带的顶部分隔线是重复的。
          '&:before': {
            display: 'none',
          },
          '&.Mui-expanded': {
            borderColor: color.borderStrong,
            margin: 0,
          },
          '&:not(:first-of-type)': {
            marginTop: -1,
          },
        },
      },
    },

    MuiAccordionSummary: {
      styleOverrides: {
        root: {
          minHeight: 48,
          padding: '0 16px',
          '&.Mui-expanded': {
            minHeight: 48,
          },
          '&:hover': {
            backgroundColor: neutralHover,
          },
        },
        content: {
          margin: '10px 0',
          '&.Mui-expanded': {
            margin: '10px 0',
          },
        },
        expandIconWrapper: {
          color: color.textSecondary,
        },
      },
    },

    MuiAccordionDetails: {
      styleOverrides: {
        root: {
          padding: '4px 16px 16px',
          borderTop: `1px solid ${color.divider}`,
        },
      },
    },

    MuiDivider: {
      styleOverrides: {
        root: {
          borderColor: color.divider,
        },
        withChildren: {
          color: color.textSecondary,
          fontSize: '0.75rem',
          fontWeight: 500,
          '&::before, &::after': {
            borderColor: color.divider,
          },
        },
        light: {
          borderColor: withAlpha(color.divider, 0.6),
        },
      },
    },

    // 反色 Tooltip：浅色模式用墨底纸字，深色模式用抬升面 + 边框，
    // 后者是因为纯白 tooltip 在墨底上过于刺眼。
    MuiTooltip: {
      styleOverrides: {
        tooltip: {
          backgroundColor: isDark ? color.surfaceRaised : color.textPrimary,
          color: isDark ? color.textPrimary : color.bgPaper,
          border: isDark ? `1px solid ${color.borderStrong}` : 'none',
          borderRadius: shape.radiusSm,
          fontSize: '0.75rem',
          lineHeight: 1.5,
          padding: '6px 10px',
          maxWidth: 320,
          boxShadow: shadow.shadow2,
        },
        arrow: {
          color: isDark ? color.surfaceRaised : color.textPrimary,
        },
      },
    },

    MuiAlert: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusSm,
          padding: '10px 14px',
          fontSize: '0.8125rem',
          lineHeight: 1.6,
          alignItems: 'flex-start',
        },
        icon: {
          fontSize: 18,
          marginRight: 10,
          padding: 0,
          opacity: 1,
        },
        message: {
          padding: 0,
        },
        action: {
          marginRight: 0,
          padding: 0,
        },
        standardSuccess: {
          backgroundColor: color.successSoft,
          color: color.success,
          '& .MuiAlert-icon': { color: color.success },
        },
        standardWarning: {
          backgroundColor: color.warningSoft,
          color: color.warning,
          '& .MuiAlert-icon': { color: color.warning },
        },
        standardError: {
          backgroundColor: color.errorSoft,
          color: color.error,
          '& .MuiAlert-icon': { color: color.error },
        },
        standardInfo: {
          backgroundColor: color.infoSoft,
          color: color.info,
          '& .MuiAlert-icon': { color: color.info },
        },
        outlinedSuccess: { borderColor: color.success, color: color.success },
        outlinedWarning: { borderColor: color.warning, color: color.warning },
        outlinedError: { borderColor: color.error, color: color.error },
        outlinedInfo: { borderColor: color.info, color: color.info },
        filledSuccess: { backgroundColor: color.success, color: color.onSuccess },
        filledWarning: { backgroundColor: color.warning, color: color.onWarning },
        filledError: { backgroundColor: color.error, color: color.onError },
        filledInfo: { backgroundColor: color.info, color: color.onInfo },
      },
    },

    MuiAlertTitle: {
      styleOverrides: {
        root: {
          fontWeight: 600,
          fontSize: '0.875rem',
          marginBottom: 2,
        },
      },
    },

    MuiSnackbar: {
      styleOverrides: {
        root: {
          // 移动端贴边时避开系统手势条。
          '@media (max-width: 600px)': {
            marginBottom: 'env(safe-area-inset-bottom, 0px)',
          },
        },
      },
    },

    MuiSnackbarContent: {
      styleOverrides: {
        root: {
          borderRadius: shape.radiusSm,
          backgroundColor: isDark ? color.surfaceRaised : color.textPrimary,
          color: isDark ? color.textPrimary : color.bgPaper,
          border: isDark ? `1px solid ${color.borderStrong}` : 'none',
          boxShadow: shadow.shadow3,
          fontSize: '0.8125rem',
        },
      },
    },

    MuiAvatar: {
      styleOverrides: {
        root: {
          backgroundColor: color.primarySoft,
          color: isDark ? color.primaryHover : color.primaryActive,
          fontWeight: 600,
          fontSize: '0.875rem',
          fontFamily: theme.typography.fontFamily,
        },
        rounded: {
          borderRadius: shape.radiusSm,
        },
        img: {
          objectFit: 'cover',
        },
      },
    },

    MuiBadge: {
      styleOverrides: {
        badge: {
          fontWeight: 600,
          fontSize: '0.6875rem',
          // 加一圈底色描边，让徽标压在图片上时仍然可辨。
          border: `2px solid ${color.surface}`,
        },
        colorPrimary: {
          backgroundColor: color.primary,
          color: color.onPrimary,
        },
        colorError: {
          backgroundColor: color.error,
          color: color.onError,
        },
      },
    },

    MuiSkeleton: {
      styleOverrides: {
        root: {
          backgroundColor: color.bgSubtle,
          borderRadius: shape.radiusXs,
        },
        rounded: {
          borderRadius: shape.radiusSm,
        },
        wave: {
          '&::after': {
            backgroundImage: `linear-gradient(90deg, transparent, ${withAlpha(
              color.textPrimary,
              isDark ? 0.06 : 0.05,
            )}, transparent)`,
          },
        },
        text: {
          transformOrigin: '0 55%',
        },
      },
    },

    MuiLinearProgress: {
      styleOverrides: {
        root: {
          backgroundColor: color.bgSubtle,
          borderRadius: shape.radiusPill,
          height: 6,
          overflow: 'hidden',
        },
        bar: {
          borderRadius: shape.radiusPill,
        },
        colorPrimary: {
          backgroundColor: color.bgSubtle,
        },
        barColorPrimary: {
          backgroundColor: color.primary,
        },
        colorSecondary: {
          backgroundColor: color.bgSubtle,
        },
        barColorSecondary: {
          backgroundColor: color.secondary,
        },
        dashedColorPrimary: {
          backgroundImage: `radial-gradient(${color.borderStrong} 0%, ${color.borderStrong} 16%, transparent 42%)`,
        },
      },
    },

    MuiCircularProgress: {
      styleOverrides: {
        colorPrimary: {
          color: color.primary,
        },
        colorSecondary: {
          color: color.secondary,
        },
      },
    },

    MuiRating: {
      styleOverrides: {
        iconFilled: {
          color: color.primary,
        },
        iconHover: {
          color: color.primaryHover,
        },
      },
    },

    MuiSlider: {
      styleOverrides: {
        root: {
          color: color.primary,
        },
        rail: {
          color: color.borderStrong,
          opacity: 1,
        },
        thumb: {
          backgroundColor: color.surfaceRaised,
          border: `2px solid ${color.primary}`,
          boxShadow: shadow.shadow1,
          '&:hover, &.Mui-focusVisible': {
            boxShadow: `0 0 0 6px ${withAlpha(color.primary, isDark ? 0.2 : 0.12)}`,
          },
        },
      },
    },
  }
}
