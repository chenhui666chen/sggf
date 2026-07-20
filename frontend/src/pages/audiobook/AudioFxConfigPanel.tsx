import { useState } from 'react'
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
  const [libraryBrowserOpen, setLibraryBrowserOpen] = useState(false)
  const updateValue = (patch: Partial<AudioFxConfig>) => {
    onChange({ ...value, ...patch })
  }

  return (
    <Box
      sx={{
        p: 1.5,
        borderRadius: 1.5,
        backgroundColor: 'rgba(0, 137, 123, 0.035)',
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
          音效与配乐
        </Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LibraryMusicIcon />}
          onClick={() => setLibraryBrowserOpen(true)}
          sx={{ alignSelf: { xs: 'flex-start', sm: 'center' } }}
        >
          浏览素材库
        </Button>
      </Box>
      <AudioLibraryBrowser
        open={libraryBrowserOpen}
        onClose={() => setLibraryBrowserOpen(false)}
      />
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1.5 }}>
        这里的设置会作为项目级默认配置保存，下次进入该项目会自动带出，并影响音效/配乐是否启用及大致密度。
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
              label="开启音效"
            />
            <FormControl size="small" fullWidth disabled={!value.enable_sound_effects}>
              <InputLabel>音效密度</InputLabel>
              <Select
                label="音效密度"
                value={value.sound_effect_density}
                onChange={(event) =>
                  updateValue({
                    sound_effect_density: event.target.value as AudioFxConfig['sound_effect_density'],
                  })
                }
              >
                <MenuItem value="off">关闭（不使用音效）</MenuItem>
                <MenuItem value="low">稀疏（仅关键场景）</MenuItem>
                <MenuItem value="medium">适中（推荐）</MenuItem>
                <MenuItem value="high">丰富（沉浸感更强）</MenuItem>
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
              label="开启配乐"
            />
            <FormControl size="small" fullWidth disabled={!value.enable_music}>
              <InputLabel>配乐密度</InputLabel>
              <Select
                label="配乐密度"
                value={value.music_density}
                onChange={(event) =>
                  updateValue({
                    music_density: event.target.value as AudioFxConfig['music_density'],
                  })
                }
              >
                <MenuItem value="off">关闭（不使用配乐）</MenuItem>
                <MenuItem value="low">稀疏（仅片头/片尾）</MenuItem>
                <MenuItem value="medium">适中（推荐）</MenuItem>
                <MenuItem value="high">丰富（几乎全程有配乐）</MenuItem>
              </Select>
            </FormControl>
          </Stack>
        </Grid>
      </Grid>

      {value.enable_sound_effects && (
        <Box sx={{ mt: 1.5, p: 1.25, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            提示：音效将由 AI 根据章节内容智能匹配，支持大雨、街道、森林等场景识别。
          </Typography>
        </Box>
      )}
      {value.enable_music && (
        <Box sx={{ mt: 1.5, p: 1.25, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            提示：配乐将由 AI 根据情节节奏和情感基调自动设计，支持悬疑、史诗、浪漫等多种风格。
          </Typography>
        </Box>
      )}
    </Box>
  )
}

export default AudioFxConfigPanel
