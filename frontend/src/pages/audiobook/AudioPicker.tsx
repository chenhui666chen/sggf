import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Autocomplete,
  Box,
  Chip,
  IconButton,
  Paper,
  TextField,
  Typography,
} from '@mui/material'
import CloseIcon from '@mui/icons-material/Close'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PauseIcon from '@mui/icons-material/Pause'

import { apiClient } from '../../services/api'
import { useAudiobookAudioPlayback } from './useAudiobookAudioPlayback'

interface AudioPickerProps {
  type: 'sfx' | 'music'
  value: string
  onChange: (value: string) => void
  label: string
}

interface SfxOption {
  id: string
  name: string
  category: string
  style?: string
  tags: string[]
  scenes?: string[]
}

interface MusicOption {
  id: string
  style: string
  mood: string
  tempo: string
  duration: number
}

type AudioOption = SfxOption | MusicOption

const AudioPicker = ({ type, value, onChange, label }: AudioPickerProps) => {
  const [options, setOptions] = useState<AudioOption[]>([])
  const [open, setOpen] = useState(false)
  const [search, setSearch] = useState('')
  const [playingId, setPlayingId] = useState<string | null>(null)
  const playbackRequestIdRef = useRef(0)
  const { playManagedBlob, stopManagedPlayback } = useAudiobookAudioPlayback()

  const loadOptions = useCallback(async () => {
    try {
      if (type === 'sfx') {
        const res = await apiClient.browseSoundEffects({ search: search || undefined })
        setOptions(res.data)
      } else {
        const res = await apiClient.browseMusic({ search: search || undefined })
        setOptions(res.data)
      }
    } catch { /* ignore */ }
  }, [type, search])

  useEffect(() => {
    if (!open) return
    loadOptions()
  }, [open, loadOptions])

  const handlePlay = async (id: string) => {
    const requestId = playbackRequestIdRef.current + 1
    playbackRequestIdRef.current = requestId

    if (playingId === id) {
      stopManagedPlayback()
      setPlayingId(null)
      return
    }

    stopManagedPlayback()
    setPlayingId(id)
    try {
      const res = await apiClient.getAudioLibraryPreviewBlob(type, id)
      if (requestId !== playbackRequestIdRef.current) return
      await playManagedBlob(res.data, {
        onEnded: () => {
          if (requestId === playbackRequestIdRef.current) setPlayingId(null)
        },
      })
    } catch {
      if (requestId === playbackRequestIdRef.current) setPlayingId(null)
    }
  }

  const resolveOptionLabel = (option: string | AudioOption): string => {
    if (typeof option === 'string') return option
    if (type === 'sfx') return (option as SfxOption).name
    const music = option as MusicOption
    return `${music.style} - ${music.mood}`
  }

  return (
    <Box sx={{ display: 'flex', gap: 0.5, alignItems: 'flex-start' }}>
      <Autocomplete
        fullWidth
        size="small"
        open={open}
        onOpen={() => setOpen(true)}
        onClose={() => setOpen(false)}
        options={options}
        getOptionLabel={resolveOptionLabel}
        isOptionEqualToValue={(o, v) => typeof o !== 'string' && typeof v !== 'string' && o.id === v.id}
        inputValue={search}
        onInputChange={(_, newInput) => setSearch(newInput)}
        onChange={(_, newValue) => {
          if (newValue && typeof newValue !== 'string') {
            onChange(resolveOptionLabel(newValue))
          } else if (typeof newValue === 'string') {
            onChange(newValue)
          }
        }}
        renderOption={(props, option) => {
          if (typeof option === 'string') return <li {...props}>{option}</li>
          const id = option.id
          return (
            <li {...props}>
              <Box sx={{ display: 'flex', alignItems: 'center', width: '100%', gap: 0.5 }}>
                <IconButton
                  size="small"
                  onClick={(e) => { e.stopPropagation(); void handlePlay(id) }}
                >
                  {playingId === id ? <PauseIcon sx={{ fontSize: 16 }} /> : <PlayArrowIcon sx={{ fontSize: 16 }} />}
                </IconButton>
                <Typography variant="body2" sx={{ flex: 1 }}>
                  {resolveOptionLabel(option)}
                </Typography>
                {type === 'sfx' && (
                  <>
                    <Chip label={(option as SfxOption).category} size="small" variant="outlined" />
                    {((option as SfxOption).scenes || []).slice(0, 2).map((scene) => (
                      <Chip key={scene} label={scene} size="small" variant="outlined" />
                    ))}
                  </>
                )}
                {type === 'music' && (
                  <>
                    <Chip label={(option as MusicOption).mood} size="small" />
                    <Chip label={`${(option as MusicOption).duration}s`} size="small" />
                  </>
                )}
              </Box>
            </li>
          )
        }}
        renderInput={(params) => (
          <TextField
            {...params}
            label={label}
            placeholder="搜索素材库或手动输入..."
          />
        )}
        PaperComponent={({ children }) => (
          <Paper elevation={4} sx={{ '& .MuiAutocomplete-listbox': { maxHeight: 280 } }}>
            {children}
          </Paper>
        )}
        freeSolo
      />
      {value && (
        <IconButton size="small" onClick={() => onChange('')} sx={{ mt: 0.5 }}>
          <CloseIcon fontSize="small" />
        </IconButton>
      )}
    </Box>
  )
}

export default AudioPicker
