import {
  Box,
  Chip,
  Divider,
  Paper,
  Stack,
  TextField,
  Typography,
} from '@mui/material'
import type { SxProps, Theme } from '@mui/material/styles'

import type {
  ScriptSegment,
  ScriptSegmentVoiceParams,
} from './types'
import {
  getInlineTagStrategySummary,
  getScriptSegmentVoiceParams,
  parseOptionalNumberInput,
} from './scriptSegmentCardUtils'
import { modelUsesBasicNumericSpeedControl } from './ttsModels'

interface ScriptSegmentDetailsPanelProps {
  segment: ScriptSegment
  index: number
  onUpdateSegment: (index: number, patch: Partial<ScriptSegment>) => void
  sx?: SxProps<Theme>
  mutedTextColor?: string
}

const ScriptSegmentDetailsPanel = ({
  segment,
  index,
  onUpdateSegment,
  sx,
  mutedTextColor,
}: ScriptSegmentDetailsPanelProps) => {
  const voiceParams = getScriptSegmentVoiceParams(segment)
  const inlineTagStrategy = getInlineTagStrategySummary(segment)
  const segmentTtsModel = voiceParams.resolved_tts_model || voiceParams.tts_model
  const showNumericSpeedControl = modelUsesBasicNumericSpeedControl(segmentTtsModel)
  const mutedCaptionSx = {
    color: mutedTextColor || 'text.secondary',
    display: 'block',
    mb: 0.5,
  } as const

  const updateVoiceParams = (patch: Partial<ScriptSegmentVoiceParams>) => {
    onUpdateSegment(index, { voice_params: { ...voiceParams, ...patch } })
  }

  return (
    <Paper
      variant="outlined"
      sx={[
        {
          mt: 1,
          p: 1,
          borderStyle: 'dashed',
        },
        ...(Array.isArray(sx) ? sx : sx ? [sx] : []),
      ]}
    >
      <Typography variant="caption" sx={mutedCaptionSx}>
        详细信息
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        表演提示：{segment.performance_notes || '—'}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        原文：{segment.original_text || '—'}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        改编原因：{segment.adaptation_reason || '—'}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        停顿：前 {segment.pause_before ?? '—'}s / 后 {segment.pause_after ?? '—'}s
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        Instruct：{segment.instruct_emotion || '—'} / {segment.instruct_scene || '—'} / {segment.instruct_role || '—'} / {segment.instruct_identity || '—'}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        音色参数：{Object.keys(voiceParams).length > 0 ? JSON.stringify(voiceParams) : '—'}
      </Typography>
      {inlineTagStrategy && (
        <Box sx={{ mt: 0.75 }}>
          <Typography variant="caption" sx={mutedCaptionSx}>
            标签注入策略
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            {inlineTagStrategy.modelFamily && (
              <Chip size="small" label={`模型：${inlineTagStrategy.modelFamily}`} />
            )}
            {inlineTagStrategy.placement && (
              <Chip size="small" label={`位置：${inlineTagStrategy.placement}`} />
            )}
            {inlineTagStrategy.useTagParser && (
              <Chip size="small" label="Tag Parser" color="primary" variant="outlined" />
            )}
            {inlineTagStrategy.tags.map((tag) => (
              <Chip key={tag} size="small" label={tag} variant="outlined" />
            ))}
          </Stack>
        </Box>
      )}
      <Typography variant="caption" sx={{ display: 'block' }}>
        音效：{segment.sound_effects ? JSON.stringify(segment.sound_effects) : (segment.sound_effects_simple ? JSON.stringify(segment.sound_effects_simple) : '—')}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        配乐：{segment.music_cue ? JSON.stringify(segment.music_cue) : (segment.music_cue_simple || '—')}
      </Typography>
      <Divider sx={{ my: 1 }} />
      <Typography variant="caption" sx={mutedCaptionSx}>
        音频提示词（可编辑）
      </Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1 }}>
        <TextField
          size="small"
          label="停顿-前(s)"
          type="number"
          value={segment.pause_before ?? ''}
          onChange={(event) =>
            onUpdateSegment(index, { pause_before: parseOptionalNumberInput(event.target.value) })
          }
        />
        <TextField
          size="small"
          label="停顿-后(s)"
          type="number"
          value={segment.pause_after ?? ''}
          onChange={(event) =>
            onUpdateSegment(index, { pause_after: parseOptionalNumberInput(event.target.value) })
          }
        />
        <TextField
          size="small"
          label="Instruct 情感"
          value={segment.instruct_emotion || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_emotion: event.target.value })
          }
        />
        <TextField
          size="small"
          label="Instruct 场景"
          value={segment.instruct_scene || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_scene: event.target.value })
          }
        />
        <TextField
          size="small"
          label="Instruct 角色"
          value={segment.instruct_role || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_role: event.target.value })
          }
        />
        <TextField
          size="small"
          label="Instruct 身份"
          value={segment.instruct_identity || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_identity: event.target.value })
          }
        />
      </Box>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1, mt: 1 }}>
        {showNumericSpeedControl && (
          <TextField
            size="small"
            label="语速 rate"
            type="number"
            value={voiceParams.rate ?? voiceParams.speed ?? ''}
            onChange={(event) => updateVoiceParams({ rate: parseOptionalNumberInput(event.target.value) })}
          />
        )}
        <TextField
          size="small"
          label="音量 volume"
          type="number"
          value={voiceParams.volume ?? ''}
          onChange={(event) => updateVoiceParams({ volume: parseOptionalNumberInput(event.target.value) })}
        />
      </Box>
    </Paper>
  )
}

export default ScriptSegmentDetailsPanel
