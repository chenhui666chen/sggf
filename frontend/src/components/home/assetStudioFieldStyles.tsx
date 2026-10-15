// 资产工作台（常暗画布）的字段样式单一事实源：
// 工作台页与视觉识别页共用同一套控件表面、卡片底、菜单与输入组件包装，
// 避免出现第二份手写描边/底色而在浅色主题下漏色。
import {
  FormHelperText as MuiFormHelperText,
  InputLabel as MuiInputLabel,
  Select as MuiSelect,
  TextField as MuiTextField,
} from '@mui/material'
import type { FormHelperTextProps, InputLabelProps, SelectProps, SxProps, TextFieldProps, Theme } from '@mui/material'
import type { SystemStyleObject } from '@mui/system'

// 工作台是常暗画布：控件表面必须钉白叠色，否则主题的浅色 borderStrong
// 会穿透到深色面板上（实测下拉与文本框曾因此圆角、边框、高度三处不一致）。
const WORKBENCH_FIELD_COLORS = {
  text: 'white',
  surface: 'rgba(255,255,255,0.045)',
  surfaceHover: 'rgba(255,255,255,0.07)',
  surfaceFocus: 'rgba(255,255,255,0.08)',
  surfaceDisabled: 'rgba(255,255,255,0.05)',
  border: 'rgba(255,255,255,0.14)',
  borderHover: 'rgba(167,186,255,0.3)',
  borderFocus: 'rgba(139,161,255,0.68)',
  label: 'rgba(255,255,255,0.68)',
  labelFilled: 'rgba(255,255,255,0.72)',
  labelFocused: 'rgba(214,224,255,0.92)',
  helper: 'rgba(255,255,255,0.6)',
  icon: 'rgba(255,255,255,0.76)',
  divider: 'rgba(255,255,255,0.3)',
} as const

/** 作用在输入框根元素本身（Select 的 sx 落点）上的表面样式。 */
const WORKBENCH_INPUT_SURFACE_SX: SystemStyleObject<Theme> = {
  color: WORKBENCH_FIELD_COLORS.text,
  borderRadius: 1.5,
  backgroundColor: WORKBENCH_FIELD_COLORS.surface,
  backdropFilter: 'blur(10px)',
  // 主题的 hover/focused/disabled 底色是浅色 token，必须逐态钉住，
  // 否则悬停与"智能时长"禁用态会把米色底 leak 进深色面板。
  '&:hover': {
    backgroundColor: WORKBENCH_FIELD_COLORS.surfaceHover,
  },
  '&.Mui-focused': {
    backgroundColor: WORKBENCH_FIELD_COLORS.surfaceFocus,
  },
  '&.Mui-disabled': {
    backgroundColor: WORKBENCH_FIELD_COLORS.surfaceDisabled,
  },
  // 单行控件统一基线：Select 内层是 div，会被行高撑到 21.56px；普通输入框是
  // 替换元素，行高不撑盒、只按 min-height 取 20.125px，实测同排差 1.43px。
  // 两者 font-size 完全一致，所以把 Select 内层行高压到同一个 min-height。
  '& .MuiSelect-select': {
    minHeight: '1.4375em',
    lineHeight: '1.4375em',
  },
  // 描边用 notchedOutline 类名而不是 fieldset 标签：MUI 的聚焦规则是
  // ".MuiOutlinedInput-root.Mui-focused .MuiOutlinedInput-notchedOutline"（3 个类），
  // 标签选择器权重只有 (0,2,1) 会被压过去，实测聚焦描边漏成浅色主题的金棕色。
  '& .MuiOutlinedInput-notchedOutline': {
    borderColor: WORKBENCH_FIELD_COLORS.border,
  },
  '&:hover .MuiOutlinedInput-notchedOutline': {
    borderColor: WORKBENCH_FIELD_COLORS.borderHover,
  },
  '&.Mui-focused .MuiOutlinedInput-notchedOutline': {
    borderColor: WORKBENCH_FIELD_COLORS.borderFocus,
  },
  '& .MuiSelect-icon': {
    color: WORKBENCH_FIELD_COLORS.icon,
  },
}

/** 作用在 FormControl 根元素（TextField、对话框字段的 sx 落点）上的同一套表面。 */
const WORKBENCH_TEXTFIELD_SX: SxProps<Theme> = {
  '& .MuiInputBase-root': WORKBENCH_INPUT_SURFACE_SX,
  '& .MuiInputLabel-root': {
    color: WORKBENCH_FIELD_COLORS.label,
    // filled 先、focused 后：两个类会同时命中（已填写且聚焦），聚焦高亮必须赢。
    '&.MuiFormLabel-filled': {
      color: WORKBENCH_FIELD_COLORS.labelFilled,
    },
    '&.Mui-focused': {
      color: WORKBENCH_FIELD_COLORS.labelFocused,
    },
  },
  '& .MuiFormHelperText-root': {
    color: WORKBENCH_FIELD_COLORS.helper,
  },
}

const WORKBENCH_SELECT_SX: SxProps<Theme> = WORKBENCH_INPUT_SURFACE_SX

const WORKBENCH_INPUT_LABEL_SX: SxProps<Theme> = {
  color: WORKBENCH_FIELD_COLORS.label,
  '&.MuiFormLabel-filled': {
    color: WORKBENCH_FIELD_COLORS.labelFilled,
  },
  '&.Mui-focused': {
    color: WORKBENCH_FIELD_COLORS.labelFocused,
  },
}

const WORKBENCH_HELPER_SX: SxProps<Theme> = {
  color: WORKBENCH_FIELD_COLORS.helper,
  mx: 0,
  mt: 1,
  fontSize: '0.82rem',
  lineHeight: 1.6,
}

const WORKBENCH_NEUTRAL_CHIP_SX: SxProps<Theme> = {
  color: WORKBENCH_FIELD_COLORS.text,
  borderColor: 'rgba(255,255,255,0.16)',
  backgroundColor: 'rgba(255,255,255,0.06)',
}

/** 页面里所有"参数分组卡片"的同一层底。 */
const WORKBENCH_CARD_BASE_SX = {
  borderRadius: 3,
  border: '1px solid rgba(255,255,255,0.1)',
  backgroundColor: 'rgba(255,255,255,0.03)',
} as const

const WORKBENCH_INNER_CARD_SX: SxProps<Theme> = { p: 2, ...WORKBENCH_CARD_BASE_SX }

const WORKBENCH_COMPACT_CARD_SX: SxProps<Theme> = { p: 1.5, ...WORKBENCH_CARD_BASE_SX }

/** 底部参数条里的单个下拉宽度。 */
const WORKBENCH_PARAM_CONTROL_SX: SxProps<Theme> = {
  minWidth: 150,
}

/** 面板里的补充说明文字。 */
const WORKBENCH_HINT_SX: SxProps<Theme> = {
  color: 'rgba(255,255,255,0.58)',
  fontSize: '0.82rem',
  lineHeight: 1.7,
}

const WORKBENCH_MENU_DIVIDER_ITEM_SX: SxProps<Theme> = {
  color: WORKBENCH_FIELD_COLORS.divider,
  fontWeight: 600,
  textAlign: 'center',
  fontSize: '0.78rem',
}

/** 模型下拉里"仅编辑能力"分组用的占位项，不参与取值。 */
const MODEL_SELECT_DIVIDER_VALUE = '---divider---'

const WORKBENCH_MENU_PAPER_SX: SxProps<Theme> = {
  mt: 1,
  color: 'white',
  borderRadius: 2.5,
  border: '1px solid rgba(255,255,255,0.12)',
  background: 'linear-gradient(180deg, rgba(53,58,92,0.94) 0%, rgba(18,21,33,0.96) 100%)',
  boxShadow: '0 20px 40px rgba(8,10,18,0.42)',
  backdropFilter: 'blur(18px)',
  '& .MuiMenuItem-root': {
    minHeight: 40,
    color: 'rgba(255,255,255,0.92)',
    transition: 'background-color 0.18s ease, color 0.18s ease',
  },
  '& .MuiMenuItem-root:hover': {
    backgroundColor: 'rgba(255,255,255,0.08)',
  },
  '& .MuiMenuItem-root.Mui-selected': {
    backgroundColor: 'rgba(126,146,255,0.22)',
  },
  '& .MuiMenuItem-root.Mui-selected:hover': {
    backgroundColor: 'rgba(126,146,255,0.28)',
  },
}

const WORKBENCH_MENU_PROPS: SelectProps<string>['MenuProps'] = {
  PaperProps: {
    elevation: 0,
    sx: WORKBENCH_MENU_PAPER_SX,
  },
  MenuListProps: {
    sx: {
      py: 0.5,
    },
  },
}

const WORKBENCH_DIALOG_PAPER_SX: SxProps<Theme> = {
  color: 'white',
  borderRadius: 4,
  border: '1px solid rgba(255,255,255,0.12)',
  background: 'linear-gradient(180deg, rgba(26,30,46,0.98) 0%, rgba(12,15,24,0.98) 100%)',
  boxShadow: '0 28px 80px rgba(2,6,16,0.52)',
  backdropFilter: 'blur(18px)',
}

const WORKBENCH_DIALOG_BACKDROP_SX: SxProps<Theme> = {
  backgroundColor: 'rgba(5,8,16,0.76)',
  backdropFilter: 'blur(10px)',
}

const WORKBENCH_DIALOG_TITLE_SX: SxProps<Theme> = {
  px: 3,
  py: 2.25,
  color: 'white',
  fontSize: '1.85rem',
  fontWeight: 700,
  borderBottom: '1px solid rgba(255,255,255,0.08)',
}

const WORKBENCH_DIALOG_CONTENT_SX: SxProps<Theme> = {
  px: 3,
  py: 2.5,
  borderColor: 'rgba(255,255,255,0.08)',
}

const WORKBENCH_DIALOG_ACTIONS_SX: SxProps<Theme> = {
  px: 3,
  py: 2,
  gap: 1,
  borderTop: '1px solid rgba(255,255,255,0.08)',
}

const WORKBENCH_DIALOG_INFO_ALERT_SX: SxProps<Theme> = {
  borderRadius: 2.5,
  color: 'rgba(224,236,255,0.96)',
  backgroundColor: 'rgba(74,115,255,0.14)',
  border: '1px solid rgba(121,149,255,0.24)',
  '& .MuiAlert-icon': {
    color: '#9db4ff',
  },
}

const WORKBENCH_DIALOG_FIELD_SX: SxProps<Theme> = WORKBENCH_TEXTFIELD_SX

const WORKBENCH_SUBTLE_ACTION_BUTTON_SX: SxProps<Theme> = {
  minHeight: 38,
  px: 1.25,
  color: 'rgba(235,241,255,0.92)',
  borderColor: 'rgba(255,255,255,0.12)',
  backgroundColor: 'rgba(255,255,255,0.03)',
  whiteSpace: 'nowrap',
  '&:hover': {
    borderColor: 'rgba(138,158,255,0.36)',
    backgroundColor: 'rgba(138,158,255,0.08)',
  },
  '&.Mui-disabled': {
    color: 'rgba(255,255,255,0.28)',
    borderColor: 'rgba(255,255,255,0.08)',
    backgroundColor: 'rgba(255,255,255,0.02)',
  },
}

function mergeSx(base: SxProps<Theme>, sx?: SxProps<Theme>): SxProps<Theme> {
  if (!sx) {
    return base
  }

  const merged = Array.isArray(sx) ? [base, ...sx] : [base, sx]
  return merged as SxProps<Theme>
}

function InputLabel(props: InputLabelProps) {
  return <MuiInputLabel {...props} sx={mergeSx(WORKBENCH_INPUT_LABEL_SX, props.sx)} />
}

function Select<T extends string = string>(props: SelectProps<T>) {
  const { sx, ...restProps } = props

  return <MuiSelect {...restProps} MenuProps={WORKBENCH_MENU_PROPS} sx={mergeSx(WORKBENCH_SELECT_SX, sx)} />
}

function TextField(props: TextFieldProps) {
  const { sx, ...restProps } = props

  return (
    <MuiTextField
      {...restProps}
      variant="outlined"
      size={props.size || 'small'}
      sx={mergeSx(WORKBENCH_TEXTFIELD_SX, sx)}
    />
  )
}

function FormHelperText(props: FormHelperTextProps) {
  const { sx, ...restProps } = props

  return <MuiFormHelperText {...restProps} sx={mergeSx(WORKBENCH_HELPER_SX, sx)} />
}

export {
  FormHelperText,
  InputLabel,
  MODEL_SELECT_DIVIDER_VALUE,
  Select,
  TextField,
  WORKBENCH_CARD_BASE_SX,
  WORKBENCH_COMPACT_CARD_SX,
  WORKBENCH_DIALOG_ACTIONS_SX,
  WORKBENCH_DIALOG_BACKDROP_SX,
  WORKBENCH_DIALOG_CONTENT_SX,
  WORKBENCH_DIALOG_FIELD_SX,
  WORKBENCH_DIALOG_INFO_ALERT_SX,
  WORKBENCH_DIALOG_PAPER_SX,
  WORKBENCH_DIALOG_TITLE_SX,
  WORKBENCH_FIELD_COLORS,
  WORKBENCH_HELPER_SX,
  WORKBENCH_HINT_SX,
  WORKBENCH_INPUT_LABEL_SX,
  WORKBENCH_INPUT_SURFACE_SX,
  WORKBENCH_INNER_CARD_SX,
  WORKBENCH_MENU_DIVIDER_ITEM_SX,
  WORKBENCH_MENU_PROPS,
  WORKBENCH_NEUTRAL_CHIP_SX,
  WORKBENCH_PARAM_CONTROL_SX,
  WORKBENCH_SELECT_SX,
  WORKBENCH_SUBTLE_ACTION_BUTTON_SX,
  WORKBENCH_TEXTFIELD_SX,
  mergeSx,
}
