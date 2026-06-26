import { useMemo, useState, type ChangeEvent } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  IconButton,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import ExpandLessIcon from '@mui/icons-material/ExpandLess'
import ExpandMoreIcon from '@mui/icons-material/ExpandMore'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { audiobookButtonSx } from './audiobookTheme'
import CosyVoiceCloneRecordDialog from './CosyVoiceCloneRecordDialog'
import type { TtsModel, VoicePreset } from './types'
import {
  convertRecordedAudioBlobToWavFile,
  isMimoCloneSupportedAudioFile,
  summarizeAudioFile,
} from './voiceCloneAudioUtils'
import { useCosyVoiceCloneRecording } from './useCosyVoiceCloneRecording'

interface MimoVoiceAssetWorkbenchProps {
  ttsModel: TtsModel
  customVoicePresets: VoicePreset[]
  previewingVoiceId: string | null
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onChanged: () => void
}

const VISIBLE_MIMO_VOICE_LIMIT = 3

const extractMimoAssetId = (voiceId: string): string =>
  voiceId.replace(/^mimo_(?:clone|design):/, '').trim()

const MimoVoiceAssetWorkbench = ({
  ttsModel,
  customVoicePresets,
  previewingVoiceId,
  onPreviewCustomVoice,
  onChanged,
}: MimoVoiceAssetWorkbenchProps) => {
  const isCloneModel = ttsModel === 'mimo-v2.5-tts-voiceclone'
  const [name, setName] = useState('')
  const [content, setContent] = useState('')
  const [cloneSampleFile, setCloneSampleFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [recordDialogOpen, setRecordDialogOpen] = useState(false)
  const [showAllPresets, setShowAllPresets] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const filteredPresets = useMemo(
    () => customVoicePresets.filter((preset) =>
      isCloneModel ? preset.customType === 'clone' : preset.customType === 'design',
    ),
    [customVoicePresets, isCloneModel],
  )
  const visiblePresets = showAllPresets
    ? filteredPresets
    : filteredPresets.slice(0, VISIBLE_MIMO_VOICE_LIMIT)
  const hiddenPresetCount = filteredPresets.length - visiblePresets.length

  const busy = loading || uploading || recording
  const cloneSampleSummary = cloneSampleFile ? summarizeAudioFile(cloneSampleFile) : ''
  const canSave = isCloneModel
    ? Boolean(name.trim() && cloneSampleFile)
    : Boolean(name.trim() && content.trim())

  const handleUploadAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    setError(null)
    setMessage(null)
    try {
      if (!isMimoCloneSupportedAudioFile(file)) {
        throw new Error('MiMo Voice Clone 仅支持 mp3 或 wav 音频，请转换格式后上传。')
      }
      setCloneSampleFile(file)
      setMessage('已选择音频样本，可保存为 MiMo 复刻音色。')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '选择 MiMo 复刻音频样本失败'))
    } finally {
      setUploading(false)
    }
  }

  const uploadRecordedAudio = async (blob: Blob) => {
    setRecordDialogOpen(false)
    setUploading(true)
    setError(null)
    setMessage(null)
    try {
      const file = await convertRecordedAudioBlobToWavFile(blob)
      setCloneSampleFile(file)
      setMessage('录音已转换为 WAV 样本，可保存为 MiMo 复刻音色。')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '录音转换为 WAV 失败，请改用上传 mp3 或 wav 文件'))
    } finally {
      setUploading(false)
    }
  }

  const {
    handleStartCloneRecording,
    handleStopCloneRecording,
  } = useCosyVoiceCloneRecording({
    cloneLoading: loading,
    cloneUploading: uploading,
    cloneRecording: recording,
    setCloneRecording: setRecording,
    onResetCloneMessages: () => {
      setError(null)
      setMessage(null)
    },
    onCloneError: setError,
    onUploadRecordedCloneAudio: uploadRecordedAudio,
  })

  const handleCreate = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      if (isCloneModel) {
        if (!cloneSampleFile) {
          throw new Error('请先录音或上传音频样本')
        }
        await apiClient.createMimoVoiceCloneAssetFromFile({
          name,
          file: cloneSampleFile,
        })
      } else {
        await apiClient.createMimoVoiceDesignAsset({
          name,
          voice_design_prompt: content,
        })
      }
      setName('')
      setContent('')
      setCloneSampleFile(null)
      setMessage('已保存 MiMo 本地音色，可在角色音色下拉中直接选择。')
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '保存 MiMo 音色失败'))
    } finally {
      setLoading(false)
    }
  }

  const handleDelete = async (voiceId: string) => {
    const assetId = extractMimoAssetId(voiceId)
    setDeletingId(voiceId)
    setError(null)
    setMessage(null)
    try {
      await apiClient.deleteMimoVoiceAsset(assetId)
      setMessage('已删除 MiMo 本地音色。')
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '删除 MiMo 音色失败'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Paper variant="outlined" sx={{ mb: 1, p: 1.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        自定义音色管理（{isCloneModel ? 'MiMo Voice Clone' : 'MiMo Voice Design'}）
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        先保存可复用音色，再到角色音色下拉中选用；生成时后端会自动展开为 MiMo 所需参数。
      </Typography>

      <Paper
        variant="outlined"
        sx={{
          p: { xs: 1.5, md: 2 },
          display: 'grid',
          gap: 1.5,
          mb: 1.5,
        }}
      >
        <Box sx={{ minWidth: 0, maxWidth: 720 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.25 }}>
            {isCloneModel ? '声音复刻' : '声音设计'}
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, lineHeight: 1.75 }}>
            {isCloneModel
              ? '上传 mp3/wav 或录制真实样本，录音会自动转换为 WAV 后保存为 MiMo 可复用复刻音色。'
              : '用文字描述声线、年龄感和情绪底色，保存为 MiMo 可复用设计音色。'}
          </Typography>
        </Box>

        <Box
          sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) 120px' },
          gap: 1.25,
          alignItems: 'stretch',
          width: '100%',
            maxWidth: 740,
          }}
        >
          <TextField
            label="音色名称"
            value={name}
            onChange={(event) => setName(event.target.value)}
            size="small"
            fullWidth
            disabled={busy}
            sx={{ minWidth: 0 }}
          />
          <Button
            fullWidth
            variant="contained"
            disabled={busy || !canSave}
            onClick={handleCreate}
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : undefined}
            sx={{ ...audiobookButtonSx.brandContained, minHeight: 40 }}
          >
            {loading ? '保存中...' : '保存音色'}
          </Button>
          {isCloneModel ? (
            <Box
              sx={{
                gridColumn: '1 / -1',
                minWidth: 0,
                minHeight: 40,
                px: 1.5,
                py: 0.75,
                border: '1px solid',
                borderColor: cloneSampleFile ? 'success.main' : 'divider',
                borderRadius: 1,
                display: 'flex',
                alignItems: 'center',
                gap: 1,
                backgroundColor: 'background.paper',
              }}
            >
              <Box sx={{ minWidth: 0, flex: 1 }}>
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', lineHeight: 1.2 }}>
                  {cloneSampleFile ? '已选择音频样本' : '音频样本'}
                </Typography>
                <Tooltip title={cloneSampleSummary || '请录音或上传音频样本'}>
                  <Typography
                    variant="body2"
                    sx={{
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {cloneSampleSummary || '尚未选择样本'}
                  </Typography>
                </Tooltip>
              </Box>
              {cloneSampleFile && (
                <Button
                  size="small"
                  variant="text"
                  disabled={busy}
                  onClick={() => {
                    setCloneSampleFile(null)
                    setMessage(null)
                  }}
                  sx={{ minWidth: 64 }}
                >
                  清除样本
                </Button>
              )}
            </Box>
          ) : (
            <TextField
              label="声音描述"
              value={content}
              onChange={(event) => setContent(event.target.value)}
              placeholder="青年女性，中音，语速中等，温柔但疲惫，适合有声书对白"
              size="small"
              fullWidth
              multiline
              minRows={3}
              maxRows={5}
              disabled={busy}
              sx={{ gridColumn: '1 / -1', minWidth: 0 }}
            />
          )}
        </Box>

        {isCloneModel && (
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
            <Button
              variant="outlined"
              disabled={busy}
              onClick={() => setRecordDialogOpen(true)}
              sx={audiobookButtonSx.neutralOutlined}
            >
              录音
            </Button>
            <Button
              variant="outlined"
              component="label"
              disabled={busy}
              startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : undefined}
              sx={audiobookButtonSx.brandOutlined}
            >
              {uploading ? '上传中...' : '上传音频'}
              <input
                type="file"
                hidden
                accept=".mp3,.wav,audio/mpeg,audio/wav"
                onChange={handleUploadAudio}
              />
            </Button>
            <Typography variant="caption" color="text.secondary" sx={{ minWidth: 220, flex: '1 1 260px' }}>
              MiMo Voice Clone 仅支持 mp3/wav；录音会自动转换为 wav，不会在页面展示大段编码内容。
            </Typography>
          </Box>
        )}
      </Paper>

      {message && <Alert severity="success" sx={{ mb: 1 }}>{message}</Alert>}
      {error && <Alert severity="warning" sx={{ mb: 1 }}>{error}</Alert>}

      {filteredPresets.length > 0 && (
        <>
          <Divider sx={{ mb: 1 }} />
          <Box sx={{ display: 'grid', gap: 1 }}>
            {visiblePresets.map((preset) => {
              const isDeleting = deletingId === preset.id
              const isPreviewing = previewingVoiceId === preset.id
              return (
                <Box
                  key={preset.id}
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: { xs: '1fr', sm: 'minmax(0, 1fr) auto' },
                    gap: 1,
                    alignItems: 'center',
                    p: 1,
                    borderRadius: 1,
                    border: '1px solid',
                    borderColor: 'divider',
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography
                      variant="body2"
                      sx={{
                        fontWeight: 700,
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                      }}
                    >
                      {preset.label || preset.id}
                    </Typography>
                    <Tooltip title={preset.description || preset.id}>
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        sx={{
                          display: 'block',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {preset.description || preset.id}
                      </Typography>
                    </Tooltip>
                  </Box>
                  <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 0.5 }}>
                    <Chip
                      label={preset.customType === 'clone' ? 'Clone' : 'Design'}
                      size="small"
                      color={preset.customType === 'clone' ? 'success' : 'warning'}
                    />
                    <Tooltip title="试听">
                      <span>
                        <IconButton
                          size="small"
                          disabled={Boolean(previewingVoiceId) || isDeleting}
                          onClick={() => onPreviewCustomVoice(preset, ttsModel)}
                          aria-label={`试听 ${preset.label || preset.id}`}
                        >
                          {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title={isDeleting ? '删除中' : '删除'}>
                      <span>
                        <IconButton
                          size="small"
                          color="error"
                          disabled={isDeleting}
                          onClick={() => handleDelete(preset.id)}
                          aria-label={`删除 ${preset.label || preset.id}`}
                        >
                          {isDeleting ? <CircularProgress size={18} /> : <DeleteOutlineIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                  </Box>
                </Box>
              )
            })}
            {filteredPresets.length > VISIBLE_MIMO_VOICE_LIMIT && (
              <Button
                size="small"
                variant="text"
                endIcon={showAllPresets ? <ExpandLessIcon /> : <ExpandMoreIcon />}
                onClick={() => setShowAllPresets((current) => !current)}
                sx={{ justifySelf: 'start', fontSize: '0.75rem', minWidth: 0 }}
              >
                {showAllPresets ? '收起' : `展开 ${hiddenPresetCount} 个`}
              </Button>
            )}
          </Box>
        </>
      )}
      <CosyVoiceCloneRecordDialog
        open={recordDialogOpen}
        cloneRecording={recording}
        cloneLoading={loading}
        cloneUploading={uploading}
        onClose={() => {
          if (!recording) setRecordDialogOpen(false)
        }}
        onStartCloneRecording={handleStartCloneRecording}
        onStopCloneRecording={handleStopCloneRecording}
      />
    </Paper>
  )
}

export default MimoVoiceAssetWorkbench
