import { Alert, AlertTitle, Box, Chip, Stack, Typography } from '@mui/material'
import type { SxProps, Theme } from '@mui/material/styles'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'

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

// value 为后端 margin_status 代码（与后端返回值比对不可翻译），label 值为 i18n key
const MARGIN_STATUS_LABEL_KEYS: Record<string, string> = {
  healthy: 'taskPointsPrecheck.marginHealthy',
  warning: 'taskPointsPrecheck.marginWarning',
  negative: 'taskPointsPrecheck.marginNegative',
}

function buildAlertTitle(detail: TaskPointsPrecheckErrorDetail, t?: TFunction): string {
  const moduleLabel = String(detail.module_label || '').trim() || (t ? t('taskPointsPrecheck.moduleFallback') : '任务')
  switch (detail.failure_code) {
    case 'insufficient_available_points':
      return t ? t('taskPointsPrecheck.titleInsufficient', { module: moduleLabel }) : `${moduleLabel}积分不足`
    case 'negative_margin_blocked':
      return t ? t('taskPointsPrecheck.titleNegativeMargin', { module: moduleLabel }) : `${moduleLabel}被定价策略拦截`
    case 'estimate_unavailable':
      return t ? t('taskPointsPrecheck.titleEstimateUnavailable', { module: moduleLabel }) : `${moduleLabel}积分估算失败`
    default:
      return t ? t('taskPointsPrecheck.titleDefault', { module: moduleLabel }) : `${moduleLabel}积分预检未通过`
  }
}

function buildMetricChips(detail: TaskPointsPrecheckErrorDetail, t?: TFunction): Array<{ label: string; value: string }> {
  const chips: Array<{ label: string; value: string }> = []

  const tr = (key: string, fallback: string, params?: Record<string, unknown>) =>
    t ? t(key, params) : fallback

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
    chips.push({ label: tr('taskPointsPrecheck.metricAvailableWithRecycled', '可用（含回收）'), value: tr('taskPointsPrecheck.valuePoints', `${effectiveAvailable} 积分`, { amount: effectiveAvailable }) })
  } else if (available) {
    chips.push({ label: tr('taskPointsPrecheck.metricCurrentAvailable', '当前可用'), value: tr('taskPointsPrecheck.valuePoints', `${available} 积分`, { amount: available }) })
  }

  if (requiredFrozen) {
    chips.push({ label: tr('taskPointsPrecheck.metricRequiredFrozen', '需冻结'), value: tr('taskPointsPrecheck.valuePoints', `${requiredFrozen} 积分`, { amount: requiredFrozen }) })
  }
  if (additionalFrozen && additionalFrozen !== requiredFrozen) {
    chips.push({ label: tr('taskPointsPrecheck.metricAdditionalFrozen', '仍需补足'), value: tr('taskPointsPrecheck.valuePoints', `${additionalFrozen} 积分`, { amount: additionalFrozen }) })
  }
  if (existingFrozen && Number(existingFrozen) > 0) {
    chips.push({ label: tr('taskPointsPrecheck.metricExistingFrozen', '已正式冻结'), value: tr('taskPointsPrecheck.valuePoints', `${existingFrozen} 积分`, { amount: existingFrozen }) })
  }
  if (estimatedYuan) {
    chips.push({ label: tr('taskPointsPrecheck.metricEstimatedCost', '预估成本'), value: tr('taskPointsPrecheck.valueYuan', `￥${estimatedYuan}`, { amount: estimatedYuan }) })
  }
  if (estimatedPoints) {
    chips.push({ label: tr('taskPointsPrecheck.metricEstimatedPoints', '预估积分'), value: tr('taskPointsPrecheck.valuePoints', `${estimatedPoints} 积分`, { amount: estimatedPoints }) })
  }
  if (estimatedShotCount && Number(estimatedShotCount) > 0) {
    chips.push({ label: tr('taskPointsPrecheck.metricEstimatedShots', '预估镜头'), value: tr('taskPointsPrecheck.valueShots', `${estimatedShotCount} 个`, { count: estimatedShotCount }) })
  }
  if (detail.operating_snapshot?.margin_status) {
    const rawStatus = String(detail.operating_snapshot.margin_status || '').trim().toLowerCase()
    const statusKey = MARGIN_STATUS_LABEL_KEYS[rawStatus]
    chips.push({ label: tr('taskPointsPrecheck.metricMarginStatus', '毛利状态'), value: statusKey ? tr(statusKey, rawStatus) : rawStatus })
  }

  return chips
}

function buildRecommendation(detail: TaskPointsPrecheckErrorDetail, t?: TFunction): string | null {
  const moduleKey = String(detail.module_key || '').trim().toLowerCase()
  if (detail.failure_code === 'insufficient_available_points') {
    if (moduleKey === 'dreamweaver') {
      return t ? t('taskPointsPrecheck.recDreamweaver') : '建议优先减少章节范围、切换成本模式，或先补充积分后再启动。'
    }
    if (moduleKey === 'audiobook') {
      return t ? t('taskPointsPrecheck.recAudiobook') : '建议优先减少本次生成章节、先仅生成剧本，或先补充积分后再启动。'
    }
  }
  if (detail.failure_code === 'negative_margin_blocked') {
    return t ? t('taskPointsPrecheck.recNegativeMargin') : '当前任务已被积分定价策略阻断，如需继续请联系管理员检查定价配置。'
  }
  return null
}

export default function TaskPointsPrecheckAlert({
  detail,
  onClose,
  sx,
}: TaskPointsPrecheckAlertProps) {
  const { t } = useTranslation()
  const title = buildAlertTitle(detail, t)
  const message = describeTaskPointsPrecheckErrorDetail(detail) || detail.message || t('taskPointsPrecheck.fallbackMessage')
  const chips = buildMetricChips(detail, t)
  const recommendation = buildRecommendation(detail, t)
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
