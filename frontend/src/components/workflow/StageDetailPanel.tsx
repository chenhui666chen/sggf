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
import { RootState } from '@/store/store'
import { StageType } from '@/store/slices/workflowSlice'
import FormattedContent from '../common/FormattedContent'

const stageDescriptions = {
  concept: {
    title: '概念开发阶段',
    description: '创意总监、世界观架构师和人物设计师协作，生成完整的故事概念。',
    steps: [
      '创意总监接收用户输入，分析创作需求',
      '并行调用世界观架构师和人物设计师',
      '三方进行"概念整合会议"，确保世界观与人物设定协调',
      '输出完整的故事概念文档',
    ],
  },
  structure: {
    title: '结构设计阶段',
    description: '情节架构师基于故事概念生成事件序列，并进行质量验证。',
    steps: [
      '创意总监将故事概念传递给情节架构师',
      '情节架构师启动EventSeed生成事件序列',
      'EventValidator对生成内容进行质量验证',
      '通过评审后输出完整情节大纲',
    ],
  },
  content: {
    title: '内容创作阶段',
    description: '内容创作师按章节进行具体内容创作，并进行文风优化。',
    steps: [
      '创意总监基于情节大纲制定章节创作计划',
      '内容创作师按章节进行具体内容创作',
      '同时进行文风优化，确保语言风格统一',
      '输出章节初稿',
    ],
  },
  review: {
    title: '质量评审阶段',
    description: '质量评审官对初稿进行全面评审，决定处理路径。',
    steps: [
      '质量评审官对初稿进行全面评审',
      '根据问题严重程度决定处理路径',
      '小问题：直接由内容创作师修改',
      '重大问题：回溯到相关设计Agent重新调整',
    ],
  },
  iteration: {
    title: '迭代优化阶段',
    description: '根据评审反馈进行问题分类和修改，确保最终质量。',
    steps: [
      '创意总监对评审反馈进行问题分类',
      '分类问题分配给相应Agent修改',
      '修改内容由质量评审官复核',
      '通过评审后输出最终成品',
    ],
  },
}

interface StageDetailPanelProps {
  stage: StageType
}

export default function StageDetailPanel({ stage }: StageDetailPanelProps) {
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
        return '已完成'
      case 'error':
        return '错误'
      case 'active':
        return '进行中'
      case 'pending':
        return '待处理'
      default:
        return '未知'
    }
  }

  return (
    <Card>
      <CardContent>
        {/* 标题和状态 */}
        <Box sx={{ display: 'flex', alignItems: 'center', mb: 2 }}>
          {getStatusIcon()}
          <Box sx={{ flex: 1 }}>
            <Typography variant="h6">{description.title}</Typography>
            <Typography variant="body2" color="textSecondary">
              {description.description}
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
            📋 工作步骤
          </Typography>
          <List dense>
            {description.steps.map((step, index) => (
              <ListItem key={index} sx={{ py: 0.5 }}>
                <ListItemText
                  primary={`${index + 1}. ${step}`}
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
              📄 输出预览
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
              ⚠️ 错误信息
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