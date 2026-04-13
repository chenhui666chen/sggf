import { Alert, AlertTitle, Box, Chip, Stack, Typography } from '@mui/material'
import type { SxProps, Theme } from '@mui/material/styles'

import { describeTaskPointsPrecheckErrorDetail, type TaskPointsPrecheckErrorDetail } from '@/services/api'

interface TaskPointsPrecheckAlertProps {
  detail: TaskPointsPrecheckErrorDetail
  onClose?: () => void
  sx?: SxProps<Theme>
}

function formatAmount(value: number | null | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return value.toFixed(2)
}

function buildAlertTitle(detail: TaskPointsPrecheckErrorDetail): string {
  const moduleLabel = String(detail.module_label || '').trim() || '任务'
  switch (detail.failure_code) {
    case 'insufficient_available_points':
      return `${moduleLabel}积分不足`
    case 'negative_margin_blocked':
      return `${moduleLabel}被定价策略拦截`
    case 'estimate_unavailable':
      return `${moduleLabel}积分估算失败`
    default:
      return `${moduleLabel}积分预检未通过`
  }
}

function buildMetricChips(detail: TaskPointsPrecheckErrorDetail): Array<{ label: string; value: string }> {
  const chips: Array<{ label: string; value: string }> = []

  const effectiveAvailable = formatAmount(detail.effective_available_points)
  const available = formatAmount(detail.available_points)
  const requiredFrozen = formatAmount(detail.required_frozen_points)
  const additionalFrozen = formatAmount(detail.additional_frozen_points)
  const existingFrozen = formatAmount(detail.existing_frozen_points)
  const estimatedYuan = formatAmount(detail.estimated_yuan)
  const estimatedPoints = formatAmount(detail.estimated_points)
  const estimatedShotCount =
    typeof detail.estimated_shot_count === 'number' && Number.isFinite(detail.estimated_shot_count)
      ? String(Math.max(Math.round(detail.estimated_shot_count), 0))
      : null

  if (effectiveAvailable && effectiveAvailable !== available) {
    chips.push({ label: '可用（含回收）', value: `${effectiveAvailable} 积分` })
  } else if (available) {
    chips.push({ label: '当前可用', value: `${available} 积分` })
  }

  if (requiredFrozen) {
    chips.push({ label: '需冻结', value: `${requiredFrozen} 积分` })
  }
  if (additionalFrozen && additionalFrozen !== requiredFrozen) {
    chips.push({ label: '仍需补足', value: `${additionalFrozen} 积分` })
  }
  if (existingFrozen && Number(existingFrozen) > 0) {
    chips.push({ label: '已正式冻结', value: `${existingFrozen} 积分` })
  }
  if (estimatedYuan) {
    chips.push({ label: '预估成本', value: `￥${estimatedYuan}` })
  }
  if (estimatedPoints) {
    chips.push({ label: '预估积分', value: `${estimatedPoints} 积分` })
  }
  if (estimatedShotCount && Number(estimatedShotCount) > 0) {
    chips.push({ label: '预估镜头', value: `${estimatedShotCount} 个` })
  }
  if (detail.operating_snapshot?.margin_status) {
    const statusMap: Record<string, string> = {
      healthy: '健康',
      warning: '预警',
      negative: '负毛利',
    }
    const rawStatus = String(detail.operating_snapshot.margin_status || '').trim().toLowerCase()
    chips.push({ label: '毛利状态', value: statusMap[rawStatus] || rawStatus })
  }

  return chips
}

function buildRecommendation(detail: TaskPointsPrecheckErrorDetail): string | null {
  const moduleKey = String(detail.module_key || '').trim().toLowerCase()
  if (detail.failure_code === 'insufficient_available_points') {
    if (moduleKey === 'dreamweaver') {
      return '建议优先减少章节范围、切换成本模式，或先补充积分后再启动。'
    }
    if (moduleKey === 'audiobook') {
      return '建议优先减少本次生成章节、先仅生成剧本，或先补充积分后再启动。'
    }
  }
  if (detail.failure_code === 'negative_margin_blocked') {
    return '当前任务已被积分定价策略阻断，如需继续请联系管理员检查定价配置。'
  }
  return null
}

export default function TaskPointsPrecheckAlert({
  detail,
  onClose,
  sx,
}: TaskPointsPrecheckAlertProps) {
  const title = buildAlertTitle(detail)
  const message = describeTaskPointsPrecheckErrorDetail(detail) || detail.message || '积分预检未通过'
  const chips = buildMetricChips(detail)
  const recommendation = buildRecommendation(detail)
  const severity = detail.failure_code === 'negative_margin_blocked' ? 'warning' : 'error'

  return (
    <Alert severity={severity} variant="outlined" onClose={onClose} sx={sx}>
      <AlertTitle>{title}</AlertTitle>
      <Typography variant="body2" sx={{ whiteSpace: 'pre-wrap' }}>
        {message}
      </Typography>
      {chips.length > 0 && (
        <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mt: 1.5 }}>
          {chips.map((item) => (
            <Chip
              key={`${item.label}-${item.value}`}
              label={`${item.label}：${item.value}`}
              size="small"
              variant="outlined"
            />
          ))}
        </Stack>
      )}
      {recommendation && (
        <Box sx={{ mt: 1.25 }}>
          <Typography variant="caption" color="text.secondary">
            {recommendation}
          </Typography>
        </Box>
      )}
    </Alert>
  )
}
