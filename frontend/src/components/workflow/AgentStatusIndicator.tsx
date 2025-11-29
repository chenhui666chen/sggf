import {
  Box,
  Typography,
  Chip,
  Tooltip,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import HourglassEmptyIcon from '@mui/icons-material/HourglassEmpty'
import PlayCircleIcon from '@mui/icons-material/PlayCircle'
import { Agent } from '@/store/slices/workflowSlice'

// Agent 功能描述映射
const agentDescriptions: Record<string, string> = {
  // 概念开发阶段
  '创意总监': '负责分析创作需求，确定整体创意方向和故事基调',
  '世界观架构师': '构建故事的世界观体系，包括时代背景、社会结构、文化特色等',
  '人物设计师': '设计角色的外貌、性格、背景故事和人物关系',
  // 结构设计阶段
  '情节架构师': '规划故事的整体结构，设计事件序列和情节走向',
  '事件验证官': '验证事件逻辑的合理性，确保情节连贯性和可信度',
  // 内容创作阶段
  '内容创作师': '根据大纲进行具体章节内容的创作',
  '文风优化师': '优化文字表达，确保语言风格统一流畅',
  // 质量评审阶段
  '质量评审官': '对初稿进行全面评审，发现问题并提出改进建议',
  // 迭代优化阶段
  '迭代协调官': '分析评审反馈、确定优化优先级、制定改进计划并协调执行',
  '内容修订师': '根据评审意见和改进计划，修订和优化章节内容',
  '最终审核官': '对修订后的内容进行最终审核，确保质量达标后输出成品',
}

interface AgentStatusIndicatorProps {
  agent: Agent
}

export default function AgentStatusIndicator({ agent }: AgentStatusIndicatorProps) {
  // 获取 Agent 功能描述
  const getAgentDescription = () => {
    return agentDescriptions[agent.name] || `${agent.name} - 智能创作助手`
  }
  const getStatusIcon = () => {
    switch (agent.status) {
      case 'completed':
        return <CheckCircleIcon sx={{ fontSize: 20, color: 'success.main' }} />
      case 'error':
        return <ErrorIcon sx={{ fontSize: 20, color: 'error.main' }} />
      case 'working':
        return <HourglassEmptyIcon sx={{ fontSize: 20, color: 'warning.main' }} />
      case 'idle':
        return <PlayCircleIcon sx={{ fontSize: 20, color: 'action.disabled' }} />
      default:
        return null
    }
  }

  const getStatusColor = () => {
    switch (agent.status) {
      case 'completed':
        return 'success'
      case 'error':
        return 'error'
      case 'working':
        return 'warning'
      case 'idle':
        return 'default'
      default:
        return 'default'
    }
  }

  const getStatusLabel = () => {
    switch (agent.status) {
      case 'completed':
        return '已完成'
      case 'error':
        return '错误'
      case 'working':
        return '工作中'
      case 'idle':
        return '就绪'
      default:
        return '未知'
    }
  }

  return (
    <Tooltip
      title={getAgentDescription()}
      placement="right"
      arrow
      enterDelay={300}
      leaveDelay={100}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          py: 0.75,
          px: 1.5,
          mb: 1,
          bgcolor: 'grey.50',
          borderRadius: 1,
          border: '1px solid',
          borderColor: 'divider',
          cursor: 'help',
          transition: 'background-color 0.2s',
          '&:hover': {
            bgcolor: 'grey.100',
          },
        }}
      >
        {/* Agent名称和图标 */}
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
          {getStatusIcon()}
          <Typography variant="body2" sx={{ fontSize: '0.875rem' }}>
            {agent.name}
          </Typography>
        </Box>

        {/* 状态标签 */}
        <Tooltip title={agent.message || getStatusLabel()}>
          <Chip
            label={getStatusLabel()}
            size="small"
            color={getStatusColor() as any}
            variant="outlined"
            sx={{ height: 20, fontSize: '0.75rem' }}
          />
        </Tooltip>
      </Box>
    </Tooltip>
  )
}

