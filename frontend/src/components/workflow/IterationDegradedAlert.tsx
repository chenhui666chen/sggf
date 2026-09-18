import { Alert, AlertTitle } from '@mui/material'
import { useTranslation } from 'react-i18next'

interface IterationDegradedAlertProps {
  /** 迭代终稿是否为「复评未达线但已交付」的降级版本 */
  degraded: boolean
  /** 降级版本的最高评分，未知时传 null */
  score?: number | null
}

/**
 * 终稿未达评分线时的提示条：结果已落库并可覆盖旧稿，但用户需要知道它没通过复评。
 */
export default function IterationDegradedAlert({ degraded, score }: IterationDegradedAlertProps) {
  const { t } = useTranslation()

  if (!degraded) {
    return null
  }

  return (
    <Alert severity="warning" sx={{ mb: 2 }}>
      <AlertTitle>{t('workflow.finalDialog.degradedTitle')}</AlertTitle>
      {score
        ? t('workflow.finalDialog.degradedDescWithScore', { score })
        : t('workflow.finalDialog.degradedDesc')}
    </Alert>
  )
}
