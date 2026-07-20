import { memo, useCallback, useEffect, useRef, useState } from 'react'
import {
  Alert,
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
  Rating,
  Select,
  Snackbar,
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
  formatAudioAssetDescriptionLabel,
  formatAudioAssetNameLabel,
  formatAudioKeywordLabel,
  formatMusicDurationLabel,
  formatSfxCategoryLabel,
  getVisibleSfxScenes,
  getVisibleSfxTags,
} from './audioLibraryDisplay'
import AudioLibraryPurgeDialog from './AudioLibraryPurgeDialog'
import AudioLibraryUploadDialog from './AudioLibraryUploadDialog'
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
  rating_count: number
  average_rating: number
  user_rating?: number | null
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
  name: string
  description: string
  prompt: string
  tags: string[]
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
  return expanded ? 246 + tagRows * 24 : 150 + tagRows * 20
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
  isRating: boolean
  onDeleteAsset: (fileType: AudioLibraryType, id: string) => void
  onPlay: (fileType: AudioLibraryType, id: string) => void
  onRate: (fileType: AudioLibraryType, id: string, score: number) => void
  onToggleDetail: (fileType: AudioLibraryType, id: string) => void
}

const AudioLibraryRow = memo(({
  entry,
  fileType,
  isAdmin,
  isExpanded,
  isPlaying,
  isPreviewLoading,
  isRating,
  onDeleteAsset,
  onPlay,
  onRate,
  onToggleDetail,
}: AudioLibraryRowProps) => {
  const isSfx = fileType === 'sfx'
  const sfxEntry = isSfx ? entry as SfxEntry : null
  const musicEntry = isSfx ? null : entry as MusicEntry
  const sfxDescription = sfxEntry ? formatAudioAssetDescriptionLabel(sfxEntry) : ''

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
            : musicEntry?.name
              ? formatAudioAssetNameLabel(musicEntry?.name)
              : `${formatAudioKeywordLabel(musicEntry?.style)} - ${formatAudioKeywordLabel(musicEntry?.mood)}${musicEntry?.variant != null ? `（变体 ${musicEntry.variant}）` : ''}`
        }
        primaryTypographyProps={{ sx: { fontWeight: 600, overflowWrap: 'anywhere' } }}
        secondary={
          <>
            {sfxEntry && sfxDescription && (
              <Typography
                variant="body2"
                color="text.secondary"
                sx={{ mt: 0.35, overflowWrap: 'anywhere' }}
              >
                {sfxDescription}
              </Typography>
            )}
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
            <Box
              onClick={(event) => event.stopPropagation()}
              sx={{ display: 'flex', alignItems: 'center', gap: 1, mt: 0.75, minHeight: 24 }}
            >
              <Rating
                size="small"
                value={entry.user_rating || 0}
                disabled={isRating}
                onChange={(event, score) => {
                  event.stopPropagation()
                  if (score) onRate(fileType, entry.id, score)
                }}
              />
              <Typography variant="caption" color="text.secondary">
                {entry.rating_count > 0
                  ? `${entry.average_rating.toFixed(1)} 分 · ${entry.rating_count} 人`
                  : '暂无评分'}
              </Typography>
              {isRating && <CircularProgress size={14} />}
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
  ratingLoadingKey: string | null
  expandedDetailIds: Record<string, boolean>
  onDeleteAsset: (fileType: AudioLibraryType, id: string) => void
  onPlay: (fileType: AudioLibraryType, id: string) => void
  onRate: (fileType: AudioLibraryType, id: string, score: number) => void
  onToggleDetail: (fileType: AudioLibraryType, id: string) => void
}

const AudioLibraryVirtualList = <T extends AudioLibraryEntry>({
  entries,
  fileType,
  isAdmin,
  playingId,
  previewLoadingKey,
  ratingLoadingKey,
  expandedDetailIds,
  onDeleteAsset,
  onPlay,
  onRate,
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
                isRating={ratingLoadingKey === detailKey}
                onDeleteAsset={onDeleteAsset}
                onPlay={onPlay}
                onRate={onRate}
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
  const [ratingLoadingKey, setRatingLoadingKey] = useState<string | null>(null)
  const [expandedDetailIds, setExpandedDetailIds] = useState<Record<string, boolean>>({})
  const playbackRequestIdRef = useRef(0)
  const previewAbortControllerRef = useRef<AbortController | null>(null)
  const { playManagedBlob, stopManagedPlayback } = useAudiobookAudioPlayback()

  const [purgeOpen, setPurgeOpen] = useState(false)
  const [uploadOpen, setUploadOpen] = useState(false)
  const [notice, setNotice] = useState('')

  const loadStats = useCallback(async () => {
    try {
      const res = await apiClient.getAudioLibraryStats()
      setSfxCategories(res.data.sfx_categories)
      setSfxScenes(res.data.sfx_scenes || [])
      setMusicStyles(res.data.music_styles)
      setMusicMoods(res.data.music_moods)
    } catch { /* ignore */ }
  }, [])

  useEffect(() => {
    if (open) loadStats()
  }, [loadStats, open])

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
    setRatingLoadingKey(null)
    setExpandedDetailIds({})
    setSearchText('')
    setSfxCategoryFilter('')
    setSfxSceneFilter('')
    setMusicStyleFilter('')
    setMusicMoodFilter('')
    setPurgeOpen(false)
    setUploadOpen(false)
    onClose()
  }

  const handleRate = useCallback(async (fileType: AudioLibraryType, id: string, score: number) => {
    const ratingKey = `${fileType}:${id}`
    setRatingLoadingKey(ratingKey)
    try {
      const res = await apiClient.rateAudioLibraryAsset(fileType, id, score)
      const result = res.data
      if (result.auto_unpublished) {
        if (fileType === 'sfx') {
          setSfxEntries((entries) => entries.filter((entry) => entry.id !== id))
        } else {
          setMusicEntries((entries) => entries.filter((entry) => entry.id !== id))
        }
        setNotice('该素材已达到低分阈值并自动下架')
        await loadStats()
        return
      }

      const ratingPatch = {
        rating_count: result.rating_count,
        average_rating: result.average_score,
        user_rating: result.user_score,
      }
      if (fileType === 'sfx') {
        setSfxEntries((entries) => entries.map((entry) => (
          entry.id === id ? { ...entry, ...ratingPatch } : entry
        )))
      } else {
        setMusicEntries((entries) => entries.map((entry) => (
          entry.id === id ? { ...entry, ...ratingPatch } : entry
        )))
      }
      setNotice('评分已更新')
    } catch {
      setNotice('评分提交失败，请稍后重试')
    } finally {
      setRatingLoadingKey(null)
    }
  }, [loadStats])

  const handleUploaded = useCallback((fileType: AudioLibraryType) => {
    setTab(fileType === 'sfx' ? 0 : 1)
    setNotice('素材已上传并加入共享素材库')
    void loadStats()
    if (fileType === 'sfx') void loadSfx()
    else void loadMusic()
  }, [loadMusic, loadSfx, loadStats])

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

        <Box sx={{ display: 'flex', gap: 1, mb: 2, flexWrap: 'wrap' }}>
          <Button
            size="small"
            variant="contained"
            startIcon={<UploadFileIcon />}
            onClick={() => setUploadOpen(true)}
          >
            上传素材
          </Button>
          {isAdmin && (
            <Button
              size="small"
              variant="outlined"
              onClick={() => setPurgeOpen(true)}
            >
              素材清理
            </Button>
          )}
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
                ratingLoadingKey={ratingLoadingKey}
                expandedDetailIds={expandedDetailIds}
                onDeleteAsset={handleDeleteAsset}
                onPlay={handlePlay}
                onRate={handleRate}
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
                ratingLoadingKey={ratingLoadingKey}
                expandedDetailIds={expandedDetailIds}
                onDeleteAsset={handleDeleteAsset}
                onPlay={handlePlay}
                onRate={handleRate}
                onToggleDetail={toggleDetail}
              />
            )}
          </>
        )}
      </DialogContent>
      <AudioLibraryUploadDialog
        open={uploadOpen}
        initialLibraryType={tab === 0 ? 'sfx' : 'music'}
        onClose={() => setUploadOpen(false)}
        onUploaded={handleUploaded}
      />
      <AudioLibraryPurgeDialog
        open={purgeOpen}
        initialLibraryType={tab === 0 ? 'sfx' : 'music'}
        onClose={() => setPurgeOpen(false)}
        onPurged={tab === 0 ? loadSfx : loadMusic}
      />
      <Snackbar
        open={Boolean(notice)}
        autoHideDuration={3200}
        onClose={() => setNotice('')}
        anchorOrigin={{ vertical: 'bottom', horizontal: 'center' }}
      >
        <Alert severity={notice.includes('失败') ? 'error' : 'success'} onClose={() => setNotice('')}>
          {notice}
        </Alert>
      </Snackbar>
    </Dialog>
  )
}

export default AudioLibraryBrowser
