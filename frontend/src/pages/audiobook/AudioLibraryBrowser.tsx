import { memo, useCallback, useEffect, useRef, useState } from 'react'
import {
  Box,
  Button,
  Chip,
  CircularProgress,
  Collapse,
  Dialog,
  DialogContent,
  DialogTitle,
  FormControl,
  IconButton,
  InputLabel,
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
import { useVirtualizer } from '@tanstack/react-virtual'
import CloseIcon from '@mui/icons-material/Close'
import GraphicEqIcon from '@mui/icons-material/GraphicEq'
import MusicNoteIcon from '@mui/icons-material/MusicNote'
import PauseIcon from '@mui/icons-material/Pause'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PlaylistAddCheckIcon from '@mui/icons-material/PlaylistAddCheck'
import SearchIcon from '@mui/icons-material/Search'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import InfoOutlinedIcon from '@mui/icons-material/InfoOutlined'
import { useSelector } from 'react-redux'

import { apiClient } from '../../services/api'
import type { RootState } from '../../store/store'
import { audiobookColors } from './audiobookTheme'
import {
  buildAudioLibraryDetailItems,
  formatAudioAssetNameLabel,
  formatAudioKeywordLabel,
  formatMusicDurationLabel,
  formatSfxCategoryLabel,
  getVisibleSfxScenes,
  getVisibleSfxTags,
} from './audioLibraryDisplay'
import AudioLibraryPurgeDialog from './AudioLibraryPurgeDialog'
import SfxCandidateReviewDialog from './SfxCandidateReviewDialog'
import SfxManifestImportDialog from './SfxManifestImportDialog'
import { useAudiobookAudioPlayback } from './useAudiobookAudioPlayback'

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

type AudioLibraryEntry = SfxEntry | MusicEntry
type AudioLibraryType = 'sfx' | 'music'

const detailButtonSx = {
  mt: 0.75,
  px: 0,
  minWidth: 0,
  justifyContent: 'flex-start',
  fontSize: 12,
}

const estimateLibraryRowHeight = (entry: AudioLibraryEntry, expanded: boolean) => {
  const tagRows = 'tags' in entry
    ? Math.ceil((2 + getVisibleSfxTags(entry.tags).slice(0, 3).length) / 4)
    : 1
  return expanded ? 188 + tagRows * 24 : 92 + tagRows * 20
}

const renderDetailPanel = (entry: AudioLibraryMetadata & { source: string }) => (
  <Box
    sx={{
      mt: 1,
      display: 'grid',
      gridTemplateColumns: { xs: '1fr', sm: 'repeat(2, minmax(0, 1fr))' },
      gap: 0.75,
      color: 'text.secondary',
    }}
  >
    {buildAudioLibraryDetailItems(entry).map((item) => (
      <Typography
        key={item.key}
        variant="caption"
        title={item.title}
        sx={{
          display: 'block',
          overflowWrap: 'anywhere',
        }}
      >
        <Box component="span" sx={{ color: 'text.primary', fontWeight: 600 }}>
          {item.label}：
        </Box>
        {item.value}
      </Typography>
    ))}
  </Box>
)

interface AudioLibraryRowProps {
  entry: AudioLibraryEntry
  fileType: AudioLibraryType
  isAdmin: boolean
  isExpanded: boolean
  isPlaying: boolean
  isPreviewLoading: boolean
  onDeleteAsset: (fileType: AudioLibraryType, id: string) => void
  onPlay: (fileType: AudioLibraryType, id: string) => void
  onToggleDetail: (fileType: AudioLibraryType, id: string) => void
}

const AudioLibraryRow = memo(({
  entry,
  fileType,
  isAdmin,
  isExpanded,
  isPlaying,
  isPreviewLoading,
  onDeleteAsset,
  onPlay,
  onToggleDetail,
}: AudioLibraryRowProps) => {
  const isSfx = fileType === 'sfx'
  const sfxEntry = isSfx ? entry as SfxEntry : null
  const musicEntry = isSfx ? null : entry as MusicEntry

  return (
    <ListItemButton
      component="div"
      onClick={() => { onPlay(fileType, entry.id) }}
      sx={{ borderBottom: '1px solid', borderColor: 'divider', alignItems: 'flex-start', py: 1.25 }}
    >
      <IconButton size="small" disabled={isPreviewLoading} sx={{ mr: 1, mt: 0.25 }}>
        {isPreviewLoading ? <CircularProgress size={18} /> : isPlaying ? <PauseIcon /> : <PlayArrowIcon />}
      </IconButton>
      <ListItemText
        primary={
          isSfx
            ? formatAudioAssetNameLabel(sfxEntry?.name)
            : `${formatAudioKeywordLabel(musicEntry?.style)} - ${formatAudioKeywordLabel(musicEntry?.mood)}${musicEntry?.variant != null ? `（变体 ${musicEntry.variant}）` : ''}`
        }
        primaryTypographyProps={{ sx: { fontWeight: 600, overflowWrap: 'anywhere' } }}
        secondary={
          <>
            <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', mt: 0.5 }}>
              {sfxEntry ? (
                <>
                  <Chip label={`分类：${formatSfxCategoryLabel(sfxEntry.category)}`} size="small" variant="outlined" />
                  {getVisibleSfxScenes(sfxEntry.scenes).slice(0, 2).map((scene) => (
                    <Chip key={scene} label={`场景：${formatAudioKeywordLabel(scene)}`} size="small" variant="outlined" />
                  ))}
                  {getVisibleSfxTags(sfxEntry.tags).slice(0, 3).map((tag) => (
                    <Chip key={tag} label={formatAudioKeywordLabel(tag)} size="small" sx={{ backgroundColor: audiobookColors.brandFaint }} />
                  ))}
                </>
              ) : musicEntry ? (
                <>
                  <Chip label={`风格：${formatAudioKeywordLabel(musicEntry.style)}`} size="small" variant="outlined" />
                  <Chip label={`情绪：${formatAudioKeywordLabel(musicEntry.mood)}`} size="small" sx={{ backgroundColor: audiobookColors.brandFaint }} />
                  <Chip label={formatMusicDurationLabel(musicEntry.duration)} size="small" />
                  <Chip label={`节奏：${formatAudioKeywordLabel(musicEntry.tempo)}`} size="small" />
                </>
              ) : null}
            </Box>
            <Button
              size="small"
              variant="text"
              startIcon={<InfoOutlinedIcon fontSize="small" />}
              onClick={(event) => {
                event.stopPropagation()
                onToggleDetail(fileType, entry.id)
              }}
              sx={detailButtonSx}
            >
              {isExpanded ? '收起详细信息' : '详细信息'}
            </Button>
            <Collapse in={isExpanded} timeout={0} unmountOnExit>
              {renderDetailPanel(entry)}
            </Collapse>
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
            onDeleteAsset(fileType, entry.id)
          }}
        >
          <DeleteOutlineIcon fontSize="small" />
        </IconButton>
      )}
    </ListItemButton>
  )
})

interface AudioLibraryVirtualListProps<T extends AudioLibraryEntry> {
  entries: T[]
  fileType: AudioLibraryType
  isAdmin: boolean
  playingId: string | null
  previewLoadingKey: string | null
  expandedDetailIds: Record<string, boolean>
  onDeleteAsset: (fileType: AudioLibraryType, id: string) => void
  onPlay: (fileType: AudioLibraryType, id: string) => void
  onToggleDetail: (fileType: AudioLibraryType, id: string) => void
}

const AudioLibraryVirtualList = <T extends AudioLibraryEntry>({
  entries,
  fileType,
  isAdmin,
  playingId,
  previewLoadingKey,
  expandedDetailIds,
  onDeleteAsset,
  onPlay,
  onToggleDetail,
}: AudioLibraryVirtualListProps<T>) => {
  const parentRef = useRef<HTMLDivElement>(null)
  const rowVirtualizer = useVirtualizer({
    count: entries.length,
    getScrollElement: () => parentRef.current,
    estimateSize: (index) => {
      const entry = entries[index]
      return estimateLibraryRowHeight(entry, Boolean(expandedDetailIds[`${fileType}:${entry.id}`]))
    },
    getItemKey: (index) => entries[index]?.id || index,
    overscan: 8,
  })

  return (
    <Paper
      ref={parentRef}
      variant="outlined"
      sx={{ height: '58vh', minHeight: 320, overflow: 'auto' }}
    >
      <Box sx={{ height: rowVirtualizer.getTotalSize(), position: 'relative' }}>
        {rowVirtualizer.getVirtualItems().map((virtualRow) => {
          const entry = entries[virtualRow.index]
          const detailKey = `${fileType}:${entry.id}`
          return (
            <Box
              key={virtualRow.key}
              ref={rowVirtualizer.measureElement}
              data-index={virtualRow.index}
              sx={{
                position: 'absolute',
                top: 0,
                left: 0,
                width: '100%',
                transform: `translateY(${virtualRow.start}px)`,
              }}
            >
              <AudioLibraryRow
                entry={entry}
                fileType={fileType}
                isAdmin={isAdmin}
                isExpanded={Boolean(expandedDetailIds[detailKey])}
                isPlaying={playingId === entry.id}
                isPreviewLoading={previewLoadingKey === detailKey}
                onDeleteAsset={onDeleteAsset}
                onPlay={onPlay}
                onToggleDetail={onToggleDetail}
              />
            </Box>
          )
        })}
      </Box>
    </Paper>
  )
}

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
  const [previewLoadingKey, setPreviewLoadingKey] = useState<string | null>(null)
  const [expandedDetailIds, setExpandedDetailIds] = useState<Record<string, boolean>>({})
  const playbackRequestIdRef = useRef(0)
  const previewAbortControllerRef = useRef<AbortController | null>(null)
  const { playManagedBlob, stopManagedPlayback } = useAudiobookAudioPlayback()

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

  useEffect(() => () => {
    previewAbortControllerRef.current?.abort()
  }, [])

  const handlePlay = useCallback(async (fileType: AudioLibraryType, id: string) => {
    const requestId = playbackRequestIdRef.current + 1
    playbackRequestIdRef.current = requestId
    const previewKey = `${fileType}:${id}`

    if (playingId === id || previewLoadingKey === previewKey) {
      previewAbortControllerRef.current?.abort()
      previewAbortControllerRef.current = null
      stopManagedPlayback()
      setPlayingId(null)
      setPreviewLoadingKey(null)
      return
    }

    previewAbortControllerRef.current?.abort()
    const abortController = new AbortController()
    previewAbortControllerRef.current = abortController
    stopManagedPlayback()
    setPlayingId(id)
    setPreviewLoadingKey(previewKey)
    try {
      const res = await apiClient.getAudioLibraryPreviewBlob(fileType, id, abortController.signal)
      if (requestId !== playbackRequestIdRef.current) return
      setPreviewLoadingKey(null)
      await playManagedBlob(res.data, {
        onEnded: () => {
          if (requestId === playbackRequestIdRef.current) setPlayingId(null)
        },
      })
    } catch {
      if (requestId === playbackRequestIdRef.current) {
        setPlayingId(null)
        setPreviewLoadingKey(null)
      }
    } finally {
      if (previewAbortControllerRef.current === abortController) previewAbortControllerRef.current = null
    }
  }, [playManagedBlob, playingId, previewLoadingKey, stopManagedPlayback])

  const toggleDetail = useCallback((fileType: AudioLibraryType, id: string) => {
    const key = `${fileType}:${id}`
    setExpandedDetailIds((current) => ({
      ...current,
      [key]: !current[key],
    }))
  }, [])

  const handleClose = () => {
    playbackRequestIdRef.current += 1
    previewAbortControllerRef.current?.abort()
    previewAbortControllerRef.current = null
    stopManagedPlayback()
    setPlayingId(null)
    setPreviewLoadingKey(null)
    setExpandedDetailIds({})
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

  const handleDeleteAsset = useCallback(async (fileType: AudioLibraryType, id: string) => {
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
  }, [isAdmin, loadMusic, loadSfx])

  return (
    <Dialog open={open} onClose={handleClose} maxWidth="lg" fullWidth>
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

        <Box sx={{ display: 'flex', gap: 1, mb: 2, alignItems: 'center', flexWrap: 'wrap' }}>
          <TextField
            size="small"
            placeholder="搜索素材..."
            value={searchText}
            onChange={(e) => setSearchText(e.target.value)}
            InputProps={{ startAdornment: <SearchIcon sx={{ mr: 1, color: 'text.secondary' }} /> }}
            sx={{ flex: '1 1 320px' }}
          />
          {tab === 0 && (
            <>
              <FormControl size="small" sx={{ minWidth: 180, flex: { xs: '1 1 160px', sm: '0 0 180px' } }}>
                <InputLabel>分类</InputLabel>
                <Select
                  label="分类"
                  value={sfxCategoryFilter}
                  onChange={(e) => setSfxCategoryFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {sfxCategories.map((c) => (
                    <MenuItem key={c} value={c}>{formatSfxCategoryLabel(c)}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 160, flex: { xs: '1 1 150px', sm: '0 0 160px' } }}>
                <InputLabel>场景</InputLabel>
                <Select
                  label="场景"
                  value={sfxSceneFilter}
                  onChange={(e) => setSfxSceneFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {getVisibleSfxScenes(sfxScenes).map((scene) => (
                    <MenuItem key={scene} value={scene}>{formatAudioKeywordLabel(scene)}</MenuItem>
                  ))}
                </Select>
              </FormControl>
            </>
          )}
          {tab === 1 && (
            <>
              <FormControl size="small" sx={{ minWidth: 150, flex: { xs: '1 1 140px', sm: '0 0 150px' } }}>
                <InputLabel>风格</InputLabel>
                <Select
                  label="风格"
                  value={musicStyleFilter}
                  onChange={(e) => setMusicStyleFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {musicStyles.map((s) => (
                    <MenuItem key={s} value={s}>{formatAudioKeywordLabel(s)}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small" sx={{ minWidth: 150, flex: { xs: '1 1 140px', sm: '0 0 150px' } }}>
                <InputLabel>情绪</InputLabel>
                <Select
                  label="情绪"
                  value={musicMoodFilter}
                  onChange={(e) => setMusicMoodFilter(e.target.value)}
                >
                  <MenuItem value="">全部</MenuItem>
                  {musicMoods.map((m) => (
                    <MenuItem key={m} value={m}>{formatAudioKeywordLabel(m)}</MenuItem>
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
          <>
            {sfxEntries.length === 0 ? (
              <Paper variant="outlined">
                <Typography variant="body2" color="text.secondary" sx={{ p: 2, textAlign: 'center' }}>
                暂无音效素材
                </Typography>
              </Paper>
            ) : (
              <AudioLibraryVirtualList
                entries={sfxEntries}
                fileType="sfx"
                isAdmin={isAdmin}
                playingId={playingId}
                previewLoadingKey={previewLoadingKey}
                expandedDetailIds={expandedDetailIds}
                onDeleteAsset={handleDeleteAsset}
                onPlay={handlePlay}
                onToggleDetail={toggleDetail}
              />
            )}
          </>
        ) : (
          <>
            {musicEntries.length === 0 ? (
              <Paper variant="outlined">
                <Typography variant="body2" color="text.secondary" sx={{ p: 2, textAlign: 'center' }}>
                  暂无音乐素材
                </Typography>
              </Paper>
            ) : (
              <AudioLibraryVirtualList
                entries={musicEntries}
                fileType="music"
                isAdmin={isAdmin}
                playingId={playingId}
                previewLoadingKey={previewLoadingKey}
                expandedDetailIds={expandedDetailIds}
                onDeleteAsset={handleDeleteAsset}
                onPlay={handlePlay}
                onToggleDetail={toggleDetail}
              />
            )}
          </>
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
