import { useState } from 'react'

import {
  Box,
  Button,
  Collapse,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import EditIcon from '@mui/icons-material/Edit'
import SendIcon from '@mui/icons-material/Send'
import { useTranslation } from 'react-i18next'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import ScriptReviewReport from './ScriptReviewReport'
import type { ScriptReviewDialogData } from './types'

interface ScriptQualityReviewDialogProps {
  open: boolean
  data: ScriptReviewDialogData | null
  audiobookProjectId?: number
  selectedIssueIndex?: number | null
  selectedSegmentIndex?: number | null
  onClose: () => void
  onOpenScriptEditor?: (chapterId: number, initialSegmentIndex?: number | null) => void | Promise<void>
  onSelectIssue?: (index: number | null) => void
  onSelectSegment?: (index: number | null) => void
}

const ScriptQualityReviewDialog = ({
  open,
  data,
  audiobookProjectId,
  selectedIssueIndex = null,
  selectedSegmentIndex = null,
  onClose,
  onOpenScriptEditor,
  onSelectIssue,
  onSelectSegment,
}: ScriptQualityReviewDialogProps) => {
  const { t } = useTranslation()
  const [feedbackOpen, setFeedbackOpen] = useState(false)
  const [feedbackText, setFeedbackText] = useState('')
  const [feedbackSubmitting, setFeedbackSubmitting] = useState(false)
  const [feedbackSubmitted, setFeedbackSubmitted] = useState(false)
  const [feedbackError, setFeedbackError] = useState<string | null>(null)

  const canOpenScriptEditor = Boolean(data?.chapterId && onOpenScriptEditor)
  const canSubmitFeedback = Boolean(audiobookProjectId && data?.chapterId)

  const handleOpenScriptEditor = () => {
    if (!data?.chapterId || !onOpenScriptEditor) return
    onClose()
    void onOpenScriptEditor(data.chapterId, selectedSegmentIndex)
  }

  const handleSubmitFeedback = async () => {
    if (!audiobookProjectId || !data?.chapterId || !feedbackText.trim()) return
    setFeedbackSubmitting(true)
    setFeedbackError(null)
    try {
      await apiClient.submitScriptReviewFeedback({
        audiobook_project_id: audiobookProjectId,
        chapter_id: data.chapterId,
        feedback: feedbackText.trim(),
      })
      setFeedbackSubmitted(true)
    } catch (err: unknown) {
      setFeedbackError(await extractApiErrorMessage(err, t('audiobook.scriptQualityReviewDialog.submitFailed')))
    } finally {
      setFeedbackSubmitting(false)
    }
  }

  const handleClose = () => {
    setFeedbackOpen(false)
    setFeedbackText('')
    setFeedbackSubmitted(false)
    setFeedbackError(null)
    setFeedbackSubmitting(false)
    onClose()
  }

  return (
    <Dialog
      open={open}
      onClose={handleClose}
      maxWidth="md"
      fullWidth
    >
      <DialogTitle>{t('audiobook.scriptQualityReviewDialog.title')}</DialogTitle>
      <DialogContent dividers>
        {!data ? (
          <Typography variant="body2" color="text.secondary">
            {t('audiobook.scriptQualityReviewDialog.emptyData')}
          </Typography>
        ) : (
          <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
            <ScriptReviewReport
              review={data.report}
              selectedIssueIndex={selectedIssueIndex}
              onSelectIssue={onSelectIssue}
            />

            <Divider />

            <Box>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                {t('audiobook.scriptQualityReviewDialog.segmentPreviewTitle', { total: data.segments.length })}
              </Typography>
              <Paper
                variant="outlined"
                sx={{ maxHeight: 400, overflow: 'auto', p: 1 }}
              >
                <List dense>
                  {data.segments.map((seg, index) => {
                    const segmentIndex = typeof seg.index === 'number' ? seg.index : index
                    const segmentType = seg.type === 'dialogue'
                      ? t('audiobook.scriptQualityReviewDialog.dialogueType')
                      : seg.type || t('audiobook.scriptQualityReviewDialog.narrationType')
                    const speaker = seg.speaker || seg.speaker_name || seg.character_name || t('audiobook.scriptQualityReviewDialog.narrationType')

                    return (
                      <ListItemButton
                        key={`${segmentIndex}-${speaker}`}
                        alignItems="flex-start"
                        selected={selectedSegmentIndex === segmentIndex}
                        onClick={() => onSelectSegment?.(
                          selectedSegmentIndex === segmentIndex ? null : segmentIndex,
                        )}
                        sx={{ mb: 0.5, borderRadius: 1 }}
                      >
                        <ListItemText
                          primary={
                            <Typography variant="body2" sx={{ fontWeight: 500 }}>
                              #{segmentIndex + 1} [{segmentType}] {speaker}
                            </Typography>
                          }
                          secondary={
                            <Typography variant="body2" color="text.secondary">
                              {seg.text || ''}
                            </Typography>
                          }
                        />
                      </ListItemButton>
                    )
                  })}
                </List>
              </Paper>
            </Box>

            {canSubmitFeedback && (
              <>
                <Divider />
                <Box>
                  <Button
                    size="small"
                    variant="text"
                    onClick={() => setFeedbackOpen(!feedbackOpen)}
                    sx={{ mb: 1 }}
                  >
                    {feedbackOpen
                      ? t('audiobook.scriptQualityReviewDialog.collapseFeedback')
                      : t('audiobook.scriptQualityReviewDialog.openFeedback')}
                  </Button>
                  <Collapse in={feedbackOpen}>
                    {feedbackSubmitted ? (
                      <Typography variant="body2" color="text.secondary">
                        {t('audiobook.scriptQualityReviewDialog.feedbackThankYou')}
                      </Typography>
                    ) : (
                      <Box sx={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
                        <TextField
                          size="small"
                          fullWidth
                          multiline
                          minRows={2}
                          maxRows={4}
                          placeholder={t('audiobook.scriptQualityReviewDialog.feedbackPlaceholder')}
                          value={feedbackText}
                          onChange={(e) => setFeedbackText(e.target.value)}
                        />
                        <Box sx={{ display: 'flex', gap: 1, alignItems: 'center' }}>
                          <Button
                            size="small"
                            variant="contained"
                            startIcon={<SendIcon />}
                            disabled={feedbackSubmitting || !feedbackText.trim()}
                            onClick={handleSubmitFeedback}
                          >
                            {feedbackSubmitting
                              ? t('audiobook.scriptQualityReviewDialog.submitting')
                              : t('audiobook.scriptQualityReviewDialog.submitFeedback')}
                          </Button>
                          {feedbackError && (
                            <Typography variant="caption" color="error">
                              {feedbackError}
                            </Typography>
                          )}
                        </Box>
                      </Box>
                    )}
                  </Collapse>
                </Box>
              </>
            )}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        {canOpenScriptEditor && (
          <Button startIcon={<EditIcon />} onClick={handleOpenScriptEditor}>
            {t('audiobook.scriptQualityReviewDialog.openScriptEditor')}
          </Button>
        )}
        <Button onClick={handleClose}>{t('action.close')}</Button>
      </DialogActions>
    </Dialog>
  )
}

export default ScriptQualityReviewDialog
