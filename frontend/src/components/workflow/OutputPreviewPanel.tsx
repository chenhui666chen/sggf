import {
  Card,
  CardContent,
  Typography,
  Box,
  Paper,
  CircularProgress,
  Chip,
} from '@mui/material'
import { StageType } from '@/store/slices/workflowSlice'
import FormattedContent from '../common/FormattedContent'

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
}: OutputPreviewPanelProps) {
  // 根据当前阶段获取对应的内容
  const getContent = (): string => {
    // 🆕 调试日志
    console.log(`🖥️ OutputPreviewPanel: stage=${stage}, isGeneratingNextChapter=${isGeneratingNextChapter}, streamLen=${generateNextChapterStreamContent?.length || 0}`)

    // 🆕 如果正在生成下一章，优先显示临时流式内容（结构设计阶段除外，只在有新内容时才显示）
    if (isGeneratingNextChapter && generateNextChapterStreamContent) {
      // 对于结构设计阶段，不覆盖原有内容（项目结构设计），只显示临时流式内容
      // 其他阶段直接显示临时流式内容
      console.log(`✅ 显示临时流式内容，长度=${generateNextChapterStreamContent.length}`)
      return generateNextChapterStreamContent
    }

    switch (stage) {
      case 'concept':
        // 概念阶段：合并故事概念、世界观、人物设定
        const parts = []
        if (conceptContent) parts.push(`## 故事概念\n${conceptContent}`)
        if (worldContent) parts.push(`## 世界观设定\n${worldContent}`)
        if (characterContent) parts.push(`## 人物设定\n${characterContent}`)
        return parts.join('\n\n')
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

  const content = getContent()
  // 🆕 修改流式状态判断：包括生成下一章的情况
  const isCurrentStageStreaming = (isStreaming && streamingStage === stage) || isGeneratingNextChapter

  return (
    <Card sx={{ height: 'auto', display: 'flex', flexDirection: 'column' }}>
      <CardContent sx={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden', py: 1.5, px: 2 }}>
        {/* 标题栏 - 与左侧模块标题风格一致 */}
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1.5 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 600, fontSize: '0.9rem' }}>
            📄 {stageTitles[stage]} - 输出预览
          </Typography>
          {isCurrentStageStreaming && (
            <Chip
              icon={<CircularProgress size={12} color="inherit" />}
              label="正在生成..."
              color="primary"
              size="small"
              variant="outlined"
              sx={{ height: 24, '& .MuiChip-label': { fontSize: '0.75rem' } }}
            />
          )}
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
                  ? '等待内容生成...'
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

