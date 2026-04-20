import {
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  LinearProgress,
  List,
  ListItem,
  Paper,
  Rating,
  TextField,
  Typography,
} from '@mui/material'

import type { PreviewType, ScriptEditorDialogProps } from './types'
import ScriptReviewReport from './ScriptReviewReport'

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
}: ScriptEditorDialogProps) => {
  const parseFloatValue = (value: string) => {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : 0
  }

  const parseCommaList = (value: string) =>
    value
      .split(',')
      .map((item) => item.trim())
      .filter((item) => item.length > 0)

  const updateVoiceParams = (index: number, patch: Record<string, any>) => {
    if (!data) return
    const current = data.scriptSegments[index]
    const currentParams = current?.voice_params && typeof current.voice_params === 'object'
      ? current.voice_params
      : {}
    onUpdateSegment(index, { voice_params: { ...currentParams, ...patch } })
  }

  return (
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
                      value={data.scriptSegments.length ? (Object.keys(segmentReviews).length / data.scriptSegments.length) * 100 : 0}
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
              </Box>
              <Paper variant="outlined" sx={{ maxHeight: 520, overflow: 'auto', p: 1 }}>
                <List dense>
                  {data.scriptSegments.map((seg: any, idx: number) => {
                    const hasSoundEffects =
                      (Array.isArray(seg.sound_effects) && seg.sound_effects.length > 0)
                      || (Array.isArray(seg.sound_effects_simple) && seg.sound_effects_simple.length > 0)
                    const hasMusicCue = Boolean(seg.music_cue) || Boolean(seg.music_cue_simple)
                    const isBusy = segmentPreviewingIndex === idx
                    const isPreviewing = (type: PreviewType) =>
                      isBusy && segmentPreviewingType === type
                    const voiceParams =
                      seg.voice_params && typeof seg.voice_params === 'object' ? seg.voice_params : {}
                    const soundEffectsSimple = Array.isArray(seg.sound_effects_simple)
                      ? seg.sound_effects_simple
                      : []
                    const soundEffectsFromDetail = Array.isArray(seg.sound_effects)
                      ? seg.sound_effects
                          .map((item: any) => item?.name || item?.effect_id || item?.id || item)
                          .filter((item: any) => typeof item === 'string' && item.length > 0)
                      : []
                    const soundEffectsValue =
                      soundEffectsSimple.length > 0
                        ? soundEffectsSimple.join(',')
                        : soundEffectsFromDetail.join(',')
                    const musicCueValue =
                      seg.music_cue_simple
                      || (seg.music_cue && (seg.music_cue.style || seg.music_cue.name))
                      || ''

                    return (
                      <ListItem key={idx} alignItems="flex-start" sx={{ mb: 1 }}>
                        <Box sx={{ width: '100%' }}>
                          <Typography variant="caption" color="text.secondary">
                            #{idx + 1} [{seg.type === 'dialogue' ? '对白' : seg.type}] {seg.speaker || '旁白'}{' '}
                            {seg.emotion ? `· 情绪: ${seg.emotion}` : ''}
                          </Typography>
                          <TextField
                            fullWidth
                            multiline
                            minRows={2}
                            margin="dense"
                            value={seg.text || ''}
                            onChange={(event) => onChangeSegmentText(idx, event.target.value)}
                          />
                          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 1, flexWrap: 'wrap' }}>
                            <Button
                              size="small"
                              variant="text"
                              onClick={() => onToggleSegmentDetails(idx)}
                            >
                              {segmentDetailsOpen[idx] ? '收起详情' : '查看详情'}
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'voice')}
                              disabled={isBusy || !seg.text?.trim()}
                              startIcon={isPreviewing('voice') ? <CircularProgress size={14} /> : undefined}
                            >
                              {isPreviewing('voice') ? '生成中...' : '人声试听'}
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'sfx')}
                              disabled={isBusy || !seg.text?.trim() || !hasSoundEffects}
                              startIcon={isPreviewing('sfx') ? <CircularProgress size={14} /> : undefined}
                            >
                              {isPreviewing('sfx') ? '生成中...' : '音效试听'}
                            </Button>
                            <Button
                              size="small"
                              variant="outlined"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'bgm')}
                              disabled={isBusy || !seg.text?.trim() || !hasMusicCue}
                              startIcon={isPreviewing('bgm') ? <CircularProgress size={14} /> : undefined}
                            >
                              {isPreviewing('bgm') ? '生成中...' : '配乐试听'}
                            </Button>
                            <Button
                              size="small"
                              variant="contained"
                              onClick={() => onPreviewSegmentAudio(idx, seg, 'mix')}
                              disabled={isBusy || !seg.text?.trim()}
                              startIcon={isPreviewing('mix') ? <CircularProgress size={14} /> : undefined}
                              sx={{
                                backgroundColor: '#9c27b0',
                                '&:hover': { backgroundColor: '#7b1fa2' },
                              }}
                            >
                              {isPreviewing('mix') ? '生成中...' : '融合试听'}
                            </Button>
                            {reviewMode && (
                              <>
                                <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, ml: 1 }}>
                                  <Typography variant="caption" color="text.secondary">评分：</Typography>
                                  <Rating
                                    size="small"
                                    value={segmentReviews[idx]?.quality_score || 0}
                                    onChange={(_, newValue) => {
                                      if (newValue) onReviewSegment(idx, newValue)
                                    }}
                                  />
                                </Box>
                                <Button
                                  size="small"
                                  variant="outlined"
                                  color="warning"
                                  onClick={() => onRegenerateSegment(idx, seg)}
                                  disabled={regeneratingSegments.has(idx) || !seg.text?.trim()}
                                  startIcon={regeneratingSegments.has(idx) ? <CircularProgress size={14} /> : undefined}
                                >
                                  {regeneratingSegments.has(idx) ? '重新生成中...' : '重新生成'}
                                </Button>
                              </>
                            )}
                          </Box>
                          {segmentDetailsOpen[idx] && (
                            <Paper
                              variant="outlined"
                              sx={{
                                mt: 1,
                                p: 1,
                                backgroundColor: 'rgba(0,0,0,0.02)',
                                borderStyle: 'dashed',
                              }}
                            >
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                                详细信息
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                表演提示：{seg.performance_notes || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                原文：{seg.original_text || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                改编原因：{seg.adaptation_reason || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                停顿：前 {seg.pause_before ?? '—'}s / 后 {seg.pause_after ?? '—'}s
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                Instruct：{seg.instruct_emotion || '—'} / {seg.instruct_scene || '—'} / {seg.instruct_role || '—'} / {seg.instruct_identity || '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                音色参数：{seg.voice_params ? JSON.stringify(seg.voice_params) : '—'}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                音效：{seg.sound_effects ? JSON.stringify(seg.sound_effects) : (seg.sound_effects_simple ? JSON.stringify(seg.sound_effects_simple) : '—')}
                              </Typography>
                              <Typography variant="caption" sx={{ display: 'block' }}>
                                配乐：{seg.music_cue ? JSON.stringify(seg.music_cue) : (seg.music_cue_simple || '—')}
                              </Typography>
                              <Divider sx={{ my: 1 }} />
                              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.5 }}>
                                音频提示词（可编辑）
                              </Typography>
                              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 1 }}>
                                <TextField
                                  size="small"
                                  label="停顿-前(s)"
                                  type="number"
                                  value={seg.pause_before ?? ''}
                                  onChange={(event) =>
                                    onUpdateSegment(idx, { pause_before: parseFloatValue(event.target.value) })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="停顿-后(s)"
                                  type="number"
                                  value={seg.pause_after ?? ''}
                                  onChange={(event) =>
                                    onUpdateSegment(idx, { pause_after: parseFloatValue(event.target.value) })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 情感"
                                  value={seg.instruct_emotion || ''}
                                  onChange={(event) =>
                                    onUpdateSegment(idx, { instruct_emotion: event.target.value })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 场景"
                                  value={seg.instruct_scene || ''}
                                  onChange={(event) =>
                                    onUpdateSegment(idx, { instruct_scene: event.target.value })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 角色"
                                  value={seg.instruct_role || ''}
                                  onChange={(event) =>
                                    onUpdateSegment(idx, { instruct_role: event.target.value })
                                  }
                                />
                                <TextField
                                  size="small"
                                  label="Instruct 身份"
                                  value={seg.instruct_identity || ''}
                                  onChange={(event) =>
                                    onUpdateSegment(idx, { instruct_identity: event.target.value })
                                  }
                                />
                              </Box>
                              <Box sx={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 1, mt: 1 }}>
                                <TextField
                                  size="small"
                                  label="语速 rate"
                                  type="number"
                                  value={voiceParams.rate ?? voiceParams.speed ?? ''}
                                  onChange={(event) => updateVoiceParams(idx, { rate: parseFloatValue(event.target.value) })}
                                />
                                <TextField
                                  size="small"
                                  label="音高 pitch"
                                  type="number"
                                  value={voiceParams.pitch ?? ''}
                                  onChange={(event) => updateVoiceParams(idx, { pitch: parseFloatValue(event.target.value) })}
                                />
                                <TextField
                                  size="small"
                                  label="音量 volume"
                                  type="number"
                                  value={voiceParams.volume ?? ''}
                                  onChange={(event) => updateVoiceParams(idx, { volume: parseFloatValue(event.target.value) })}
                                />
                              </Box>
                              <TextField
                                fullWidth
                                size="small"
                                label="音效提示（逗号分隔）"
                                value={soundEffectsValue}
                                onChange={(event) =>
                                  onUpdateSegment(idx, {
                                    sound_effects_simple: parseCommaList(event.target.value),
                                    sound_effects: [],
                                  })
                                }
                                sx={{ mt: 1 }}
                              />
                              <TextField
                                fullWidth
                                size="small"
                                label="配乐提示"
                                value={musicCueValue}
                                onChange={(event) =>
                                  onUpdateSegment(idx, {
                                    music_cue_simple: event.target.value,
                                    music_cue: null,
                                  })
                                }
                                sx={{ mt: 1 }}
                              />
                            </Paper>
                          )}
                          {segmentAudioUrls[idx] && (
                            <Box sx={{ mt: 1 }}>
                              <audio controls src={segmentAudioUrls[idx]} />
                            </Box>
                          )}
                        </Box>
                      </ListItem>
                    )
                  })}
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
          sx={{
            backgroundColor: '#9c27b0',
            '&:hover': { backgroundColor: '#7b1fa2' },
          }}
        >
          保存并生成该章节音频
        </Button>
      </DialogActions>
    </Dialog>
  )
}

export default ScriptEditorDialog
