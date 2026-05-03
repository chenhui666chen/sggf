import { useEffect, useState } from 'react'

import {
  Box,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
} from '@mui/material'

import NarrationStyleSelector from '../../components/audiobook/NarrationStyleSelector'
import { apiClient } from '../../services/api'
import AudioFxConfigPanel from './AudioFxConfigPanel'
import { audiobookColors } from './audiobookTheme'
import {
  NARRATION_STYLE_OPTIONS,
  normalizeNarrationStyleOptions,
  normalizeNarrationStyleValue,
  type NarrationStyleId,
  type NarrationStyleOption,
} from './narrationStyles'
import type { AudioFxConfig, AudioOutputFormat, TtsModel } from './types'
import {
  getTtsModelLabel,
  normalizeTtsModelValue,
} from './ttsModels'

interface NarrationAudioConfigPanelProps {
  narrationStyle: NarrationStyleId
  narrationStylePrompt: string
  ttsModel: TtsModel
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  audioFxConfig: AudioFxConfig
  onNarrationStyleChange: (value: NarrationStyleId) => void
  onNarrationStylePromptChange: (value: string) => void
  onOutputFormatChange: (value: AudioOutputFormat) => void
  onGenerateSubtitleChange: (value: boolean) => void
  onAudioFxConfigChange: (value: AudioFxConfig) => void
}

const NarrationAudioConfigPanel = ({
  narrationStyle,
  narrationStylePrompt,
  ttsModel,
  outputFormat,
  generateSubtitle,
  audioFxConfig,
  onNarrationStyleChange,
  onNarrationStylePromptChange,
  onOutputFormatChange,
  onGenerateSubtitleChange,
  onAudioFxConfigChange,
}: NarrationAudioConfigPanelProps) => {
  const [narrationStyleOptions, setNarrationStyleOptions] = useState<readonly NarrationStyleOption[]>(
    NARRATION_STYLE_OPTIONS,
  )

  useEffect(() => {
    let active = true

    apiClient.getNarrationStyles()
      .then((response) => {
        if (active) {
          setNarrationStyleOptions(normalizeNarrationStyleOptions(response.data))
        }
      })
      .catch(() => {
        if (active) {
          setNarrationStyleOptions(NARRATION_STYLE_OPTIONS)
        }
      })

    return () => {
      active = false
    }
  }, [])

  return (
    <>
      <Paper
        variant="outlined"
        sx={{
          mb: 2,
          p: 2,
          backgroundColor: audiobookColors.brandFaint,
        }}
      >
        <NarrationStyleSelector
          styles={narrationStyleOptions}
          selectedStyle={narrationStyle}
          customPrompt={narrationStylePrompt}
          onStyleChange={(styleId) => onNarrationStyleChange(normalizeNarrationStyleValue(styleId))}
          onPromptChange={onNarrationStylePromptChange}
          currentModel={ttsModel}
          formatModelLabel={(modelId) => {
            const normalizedModel = normalizeTtsModelValue(modelId)
            return normalizedModel ? getTtsModelLabel(normalizedModel) : modelId
          }}
        />
        <Box sx={{ mt: 2, display: 'flex', gap: 2, flexWrap: 'wrap', alignItems: 'center' }}>
          <FormControl size="small" sx={{ minWidth: 140 }}>
            <InputLabel>输出格式</InputLabel>
            <Select
              label="输出格式"
              value={outputFormat}
              onChange={(event) => onOutputFormatChange(event.target.value as AudioOutputFormat)}
            >
              <MenuItem value="mp3">MP3</MenuItem>
              <MenuItem value="wav">WAV</MenuItem>
              <MenuItem value="m4b">M4B</MenuItem>
            </Select>
          </FormControl>
          <FormControlLabel
            control={
              <Checkbox
                checked={generateSubtitle}
                onChange={(_, checked) => onGenerateSubtitleChange(checked)}
              />
            }
            label="生成字幕"
          />
        </Box>
      </Paper>

      <AudioFxConfigPanel
        value={audioFxConfig}
        onChange={onAudioFxConfigChange}
      />
    </>
  )
}

export default NarrationAudioConfigPanel
