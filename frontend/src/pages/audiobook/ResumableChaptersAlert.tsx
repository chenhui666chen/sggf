import { useMemo, useState } from 'react'
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  List,
  ListItem,
  TextField,
  Typography,
} from '@mui/material'
import WarningIcon from '@mui/icons-material/Warning'

import { audiobookButtonSx } from './audiobookTheme'
import {
  hasRecoverableSegmentFailure,
  resolveMissingSegments,
} from './generationActionUtils'
import type { ResumableChapterEntry } from './useAudiobookResumeCheckpoints'
import type { RecoverAction } from './types'
import { apiClient } from '../../services/api'

interface ResumableChaptersAlertProps {
  entries: ResumableChapterEntry[]
  resumingChapterId: number | null
  resumeCheckpointLoading: boolean
  audiobookProjectId: number
  onResumeChapterGeneration: (chapterId: number) => void
}

const getResumableChapterLabel = (entry: ResumableChapterEntry) => {
  if (entry.chapter) {
    return `继续第${entry.chapter.chapter_number}章`
  }
  return `继续章节${entry.chapterAudio.chapter_id}`
}

const getChapterLabel = (entry: ResumableChapterEntry) => {
  if (entry.chapter) {
    return `第${entry.chapter.chapter_number}章`
  }
  return `章节${entry.chapterAudio.chapter_id}`
}

const ResumableChaptersAlert = ({
  entries,
  resumingChapterId,
  resumeCheckpointLoading,
  audiobookProjectId,
  onResumeChapterGeneration,
}: ResumableChaptersAlertProps) => {
  const [missingDialogEntry, setMissingDialogEntry] = useState<ResumableChapterEntry | null>(null)
  const [voiceDialogEntry, setVoiceDialogEntry] = useState<ResumableChapterEntry | null>(null)
  const [voiceOverrides, setVoiceOverrides] = useState<Record<string, string>>({})
  const [voiceRecoverySubmitting, setVoiceRecoverySubmitting] = useState(false)

  const segmentFailureEntries = useMemo(
    () => entries.filter((entry) => hasRecoverableSegmentFailure(entry.checkpoint)),
    [entries],
  )
  const plainEntries = useMemo(
    () => entries.filter((entry) => !hasRecoverableSegmentFailure(entry.checkpoint)),
    [entries],
  )

  const dialogMissingSegments = useMemo(
    () => resolveMissingSegments(missingDialogEntry?.checkpoint),
    [missingDialogEntry],
  )

  const handleRetryMissing = (chapterId: number) => {
    setMissingDialogEntry(null)
    onResumeChapterGeneration(chapterId)
  }

  const handleOpenVoiceDialog = (entry: ResumableChapterEntry) => {
    setMissingDialogEntry(null)
    // 提取缺失片段涉及的角色
    const segments = resolveMissingSegments(entry.checkpoint)
    const speakers = [...new Set(segments.map((s) => s.speaker).filter(Boolean))] as string[]
    const initialOverrides: Record<string, string> = {}
    speakers.forEach((speaker) => { initialOverrides[speaker] = '' })
    setVoiceOverrides(initialOverrides)
    setVoiceDialogEntry(entry)
  }

  const handleVoiceRecoverySubmit = async (action: RecoverAction) => {
    if (!voiceDialogEntry) return
    const chapterId = voiceDialogEntry.chapterAudio.chapter_id
    const overrides: Record<string, { voice_id: string }> = {}
    for (const [name, voiceId] of Object.entries(voiceOverrides)) {
      if (voiceId.trim()) {
        overrides[name] = { voice_id: voiceId.trim() }
      }
    }
    if (Object.keys(overrides).length === 0) return

    try {
      setVoiceRecoverySubmitting(true)
      await apiClient.recoverSegments(audiobookProjectId, chapterId, {
        action,
        voice_overrides: overrides,
      })
      setVoiceDialogEntry(null)
      // 触发父组件任务轮询
      onResumeChapterGeneration(chapterId)
    } catch {
      // 错误由全局拦截器处理
    } finally {
      setVoiceRecoverySubmitting(false)
    }
  }

  const voiceDialogSpeakers = useMemo(() => {
    if (!voiceDialogEntry) return []
    const segments = resolveMissingSegments(voiceDialogEntry.checkpoint)
    return [...new Set(segments.map((s) => s.speaker).filter(Boolean))] as string[]
  }, [voiceDialogEntry])

  return (
    <>
      {segmentFailureEntries.length > 0 && (
        <Alert
          severity="error"
          icon={<WarningIcon fontSize="inherit" />}
          sx={{ mb: 3, alignItems: 'flex-start' }}
        >
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {`${segmentFailureEntries.length} 个章节存在部分片段合成失败`}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                已成功片段已缓存，重试只会重新合成缺失片段，不会改变其他片段的声音。
              </Typography>
            </Box>

            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {segmentFailureEntries.slice(0, 3).map((entry) => {
                const chapterId = entry.chapterAudio.chapter_id
                const missingCount = entry.checkpoint?.failed_segment_indices?.length || 0
                return (
                  <Button
                    key={chapterId}
                    variant="outlined"
                    size="small"
                    color="error"
                    onClick={() => setMissingDialogEntry(entry)}
                    disabled={resumingChapterId !== null}
                    sx={audiobookButtonSx.dangerOutlined}
                  >
                    {`${getChapterLabel(entry)}：${missingCount} 个片段缺失`}
                  </Button>
                )
              })}
              {segmentFailureEntries.length > 3 && (
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  其余章节可在下方结果区查看
                </Typography>
              )}
              {isAnyResuming(segmentFailureEntries, resumingChapterId) && (
                <CircularProgress size={16} color="inherit" sx={{ alignSelf: 'center' }} />
              )}
            </Box>
          </Box>
        </Alert>
      )}

      {plainEntries.length > 0 && (
        <Alert
          severity="warning"
          icon={<WarningIcon fontSize="inherit" />}
          sx={{ mb: 3, alignItems: 'flex-start' }}
        >
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1.5 }}>
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                检测到 {plainEntries.length} 个章节存在可继续生成的进度
              </Typography>
              <Typography variant="caption" color="text.secondary">
                页面只负责发现入口，是否可恢复与如何入队由服务端 checkpoint 规则判定。
              </Typography>
            </Box>

            <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
              {plainEntries.slice(0, 3).map((entry) => {
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

              {plainEntries.length > 3 && (
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
      )}

      <Dialog
        open={missingDialogEntry !== null}
        onClose={() => setMissingDialogEntry(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>
          {missingDialogEntry
            ? `${getChapterLabel(missingDialogEntry)} 部分片段合成失败`
            : '部分片段合成失败'}
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            以下片段未合成成功，章节尚未混音。重试将保持原音色，仅重新合成缺失片段。
          </Typography>
          <List dense disablePadding>
            {dialogMissingSegments.map((segment) => (
              <ListItem
                key={segment.index}
                disableGutters
                sx={{ display: 'block', alignItems: 'flex-start', py: 0.75 }}
              >
                <Typography variant="caption" color="text.secondary">
                  {`片段 #${segment.index}`}
                  {segment.speaker ? ` · ${segment.speaker}` : ''}
                  {segment.voice ? ` · 音色 ${segment.voice}` : ''}
                  {segment.error_type ? ` · ${segment.error_type}` : ''}
                </Typography>
                {segment.text ? (
                  <Typography variant="body2" noWrap sx={{ maxWidth: '100%' }}>
                    {segment.text}
                  </Typography>
                ) : null}
                {segment.error_message ? (
                  <Typography variant="caption" color="text.secondary" noWrap sx={{ maxWidth: '100%' }}>
                    {segment.error_message}
                  </Typography>
                ) : null}
              </ListItem>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setMissingDialogEntry(null)} color="inherit">
            稍后处理
          </Button>
          <Button
            variant="outlined"
            color="warning"
            disabled={resumingChapterId !== null || !missingDialogEntry}
            onClick={() => missingDialogEntry && handleOpenVoiceDialog(missingDialogEntry)}
          >
            换音色重试…
          </Button>
          <Button
            variant="contained"
            color="error"
            disabled={resumingChapterId !== null || !missingDialogEntry}
            onClick={() =>
              missingDialogEntry && handleRetryMissing(missingDialogEntry.chapterAudio.chapter_id)
            }
            sx={audiobookButtonSx.brandContained}
          >
            {missingDialogEntry && resumingChapterId === missingDialogEntry.chapterAudio.chapter_id
              ? '提交中...'
              : '重试缺失片段'}
          </Button>
        </DialogActions>
      </Dialog>

      {/* 二级弹窗：换音色恢复 */}
      <Dialog
        open={voiceDialogEntry !== null}
        onClose={() => setVoiceDialogEntry(null)}
        maxWidth="sm"
        fullWidth
      >
        <DialogTitle>换音色恢复</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            为缺失片段涉及的角色指定新音色。“换音色重生成整个角色”会重新合成该角色所有片段（语义正确）；
            “仅缺失片段临时换色”只重合成失败片段（同角色可能出现两种声音）。
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {voiceDialogSpeakers.map((speaker) => (
              <TextField
                key={speaker}
                label={`${speaker} 新音色 ID`}
                size="small"
                value={voiceOverrides[speaker] || ''}
                onChange={(e) =>
                  setVoiceOverrides((prev) => ({ ...prev, [speaker]: e.target.value }))
                }
                placeholder="输入目标 voice_id"
                fullWidth
              />
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVoiceDialogEntry(null)} color="inherit">
            取消
          </Button>
          <Button
            variant="outlined"
            color="warning"
            disabled={voiceRecoverySubmitting}
            onClick={() => handleVoiceRecoverySubmit('replace_voice_missing')}
          >
            仅缺失片段临时换色
          </Button>
          <Button
            variant="contained"
            disabled={voiceRecoverySubmitting}
            onClick={() => handleVoiceRecoverySubmit('replace_voice_all')}
            sx={audiobookButtonSx.brandContained}
          >
            {voiceRecoverySubmitting ? '提交中...' : '换音色重生成整个角色'}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  )
}

const isAnyResuming = (
  entries: ResumableChapterEntry[],
  resumingChapterId: number | null,
): boolean =>
  resumingChapterId !== null &&
  entries.some((entry) => entry.chapterAudio.chapter_id === resumingChapterId)

export default ResumableChaptersAlert
