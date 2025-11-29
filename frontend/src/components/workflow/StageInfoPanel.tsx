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
import { RootState } from '@/store/store'
import { StageType } from '@/store/slices/workflowSlice'

const stageInfo = {
  concept: {
    title: '概念开发阶段',
    description: '生成故事概念、世界观和人物设定',
    steps: [
      '创意总监分析创作需求',
      '世界观架构师和人物设计师协作',
      '输出完整的故事概念文档',
    ],
  },
  structure: {
    title: '结构设计阶段',
    description: '生成事件序列和情节大纲',
    steps: [
      '情节架构师生成事件序列',
      '事件验证官进行质量验证',
      '输出完整情节大纲',
    ],
  },
  content: {
    title: '内容创作阶段',
    description: '按章节进行具体内容创作',
    steps: [
      '内容创作师按章节创作',
      '文风优化确保语言统一',
      '输出章节初稿',
    ],
  },
  review: {
    title: '质量评审阶段',
    description: '对初稿进行全面评审',
    steps: [
      '质量评审官全面评审',
      '根据问题严重程度决定处理路径',
      '输出评审报告',
    ],
  },
  iteration: {
    title: '迭代优化阶段',
    description: '根据评审反馈进行内容优化和最终审核',
    steps: [
      '迭代协调官分析评审反馈，制定改进计划',
      '内容修订师执行修改，优化章节内容',
      '最终审核官审核确认，输出最终成品',
    ],
  },
}

interface StageInfoPanelProps {
  stage: StageType
}

export default function StageInfoPanel({ stage }: StageInfoPanelProps) {
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
      case 'completed': return '已完成'
      case 'error': return '错误'
      case 'active': return '进行中'
      default: return '待处理'
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
              {info.title}
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
          {info.description}
        </Typography>

        {/* 步骤列表 */}
        <Typography variant="caption" sx={{ fontWeight: 600, color: 'text.secondary', display: 'block', mb: 0.5, fontSize: '0.75rem' }}>
          📋 工作步骤
        </Typography>
        <List dense disablePadding>
          {info.steps.map((step, index) => (
            <ListItem key={index} sx={{ py: 0.25, px: 0 }}>
              <ListItemText
                primary={`${index + 1}. ${step}`}
                primaryTypographyProps={{ variant: 'body2', fontSize: '0.8rem', lineHeight: 1.4 }}
              />
            </ListItem>
          ))}
        </List>
      </CardContent>
    </Card>
  )
}

