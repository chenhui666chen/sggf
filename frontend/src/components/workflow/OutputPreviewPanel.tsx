import {
  Card,
  CardContent,
  Typography,
  Box,
  Paper,
  CircularProgress,
  Chip,
  Button,
} from '@mui/material'
import { StageType } from '@/store/slices/workflowSlice'
import FormattedContent from '../common/FormattedContent'
import { useNavigate } from 'react-router-dom'
import {
  getWorkflowPreviewEmptyMessage,
  getWorkflowPreviewLoadingLabel,
} from '@/utils/workflowPreviewMessages'
import ReviewMetaPanel, { type ReviewMeta } from './ReviewMetaPanel'

interface OutputPreviewPanelProps {
  stage: StageType
  isStreaming: boolean
  streamingStage: StageType | null
  // 各阶段的内容
  conceptContent: string
  worldContent: string
  characterContent: string
  structureContent: string
  contentDraftContent: string
  reviewReportContent: string
  finalVersionContent: string
  // 🆕 生成下一章的临时流式内容
  generateNextChapterStreamContent?: string
  isGeneratingNextChapter?: boolean
  // 🆕 新增：进度消息（如"正在迭代第1/3轮..."）
  progressMessage?: string
  // 🆕 概念开发阶段预览选择
  selectedConceptView?: 'concept' | 'world' | 'character'
  // 🆕 项目ID（用于跳转知识库）
  projectId?: string
  // 多模型评审元信息
  reviewMeta?: ReviewMeta | null
}

const stageTitles: Record<StageType, string> = {
  concept: '概念开发',
  structure: '结构设计',
  content: '章节初稿',
  review: '质量评审',
  iteration: '迭代优化',
}

export default function OutputPreviewPanel({
  stage,
  isStreaming,
  streamingStage,
  conceptContent,
  worldContent,
  characterContent,
  structureContent,
  contentDraftContent,
  reviewReportContent,
  finalVersionContent,
  generateNextChapterStreamContent = '',
  isGeneratingNextChapter = false,
  progressMessage = '',  // 🆕 新增默认值
  selectedConceptView = 'concept',  // 🆕 新增默认值
  projectId = '',  // 🆕 新增默认值
  reviewMeta = null,
}: OutputPreviewPanelProps) {
  const navigate = useNavigate()
  // 🆕 根据当前阶段和选择获取对应的内容
  const getContent = (): string => {
    if (isGeneratingNextChapter && generateNextChapterStreamContent) {
      return generateNextChapterStreamContent
    }

    switch (stage) {
      case 'concept':
        // 🆕 概念阶段：根据selectedConceptView显示对应内容
        switch (selectedConceptView) {
          case 'concept':
            return conceptContent || ''
          case 'world':
            return worldContent || ''
          case 'character':
            return characterContent || ''
          default:
            return conceptContent || ''
        }
      case 'structure':
        return structureContent || ''
      case 'content':
        return contentDraftContent || ''
      case 'review':
        return reviewReportContent || ''
      case 'iteration':
        return finalVersionContent || ''
      default:
        return ''
    }
  }

  // 🆕 获取动态标题
  const getTitle = (): string => {
    if (stage === 'concept') {
      const titles = {
        concept: '故事概念预览',
        world: '世界观预览',
        character: '人物设定预览'
      }
      return titles[selectedConceptView]
    }
    return `${stageTitles[stage]} - 输出预览`
  }

  const content = getContent()
  // 🆕 修改流式状态判断：包括生成下一章的情况
  const isCurrentStageStreaming = (isStreaming && streamingStage === stage) || isGeneratingNextChapter

  return (
    <Card sx={{ height: 'auto', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', py: 1.5, px: 2 }}>
        {/* 标题栏 - 与左侧模块标题风格一致 */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, fontSize: '0.9rem' }}>
            📄 {getTitle()}
          </Typography>
          
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
            {/* 🆕 概念阶段显示“前往知识库编辑”按钮 */}
            {stage === 'concept' && projectId && (
              <Button
                variant="outlined"
                size="small"
                onClick={() => {
                  navigate(`/knowledge-base/${projectId}`)
                }}
                sx={{
                  borderRadius: 1.5,
                  textTransform: 'none',
                  fontSize: '0.75rem',
                  px: 2,
                  height: 28,
                }}
              >
                前往知识库编辑
              </Button>
            )}
            
            {/* 流式输出状态指示器 */}
            {isCurrentStageStreaming && (
              <Chip
                icon={<CircularProgress size={12} color="inherit" />}
                label={getWorkflowPreviewLoadingLabel(stage, isGeneratingNextChapter)}
                color="primary"
                size="small"
                variant="outlined"
                sx={{ height: 24, '& .MuiChip-label': { fontSize: '0.75rem' } }}
              />
            )}
          </Box>
        </Box>

        {/* 内容区域 - 自适应填充可用空间 */}
        <Paper
          sx={{
            flex: 1,
            p: 2,
            bgcolor: 'grey.50',
            overflow: 'auto',
            minHeight: 320,
            height: 'calc(100vh - 300px)',
            maxHeight: 'calc(100vh - 300px)',
            position: 'relative',
          }}
        >
          {stage === 'review' && !isCurrentStageStreaming ? (
            <ReviewMetaPanel reviewMeta={reviewMeta} reviewText={reviewReportContent} />
          ) : null}

          {content ? (
            <FormattedContent
              content={content}
              sx={{
                fontSize: '0.9rem',
                lineHeight: 1.8,
              }}
            />
          ) : (
            <Box
              sx={{
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                height: '100%',
                color: 'text.secondary',
              }}
            >
              <Typography variant="body2">
                {isCurrentStageStreaming
                  ? getWorkflowPreviewEmptyMessage(stage, progressMessage, isGeneratingNextChapter)
                  : '暂无内容，请执行当前阶段生成内容'}
              </Typography>
            </Box>
          )}

          {/* 流式输出光标效果 */}
          {isCurrentStageStreaming && content && (
            <Box
              component="span"
              sx={{
                display: 'inline-block',
                width: 2,
                height: '1.2em',
                bgcolor: 'primary.main',
                animation: 'blink 1s step-end infinite',
                verticalAlign: 'text-bottom',
                ml: 0.5,
                '@keyframes blink': {
                  '50%': { opacity: 0 },
                },
              }}
            />
          )}
        </Paper>
      </CardContent>
    </Card>
  )
}
