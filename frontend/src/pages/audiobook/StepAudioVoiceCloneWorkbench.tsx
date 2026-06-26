import { useMemo, useState, type ChangeEvent } from 'react'

import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Divider,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
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

interface StepAudioVoiceCloneWorkbenchProps {
  customVoicePresets: VoicePreset[]
  previewingVoiceId: string | null
  onPreviewCustomVoice: (voice: VoicePreset, model?: TtsModel) => void
  onChanged: () => void
}

interface StepAudioClonePreviewResult {
  fileId: string
  sampleText: string
  previewText: string
  instruction: string
  previewAudioUrl: string
  audioMimeType: string
  audioSizeBytes: number
}

const VISIBLE_STEPAUDIO_VOICE_LIMIT = 3

const extractStepAudioAssetId = (voiceId: string): string =>
  voiceId.replace(/^stepaudio_clone:/, '').trim()

const StepAudioVoiceCloneWorkbench = ({
  customVoicePresets,
  previewingVoiceId,
  onPreviewCustomVoice,
  onChanged,
}: StepAudioVoiceCloneWorkbenchProps) => {
  const [name, setName] = useState('')
  const [sampleText, setSampleText] = useState('')
  const [fileId, setFileId] = useState('')
  const [cloneSampleFile, setCloneSampleFile] = useState<File | null>(null)
  const [loading, setLoading] = useState(false)
  const [previewing, setPreviewing] = useState(false)
  const [previewResult, setPreviewResult] = useState<StepAudioClonePreviewResult | null>(null)
  const [uploading, setUploading] = useState(false)
  const [recording, setRecording] = useState(false)
  const [recordDialogOpen, setRecordDialogOpen] = useState(false)
  const [billingConfirmOpen, setBillingConfirmOpen] = useState(false)
  const [showAllPresets, setShowAllPresets] = useState(false)
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const filteredPresets = useMemo(
    () => customVoicePresets.filter((preset) => preset.id.startsWith('stepaudio_clone:')),
    [customVoicePresets],
  )
  const visiblePresets = showAllPresets
    ? filteredPresets
    : filteredPresets.slice(0, VISIBLE_STEPAUDIO_VOICE_LIMIT)
  const hiddenPresetCount = filteredPresets.length - visiblePresets.length

  const busy = loading || previewing || uploading || recording
  const cloneSampleSummary = cloneSampleFile ? summarizeAudioFile(cloneSampleFile) : ''
  const canPreview = Boolean(cloneSampleFile && sampleText.trim())
  const canSave = Boolean(name.trim() && cloneSampleFile && previewResult)

  const clearPreviewResult = () => {
    setPreviewResult(null)
  }

  const handleUploadAudio = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    event.target.value = ''
    if (!file) return
    setUploading(true)
    setError(null)
    setMessage(null)
    try {
      if (!isMimoCloneSupportedAudioFile(file)) {
        throw new Error('StepAudio Voice Clone 参考样本仅支持 mp3 或 wav 音频')
      }
      setCloneSampleFile(file)
      clearPreviewResult()
      setMessage('已选择参考样本，请先预试听，满意后再确认保存。')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '选择 StepAudio 参考样本失败'))
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
      clearPreviewResult()
      setMessage('录音已转换为 WAV 参考样本，请先预试听，满意后再确认保存。')
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
    cloneLoading: loading || previewing,
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

  const handleOpenRecordDialog = () => {
    setError(null)
    setMessage(null)
    if (!sampleText.trim()) {
      setError('请先填写参考音频逐字内容，再开始录音')
      return
    }
    setRecordDialogOpen(true)
  }

  const handlePreviewClone = async () => {
    setPreviewing(true)
    setError(null)
    setMessage(null)
    clearPreviewResult()
    try {
      if (!cloneSampleFile) {
        throw new Error('请先录音或上传音频样本')
      }
      if (!sampleText.trim()) {
        throw new Error('请填写参考音频逐字内容')
      }
      const response = await apiClient.previewStepAudioVoiceCloneAssetFromFile({
        name: name.trim(),
        file: cloneSampleFile,
        sampleText: sampleText.trim(),
        fileId: fileId.trim(),
      })
      const payload = response.data
      const audioMimeType = payload.audio_mime_type || 'audio/mpeg'
      const previewAudioUrl = `data:${audioMimeType};base64,${payload.audio_data_base64}`
      setFileId(payload.file_id || fileId.trim())
      setSampleText(payload.sample_text || sampleText.trim())
      setPreviewResult({
        fileId: payload.file_id || fileId.trim(),
        sampleText: payload.sample_text || sampleText.trim(),
        previewText: payload.preview_text || '',
        instruction: payload.instruction || '',
        previewAudioUrl,
        audioMimeType,
        audioSizeBytes: payload.audio_size_bytes || 0,
      })
      setMessage('预试听已生成，请先听效果，满意后再确认保存。')
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, 'StepAudio 复刻预试听失败'))
    } finally {
      setPreviewing(false)
    }
  }

  const handleRequestConfirmSave = () => {
    setError(null)
    setMessage(null)
    if (!name.trim()) {
      setError('请填写音色名称')
      return
    }
    if (!cloneSampleFile) {
      setError('请先录音或上传音频样本')
      return
    }
    if (!sampleText.trim()) {
      setError('请填写参考音频逐字内容')
      return
    }
    if (!previewResult) {
      setError('请先完成预试听，满意后再确认保存')
      return
    }
    setBillingConfirmOpen(true)
  }

  const handleCloseBillingConfirm = () => {
    if (loading) return
    setBillingConfirmOpen(false)
  }

  const handleConfirmSave = async () => {
    setLoading(true)
    setError(null)
    setMessage(null)
    try {
      if (!cloneSampleFile) {
        throw new Error('请先录音或上传音频样本')
      }
      if (!sampleText.trim()) {
        throw new Error('请填写参考音频逐字内容')
      }
      if (!previewResult) {
        throw new Error('请先完成预试听，满意后再确认保存')
      }
      await apiClient.createStepAudioVoiceCloneAssetFromFile({
        name: name.trim(),
        file: cloneSampleFile,
        sampleText: previewResult.sampleText,
        fileId: previewResult.fileId,
      })
      setName('')
      setSampleText('')
      setFileId('')
      setCloneSampleFile(null)
      clearPreviewResult()
      setMessage('已保存 StepAudio 参考音色，可在角色音色下拉中选择。')
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '保存 StepAudio 参考音色失败'))
    } finally {
      setLoading(false)
    }
  }

  const handleConfirmBillingSave = async () => {
    setBillingConfirmOpen(false)
    await handleConfirmSave()
  }

  const handleDelete = async (voiceId: string) => {
    const assetId = extractStepAudioAssetId(voiceId)
    setDeletingId(voiceId)
    setError(null)
    setMessage(null)
    try {
      await apiClient.deleteStepAudioVoiceAsset(assetId)
      setMessage('已删除 StepAudio 本地参考音色。')
      onChanged()
    } catch (err: unknown) {
      setError(await extractApiErrorMessage(err, '删除 StepAudio 参考音色失败'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <Paper variant="outlined" sx={{ mb: 1, p: 1.5 }}>
      <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
        自定义音色管理（StepAudio Zero-shot 参考样本）
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        StepAudio 与其他声音克隆不同，参考音频必须和“参考音频逐字内容”一致；先预试听，再确认保存，正式复刻/生成音色可能产生 9.9 元/音色费用。
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
        <Box sx={{ minWidth: 0, maxWidth: 760 }}>
          <Typography variant="subtitle1" sx={{ fontWeight: 800, lineHeight: 1.25 }}>
            声音复刻参考
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mt: 0.5, lineHeight: 1.75 }}>
            上传 mp3/wav 或录制真实样本。预试听会生成并回填官方 file_id，确认保存后可在角色音色下拉中选择。
          </Typography>
        </Box>

        <Box
          sx={{
            display: 'grid',
            gridTemplateColumns: { xs: '1fr', md: 'minmax(0, 1fr) minmax(220px, 240px)' },
            gap: 1.25,
            alignItems: 'stretch',
            width: '100%',
            maxWidth: 760,
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
          <Box sx={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 0.75, minWidth: 0 }}>
            <Button
              fullWidth
              variant="outlined"
              disabled={busy || !canPreview}
              onClick={handlePreviewClone}
              startIcon={previewing ? <CircularProgress size={18} color="inherit" /> : undefined}
              sx={{ ...audiobookButtonSx.brandOutlined, minHeight: 40 }}
            >
              {previewing ? '预试听中...' : '预试听'}
            </Button>
            <Button
              fullWidth
              variant="contained"
              disabled={busy || !canSave}
              onClick={handleRequestConfirmSave}
              startIcon={loading ? <CircularProgress size={18} color="inherit" /> : undefined}
              sx={{ ...audiobookButtonSx.brandContained, minHeight: 40 }}
            >
              {loading ? '保存中...' : '确认保存'}
            </Button>
          </Box>
          <TextField
            label="参考音频逐字内容"
            value={sampleText}
            onChange={(event) => {
              setSampleText(event.target.value)
              clearPreviewResult()
            }}
            size="small"
            fullWidth
            multiline
            minRows={3}
            maxRows={5}
            disabled={busy}
            placeholder="逐字填写录音或上传音频里实际说出的内容"
            helperText="官方会校验样本文本与音频 ASR；请填写参考音频里实际说出的完整内容，不要填写试听文本。"
            sx={{ gridColumn: '1 / -1', minWidth: 0 }}
          />
          <TextField
            label="StepAudio file_id（可选，留空自动上传生成）"
            value={fileId}
            onChange={(event) => {
              setFileId(event.target.value)
              clearPreviewResult()
            }}
            size="small"
            fullWidth
            disabled={busy}
            placeholder="file-Ckyl3cV09A"
            helperText="留空时预试听会使用 STEP_API_KEY/STEPFUN_API_KEY 调用 StepFun 文件接口生成 file_id；确认保存会复用该 file_id。"
            sx={{ gridColumn: '1 / -1', minWidth: 0 }}
          />
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
                  clearPreviewResult()
                  setMessage(null)
                }}
                sx={{ minWidth: 64 }}
              >
                清除样本
              </Button>
            )}
          </Box>
          {previewResult && (
            <Box
              sx={{
                gridColumn: '1 / -1',
                minWidth: 0,
                p: 1,
                border: '1px solid',
                borderColor: 'success.main',
                borderRadius: 1,
                backgroundColor: 'rgba(46, 125, 50, 0.06)',
              }}
            >
              <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 0.75 }}>
                预试听已生成，file_id：{previewResult.fileId || '未返回'}
              </Typography>
              <audio controls src={previewResult.previewAudioUrl} style={{ width: '100%', display: 'block' }} />
            </Box>
          )}
        </Box>

        <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, flexWrap: 'wrap' }}>
          <Button
            variant="outlined"
            disabled={busy}
            onClick={handleOpenRecordDialog}
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
          <Typography variant="caption" color="text.secondary" sx={{ minWidth: 220, flex: '1 1 280px' }}>
            StepAudio 参考样本当前限制 mp3/wav；录音会自动转换为 wav，本地索引不会保存大段编码内容。
          </Typography>
        </Box>
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
              const presetDisabled = Boolean(preset.disabled)
              const previewTooltip = presetDisabled
                ? (preset.disabledReason || '当前音色暂不可试听')
                : '试听'
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
                    {preset.disabledReason && (
                      <Typography
                        variant="caption"
                        color="warning.main"
                        sx={{
                          display: 'block',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                        }}
                      >
                        {preset.disabledReason}
                      </Typography>
                    )}
                  </Box>
                  <Box sx={{ display: 'flex', justifyContent: 'flex-end', alignItems: 'center', gap: 0.5 }}>
                    <Chip label="Clone" size="small" color="success" />
                    <Tooltip title={previewTooltip}>
                      <span>
                        <IconButton
                          size="small"
                          disabled={presetDisabled || Boolean(previewingVoiceId) || isDeleting}
                          onClick={() => onPreviewCustomVoice(preset, 'stepaudio-2.5-tts')}
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
            {filteredPresets.length > VISIBLE_STEPAUDIO_VOICE_LIMIT && (
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
        onClose={handleCloseBillingConfirm}
        fullWidth
        maxWidth="xs"
      >
        <DialogTitle>收费确认</DialogTitle>
        <DialogContent dividers>
          <Typography variant="body2" sx={{ mb: 1 }}>
            本次确认保存可能产生 9.9 元/音色费用。
          </Typography>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
            请确认已经完成预试听，并且对参考音色效果满意。确认后会保存该 StepAudio 复刻音色，后续可在角色音色下拉中直接选择。
          </Typography>
          <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
            音色名称：{name.trim() || '未命名'}；file_id：{previewResult?.fileId || '未返回'}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={handleCloseBillingConfirm} disabled={loading}>
            取消
          </Button>
          <Button
            variant="contained"
            color="warning"
            disabled={loading || !canSave}
            onClick={handleConfirmBillingSave}
            startIcon={loading ? <CircularProgress size={18} color="inherit" /> : undefined}
          >
            {loading ? '保存中...' : '确认收费并保存'}
          </Button>
        </DialogActions>
      </Dialog>
    </Paper>
  )
}

export default StepAudioVoiceCloneWorkbench
