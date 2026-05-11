import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Typography,
} from '@mui/material'
import WarningIcon from '@mui/icons-material/Warning'

import { audiobookButtonSx } from './audiobookTheme'
import type { ResumableChapterEntry } from './useAudiobookResumeCheckpoints'

interface ResumableChaptersAlertProps {
  entries: ResumableChapterEntry[]
  resumingChapterId: number | null
  resumeCheckpointLoading: boolean
  onResumeChapterGeneration: (chapterId: number) => void
}

const getResumableChapterLabel = (entry: ResumableChapterEntry) => {
  if (entry.chapter) {
    return `继续第${entry.chapter.chapter_number}章`
  }
  return `继续章节${entry.chapterAudio.chapter_id}`
}

const ResumableChaptersAlert = ({
  entries,
  resumingChapterId,
  resumeCheckpointLoading,
  onResumeChapterGeneration,
}: ResumableChaptersAlertProps) => (
  <Alert
    severity="warning"
    icon={<WarningIcon fontSize="inherit" />}
    sx={{ mb: 3, alignItems: 'flex-start' }}
  >
    <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
      <Box>
        <Typography variant="body2" sx={{ fontWeight: 600 }}>
          检测到 {entries.length} 个章节存在可继续生成的进度
        </Typography>
        <Typography variant="caption" color="text.secondary">
          页面只负责发现入口，是否可恢复与如何入队由服务端 checkpoint 规则判定。
        </Typography>
      </Box>

      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        {entries.slice(0, 3).map((entry) => {
          const chapterId = entry.chapterAudio.chapter_id
          const isResuming = resumingChapterId === chapterId

          return (
            <Button
              key={chapterId}
              variant="outlined"
              size="small"
              onClick={() => onResumeChapterGeneration(chapterId)}
              disabled={resumingChapterId !== null}
              startIcon={
                isResuming
                  ? <CircularProgress size={14} color="inherit" />
                  : undefined
              }
              sx={audiobookButtonSx.warningOutlined}
            >
              {isResuming ? '提交中...' : getResumableChapterLabel(entry)}
            </Button>
          )
        })}

        {entries.length > 3 && (
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
            其余章节可在下方结果区继续生成
          </Typography>
        )}

        {resumeCheckpointLoading && (
          <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
            正在同步最新断点信息...
          </Typography>
        )}
      </Box>
    </Box>
  </Alert>
)

export default ResumableChaptersAlert
