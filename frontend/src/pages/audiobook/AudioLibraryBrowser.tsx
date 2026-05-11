import { useCallback, useEffect, useState } from 'react'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Tab,
  Tabs,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import MusicNoteIcon from '@mui/icons-material/MusicNote'
import PauseIcon from '@mui/icons-material/Pause'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'
import SearchIcon from '@mui/icons-material/Search'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import { useSelector } from 'react-redux'

import { apiClient } from '../../services/api'
import type { RootState } from '../../store/store'
import { audiobookColors } from './audiobookTheme'
import AudioLibraryPurgeDialog from './AudioLibraryPurgeDialog'
import SfxCandidateReviewDialog from './SfxCandidateReviewDialog'
import SfxManifestImportDialog from './SfxManifestImportDialog'

interface AudioLibraryBrowserProps {
  open: boolean
  onClose: () => void
}

interface AudioLibraryMetadata {
  source_id?: string
  source_url?: string
  author?: string
  author_url?: string
  license?: string
  license_url?: string
  license_version?: string
  license_commercial?: boolean
  attribution_required?: boolean
  attribution_text?: string
  quality_score?: number
  quality_grade?: string
  quality_status?: string
  retrieved_at?: string
  license_checked_at?: string
}

interface SfxEntry extends AudioLibraryMetadata {
  id: string
  name: string
  category: string
  style?: string
  description: string
  tags: string[]
  scenes?: string[]
  source: string
}

interface MusicEntry extends AudioLibraryMetadata {
  id: string
  style: string
  duration: number
  tempo: string
  mood: string
  bucket: string
  source: string
  variant: number | null
}

const formatQualityLabel = (entry: AudioLibraryMetadata) => {
  const score = typeof entry.quality_score === 'number' ? entry.quality_score.toFixed(1) : '未评分'
  const grade = entry.quality_grade ? `/${entry.quality_grade}` : ''
  const status = entry.quality_status ? ` ${entry.quality_status}` : ''
  return `质量 ${score}${grade}${status}`
}

const formatCommercialLabel = (entry: AudioLibraryMetadata) => {
  if (entry.license_commercial === true) return '允许商用'
  if (entry.license_commercial === false) return '非商用'
  return '商用未知'
}

const formatAttributionLabel = (entry: AudioLibraryMetadata) => {
  if (entry.attribution_required === true) return '需署名'
  if (entry.attribution_required === false) return '免署名'
  return '署名未知'
}

const formatDateLabel = (value?: string) => {
  if (!value) return ''
  return value.slice(0, 10)
}

const renderMetadata = (entry: AudioLibraryMetadata & { source: string }) => (
  <>
    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
      <Chip label={formatQualityLabel(entry)} size="small" color={entry.quality_status === 'accepted' ? 'success' : 'default'} variant="outlined" />
      <Chip label={`授权 ${entry.license || '未记录'}`} size="small" variant="outlined" title={entry.license_url || undefined} />
      <Chip label={formatCommercialLabel(entry)} size="small" variant="outlined" />
      <Chip label={formatAttributionLabel(entry)} size="small" variant="outlined" />
      {entry.author && (
        <Chip label={`作者 ${entry.author}`} size="small" variant="outlined" title={entry.author_url || undefined} />
      )}
      <Chip label={`来源 ${entry.source || '本地'}`} size="small" variant="outlined" title={entry.source_url || entry.source_id || undefined} />
      {entry.retrieved_at && <Chip label={`入库 ${formatDateLabel(entry.retrieved_at)}`} size="small" variant="outlined" />}
      {entry.license_checked_at && <Chip label={`授权检查 ${formatDateLabel(entry.license_checked_at)}`} size="small" variant="outlined" />}
    </Box>
    {entry.attribution_text && (
      <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
        {entry.attribution_text}
      </Typography>
    )}
  </>
)

const AudioLibraryBrowser = ({ open, onClose }: AudioLibraryBrowserProps) => {
  const { user } = useSelector((state: RootState) => state.auth)
  const isAdmin = user?.roles?.some((role) => role.code === 'admin' || role.code === 'super_admin') ?? false
  const [tab, setTab] = useState(0)
  const [loading, setLoading] = useState(false)
  const [sfxEntries, setSfxEntries] = useState<SfxEntry[]>([])
  const [musicEntries, setMusicEntries] = useState<MusicEntry[]>([])
  const [sfxCategories, setSfxCategories] = useState<string[]>([])
  const [sfxScenes, setSfxScenes] = useState<string[]>([])
  const [musicStyles, setMusicStyles] = useState<string[]>([])
  const [musicMoods, setMusicMoods] = useState<string[]>([])
  const [sfxCategoryFilter, setSfxCategoryFilter] = useState('')
  const [sfxSceneFilter, setSfxSceneFilter] = useState('')
  const [musicStyleFilter, setMusicStyleFilter] = useState('')
  const [musicMoodFilter, setMusicMoodFilter] = useState('')
  const [searchText, setSearchText] = useState('')
  const [playingId, setPlayingId] = useState<string | null>(null)
  const [audioEl, setAudioEl] = useState<HTMLAudioElement | null>(null)

  const [candidateReviewOpen, setCandidateReviewOpen] = useState(false)
  const [manifestImportOpen, setManifestImportOpen] = useState(false)
  const [purgeOpen, setPurgeOpen] = useState(false)

  useEffect(() => {
    if (!open) return
    const loadStats = async () => {
      try {
        const res = await apiClient.getAudioLibraryStats()
        setSfxCategories(res.data.sfx_categories)
        setSfxScenes(res.data.sfx_scenes || [])
        setMusicStyles(res.data.music_styles)
        setMusicMoods(res.data.music_moods)
      } catch { /* ignore */ }
    }
    loadStats()
  }, [open])

  const loadSfx = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.browseSoundEffects({
        category: sfxCategoryFilter || undefined,
        scene: sfxSceneFilter || undefined,
        search: searchText || undefined,
      })
      setSfxEntries(res.data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [sfxCategoryFilter, sfxSceneFilter, searchText])

  const loadMusic = useCallback(async () => {
    setLoading(true)
    try {
      const res = await apiClient.browseMusic({
        style: musicStyleFilter || undefined,
        mood: musicMoodFilter || undefined,
        search: searchText || undefined,
      })
      setMusicEntries(res.data)
    } catch { /* ignore */ }
    finally { setLoading(false) }
  }, [musicStyleFilter, musicMoodFilter, searchText])

  useEffect(() => {
    if (!open) return
    if (tab === 0) loadSfx()
    else loadMusic()
  }, [open, tab, loadSfx, loadMusic])

  useEffect(() => {
    return () => { audioEl?.pause(); setAudioEl(null) }
  }, [audioEl])

  const handlePlay = (fileType: 'sfx' | 'music', id: string) => {
    if (playingId === id) {
      audioEl?.pause()
      setPlayingId(null)
      setAudioEl(null)
      return
    }
    audioEl?.pause()
    const url = apiClient.getAudioLibraryPreviewUrl(fileType, id)
    const el = new Audio(url)
    el.addEventListener('ended', () => { setPlayingId(null); setAudioEl(null) })
    el.play().catch(() => { /* ignore */ })
    setAudioEl(el)
    setPlayingId(id)
  }

  const handleClose = () => {
    audioEl?.pause()
    setAudioEl(null)
    setPlayingId(null)
    setSearchText('')
    setSfxCategoryFilter('')
    setSfxSceneFilter('')
    setMusicStyleFilter('')
    setMusicMoodFilter('')
    setCandidateReviewOpen(false)
    setManifestImportOpen(false)
    setPurgeOpen(false)
    onClose()
  }

  const handleDeleteAsset = async (fileType: 'sfx' | 'music', id: string) => {
    if (!isAdmin) return
    if (!window.confirm('确认删除该素材？此操作会从公共素材库移除。')) return
    try {
      await apiClient.deleteAudioLibraryAsset(fileType, id, {
        dry_run: false,
        confirm: true,
      })
      if (fileType === 'sfx') await loadSfx()
      else await loadMusic()
    } catch {
      /* ignore */
    }
  }

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="md" fullWidth>
      <DialogTitle sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        音频素材库
        <IconButton onClick={handleClose} size="small">
          <CloseIcon />
        </IconButton>
      </DialogTitle>
      <DialogContent dividers>
        <Tabs value={tab} onChange={(_, v) => setTab(v)} sx={{ mb: 2 }}>
          <Tab icon={<GraphicEqIcon />} iconPosition="start" label="音效库" />
          <Tab icon={<MusicNoteIcon />} iconPosition="start" label="音乐库" />
        </Tabs>

        <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center' }}>
          <TextField
            size="small"
            placeholder="搜索素材..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            InputProps={{ startAdornment: <SearchIcon sx={{ mr: 1, color: 'text.secondary' }} /> }}
            sx={{ flex: 1 }}
          />
          {tab === 0 && (
            <>
              <FormControl size="small" sx={{ minWidth: 160 }}>
                <InputLabel>分类</InputLabel>
                <Select
                  label="分类"
                  value={sfxCategoryFilter}
                  onChange={(e) => setSfxCategoryFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {sfxCategories.map((c) => (
                    <MenuItem key={c} value={c}>{c}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 140 }}>
                <InputLabel>场景</InputLabel>
                <Select
                  label="场景"
                  value={sfxSceneFilter}
                  onChange={(e) => setSfxSceneFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {sfxScenes.map((scene) => (
                    <MenuItem key={scene} value={scene}>{scene}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </>
          )}
          {tab === 1 && (
            <>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>风格</InputLabel>
                <Select
                  label="风格"
                  value={musicStyleFilter}
                  onChange={(e) => setMusicStyleFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {musicStyles.map((s) => (
                    <MenuItem key={s} value={s}>{s}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 120 }}>
                <InputLabel>情绪</InputLabel>
                <Select
                  label="情绪"
                  value={musicMoodFilter}
                  onChange={(e) => setMusicMoodFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {musicMoods.map((m) => (
                    <MenuItem key={m} value={m}>{m}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </>
          )}
        </Box>

        <Box sx={{ display: isAdmin ? 'flex' : 'none', gap: 1, mb: isAdmin ? 2 : 0 }}>
          {tab === 0 && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<PlaylistAddCheckIcon />}
              onClick={() => setCandidateReviewOpen(true)}
            >
              候选审核
            </Button>
          )}
          {tab === 0 && (
            <Button
              size="small"
              variant="outlined"
              startIcon={<UploadFileIcon />}
              onClick={() => setManifestImportOpen(true)}
            >
              manifest 导入
            </Button>
          )}
          <Button
            size="small"
            variant="outlined"
            onClick={() => setPurgeOpen(true)}
          >
            素材清理
          </Button>
        </Box>

        {loading ? (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={28} />
          </Box>
        ) : tab === 0 ? (
          <Paper variant="outlined" sx={{ maxHeight: 480, overflow: 'auto' }}>
            {sfxEntries.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ p: 2, textAlign: 'center' }}>
                暂无音效素材
              </Typography>
            ) : (
              <List dense disablePadding>
                {sfxEntries.map((entry) => (
                  <ListItemButton
                    key={entry.id}
                    onClick={() => handlePlay('sfx', entry.id)}
                    sx={{ borderBottom: '1px solid', borderColor: 'divider' }}
                  >
                    <IconButton size="small" sx={{ mr: 1 }}>
                      {playingId === entry.id ? <PauseIcon /> : <PlayArrowIcon />}
                    </IconButton>
                    <ListItemText
                      primary={entry.name}
                      secondary={
                        <>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                            <Chip label={entry.category} size="small" variant="outlined" />
                            {(entry.scenes || []).slice(0, 2).map((scene) => (
                              <Chip key={scene} label={scene} size="small" variant="outlined" />
                            ))}
                            {entry.tags.slice(0, 3).map((t) => (
                              <Chip key={t} label={t} size="small" sx={{ backgroundColor: audiobookColors.brandFaint }} />
                            ))}
                          </Box>
                          {renderMetadata(entry)}
                        </>
                      }
                      secondaryTypographyProps={{ component: 'div' }}
                    />
                    {isAdmin && (
                      <IconButton
                        size="small"
                        color="error"
                        onClick={(event) => {
                          event.stopPropagation()
                          void handleDeleteAsset('sfx', entry.id)
                        }}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    )}
                    <Typography variant="caption" color="text.secondary">
                      {entry.source}
                    </Typography>
                  </ListItemButton>
                ))}
              </List>
            )}
          </Paper>
        ) : (
          <Paper variant="outlined" sx={{ maxHeight: 480, overflow: 'auto' }}>
            {musicEntries.length === 0 ? (
              <Typography variant="body2" color="text.secondary" sx={{ p: 2, textAlign: 'center' }}>
                暂无音乐素材
              </Typography>
            ) : (
              <List dense disablePadding>
                {musicEntries.map((entry) => (
                  <ListItemButton
                    key={entry.id}
                    onClick={() => handlePlay('music', entry.id)}
                    sx={{ borderBottom: '1px solid', borderColor: 'divider' }}
                  >
                    <IconButton size="small" sx={{ mr: 1 }}>
                      {playingId === entry.id ? <PauseIcon /> : <PlayArrowIcon />}
                    </IconButton>
                    <ListItemText
                      primary={`${entry.style} - ${entry.mood}${entry.variant != null ? ` (V${entry.variant})` : ''}`}
                      secondary={
                        <>
                          <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
                            <Chip label={entry.style} size="small" variant="outlined" />
                            <Chip label={entry.mood} size="small" sx={{ backgroundColor: audiobookColors.brandFaint }} />
                            <Chip label={`${entry.duration}s`} size="small" />
                            <Chip label={entry.tempo} size="small" />
                          </Box>
                          {renderMetadata(entry)}
                        </>
                      }
                      secondaryTypographyProps={{ component: 'div' }}
                    />
                    {isAdmin && (
                      <IconButton
                        size="small"
                        color="error"
                        onClick={(event) => {
                          event.stopPropagation()
                          void handleDeleteAsset('music', entry.id)
                        }}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    )}
                    <Typography variant="caption" color="text.secondary">
                      {entry.source}
                    </Typography>
                  </ListItemButton>
                ))}
              </List>
            )}
          </Paper>
        )}
      </DialogContent>
      <SfxCandidateReviewDialog
        open={candidateReviewOpen}
        onClose={() => setCandidateReviewOpen(false)}
      />
      <SfxManifestImportDialog
        open={manifestImportOpen}
        onClose={() => setManifestImportOpen(false)}
        onImported={loadSfx}
      />
      <AudioLibraryPurgeDialog
        open={purgeOpen}
        initialLibraryType={tab === 0 ? 'sfx' : 'music'}
        onClose={() => setPurgeOpen(false)}
        onPurged={tab === 0 ? loadSfx : loadMusic}
      />
    </Dialog>
  )
}

export default AudioLibraryBrowser
