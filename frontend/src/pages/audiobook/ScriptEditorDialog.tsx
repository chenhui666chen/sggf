import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  List,
  Paper,
  Typography,
} from '@mui/material'

import type {
  ScriptEditorDialogProps,
  ScriptSegment,
} from './types'
import ScriptReviewReport from './ScriptReviewReport'
import ScriptEditorConflictNotice from './ScriptEditorConflictNotice'
import ScriptSegmentCard from './ScriptSegmentCard'
import SmartChunkPreviewPanel from './SmartChunkPreviewPanel'
import { audiobookButtonSx } from './audiobookTheme'

const ScriptEditorDialog = ({
  open,
  loading,
  chapter,
  data,
  onClose,
  onChangeSegmentText,
  onSaveScript,
  onPreviewSegmentAudio,
  onRegenerateSegment,
  onReviewSegment,
  segmentReviews,
  segmentPreviewingIndex,
  segmentPreviewingType,
  segmentAudioUrls,
  segmentDetailsOpen,
  onToggleSegmentDetails,
  onUpdateSegment,
  reviewMode,
  onToggleReviewMode,
  regeneratingSegments,
  smartChunkPreview,
  smartChunkPreviewLoading,
  onPreviewSmartChunking,
  editorConflict,
  editorConflictTimeLabel,
  editorConflictPreview,
  visibleEditorConflictSegmentDiffs = [],
  hiddenEditorConflictSegmentDiffCount = 0,
  onApplyIncomingDraft,
  onKeepLocalDraft,
}: ScriptEditorDialogProps) => (
  <Dialog open={open} onClose={onClose} maxWidth="lg" fullWidth>
    <DialogTitle>
      {chapter ? `编辑剧本与音频提示词 - ${chapter.title}` : '编辑章节剧本与音频提示词'}
    </DialogTitle>
    <DialogContent dividers sx={{ minHeight: 400 }}>
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={28} />
        </Box>
      ) : !data ? (
        <Typography variant="body2" color="text.secondary">
          暂无剧本数据，请先生成剧本。
        </Typography>
      ) : (
        <Box sx={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
          {editorConflict && (
            <ScriptEditorConflictNotice
              timeLabel={editorConflictTimeLabel}
              preview={editorConflictPreview}
              visibleSegmentDiffs={visibleEditorConflictSegmentDiffs}
              hiddenSegmentDiffCount={hiddenEditorConflictSegmentDiffCount}
              onApplyIncomingDraft={onApplyIncomingDraft}
              onKeepLocalDraft={onKeepLocalDraft}
            />
          )}

          <Box sx={{ display: 'flex', gap: 2 }}>
            <Box sx={{ flex: 2, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
                剧本片段（支持文本与音频提示词调整）
              </Typography>
              <Box sx={{ display: 'flex', justifyContent: 'flex-end', mb: 1, gap: 1, alignItems: 'center' }}>
                {reviewMode && (
                  <Box sx={{ flex: 1, mr: 2 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">
                        审查进度
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {Object.keys(segmentReviews).length} / {data.scriptSegments.length || 0}
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={
                        data.scriptSegments.length
                          ? (Object.keys(segmentReviews).length / data.scriptSegments.length) * 100
                          : 0
                      }
                      sx={{ height: 6, borderRadius: 1 }}
                    />
                  </Box>
                )}
                <Button
                  size="small"
                  variant={reviewMode ? 'contained' : 'outlined'}
                  color={reviewMode ? 'primary' : 'inherit'}
                  onClick={onToggleReviewMode}
                  startIcon={(
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                      <path d="M12 20h9" />
                      <path d="M16.5 3.5a2.121 2.121 0 0 1 3 3L7 19l-4 1 1-4L16.5 3.5z" />
                    </svg>
                  )}
                >
                  {reviewMode ? '退出审查模式' : '进入审查模式'}
                </Button>
                <Button
                  size="small"
                  variant="outlined"
                  onClick={onPreviewSmartChunking}
                  disabled={smartChunkPreviewLoading}
                >
                  {smartChunkPreviewLoading ? '诊断中...' : '分块诊断'}
                </Button>
              </Box>

              <Paper variant="outlined" sx={{ maxHeight: 520, overflow: 'auto', p: 1 }}>
                <List dense>
                  {data.scriptSegments.map((segment: ScriptSegment, index: number) => (
                    <ScriptSegmentCard
                      key={index}
                      segment={segment}
                      index={index}
                      detailsOpen={Boolean(segmentDetailsOpen[index])}
                      reviewMode={reviewMode}
                      review={segmentReviews[index]}
                      previewingType={segmentPreviewingIndex === index ? segmentPreviewingType : null}
                      audioUrl={segmentAudioUrls[index]}
                      regenerating={regeneratingSegments.has(index)}
                      onChangeText={onChangeSegmentText}
                      onPreviewAudio={onPreviewSegmentAudio}
                      onRegenerate={onRegenerateSegment}
                      onReview={onReviewSegment}
                      onToggleDetails={onToggleSegmentDetails}
                      onUpdateSegment={onUpdateSegment}
                    />
                  ))}
                </List>
              </Paper>
            </Box>

            <Box sx={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 600 }}>
                评审报告
              </Typography>
              {data.scriptReview ? (
                <Paper variant="outlined" sx={{ p: 2, maxHeight: 520, overflow: 'auto' }}>
                  <ScriptReviewReport review={data.scriptReview} />
                </Paper>
              ) : (
                <Typography variant="body2" color="text.secondary">
                  暂无评审数据。
                </Typography>
              )}

              <Typography variant="caption" color="text.secondary" sx={{ mt: 1 }}>
                修改剧本后，建议重新生成该章节音频以保证文本与音频一致。
              </Typography>

              <Typography variant="subtitle1" sx={{ fontWeight: 600, mt: 2 }}>
                分块诊断
              </Typography>
              <Paper variant="outlined" sx={{ p: 2 }}>
                {smartChunkPreview ? (
                  <SmartChunkPreviewPanel preview={smartChunkPreview} />
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    暂无诊断结果。
                  </Typography>
                )}
              </Paper>
            </Box>
          </Box>
        </Box>
      )}
    </DialogContent>
    <DialogActions>
      <Button onClick={onClose} disabled={loading}>
        关闭
      </Button>
      <Button
        onClick={() => onSaveScript({ nextStatus: 'reviewed', generateAudio: false })}
        disabled={loading || !data}
      >
        仅保存剧本
      </Button>
      <Button
        onClick={() => onSaveScript({ nextStatus: 'approved', generateAudio: true })}
        disabled={loading || !data}
        variant="contained"
        sx={audiobookButtonSx.brandContained}
      >
        保存并生成该章节音频
      </Button>
    </DialogActions>
  </Dialog>
)

export default ScriptEditorDialog
