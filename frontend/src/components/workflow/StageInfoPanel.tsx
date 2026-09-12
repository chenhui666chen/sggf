import {
  Card,
  CardContent,
  Typography,
  Box,
  Chip,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import RadioButtonUncheckedIcon from '@mui/icons-material/RadioButtonUnchecked'
import { useSelector } from 'react-redux'
import { useTranslation } from 'react-i18next'
import { RootState } from '@/store/store'
import { StageType } from '@/store/slices/workflowSlice'

const stageInfo: Record<StageType, { titleKey: string; descriptionKey: string; stepKeys: string[] }> = {
  concept: {
    titleKey: 'workflow.stageInfo.conceptTitle',
    descriptionKey: 'workflow.stageInfo.conceptDescription',
    stepKeys: [
      'workflow.stageInfo.conceptStep1',
      'workflow.stageInfo.conceptStep2',
      'workflow.stageInfo.conceptStep3',
    ],
  },
  structure: {
    titleKey: 'workflow.stageInfo.structureTitle',
    descriptionKey: 'workflow.stageInfo.structureDescription',
    stepKeys: [
      'workflow.stageInfo.structureStep1',
      'workflow.stageInfo.structureStep2',
      'workflow.stageInfo.structureStep3',
    ],
  },
  content: {
    titleKey: 'workflow.stageInfo.contentTitle',
    descriptionKey: 'workflow.stageInfo.contentDescription',
    stepKeys: [
      'workflow.stageInfo.contentStep1',
      'workflow.stageInfo.contentStep2',
      'workflow.stageInfo.contentStep3',
    ],
  },
  review: {
    titleKey: 'workflow.stageInfo.reviewTitle',
    descriptionKey: 'workflow.stageInfo.reviewDescription',
    stepKeys: [
      'workflow.stageInfo.reviewStep1',
      'workflow.stageInfo.reviewStep2',
      'workflow.stageInfo.reviewStep3',
    ],
  },
  iteration: {
    titleKey: 'workflow.stageInfo.iterationTitle',
    descriptionKey: 'workflow.stageInfo.iterationDescription',
    stepKeys: [
      'workflow.stageInfo.iterationStep1',
      'workflow.stageInfo.iterationStep2',
      'workflow.stageInfo.iterationStep3',
    ],
  },
}

interface StageInfoPanelProps {
  stage: StageType
}

export default function StageInfoPanel({ stage }: StageInfoPanelProps) {
  const { t } = useTranslation()
  const workflow = useSelector((state: RootState) => state.workflow)
  const stageData = workflow.stages[stage]
  const info = stageInfo[stage]

  const getStatusIcon = () => {
    switch (stageData.status) {
      case 'completed':
        return <CheckCircleIcon sx={{ color: 'success.main' }} fontSize="small" />
      case 'error':
        return <ErrorIcon sx={{ color: 'error.main' }} fontSize="small" />
      case 'active':
        return <HourglassEmptyIcon sx={{ color: 'warning.main' }} fontSize="small" />
      default:
        return <RadioButtonUncheckedIcon sx={{ color: 'text.disabled' }} fontSize="small" />
    }
  }

  const getStatusLabel = () => {
    switch (stageData.status) {
      case 'completed': return t('workflow.stage.statusCompleted')
      case 'error': return t('workflow.stage.statusError')
      case 'active': return t('workflow.stage.statusActive')
      default: return t('workflow.stage.statusPending')
    }
  }

  const getStatusColor = () => {
    switch (stageData.status) {
      case 'completed': return 'success'
      case 'error': return 'error'
      case 'active': return 'warning'
      default: return 'default'
    }
  }

  return (
    <Card sx={{ mb: 1.5 }}>
      <CardContent sx={{ py: 1.5, px: 2, '&:last-child': { pb: 1.5 } }}>
        {/* 标题和状态 */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.75 }}>
            {getStatusIcon()}
            <Typography variant="subtitle2" sx={{ fontWeight: 600, fontSize: '0.85rem' }}>
              {t(info.titleKey)}
            </Typography>
          </Box>
          <Chip
            label={getStatusLabel()}
            color={getStatusColor() as any}
            size="small"
            variant="outlined"
            sx={{ height: 22, '& .MuiChip-label': { fontSize: '0.7rem', px: 1 } }}
          />
        </Box>

        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5, lineHeight: 1.5, fontSize: '0.8rem' }}>
          {t(info.descriptionKey)}
        </Typography>

        {/* 步骤列表 */}
        <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', display: 'block', mb: 0.5, fontSize: '0.75rem' }}>
          📋 {t('workflow.stageInfo.workSteps')}
        </Typography>
        <List dense disablePadding>
          {info.stepKeys.map((stepKey, index) => (
            <ListItem key={index} sx={{ py: 0.25, px: 0 }}>
              <ListItemText
                primary={`${index + 1}. ${t(stepKey)}`}
                primaryTypographyProps={{ variant: 'body2', fontSize: '0.8rem', lineHeight: 1.4 }}
              />
            </ListItem>
          ))}
        </List>
      </CardContent>
    </Card>
  )
}

