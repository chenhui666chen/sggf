import { useCallback, useMemo, useState } from 'react'

import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Collapse,
  Divider,
  Dialog,
  DialogContent,
  LinearProgress,
  List,
  Slider,
  Stack,
  Typography,
} from '@mui/material'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import ErrorIcon from '@mui/icons-material/Error'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'
import MicIcon from '@mui/icons-material/Mic'
import NotesIcon from '@mui/icons-material/Notes'
import TuneIcon from '@mui/icons-material/Tune'
import VerifiedUserIcon from '@mui/icons-material/VerifiedUser'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import type {
  ScriptEditorDialogProps,
  ScriptSegment,
} from './types'
import ScriptReviewReport from './ScriptReviewReport'
import ScriptEditorConflictNotice from './ScriptEditorConflictNotice'
import ScriptSegmentCard from './ScriptSegmentCard'
import SmartChunkPreviewPanel from './SmartChunkPreviewPanel'
import { audiobookButtonSx, audiobookColors } from './audiobookTheme'
import {
  getScriptSegmentSpeakerLabel,
  getScriptSegmentTypeLabel,
  getMusicCueInputValue,
  getSoundEffectsInputValue,
} from './scriptSegmentCardUtils'

const TIMELINE_SCALE_OPTIONS = [
  { value: 0.8, label: '紧凑' },
  { value: 1, label: '标准' },
  { value: 1.35, label: '精细' },
]

const editorShellSx = {
  height: '100%',
  minHeight: 0,
  display: 'grid',
  gridTemplateRows: 'auto minmax(0, 1fr) minmax(260px, 34vh)',
  bgcolor: '#f4f6f8',
}

const editorToolbarSx = {
  px: 2,
  py: 1,
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', lg: 'minmax(260px, 1.2fr) auto auto' },
  gap: 1,
  alignItems: 'center',
  flexWrap: 'wrap',
  borderBottom: '1px solid',
  borderColor: 'divider',
  bgcolor: '#ffffff',
}

const workbenchActionBarSx = {
  display: 'flex',
  gap: 1,
  alignItems: 'center',
  flexWrap: 'wrap',
  justifyContent: 'flex-end',
}

const editorWorkspaceSx = {
  minHeight: 0,
  display: 'grid',
  gridTemplateColumns: { xs: '1fr', lg: 'minmax(0, 1fr) 360px' },
  gap: 0,
}

const segmentTrackSx = {
  minHeight: 0,
  display: 'flex',
  flexDirection: 'column',
  borderRight: { xs: 0, lg: '1px solid' },
  borderColor: 'divider',
}

const inspectorSx = {
  minHeight: 0,
  display: { xs: 'none', lg: 'flex' },
  flexDirection: 'column',
  bgcolor: '#ffffff',
}

const panelHeaderSx = {
  px: 2,
  py: 1.25,
  display: 'flex',
  alignItems: 'center',
  justifyContent: 'space-between',
  borderBottom: '1px solid',
  borderColor: 'divider',
  bgcolor: '#ffffff',
}

const timelinePanelSx = {
  borderTop: '1px solid',
  borderColor: 'divider',
  bgcolor: '#111827',
  color: '#e5e7eb',
  overflow: 'auto',
}

const trackRowSx = {
  display: 'grid',
  gridTemplateColumns: '96px minmax(0, 1fr)',
  alignItems: 'center',
  minHeight: 34,
  borderTop: '1px solid rgba(255,255,255,0.08)',
}

const trackLabelSx = {
  px: 1.25,
  height: '100%',
  display: 'flex',
  alignItems: 'center',
  gap: 0.75,
  bgcolor: 'rgba(255,255,255,0.05)',
  color: '#cbd5e1',
  fontSize: 12,
}

interface TimelineBlock {
  key: string
  index: number
  label: string
  baseWidth: number
  enabled: boolean
}

interface TimelineTick {
  key: string
  label: string
}

const buildTimelineTicks = (segmentCount: number): TimelineTick[] => {
  if (segmentCount <= 0) return []

  const step = segmentCount > 16 ? 4 : segmentCount > 8 ? 2 : 1
  return Array.from({ length: segmentCount }, (_, index) => index)
    .filter((index) => index === 0 || index === segmentCount - 1 || index % step === 0)
    .map((index) => ({
      key: `tick-${index}`,
      label: `#${index + 1}`,
    }))
}

const buildTimelineBlocks = (
  segments: ScriptSegment[],
  track: 'text' | 'voice' | 'sfx' | 'music',
): TimelineBlock[] =>
  segments.map((segment, index) => {
    const textLength = String(segment.text || '').trim().length
    const width = Math.max(44, Math.min(180, textLength * 1.8 + 28))
    const hasText = textLength > 0
    const hasSfx = getSoundEffectsInputValue(segment).length > 0
    const hasMusic = getMusicCueInputValue(segment).length > 0
    const enabled = track === 'sfx'
      ? hasSfx
      : track === 'music'
        ? hasMusic
        : hasText

    return {
      key: `${track}-${index}`,
      index,
      label: `#${index + 1}`,
      baseWidth: width,
      enabled,
    }
  })

const TimelineTrack = ({
  label,
  icon,
  color,
  blocks,
  selectedIndex,
  scale,
  onSelectBlock,
}: {
  label: string
  icon: JSX.Element
  color: string
  blocks: TimelineBlock[]
  selectedIndex: number
  scale: number
  onSelectBlock: (index: number) => void
}) => (
  <Box sx={trackRowSx}>
    <Box sx={trackLabelSx}>
      {icon}
      {label}
    </Box>
    <Box sx={{ display: 'flex', gap: 0.5, overflowX: 'auto', py: 0.75, px: 1 }}>
      {blocks.map((block) => (
        <Box
          key={block.key}
          title={`${label} ${block.label}`}
          role="button"
          tabIndex={0}
          onClick={() => onSelectBlock(block.index)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' || event.key === ' ') {
              event.preventDefault()
              onSelectBlock(block.index)
            }
          }}
          sx={{
            flex: `0 0 ${Math.round(block.baseWidth * scale)}px`,
            height: 22,
            borderRadius: 0.75,
            bgcolor: block.enabled ? color : 'rgba(148, 163, 184, 0.18)',
            border: '1px solid',
            borderColor: block.index === selectedIndex
              ? '#f8fafc'
              : block.enabled
                ? 'rgba(255,255,255,0.2)'
                : 'rgba(148,163,184,0.14)',
            boxShadow: block.index === selectedIndex ? '0 0 0 2px rgba(248,250,252,0.28)' : 'none',
            color: block.enabled ? '#ffffff' : '#94a3b8',
            cursor: 'pointer',
            fontSize: 10,
            lineHeight: '20px',
            textAlign: 'center',
            overflow: 'hidden',
            whiteSpace: 'nowrap',
            transition: 'border-color 120ms ease, box-shadow 120ms ease, transform 120ms ease',
            '&:hover': {
              transform: 'translateY(-1px)',
              borderColor: '#f8fafc',
            },
          }}
        >
          {block.label}
        </Box>
      ))}
    </Box>
  </Box>
)

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
  projectId,
}: ScriptEditorDialogProps) => {
  const [consistencyChecking, setConsistencyChecking] = useState(false)
  const [selectedSegmentIndex, setSelectedSegmentIndex] = useState(0)
  const [timelineScale, setTimelineScale] = useState(1)
  const [consistencyResult, setConsistencyResult] = useState<{
    is_consistent: boolean
    consistency_score: number
    analysis_summary: string
  } | null>(null)
  const [consistencyError, setConsistencyError] = useState<string | null>(null)
  const scriptSegments = data?.scriptSegments || []
  const safeSelectedSegmentIndex = scriptSegments.length
    ? Math.min(selectedSegmentIndex, scriptSegments.length - 1)
    : 0
  const selectedSegment = scriptSegments[safeSelectedSegmentIndex] || null
  const selectedSegmentSfx = useMemo(
    () => (selectedSegment ? getSoundEffectsInputValue(selectedSegment) : ''),
    [selectedSegment],
  )
  const selectedSegmentMusic = useMemo(
    () => (selectedSegment ? getMusicCueInputValue(selectedSegment) : ''),
    [selectedSegment],
  )
  const selectedSegmentTextLength = String(selectedSegment?.text || '').trim().length
  const reviewedCount = useMemo(() => Object.keys(segmentReviews).length, [segmentReviews])
  const audioCueStats = useMemo(() => {
    let sfxCueCount = 0
    let musicCueCount = 0
    let totalTextLength = 0

    for (const segment of scriptSegments) {
      totalTextLength += String(segment.text || '').trim().length
      if (getSoundEffectsInputValue(segment).length > 0) {
        sfxCueCount += 1
      }
      if (getMusicCueInputValue(segment).length > 0) {
        musicCueCount += 1
      }
    }

    return { sfxCueCount, musicCueCount, totalTextLength }
  }, [scriptSegments])
  const timelineBlocks = useMemo(() => ({
    text: buildTimelineBlocks(scriptSegments, 'text'),
    voice: buildTimelineBlocks(scriptSegments, 'voice'),
    sfx: buildTimelineBlocks(scriptSegments, 'sfx'),
    music: buildTimelineBlocks(scriptSegments, 'music'),
  }), [scriptSegments])
  const timelineTicks = useMemo(
    () => buildTimelineTicks(scriptSegments.length),
    [scriptSegments.length],
  )

  const handleCheckConsistency = async () => {
    if (!data?.scriptSegments?.length) return
    setConsistencyChecking(true)
    setConsistencyError(null)
    try {
      const segmentsText = data.scriptSegments
        .map((s: ScriptSegment, i: number) => `[${i + 1}] ${s.text || ''}`)
        .join('\n')
      const res = await apiClient.checkConsistency({
        world_settings: [{ type: '剧本', name: chapter?.title || '当前章节', content: segmentsText }],
        new_content: segmentsText,
        project_id: projectId,
      })
      setConsistencyResult({
        is_consistent: res.data.is_consistent,
        consistency_score: res.data.consistency_check.consistency_score,
        analysis_summary: res.data.consistency_check.analysis_summary,
      })
    } catch (err: unknown) {
      setConsistencyError(await extractApiErrorMessage(err, '一致性检查失败'))
    } finally {
      setConsistencyChecking(false)
    }
  }

  const handleSelectSegment = useCallback((index: number) => {
    setSelectedSegmentIndex(index)
  }, [])

  const handlePreviousSegment = useCallback(() => {
    setSelectedSegmentIndex((current) => Math.max(0, current - 1))
  }, [])

  const handleNextSegment = useCallback(() => {
    setSelectedSegmentIndex((current) => Math.min(scriptSegments.length - 1, current + 1))
  }, [scriptSegments.length])

  return (
  <Dialog
    open={open}
    onClose={onClose}
    maxWidth={false}
    fullWidth
    PaperProps={{
      sx: {
        width: 'min(1760px, 98vw)',
        maxWidth: '98vw',
        height: '94vh',
        display: 'grid',
        gridTemplateRows: 'minmax(0, 1fr)',
      },
    }}
  >
    <DialogContent dividers sx={{ p: 0, overflow: 'hidden', minHeight: 0 }}>
      {loading ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={28} />
        </Box>
      ) : !data ? (
        <Typography variant="body2" color="text.secondary">
          暂无剧本数据，请先生成剧本。
        </Typography>
      ) : (
        <Box sx={editorShellSx}>
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

          <Box sx={editorToolbarSx}>
            <Box sx={{ minWidth: 0 }}>
              <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.2 }}>
                {chapter ? `剪辑剧本与音频提示词 - ${chapter.title}` : '剪辑章节剧本与音频提示词'}
              </Typography>
              <Typography variant="caption" color="text.secondary">
                剪辑工具栏
              </Typography>
            <Stack direction="row" spacing={1} sx={{ flexWrap: 'wrap', rowGap: 1, mt: 0.75 }}>
              <Button
                size="small"
                variant={reviewMode ? 'contained' : 'outlined'}
                color={reviewMode ? 'primary' : 'inherit'}
                onClick={onToggleReviewMode}
                startIcon={<TuneIcon fontSize="small" />}
              >
                {reviewMode ? '退出审查' : '审查模式'}
              </Button>
              <Button
                size="small"
                variant="outlined"
                onClick={onPreviewSmartChunking}
                disabled={smartChunkPreviewLoading}
              >
                {smartChunkPreviewLoading ? '诊断中...' : '分块诊断'}
              </Button>
              <Button
                size="small"
                variant="outlined"
                startIcon={consistencyChecking ? <CircularProgress size={14} /> : <VerifiedUserIcon />}
                onClick={handleCheckConsistency}
                disabled={consistencyChecking || !scriptSegments.length}
              >
                {consistencyChecking ? '检查中...' : '一致性检查'}
              </Button>
            </Stack>
            </Box>
            <Stack
              direction="row"
              spacing={1.25}
              sx={{ justifyContent: 'flex-end', flexWrap: 'wrap', rowGap: 0.75, color: 'text.secondary' }}
            >
              <Typography variant="caption">片段 {scriptSegments.length}</Typography>
              <Typography variant="caption">字数 {audioCueStats.totalTextLength}</Typography>
              <Typography variant="caption">音效 {audioCueStats.sfxCueCount}</Typography>
              <Typography variant="caption">配乐 {audioCueStats.musicCueCount}</Typography>
            </Stack>
            <Box sx={workbenchActionBarSx}>
              <Button onClick={onClose} disabled={loading} size="small">
                关闭
              </Button>
              <Button
                onClick={() => onSaveScript({ nextStatus: 'reviewed', generateAudio: false })}
                disabled={loading || !data}
                size="small"
              >
                仅保存剧本
              </Button>
              <Button
                onClick={() => onSaveScript({ nextStatus: 'approved', generateAudio: true })}
                disabled={loading || !data}
                variant="contained"
                size="small"
                sx={audiobookButtonSx.brandContained}
              >
                保存并生成该章节音频
              </Button>
            </Box>
          </Box>

          <Box sx={editorWorkspaceSx}>
            <Box sx={segmentTrackSx}>
              <Box sx={panelHeaderSx}>
                <Box>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    片段轨道
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    文本、人声提示、音效、配乐
                  </Typography>
                </Box>
                {reviewMode && (
                  <Box sx={{ width: 220 }}>
                    <Box sx={{ display: 'flex', justifyContent: 'space-between', mb: 0.5 }}>
                      <Typography variant="caption" color="text.secondary">
                        审查进度
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        {reviewedCount} / {scriptSegments.length || 0}
                      </Typography>
                    </Box>
                    <LinearProgress
                      variant="determinate"
                      value={
                        scriptSegments.length
                          ? (reviewedCount / scriptSegments.length) * 100
                          : 0
                      }
                      sx={{ height: 6, borderRadius: 1 }}
                    />
                  </Box>
                )}
              </Box>

              <Box sx={{ minHeight: 0, overflow: 'auto', p: 1.25 }}>
                <List dense>
                  {scriptSegments.map((segment: ScriptSegment, index: number) => (
                    <ScriptSegmentCard
                      key={index}
                      segment={segment}
                      index={index}
                      detailsOpen={Boolean(segmentDetailsOpen[index])}
                      selected={index === safeSelectedSegmentIndex}
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
                      onSelect={handleSelectSegment}
                    />
                  ))}
                </List>
              </Box>
            </Box>

            <Box sx={inspectorSx}>
              <Box sx={panelHeaderSx}>
                <Box>
                  <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
                    属性检查器
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    评审、诊断与一致性状态
                  </Typography>
                </Box>
              </Box>
              <Box sx={{ minHeight: 0, overflow: 'auto', p: 2 }}>
                <Box
                  sx={{
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                    p: 1.5,
                    mb: 2,
                    bgcolor: '#f8fafc',
                  }}
                >
                  <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
                    <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                      当前片段
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {selectedSegment ? `#${safeSelectedSegmentIndex + 1}` : '未选择'}
                    </Typography>
                  </Stack>
                  {selectedSegment ? (
                    <Stack spacing={0.75}>
                      <Stack direction="row" spacing={1} alignItems="center">
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={handlePreviousSegment}
                          disabled={safeSelectedSegmentIndex <= 0}
                        >
                          上一段
                        </Button>
                        <Button
                          size="small"
                          variant="outlined"
                          onClick={handleNextSegment}
                          disabled={safeSelectedSegmentIndex >= scriptSegments.length - 1}
                        >
                          下一段
                        </Button>
                      </Stack>
                      <Typography variant="caption" color="text.secondary">
                        当前位置：{safeSelectedSegmentIndex + 1} / {scriptSegments.length}
                      </Typography>
                      <Typography variant="body2">
                        {getScriptSegmentTypeLabel(selectedSegment)} · {getScriptSegmentSpeakerLabel(selectedSegment)}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        情绪：{selectedSegment.emotion || selectedSegment.voice_params?.emotion || '未标注'}
                      </Typography>
                      <Typography variant="caption" color="text.secondary">
                        字数 {selectedSegmentTextLength} · 音效 {selectedSegmentSfx ? selectedSegmentSfx.split(',').length : 0} · 配乐 {selectedSegmentMusic ? '已配置' : '未配置'}
                      </Typography>
                      {(selectedSegmentSfx || selectedSegmentMusic) && (
                        <Typography
                          variant="caption"
                          color="text.secondary"
                          sx={{ display: 'block', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}
                        >
                          {selectedSegmentSfx || selectedSegmentMusic}
                        </Typography>
                      )}
                    </Stack>
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      暂无可检查的片段。
                    </Typography>
                  )}
                </Box>

                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                  评审报告
                </Typography>
                {data.scriptReview ? (
                  <ScriptReviewReport review={data.scriptReview} />
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    暂无评审数据。
                  </Typography>
                )}

                <Divider sx={{ my: 2 }} />
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                  一致性检查
                </Typography>
                <Collapse in={Boolean(consistencyResult || consistencyError)} unmountOnExit>
                  <Box sx={{ mb: 1 }}>
                    {consistencyError && <Alert severity="error">{consistencyError}</Alert>}
                    {consistencyResult && (
                    <Alert
                      severity={consistencyResult.is_consistent ? 'success' : 'warning'}
                      icon={consistencyResult.is_consistent ? <CheckCircleIcon /> : <ErrorIcon />}
                    >
                      <Typography variant="body2" sx={{ fontWeight: 600 }}>
                        {consistencyResult.is_consistent ? '未发现一致性问题' : '发现潜在不一致'}
                        {consistencyResult.consistency_score > 0 && (
                          <>（评分：{(consistencyResult.consistency_score * 100).toFixed(0)}%）</>
                        )}
                      </Typography>
                      {consistencyResult.analysis_summary && (
                        <Typography variant="caption" sx={{ display: 'block', mt: 0.5, whiteSpace: 'pre-wrap' }}>
                          {consistencyResult.analysis_summary}
                        </Typography>
                      )}
                    </Alert>
                    )}
                  </Box>
                </Collapse>
                {!consistencyResult && !consistencyError && (
                  <Typography variant="body2" color="text.secondary">
                    尚未执行检查。
                  </Typography>
                )}

                <Divider sx={{ my: 2 }} />
                <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
                  分块诊断
                </Typography>
                {smartChunkPreview ? (
                  <SmartChunkPreviewPanel preview={smartChunkPreview} />
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    暂无诊断结果。
                  </Typography>
                )}
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 2 }}>
                  修改剧本后，建议重新生成该章节音频以保证文本与音频一致。
                </Typography>
              </Box>
            </Box>
          </Box>

          <Box sx={timelinePanelSx}>
            <Box
              sx={{
                px: 1.5,
                py: 0.75,
                display: 'grid',
                gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) 260px' },
                gap: 2,
                alignItems: 'center',
              }}
            >
              <Box>
              <Typography variant="subtitle2" sx={{ fontWeight: 700, color: '#f8fafc' }}>
                时间线
              </Typography>
              <Typography variant="caption" sx={{ color: '#94a3b8' }}>
                文本 {scriptSegments.length} · 音效 {audioCueStats.sfxCueCount} · 配乐 {audioCueStats.musicCueCount}
              </Typography>
              </Box>
              <Box sx={{ display: 'grid', gridTemplateColumns: '72px minmax(0, 1fr)', gap: 1, alignItems: 'center' }}>
                <Typography variant="caption" sx={{ color: '#94a3b8' }}>
                  时间线缩放
                </Typography>
                <Slider
                  size="small"
                  value={timelineScale}
                  min={0.8}
                  max={1.35}
                  step={null}
                  marks={TIMELINE_SCALE_OPTIONS}
                  onChange={(_, value) => setTimelineScale(Array.isArray(value) ? value[0] : value)}
                  sx={{ color: '#e5e7eb' }}
                />
              </Box>
              <Typography variant="caption" sx={{ color: '#94a3b8', gridColumn: { xs: '1', md: '1 / -1' } }}>
                当前位置：{scriptSegments.length ? safeSelectedSegmentIndex + 1 : 0} / {scriptSegments.length}
              </Typography>
            </Box>
            <Box sx={trackRowSx}>
              <Box sx={trackLabelSx}>时间尺</Box>
              <Box sx={{ display: 'flex', gap: 2, overflowX: 'auto', py: 0.5, px: 1 }}>
                {timelineTicks.map((tick) => (
                  <Typography
                    key={tick.key}
                    variant="caption"
                    sx={{ flex: '0 0 52px', color: '#94a3b8', fontSize: 10 }}
                  >
                    {tick.label}
                  </Typography>
                ))}
              </Box>
            </Box>
            <TimelineTrack
              label="文本轨"
              icon={<NotesIcon sx={{ fontSize: 16 }} />}
              color="#2563eb"
              blocks={timelineBlocks.text}
              selectedIndex={safeSelectedSegmentIndex}
              scale={timelineScale}
              onSelectBlock={handleSelectSegment}
            />
            <TimelineTrack
              label="人声轨"
              icon={<MicIcon sx={{ fontSize: 16 }} />}
              color="#16a34a"
              blocks={timelineBlocks.voice}
              selectedIndex={safeSelectedSegmentIndex}
              scale={timelineScale}
              onSelectBlock={handleSelectSegment}
            />
            <TimelineTrack
              label="音效轨"
              icon={<GraphicEqIcon sx={{ fontSize: 16 }} />}
              color="#f97316"
              blocks={timelineBlocks.sfx}
              selectedIndex={safeSelectedSegmentIndex}
              scale={timelineScale}
              onSelectBlock={handleSelectSegment}
            />
            <TimelineTrack
              label="配乐轨"
              icon={<LibraryMusicIcon sx={{ fontSize: 16 }} />}
              color={audiobookColors.brand}
              blocks={timelineBlocks.music}
              selectedIndex={safeSelectedSegmentIndex}
              scale={timelineScale}
              onSelectBlock={handleSelectSegment}
            />
          </Box>
        </Box>
      )}
    </DialogContent>
  </Dialog>
  )
}

export default ScriptEditorDialog
