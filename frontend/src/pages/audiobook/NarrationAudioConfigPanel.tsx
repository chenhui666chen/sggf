import {
  Box,
  FormControl,
  FormLabel,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  ToggleButton,
  ToggleButtonGroup,
} from '@mui/material'
import AutoAwesomeIcon from '@mui/icons-material/AutoAwesome'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'

import AudioFxConfigPanel from './AudioFxConfigPanel'
import type { AudioEngineMode, AudioFxConfig, AudioOutputFormat } from './types'

interface NarrationAudioConfigPanelProps {
  outputFormat: AudioOutputFormat
  audioFxConfig: AudioFxConfig
  audioEngineMode: AudioEngineMode
  onOutputFormatChange: (value: AudioOutputFormat) => void
  onAudioFxConfigChange: (value: AudioFxConfig) => void
  onAudioEngineModeChange: (value: AudioEngineMode) => void
}

const NarrationAudioConfigPanel = ({
  outputFormat,
  audioFxConfig,
  audioEngineMode,
  onOutputFormatChange,
  onAudioFxConfigChange,
  onAudioEngineModeChange,
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
          <FormControl sx={{ minWidth: { xs: '100%', sm: 244 } }}>
            <FormLabel sx={{ mb: 0.75, typography: 'caption', color: 'text.secondary' }}>
              生成引擎
            </FormLabel>
            <ToggleButtonGroup
              exclusive
              size="small"
              fullWidth
              aria-label="生成引擎"
              value={audioEngineMode}
              onChange={(_, value: AudioEngineMode | null) => {
                if (value) onAudioEngineModeChange(value)
              }}
              sx={{
                height: 36,
                '& .MuiToggleButton-root': {
                  gap: 0.75,
                  px: 1.25,
                  letterSpacing: 0,
                  whiteSpace: 'nowrap',
                },
              }}
            >
              <ToggleButton value="legacy_stems" aria-label="分轨合成">
                <GraphicEqIcon fontSize="small" />
                分轨合成
              </ToggleButton>
              <ToggleButton value="seed_scene" aria-label="场景生成">
                <AutoAwesomeIcon fontSize="small" />
                场景生成
              </ToggleButton>
            </ToggleButtonGroup>
          </FormControl>
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

      <AudioFxConfigPanel
        value={audioFxConfig}
        onChange={onAudioFxConfigChange}
      />
    </Stack>
  )

export default NarrationAudioConfigPanel
