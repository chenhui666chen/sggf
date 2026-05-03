import {
  Box,
  Checkbox,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Typography,
} from '@mui/material'

import { audiobookColors } from './audiobookTheme'
import type { AudioFxConfig } from './types'

interface AudioFxConfigPanelProps {
  value: AudioFxConfig
  onChange: (value: AudioFxConfig) => void
}

const AudioFxConfigPanel = ({ value, onChange }: AudioFxConfigPanelProps) => {
  const updateValue = (patch: Partial<AudioFxConfig>) => {
    onChange({ ...value, ...patch })
  }

  return (
    <Paper
      variant="outlined"
      sx={{
        mb: 2,
        p: 2,
        backgroundColor: audiobookColors.brandFaint,
      }}
    >
      <Typography variant="subtitle2" sx={{ mb: 1 }}>
        音效与背景音乐
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        这里的设置会作为项目级默认配置保存，下次进入该项目会自动带出，并影响音效/配乐是否启用及大致密度。
      </Typography>
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <FormControlLabel
            control={
              <Checkbox
                checked={value.enable_sound_effects}
                onChange={(_, checked) => updateValue({ enable_sound_effects: checked })}
                color="primary"
              />
            }
            label="开启音效（环境音 + 关键动作音）"
          />
          <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!value.enable_sound_effects}>
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
        </Grid>
        <Grid item xs={12} md={6}>
          <FormControlLabel
            control={
              <Checkbox
                checked={value.enable_music}
                onChange={(_, checked) => updateValue({ enable_music: checked })}
                color="primary"
              />
            }
            label="开启背景音乐（AI 配乐）"
          />
          <FormControl size="small" sx={{ mt: 1, minWidth: 200 }} disabled={!value.enable_music}>
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
        </Grid>
      </Grid>

      {value.enable_sound_effects && (
        <Box sx={{ mt: 2, p: 1.5, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            提示：音效将由 AI 根据章节内容智能匹配，支持大雨、街道、森林等场景识别。
          </Typography>
        </Box>
      )}
    </Paper>
  )
}

export default AudioFxConfigPanel
