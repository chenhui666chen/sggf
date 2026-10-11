import type { ReactNode } from 'react'
import { Box, Checkbox, FormControlLabel, FormHelperText, Stack, Typography } from '@mui/material'

import { ConsentType } from '@/constants/consent'

export interface ConsentOption {
  type: ConsentType
  /** 勾选项文案，支持传入链接等节点 */
  label: ReactNode
  required?: boolean
}

interface ConsentCheckboxesProps {
  options: ConsentOption[]
  checked: Partial<Record<ConsentType, boolean>>
  onChange: (type: ConsentType, checked: boolean) => void
  error?: string
  disabled?: boolean
}

/**
 * P2-5.2：同意勾选组件。
 *
 * 只收集用户**显式勾选**的项；未勾选的项不会出现在提交给后端的同意里，
 * 后端据此只记录真实存在的同意（不再无条件代用户同意）。
 */
export default function ConsentCheckboxes({
  options,
  checked,
  onChange,
  error,
  disabled,
}: ConsentCheckboxesProps) {
  return (
    <Stack spacing={0.25}>
      {options.map((option) => (
        <FormControlLabel
          key={option.type}
          disabled={disabled}
          sx={{ alignItems: 'flex-start', ml: 0 }}
          control={
            <Checkbox
              size="small"
              checked={Boolean(checked[option.type])}
              onChange={(event) => onChange(option.type, event.target.checked)}
              sx={{ mt: 0.5 }}
            />
          }
          label={
            <Typography variant="body2" color="text.secondary" sx={{ pt: 0.6 }}>
              {option.label}
              {option.required ? (
                <Box component="span" sx={{ color: 'error.main', ml: 0.3 }}>
                  *
                </Box>
              ) : null}
            </Typography>
          }
        />
      ))}
      {error ? <FormHelperText error>{error}</FormHelperText> : null}
    </Stack>
  )
}
