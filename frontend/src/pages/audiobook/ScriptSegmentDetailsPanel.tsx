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
import { useTranslation } from 'react-i18next'

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
  const { t } = useTranslation()
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
        {t('audiobook.scriptSegmentDetailsPanel.detailsTitle')}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.performanceNotes', { value: segment.performance_notes || '—' })}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.originalText', { value: segment.original_text || '—' })}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.adaptationReason', { value: segment.adaptation_reason || '—' })}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.pauseLabel', {
          before: segment.pause_before ?? '—',
          after: segment.pause_after ?? '—',
        })}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.instructLabel', {
          emotion: segment.instruct_emotion || '—',
          scene: segment.instruct_scene || '—',
          role: segment.instruct_role || '—',
          identity: segment.instruct_identity || '—',
        })}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.voiceParamsLabel', {
          value: Object.keys(voiceParams).length > 0 ? JSON.stringify(voiceParams) : '—',
        })}
      </Typography>
      {inlineTagStrategy && (
        <Box sx={{ mt: 0.75 }}>
          <Typography variant="caption" sx={mutedCaptionSx}>
            {t('audiobook.scriptSegmentDetailsPanel.tagStrategyTitle')}
          </Typography>
          <Stack direction="row" spacing={0.75} useFlexGap flexWrap="wrap">
            {inlineTagStrategy.modelFamily && (
              <Chip size="small" label={t('audiobook.scriptSegmentDetailsPanel.modelChip', { value: inlineTagStrategy.modelFamily })} />
            )}
            {inlineTagStrategy.placement && (
              <Chip size="small" label={t('audiobook.scriptSegmentDetailsPanel.placementChip', { value: inlineTagStrategy.placement })} />
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
        {t('audiobook.scriptSegmentDetailsPanel.sfxLabel', {
          value: segment.sound_effects
            ? JSON.stringify(segment.sound_effects)
            : (segment.sound_effects_simple ? JSON.stringify(segment.sound_effects_simple) : '—'),
        })}
      </Typography>
      <Typography variant="caption" sx={{ display: 'block' }}>
        {t('audiobook.scriptSegmentDetailsPanel.bgmLabel', {
          value: segment.music_cue
            ? JSON.stringify(segment.music_cue)
            : (segment.music_cue_simple || '—'),
        })}
      </Typography>
      <Divider sx={{ my: 1 }} />
      <Typography variant="caption" sx={mutedCaptionSx}>
        {t('audiobook.scriptSegmentDetailsPanel.audioPromptTitle')}
      </Typography>
      <Box sx={{ display: 'grid', gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' }, gap: 1 }}>
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.pauseBeforeLabel')}
          type="number"
          value={segment.pause_before ?? ''}
          onChange={(event) =>
            onUpdateSegment(index, { pause_before: parseOptionalNumberInput(event.target.value) })
          }
        />
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.pauseAfterLabel')}
          type="number"
          value={segment.pause_after ?? ''}
          onChange={(event) =>
            onUpdateSegment(index, { pause_after: parseOptionalNumberInput(event.target.value) })
          }
        />
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.instructEmotionLabel')}
          value={segment.instruct_emotion || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_emotion: event.target.value })
          }
        />
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.instructSceneLabel')}
          value={segment.instruct_scene || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_scene: event.target.value })
          }
        />
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.instructRoleLabel')}
          value={segment.instruct_role || ''}
          onChange={(event) =>
            onUpdateSegment(index, { instruct_role: event.target.value })
          }
        />
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.instructIdentityLabel')}
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
            label={t('audiobook.scriptSegmentDetailsPanel.rateLabel')}
            type="number"
            value={voiceParams.rate ?? voiceParams.speed ?? ''}
            onChange={(event) => updateVoiceParams({ rate: parseOptionalNumberInput(event.target.value) })}
          />
        )}
        <TextField
          size="small"
          label={t('audiobook.scriptSegmentDetailsPanel.volumeLabel')}
          type="number"
          value={voiceParams.volume ?? ''}
          onChange={(event) => updateVoiceParams({ volume: parseOptionalNumberInput(event.target.value) })}
        />
      </Box>
    </Paper>
  )
}

export default ScriptSegmentDetailsPanel
