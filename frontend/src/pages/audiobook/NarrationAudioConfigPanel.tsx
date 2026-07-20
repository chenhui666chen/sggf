import {
  Box,
  Checkbox,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
} from '@mui/material'

import AudioFxConfigPanel from './AudioFxConfigPanel'
import type { AudioFxConfig, AudioOutputFormat } from './types'

interface NarrationAudioConfigPanelProps {
  outputFormat: AudioOutputFormat
  generateSubtitle: boolean
  audioFxConfig: AudioFxConfig
  onOutputFormatChange: (value: AudioOutputFormat) => void
  onGenerateSubtitleChange: (value: boolean) => void
  onAudioFxConfigChange: (value: AudioFxConfig) => void
}

const NarrationAudioConfigPanel = ({
  outputFormat,
  generateSubtitle,
  audioFxConfig,
  onOutputFormatChange,
  onGenerateSubtitleChange,
  onAudioFxConfigChange,
}: NarrationAudioConfigPanelProps) => (
    <Stack spacing={2}>
      <Box
        sx={{
          p: 1.5,
          borderRadius: 1.5,
          backgroundColor: 'rgba(123, 31, 162, 0.035)',
          border: '1px solid rgba(123, 31, 162, 0.12)',
        }}
      >
        <Box sx={{ display: 'flex', gap: 1.5, flexWrap: 'wrap', alignItems: 'center' }}>
          <FormControl size="small" sx={{ minWidth: { xs: '100%', sm: 140 } }}>
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
            sx={{ m: 0 }}
            control={
              <Checkbox
                checked={generateSubtitle}
                onChange={(_, checked) => onGenerateSubtitleChange(checked)}
              />
            }
            label="生成字幕"
          />
        </Box>
      </Box>

      <AudioFxConfigPanel
        value={audioFxConfig}
        onChange={onAudioFxConfigChange}
      />
    </Stack>
  )

export default NarrationAudioConfigPanel
