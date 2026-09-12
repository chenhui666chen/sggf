import { useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
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

const getResumableChapterLabel = (entry: ResumableChapterEntry, t: TFunction) => {
  if (entry.chapter) {
    return t('audiobook.resumableChaptersAlert.resumeChapterLabel', {
      number: entry.chapter.chapter_number,
    })
  }
  return t('audiobook.resumableChaptersAlert.resumeChapterIdLabel', {
    number: entry.chapterAudio.chapter_id,
  })
}

const getChapterLabel = (entry: ResumableChapterEntry, t: TFunction) => {
  if (entry.chapter) {
    return t('audiobook.resumableChaptersAlert.chapterLabel', {
      number: entry.chapter.chapter_number,
    })
  }
  return t('audiobook.resumableChaptersAlert.chapterIdLabel', {
    number: entry.chapterAudio.chapter_id,
  })
}

const ResumableChaptersAlert = ({
  entries,
  resumingChapterId,
  resumeCheckpointLoading,
  audiobookProjectId,
  onResumeChapterGeneration,
}: ResumableChaptersAlertProps) => {
  const { t } = useTranslation()
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
                {t('audiobook.resumableChaptersAlert.segmentFailureSummary', {
                  total: segmentFailureEntries.length,
                })}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {t('audiobook.resumableChaptersAlert.segmentFailureHint')}
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
                    {t('audiobook.resumableChaptersAlert.missingCountSummary', {
                      chapter: getChapterLabel(entry, t),
                      total: missingCount,
                    })}
                  </Button>
                )
              })}
              {segmentFailureEntries.length > 3 && (
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  {t('audiobook.resumableChaptersAlert.othersInResults')}
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
                {t('audiobook.resumableChaptersAlert.resumableSummary', {
                  total: plainEntries.length,
                })}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                {t('audiobook.resumableChaptersAlert.resumableHint')}
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
                    {isResuming
                      ? t('audiobook.resumableChaptersAlert.submittingText')
                      : getResumableChapterLabel(entry, t)}
                  </Button>
                )
              })}

              {plainEntries.length > 3 && (
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  {t('audiobook.resumableChaptersAlert.othersInResultsContinue')}
                </Typography>
              )}

              {resumeCheckpointLoading && (
                <Typography variant="caption" color="text.secondary" sx={{ alignSelf: 'center' }}>
                  {t('audiobook.resumableChaptersAlert.syncingCheckpointText')}
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
            ? t('audiobook.resumableChaptersAlert.dialogTitleWithChapter', {
                chapter: getChapterLabel(missingDialogEntry, t),
              })
            : t('audiobook.resumableChaptersAlert.dialogTitle')}
        </DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
            {t('audiobook.resumableChaptersAlert.dialogBody')}
          </Typography>
          <List dense disablePadding>
            {dialogMissingSegments.map((segment) => (
              <ListItem
                key={segment.index}
                disableGutters
                sx={{ display: 'block', alignItems: 'flex-start', py: 0.75 }}
              >
                <Typography variant="caption" color="text.secondary">
                  {t('audiobook.resumableChaptersAlert.segmentIndex', { index: segment.index })}
                  {segment.speaker
                    ? t('audiobook.resumableChaptersAlert.segmentSpeaker', { speaker: segment.speaker })
                    : ''}
                  {segment.voice
                    ? t('audiobook.resumableChaptersAlert.segmentVoice', { voice: segment.voice })
                    : ''}
                  {segment.error_type
                    ? t('audiobook.resumableChaptersAlert.segmentErrorType', { errorType: segment.error_type })
                    : ''}
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
            {t('audiobook.resumableChaptersAlert.laterAction')}
          </Button>
          <Button
            variant="outlined"
            color="warning"
            disabled={resumingChapterId !== null || !missingDialogEntry}
            onClick={() => missingDialogEntry && handleOpenVoiceDialog(missingDialogEntry)}
          >
            {t('audiobook.resumableChaptersAlert.retryWithVoice')}
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
              ? t('audiobook.resumableChaptersAlert.submittingText')
              : t('audiobook.resumableChaptersAlert.retryMissingSegments')}
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
        <DialogTitle>{t('audiobook.resumableChaptersAlert.voiceDialogTitle')}</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {t('audiobook.resumableChaptersAlert.voiceDialogBody')}
          </Typography>
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            {voiceDialogSpeakers.map((speaker) => (
              <TextField
                key={speaker}
                label={t('audiobook.resumableChaptersAlert.speakerVoiceIdLabel', { speaker })}
                size="small"
                value={voiceOverrides[speaker] || ''}
                onChange={(e) =>
                  setVoiceOverrides((prev) => ({ ...prev, [speaker]: e.target.value }))
                }
                placeholder={t('audiobook.resumableChaptersAlert.voiceIdPlaceholder')}
                fullWidth
              />
            ))}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setVoiceDialogEntry(null)} color="inherit">
            {t('action.cancel')}
          </Button>
          <Button
            variant="outlined"
            color="warning"
            disabled={voiceRecoverySubmitting}
            onClick={() => handleVoiceRecoverySubmit('replace_voice_missing')}
          >
            {t('audiobook.resumableChaptersAlert.replaceVoiceMissing')}
          </Button>
          <Button
            variant="contained"
            disabled={voiceRecoverySubmitting}
            onClick={() => handleVoiceRecoverySubmit('replace_voice_all')}
            sx={audiobookButtonSx.brandContained}
          >
            {voiceRecoverySubmitting
              ? t('audiobook.resumableChaptersAlert.submittingText')
              : t('audiobook.resumableChaptersAlert.replaceVoiceAll')}
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
