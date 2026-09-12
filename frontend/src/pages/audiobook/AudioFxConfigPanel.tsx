import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import {
  Box,
  Button,
  Checkbox,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from '@mui/material'
import LibraryMusicIcon from '@mui/icons-material/LibraryMusic'

import { audiobookColors } from './audiobookTheme'
import AudioLibraryBrowser from './AudioLibraryBrowser'
import {
  buildMusicTogglePatch,
  buildSoundEffectsTogglePatch,
} from './audioFxConfigPanelUtils'
import type { AudioFxConfig } from './types'

interface AudioFxConfigPanelProps {
  value: AudioFxConfig
  onChange: (value: AudioFxConfig) => void
}

const AudioFxConfigPanel = ({ value, onChange }: AudioFxConfigPanelProps) => {
  const { t } = useTranslation()
  const [libraryBrowserOpen, setLibraryBrowserOpen] = useState(false)
  const updateValue = (patch: Partial<AudioFxConfig>) => {
    onChange({ ...value, ...patch })
  }

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 1.5,
        backgroundColor: audiobookColors.collectSoft,
        border: `1px solid ${audiobookColors.surfaceBorder}`,
      }}
    >
      <Box
        sx={{
          display: 'flex',
          alignItems: { xs: 'stretch', sm: 'center' },
          justifyContent: 'space-between',
          gap: 1,
          mb: 1,
          flexDirection: { xs: 'column', sm: 'row' },
        }}
      >
        <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
          {t('audiobook.audioFxConfigPanel.title')}
        </Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LibraryMusicIcon />}
          onClick={() => setLibraryBrowserOpen(true)}
          sx={{ alignSelf: { xs: 'flex-start', sm: 'center' } }}
        >
          {t('audiobook.audioFxConfigPanel.browseLibrary')}
        </Button>
      </Box>
      <AudioLibraryBrowser
        open={libraryBrowserOpen}
        onClose={() => setLibraryBrowserOpen(false)}
      />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        {t('audiobook.audioFxConfigPanel.hint')}
      </Typography>
      <Grid container spacing={1.5}>
        <Grid item xs={12} md={6}>
          <Stack spacing={1}>
            <FormControlLabel
              sx={{ m: 0 }}
              control={
                <Checkbox
                  checked={value.enable_sound_effects}
                  onChange={(_, checked) =>
                    updateValue(buildSoundEffectsTogglePatch(checked, value.sound_effect_density))
                  }
                  color="primary"
                />
              }
              label={t('audiobook.audioFxConfigPanel.enableSfx')}
            />
            <FormControl size="small" fullWidth disabled={!value.enable_sound_effects}>
              <InputLabel>{t('audiobook.audioFxConfigPanel.sfxDensity')}</InputLabel>
              <Select
                label={t('audiobook.audioFxConfigPanel.sfxDensity')}
                value={value.sound_effect_density}
                onChange={(event) =>
                  updateValue({
                    sound_effect_density: event.target.value as AudioFxConfig['sound_effect_density'],
                  })
                }
              >
                <MenuItem value="off">{t('audiobook.audioFxConfigPanel.sfxOff')}</MenuItem>
                <MenuItem value="low">{t('audiobook.audioFxConfigPanel.sfxLow')}</MenuItem>
                <MenuItem value="medium">{t('audiobook.audioFxConfigPanel.sfxMedium')}</MenuItem>
                <MenuItem value="high">{t('audiobook.audioFxConfigPanel.sfxHigh')}</MenuItem>
              </Select>
            </FormControl>
          </Stack>
        </Grid>
        <Grid item xs={12} md={6}>
          <Stack spacing={1}>
            <FormControlLabel
              sx={{ m: 0 }}
              control={
                <Checkbox
                  checked={value.enable_music}
                  onChange={(_, checked) =>
                    updateValue(buildMusicTogglePatch(checked, value.music_density))
                  }
                  color="primary"
                />
              }
              label={t('audiobook.audioFxConfigPanel.enableMusic')}
            />
            <FormControl size="small" fullWidth disabled={!value.enable_music}>
              <InputLabel>{t('audiobook.audioFxConfigPanel.musicDensity')}</InputLabel>
              <Select
                label={t('audiobook.audioFxConfigPanel.musicDensity')}
                value={value.music_density}
                onChange={(event) =>
                  updateValue({
                    music_density: event.target.value as AudioFxConfig['music_density'],
                  })
                }
              >
                <MenuItem value="off">{t('audiobook.audioFxConfigPanel.musicOff')}</MenuItem>
                <MenuItem value="low">{t('audiobook.audioFxConfigPanel.musicLow')}</MenuItem>
                <MenuItem value="medium">{t('audiobook.audioFxConfigPanel.musicMedium')}</MenuItem>
                <MenuItem value="high">{t('audiobook.audioFxConfigPanel.musicHigh')}</MenuItem>
              </Select>
            </FormControl>
          </Stack>
        </Grid>
      </Grid>

      {value.enable_sound_effects && (
        <Box sx={{ mt: 1.5, p: 1.25, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {t('audiobook.audioFxConfigPanel.sfxHint')}
          </Typography>
        </Box>
      )}
      {value.enable_music && (
        <Box sx={{ mt: 1.5, p: 1.25, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            {t('audiobook.audioFxConfigPanel.musicHint')}
          </Typography>
        </Box>
      )}
    </Box>
  )
}

export default AudioFxConfigPanel
