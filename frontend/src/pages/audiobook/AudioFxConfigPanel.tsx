import { useState } from 'react'
import {
  Box,
  Button,
  Checkbox,
  Collapse,
  FormControl,
  FormControlLabel,
  Grid,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Slider,
  Typography,
} from '@mui/material'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
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
  const [advancedOpen, setAdvancedOpen] = useState(false)
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
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 1 }}>
        <Typography variant="subtitle2">
          音效与背景音乐
        </Typography>
        <Button
          size="small"
          variant="outlined"
          startIcon={<LibraryMusicIcon />}
          onClick={() => setLibraryBrowserOpen(true)}
        >
          浏览素材库
        </Button>
      </Box>
      <AudioLibraryBrowser
        open={libraryBrowserOpen}
        onClose={() => setLibraryBrowserOpen(false)}
      />
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        这里的设置会作为项目级默认配置保存，下次进入该项目会自动带出，并影响音效/配乐是否启用及大致密度。
      </Typography>
      <Grid container spacing={2}>
        <Grid item xs={12} md={6}>
          <FormControlLabel
            control={
              <Checkbox
                checked={value.enable_sound_effects}
                onChange={(_, checked) =>
                  updateValue(buildSoundEffectsTogglePatch(checked, value.sound_effect_density))
                }
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
                onChange={(_, checked) =>
                  updateValue(buildMusicTogglePatch(checked, value.music_density))
                }
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
      {value.enable_music && (
        <Box sx={{ mt: 2, p: 1.5, backgroundColor: audiobookColors.infoSoft, borderRadius: 1 }}>
          <Typography variant="caption" color="text.secondary">
            提示：配乐将由 AI 根据情节节奏和情感基调自动设计，支持悬疑、史诗、浪漫等多种风格。
          </Typography>
        </Box>
      )}

      <Box sx={{ mt: 2 }}>
        <Button
          size="small"
          variant="text"
          endIcon={advancedOpen ? <ExpandLessIcon /> : <ExpandMoreIcon />}
          onClick={() => setAdvancedOpen(!advancedOpen)}
        >
          高级选项
        </Button>
        <Collapse in={advancedOpen}>
          <Paper variant="outlined" sx={{ p: 2, mt: 1 }}>
            <Grid container spacing={2}>
              <Grid item xs={12}>
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={value.intelligent_balance ?? false}
                      onChange={(_, checked) => updateValue({ intelligent_balance: checked })}
                      color="primary"
                    />
                  }
                  label="智能音量平衡（自动调节 BGM/音效与旁白之间的音量比例）"
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <FormControl size="small" fullWidth disabled={value.balance_strategy === 'none'}>
                  <InputLabel>平衡策略</InputLabel>
                  <Select
                    label="平衡策略"
                    value={value.balance_strategy || 'auto'}
                    onChange={(event) =>
                      updateValue({ balance_strategy: event.target.value as AudioFxConfig['balance_strategy'] })
                    }
                  >
                    <MenuItem value="auto">自动（推荐）</MenuItem>
                    <MenuItem value="ducking">闪避（旁白时压低背景音）</MenuItem>
                    <MenuItem value="sidechain">侧链压缩（更平滑的过渡）</MenuItem>
                    <MenuItem value="none">不使用平衡策略</MenuItem>
                  </Select>
                </FormControl>
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="caption" color="text.secondary" gutterBottom>
                  BGM 音量：{Math.round((value.bgm_volume ?? 0.7) * 100)}%
                </Typography>
                <Slider
                  size="small"
                  min={0}
                  max={1}
                  step={0.05}
                  value={value.bgm_volume ?? 0.7}
                  onChange={(_, v) => updateValue({ bgm_volume: v as number })}
                  disabled={!value.enable_music}
                  valueLabelDisplay="auto"
                  valueLabelFormat={(v) => `${Math.round(v * 100)}%`}
                />
              </Grid>
              <Grid item xs={12} md={6}>
                <Typography variant="caption" color="text.secondary" gutterBottom>
                  音效音量：{Math.round((value.sfx_volume ?? 0.8) * 100)}%
                </Typography>
                <Slider
                  size="small"
                  min={0}
                  max={1}
                  step={0.05}
                  value={value.sfx_volume ?? 0.8}
                  onChange={(_, v) => updateValue({ sfx_volume: v as number })}
                  disabled={!value.enable_sound_effects}
                  valueLabelDisplay="auto"
                  valueLabelFormat={(v) => `${Math.round(v * 100)}%`}
                />
              </Grid>
            </Grid>
          </Paper>
        </Collapse>
      </Box>
    </Paper>
  )
}

export default AudioFxConfigPanel
