import {
  Card,
  CardContent,
  Typography,
  Box,
  Chip,
  Divider,
  Paper,
  List,
  ListItem,
  ListItemText,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import { useSelector } from 'react-redux'
import { useTranslation } from 'react-i18next'
import { RootState } from '@/store/store'
import { StageType } from '@/store/slices/workflowSlice'
import FormattedContent from '../common/FormattedContent'

const stageDescriptions: Record<StageType, { titleKey: string; descriptionKey: string; stepKeys: string[] }> = {
  concept: {
    titleKey: 'workflow.stageDetail.conceptTitle',
    descriptionKey: 'workflow.stageDetail.conceptDescription',
    stepKeys: [
      'workflow.stageDetail.conceptStep1',
      'workflow.stageDetail.conceptStep2',
      'workflow.stageDetail.conceptStep3',
      'workflow.stageDetail.conceptStep4',
    ],
  },
  structure: {
    titleKey: 'workflow.stageDetail.structureTitle',
    descriptionKey: 'workflow.stageDetail.structureDescription',
    stepKeys: [
      'workflow.stageDetail.structureStep1',
      'workflow.stageDetail.structureStep2',
      'workflow.stageDetail.structureStep3',
      'workflow.stageDetail.structureStep4',
    ],
  },
  content: {
    titleKey: 'workflow.stageDetail.contentTitle',
    descriptionKey: 'workflow.stageDetail.contentDescription',
    stepKeys: [
      'workflow.stageDetail.contentStep1',
      'workflow.stageDetail.contentStep2',
      'workflow.stageDetail.contentStep3',
      'workflow.stageDetail.contentStep4',
    ],
  },
  review: {
    titleKey: 'workflow.stageDetail.reviewTitle',
    descriptionKey: 'workflow.stageDetail.reviewDescription',
    stepKeys: [
      'workflow.stageDetail.reviewStep1',
      'workflow.stageDetail.reviewStep2',
      'workflow.stageDetail.reviewStep3',
      'workflow.stageDetail.reviewStep4',
    ],
  },
  iteration: {
    titleKey: 'workflow.stageDetail.iterationTitle',
    descriptionKey: 'workflow.stageDetail.iterationDescription',
    stepKeys: [
      'workflow.stageDetail.iterationStep1',
      'workflow.stageDetail.iterationStep2',
      'workflow.stageDetail.iterationStep3',
      'workflow.stageDetail.iterationStep4',
    ],
  },
}

interface StageDetailPanelProps {
  stage: StageType
}

export default function StageDetailPanel({ stage }: StageDetailPanelProps) {
  const { t } = useTranslation()
  const workflow = useSelector((state: RootState) => state.workflow)
  const stageData = workflow.stages[stage]
  const description = stageDescriptions[stage]

  // 处理显示内容，添加适当的排版
  const displayContent = stageData.output
  const formatContent = (content: any) => {
    if (!content) return ''
    
    // 如果是字符串，直接返回
    if (typeof content === 'string') {
      return content
    }
    
    // 如果是对象，尝试格式化
    if (typeof content === 'object') {
      // 如果有特定的字段，优先显示这些字段
      if (content.concept) return content.concept
      if (content.worldview || content.world_setting) return content.worldview || content.world_setting
      if (content.characters) return content.characters
      if (content.plot_outline) return content.plot_outline
      if (content.content || content.chapters) return content.content || content.chapters
      if (content.review) return content.review
      if (content.revised_content || content.final_review) return content.revised_content || content.final_review
      
      // 否则返回格式化的JSON
      return JSON.stringify(content, null, 2)
    }
    
    return String(content)
  }

  const getStatusIcon = () => {
    switch (stageData.status) {
      case 'completed':
        return <CheckCircleIcon sx={{ color: 'success.main', mr: 1 }} />
      case 'error':
        return <ErrorIcon sx={{ color: 'error.main', mr: 1 }} />
      case 'active':
        return <HourglassEmptyIcon sx={{ color: 'warning.main', mr: 1 }} />
      default:
        return null
    }
  }

  const getStatusColor = () => {
    switch (stageData.status) {
      case 'completed':
        return 'success'
      case 'error':
        return 'error'
      case 'active':
        return 'warning'
      default:
        return 'default'
    }
  }

  const getStatusLabel = () => {
    switch (stageData.status) {
      case 'completed':
        return t('workflow.stage.statusCompleted')
      case 'error':
        return t('workflow.stage.statusError')
      case 'active':
        return t('workflow.stage.statusActive')
      case 'pending':
        return t('workflow.stage.statusPending')
      default:
        return t('workflow.stage.statusUnknown')
    }
  }

  return (
    <Card>
      <CardContent>
        {/* 标题和状态 */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
          {getStatusIcon()}
          <Box sx={{ flex: 1 }}>
            <Typography variant="h6">{t(description.titleKey)}</Typography>
            <Typography variant="body2" color="textSecondary">
              {t(description.descriptionKey)}
            </Typography>
          </Box>
          <Chip
            label={getStatusLabel()}
            color={getStatusColor() as any}
            variant="outlined"
          />
        </Box>

        <Divider sx={{ my: 2 }} />

        {/* 步骤列表 */}
        <Box sx={{ mb: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
            📋 {t('workflow.stageDetail.workSteps')}
          </Typography>
          <List dense>
            {description.stepKeys.map((stepKey, index) => (
              <ListItem key={index} sx={{ py: 0.5 }}>
                <ListItemText
                  primary={`${index + 1}. ${t(stepKey)}`}
                  primaryTypographyProps={{ variant: 'body2' }}
                />
              </ListItem>
            ))}
          </List>
        </Box>

        {/* 输出预览 */}
        {displayContent && (
          <Box>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600 }}>
              📄 {t('workflow.stageDetail.outputPreview')}
            </Typography>
            <Paper
              sx={{
                p: 2,
                bgcolor: 'grey.50',
                maxHeight: 400,
                overflow: 'auto',
              }}
            >
              <FormattedContent
                content={formatContent(displayContent)}
                sx={{
                  fontSize: '0.875rem',
                }}
              />
            </Paper>
          </Box>
        )}

        {/* 错误信息 */}
        {stageData.error && (
          <Box sx={{ mt: 2 }}>
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 600, color: 'error.main' }}>
              ⚠️ {t('workflow.stageDetail.errorInfo')}
            </Typography>
            <Paper sx={{ p: 2, bgcolor: 'error.light' }}>
              <Typography variant="body2" color="error">
                {stageData.error}
              </Typography>
            </Paper>
          </Box>
        )}
      </CardContent>
    </Card>
  )
}