import {
  Box,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
} from '@mui/material'

import AudioFxConfigPanel from './AudioFxConfigPanel'
import type { AudioEngineMode, AudioFxConfig, AudioOutputFormat } from './types'

interface NarrationAudioConfigPanelProps {
  outputFormat: AudioOutputFormat
  audioFxConfig: AudioFxConfig
  audioEngineMode: AudioEngineMode
  onOutputFormatChange: (value: AudioOutputFormat) => void
  onAudioFxConfigChange: (value: AudioFxConfig) => void
}

const NarrationAudioConfigPanel = ({
  outputFormat,
  audioFxConfig,
  audioEngineMode,
  onOutputFormatChange,
  onAudioFxConfigChange,
}: NarrationAudioConfigPanelProps) => (
    <Stack spacing={2}>
      <Box
        sx={{
          p: 1.5,
          borderRadius: 1,
          backgroundColor: 'action.hover',
          border: '1px solid',
          borderColor: 'divider',
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
        </Box>
      </Box>

      {audioEngineMode !== 'seed_scene' && (
        <AudioFxConfigPanel
          value={audioFxConfig}
          onChange={onAudioFxConfigChange}
        />
      )}
    </Stack>
  )

export default NarrationAudioConfigPanel
