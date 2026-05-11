export const audiobookColors = {
  primary: '#1976d2',
  primaryDark: '#1565c0',
  brand: '#7b1fa2',
  brandDark: '#6a1b9a',
  brandSoft: 'rgba(123, 31, 162, 0.08)',
  brandFaint: 'rgba(123, 31, 162, 0.03)',
  success: '#2e7d32',
  successMain: '#4caf50',
  successChip: 'rgba(76, 175, 80, 0.15)',
  successSoft: 'rgba(76, 175, 80, 0.08)',
  warning: '#e65100',
  warningMain: '#ff9800',
  reviewWarning: '#f57c00',
  reviewWarningChip: 'rgba(255, 152, 0, 0.15)',
  warningSoft: 'rgba(239, 108, 0, 0.12)',
  danger: '#c2185b',
  dangerDark: '#ad1457',
  reviewDanger: '#c62828',
  dangerMain: '#f44336',
  dangerHover: '#d32f2f',
  dangerChip: 'rgba(244, 67, 54, 0.15)',
  dangerFaint: 'rgba(244, 67, 54, 0.05)',
  dangerSoft: 'rgba(194, 24, 91, 0.08)',
  collect: '#00897b',
  collectSoft: 'rgba(0, 137, 123, 0.08)',
  neutral: '#607d8b',
  neutralText: '#616161',
  neutralMuted: '#757575',
  neutralChip: 'rgba(158, 158, 158, 0.12)',
  neutralChipStrong: 'rgba(189, 189, 189, 0.18)',
  neutralSoft: 'rgba(96, 125, 139, 0.08)',
  infoSoft: 'rgba(25, 118, 210, 0.06)',
  surfacePaper: 'rgba(255,255,255,0.95)',
  surfaceRaised: 'rgba(255,255,255,0.75)',
  surfaceBorder: 'rgba(0,0,0,0.08)',
  surfaceDashedBorder: 'rgba(0,0,0,0.18)',
  surfaceSubtle: 'rgba(0,0,0,0.02)',
  shadowSoft: '0 2px 8px rgba(0,0,0,0.1)',
  warningFaint: 'rgba(255, 248, 225, 0.6)',
  pendingBg: '#f5f5f5',
  pendingBorder: '#e0e0e0',
  pendingText: '#9e9e9e',
} as const

export const audiobookColorRoles = {
  destructiveAction: {
    main: audiobookColors.dangerMain,
    hover: audiobookColors.dangerHover,
    text: audiobookColors.danger,
    softBg: audiobookColors.dangerFaint,
    emphasisBg: audiobookColors.dangerChip,
  },
  reviewRisk: {
    good: {
      text: audiobookColors.success,
      bg: audiobookColors.successChip,
    },
    warning: {
      text: audiobookColors.reviewWarning,
      bg: audiobookColors.reviewWarningChip,
    },
    danger: {
      text: audiobookColors.reviewDanger,
      bg: audiobookColors.dangerChip,
    },
  },
  taskStatus: {
    pending: {
      bg: audiobookColors.pendingBg,
      border: audiobookColors.pendingBorder,
      text: audiobookColors.pendingText,
      chipBg: audiobookColors.pendingText,
    },
    running: {
      bg: audiobookColors.brandSoft,
      border: audiobookColors.brand,
      text: audiobookColors.brand,
      chipBg: audiobookColors.warningMain,
    },
    completed: {
      bg: audiobookColors.successSoft,
      border: audiobookColors.successMain,
      text: audiobookColors.successMain,
      chipBg: audiobookColors.successMain,
    },
    failed: {
      bg: audiobookColors.dangerChip,
      border: audiobookColors.dangerMain,
      text: audiobookColors.dangerMain,
      chipBg: audiobookColors.dangerMain,
    },
  },
  notice: {
    warning: {
      text: audiobookColors.warning,
      bg: audiobookColors.warningSoft,
      faintBg: audiobookColors.warningFaint,
    },
  },
} as const

export const audiobookButtonSx = {
  primaryOutlined: {
    borderColor: audiobookColors.primary,
    color: audiobookColors.primaryDark,
    '&:hover': {
      borderColor: audiobookColors.primaryDark,
      backgroundColor: audiobookColors.infoSoft,
    },
  },
  brandOutlined: {
    borderColor: audiobookColors.brand,
    color: audiobookColors.brand,
    '&:hover': {
      borderColor: audiobookColors.brandDark,
      backgroundColor: audiobookColors.brandSoft,
    },
  },
  brandContained: {
    backgroundColor: audiobookColors.brand,
    '&:hover': { backgroundColor: audiobookColors.brandDark },
  },
  successOutlined: {
    borderColor: audiobookColors.successMain,
    color: audiobookColors.success,
    '&:hover': {
      borderColor: audiobookColors.success,
      backgroundColor: audiobookColors.successSoft,
    },
  },
  dangerOutlined: {
    borderColor: audiobookColorRoles.destructiveAction.main,
    color: audiobookColorRoles.destructiveAction.text,
    '&:hover': {
      borderColor: audiobookColorRoles.destructiveAction.hover,
      backgroundColor: audiobookColorRoles.destructiveAction.softBg,
    },
  },
  dangerContained: {
    backgroundColor: audiobookColorRoles.destructiveAction.main,
    '&:hover': { backgroundColor: audiobookColorRoles.destructiveAction.hover },
  },
  warningOutlined: {
    borderColor: audiobookColors.warning,
    color: audiobookColors.warning,
    '&:hover': {
      borderColor: audiobookColors.warning,
      backgroundColor: audiobookColors.warningSoft,
    },
  },
  neutralOutlined: {
    borderColor: audiobookColors.neutral,
    color: audiobookColors.neutralText,
    '&:hover': {
      borderColor: audiobookColors.neutral,
      backgroundColor: audiobookColors.neutralSoft,
    },
  },
  collectOutlined: {
    borderColor: audiobookColors.collect,
    color: audiobookColors.collect,
    '&:hover': {
      borderColor: audiobookColors.collect,
      backgroundColor: audiobookColors.collectSoft,
    },
  },
  brandIcon: {
    color: audiobookColors.brand,
    '&:hover': {
      backgroundColor: audiobookColors.brandSoft,
    },
    '&.Mui-disabled': {
      color: 'action.disabled',
    },
  },
  collectIcon: {
    color: audiobookColors.collect,
    '&:hover': {
      backgroundColor: audiobookColors.collectSoft,
    },
    '&.Mui-disabled': {
      color: 'action.disabled',
    },
  },
  neutralIcon: {
    color: audiobookColors.neutral,
    '&:hover': {
      backgroundColor: audiobookColors.neutralSoft,
    },
    '&.Mui-disabled': {
      color: 'action.disabled',
    },
  },
} as const

export const audiobookButtonRowSx = {
  centeredWrap: {
    display: 'flex',
    gap: 1.5,
    justifyContent: 'center',
    flexWrap: 'wrap',
    alignItems: 'stretch',
    mb: 3,
    '& .MuiButton-root': {
      minHeight: 40,
      minWidth: { xs: 'calc(50% - 6px)', sm: 'auto' },
      flex: { xs: '1 1 calc(50% - 6px)', sm: '0 1 auto' },
      maxWidth: { xs: '100%', sm: 'none' },
      fontSize: { xs: '0.8125rem', sm: '0.875rem' },
      lineHeight: 1.35,
      whiteSpace: 'normal',
    },
  },
  singlePrimary: {
    display: 'flex',
    gap: 2,
    justifyContent: 'center',
    '& .MuiButton-root': {
      minHeight: 42,
      minWidth: { xs: '100%', sm: 180 },
      fontSize: { xs: '0.875rem', sm: '0.9375rem' },
      lineHeight: 1.35,
    },
  },
} as const
