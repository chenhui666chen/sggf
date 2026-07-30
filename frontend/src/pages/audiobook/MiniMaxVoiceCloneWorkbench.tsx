import { useMemo, useState, type ChangeEvent } from 'react'

import DeleteOutlineIcon from '@mui/icons-material/DeleteOutline'
import MicIcon from '@mui/icons-material/Mic'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import UploadFileIcon from '@mui/icons-material/UploadFile'
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  IconButton,
  Paper,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'

import { apiClient, extractApiErrorMessage } from '../../services/api'
import { audiobookButtonSx } from './audiobookTheme'
import CosyVoiceCloneRecordDialog from './CosyVoiceCloneRecordDialog'
import type { TtsModel, VoicePreset } from './types'
import { useCosyVoiceCloneRecording } from './useCosyVoiceCloneRecording'
import {
  convertRecordedAudioBlobToWavFile,
  isMimoCloneSupportedAudioFile,
  summarizeAudioFile,
} from './voiceCloneAudioUtils'

interface MiniMaxVoiceCloneWorkbenchProps {
  ttsModel: TtsModel
  customVoicePresets: VoicePreset[]
  previewingVoiceId: string | null
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onChanged: () => void
}

interface CreatedClonePreview {
  voiceId: string
  audioUrl: string
  billingNotice: string
}

const MINIMAX_PREVIEW_PRICES: Record<string, string> = {
  'minimax-speech-2.8-hd': '3.5 元/万字符',
  'minimax-speech-2.8-turbo': '2 元/万字符',
}

const MiniMaxVoiceCloneWorkbench = ({
  ttsModel,
  customVoicePresets,
  previewingVoiceId,
  onPreviewCustomVoice,
  onChanged,
}: MiniMaxVoiceCloneWorkbenchProps) => {
  const [name, setName] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [sampleFile, setSampleFile] = useState<File | null>(null)
  const [creating, setCreating] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [recordDialogOpen, setRecordDialogOpen] = useState(false)
  const [billingConfirmOpen, setBillingConfirmOpen] = useState(false)
  const [createdPreview, setCreatedPreview] = useState<CreatedClonePreview | null>(null)
  const [removeTarget, setRemoveTarget] = useState<VoicePreset | null>(null)
  const [removing, setRemoving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const minimaxPresets = useMemo(
    () => customVoicePresets.filter(
      (preset) => preset.provider === 'minimax' || preset.id.startsWith('mmx_'),
    ),
    [customVoicePresets],
  )
  const busy = creating || uploading || recording
  const previewPrice = MINIMAX_PREVIEW_PRICES[ttsModel] || '当前模型公开价'
  const sampleSummary = sampleFile ? summarizeAudioFile(sampleFile) : ''
  const canCreate = Boolean(name.trim() && sampleText.trim() && sampleFile)

  const resetMessages = () => {
    setMessage(null)
    setError(null)
  }

  const handleUploadAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    resetMessages()
    try {
      if (!isMimoCloneSupportedAudioFile(file)) {
        throw new Error('MiniMax 音色复刻参考样本仅支持 mp3 或 wav 音频')
      }
      setSampleFile(file)
      setMessage('已选择参考样本。请核对逐字内容，创建前会再次确认费用。')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '选择 MiniMax 参考样本失败'))
    } finally {
      setUploading(false)
    }
  }

  const uploadRecordedAudio = async (blob: Blob) => {
    setRecordDialogOpen(false)
    setUploading(true)
    resetMessages()
    try {
      const file = await convertRecordedAudioBlobToWavFile(blob)
      setSampleFile(file)
      setMessage('录音已转换为 WAV 样本。请核对逐字内容，创建前会再次确认费用。')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '录音转换为 WAV 失败，请改用 mp3 或 wav 文件'))
    } finally {
      setUploading(false)
    }
  }

  const {
    handleStartCloneRecording,
    handleStopCloneRecording,
  } = useCosyVoiceCloneRecording({
    cloneLoading: creating,
    cloneUploading: uploading,
    cloneRecording: recording,
    setCloneRecording: setRecording,
    onResetCloneMessages: resetMessages,
    onCloneError: setError,
    onUploadRecordedCloneAudio: uploadRecordedAudio,
  })

  const handleOpenRecordDialog = () => {
    resetMessages()
    if (!sampleText.trim()) {
      setError('请先填写准备朗读的逐字内容，再开始录音')
      return
    }
    setRecordDialogOpen(true)
  }

  const handleRequestCreate = () => {
    resetMessages()
    if (!name.trim()) {
      setError('请填写音色名称')
      return
    }
    if (!sampleText.trim()) {
      setError('请填写参考音频逐字内容')
      return
    }
    if (!sampleFile) {
      setError('请先录音或上传 mp3/wav 参考样本')
      return
    }
    setBillingConfirmOpen(true)
  }

  const handleConfirmCreate = async () => {
    if (!sampleFile) return
    setBillingConfirmOpen(false)
    setCreating(true)
    resetMessages()
    try {
      const response = await apiClient.createMiniMaxVoiceCloneFromFile({
        model: ttsModel,
        name: name.trim(),
        sampleText: sampleText.trim(),
        file: sampleFile,
      })
      const payload = response.data
      const audioUrl = payload.preview_audio_data_base64
        ? `data:${payload.preview_audio_mime_type || 'audio/mpeg'};base64,${payload.preview_audio_data_base64}`
        : payload.preview_audio_url || ''
      setCreatedPreview({
        voiceId: payload.voice_id,
        audioUrl,
        billingNotice: payload.billing_notice,
      })
      setName('')
      setSampleText('')
      setSampleFile(null)
      setMessage('MiniMax 复刻音色已创建，可在角色音色下拉中选择。')
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '创建 MiniMax 复刻音色失败'))
    } finally {
      setCreating(false)
    }
  }

  const handleRemove = async () => {
    if (!removeTarget) return
    setRemoving(true)
    resetMessages()
    try {
      await apiClient.removeMiniMaxVoiceClone(removeTarget.id)
      setMessage('已从本系统音色目录移除；百炼账号中的云端音色仍保留。')
      setRemoveTarget(null)
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '移除 MiniMax 复刻音色失败'))
    } finally {
      setRemoving(false)
    }
  }

  return (
    <Paper variant="outlined" sx={{ mb: 1, p: { xs: 1.5, md: 2 } }}>
      <Box sx={{ display: 'grid', gap: 0.75, mb: 1.5 }}>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          MiniMax 音色复刻
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ lineHeight: 1.7 }}>
          上传或录制授权的 mp3/wav 样本，并填写与音频完全一致的逐字内容。创建成功后会得到百炼真实 voice_id，可直接分配给角色。
        </Typography>
        <Alert severity="warning">
          创建复刻试听按 {previewPrice} 计费；该音色首次用于正式语音合成时，阿里云百炼另收 9.9 元音色解锁费。后续重复使用不会按章节再次收取解锁费。
        </Alert>
      </Box>

      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', md: 'minmax(180px, 0.7fr) minmax(280px, 1.3fr)' },
          gap: 1.25,
          mb: 1.25,
        }}
      >
        <TextField
          label="音色名称"
          value={name}
          onChange={(event) => setName(event.target.value)}
          size="small"
          fullWidth
          disabled={busy}
        />
        <TextField
          label="参考音频逐字内容"
          value={sampleText}
          onChange={(event) => setSampleText(event.target.value)}
          size="small"
          fullWidth
          multiline
          minRows={2}
          disabled={busy}
        />
      </Box>

      <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap', mb: 1.25 }}>
        <Button
          variant="outlined"
          disabled={busy}
          onClick={handleOpenRecordDialog}
          startIcon={<MicIcon />}
          sx={audiobookButtonSx.neutralOutlined}
        >
          录音
        </Button>
        <Button
          variant="outlined"
          component="label"
          disabled={busy}
          startIcon={uploading ? <CircularProgress size={16} color="inherit" /> : <UploadFileIcon />}
          sx={audiobookButtonSx.brandOutlined}
        >
          {uploading ? '处理中...' : '上传音频'}
          <input
            type="file"
            hidden
            accept=".mp3,.wav,audio/mpeg,audio/wav"
            onChange={handleUploadAudio}
          />
        </Button>
        <Button
          variant="contained"
          disabled={busy || !canCreate}
          onClick={handleRequestCreate}
          startIcon={creating ? <CircularProgress size={18} color="inherit" /> : undefined}
          sx={audiobookButtonSx.brandContained}
        >
          {creating ? '创建中...' : '创建复刻音色'}
        </Button>
        <Typography
          variant="caption"
          color="text.secondary"
          sx={{ minWidth: 240, flex: '1 1 280px', overflowWrap: 'anywhere' }}
        >
          {sampleSummary || '尚未选择参考音频'}
        </Typography>
      </Box>

      {createdPreview?.audioUrl && (
        <Box sx={{ mb: 1.25 }}>
          <Typography variant="body2" sx={{ fontWeight: 700, mb: 0.5 }}>
            新音色试听
          </Typography>
          <audio controls src={createdPreview.audioUrl} style={{ width: '100%', maxWidth: 560 }} />
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mt: 0.5 }}>
            voice_id：{createdPreview.voiceId}
          </Typography>
        </Box>
      )}
      {message && <Alert severity="success" sx={{ mb: 1 }}>{message}</Alert>}
      {error && <Alert severity="warning" sx={{ mb: 1 }}>{error}</Alert>}

      {minimaxPresets.length > 0 && (
        <>
          <Divider sx={{ my: 1.25 }} />
          <Typography variant="subtitle2" sx={{ mb: 0.75 }}>
            当前模型的复刻音色
          </Typography>
          <Box sx={{ display: 'grid', gap: 0.75, maxHeight: 280, overflowY: 'auto' }}>
            {minimaxPresets.map((preset) => {
              const isPreviewing = previewingVoiceId === preset.id
              return (
                <Box
                  key={preset.id}
                  sx={{
                    display: 'grid',
                    gridTemplateColumns: 'minmax(0, 1fr) auto',
                    gap: 1,
                    alignItems: 'center',
                    border: '1px solid',
                    borderColor: 'divider',
                    borderRadius: 1,
                    p: 1,
                  }}
                >
                  <Box sx={{ minWidth: 0 }}>
                    <Typography variant="body2" sx={{ fontWeight: 700 }} noWrap>
                      {preset.label || preset.id}
                    </Typography>
                    <Typography variant="caption" color="text.secondary" noWrap sx={{ display: 'block' }}>
                      {preset.id}
                    </Typography>
                  </Box>
                  <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.25 }}>
                    <Chip label="MiniMax Clone" size="small" color="success" />
                    <Tooltip title="试听">
                      <span>
                        <IconButton
                          size="small"
                          disabled={Boolean(previewingVoiceId)}
                          onClick={() => onPreviewCustomVoice(preset, ttsModel)}
                          aria-label={`试听 ${preset.label || preset.id}`}
                        >
                          {isPreviewing ? <CircularProgress size={18} /> : <PlayArrowIcon fontSize="small" />}
                        </IconButton>
                      </span>
                    </Tooltip>
                    <Tooltip title="从本系统列表移除">
                      <IconButton
                        size="small"
                        color="error"
                        onClick={() => setRemoveTarget(preset)}
                        aria-label={`移除 ${preset.label || preset.id}`}
                      >
                        <DeleteOutlineIcon fontSize="small" />
                      </IconButton>
                    </Tooltip>
                  </Box>
                </Box>
              )
            })}
          </Box>
        </>
      )}

      <CosyVoiceCloneRecordDialog
        open={recordDialogOpen}
        cloneRecording={recording}
        cloneLoading={creating}
        cloneUploading={uploading}
        strictTranscriptMode
        transcriptText={sampleText.trim()}
        onClose={() => {
          if (!recording) setRecordDialogOpen(false)
        }}
        onStartCloneRecording={handleStartCloneRecording}
        onStopCloneRecording={handleStopCloneRecording}
      />

      <Dialog
        open={billingConfirmOpen}
        onClose={() => {
          if (!creating) setBillingConfirmOpen(false)
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>收费确认</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>
            创建复刻试听按 {previewPrice} 计费。
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            此操作会调用阿里云百炼创建真实 voice_id。该音色首次用于正式语音合成时另收 9.9 元，后续重复使用不会按章节再次收取解锁费。
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            音色名称：{name.trim() || '未命名'}；模型：{ttsModel}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setBillingConfirmOpen(false)} disabled={creating}>
            取消
          </Button>
          <Button
            variant="contained"
            color="warning"
            disabled={creating || !canCreate}
            onClick={handleConfirmCreate}
          >
            {creating ? '创建中...' : '确认收费并创建'}
          </Button>
        </DialogActions>
      </Dialog>

      <Dialog
        open={Boolean(removeTarget)}
        onClose={() => {
          if (!removing) setRemoveTarget(null)
        }}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>移除本地登记</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2">
            仅从当前用户的本系统音色目录移除“{removeTarget?.label || removeTarget?.id}”。百炼账号中的云端音色不会删除，也不会退还已产生的费用。
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setRemoveTarget(null)} disabled={removing}>取消</Button>
          <Button color="error" onClick={handleRemove} disabled={removing}>
            {removing ? '移除中...' : '确认移除'}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  )
}

export default MiniMaxVoiceCloneWorkbench
