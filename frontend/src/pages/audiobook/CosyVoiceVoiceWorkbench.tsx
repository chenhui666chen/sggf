import { useState, type ChangeEvent } from 'react'
import {
  Box,
  Paper,
  Typography,
} from '@mui/material'

import { useTranslation } from 'react-i18next'

import CosyVoiceCloneRecordDialog from './CosyVoiceCloneRecordDialog'
import CosyVoiceCloneVoicePanel from './CosyVoiceCloneVoicePanel'
import CosyVoiceCustomVoiceList from './CosyVoiceCustomVoiceList'
import CosyVoiceDeleteVoiceDialog, { type PendingDeleteVoice } from './CosyVoiceDeleteVoiceDialog'
import CosyVoiceDesignVoicePanel from './CosyVoiceDesignVoicePanel'
import type { VoicePreset } from './types'

export interface CosyVoiceWorkbench {
  cloneName: string
  cloneUrl: string
  cloneLoading: boolean
  cloneUploading: boolean
  cloneRecording: boolean
  cloneDeletingId: string | null
  cloneError: string | null
  cloneSuccess: string | null
  cloneRecordDialogOpen: boolean
  designName: string
  designPrompt: string
  designPreviewAudioUrl: string
  designPreviewVoiceId: string
  designLoading: boolean
  designError: string | null
  designSuccess: string | null
  customVoicePreviewingId: string | null
  customVoicePresets: VoicePreset[]
  onCloneNameChange: (value: string) => void
  onCloneUrlChange: (value: string) => void
  onCreateCloneVoice: () => void
  onOpenCloneRecordDialog: () => void
  onUploadCloneAudio: (event: ChangeEvent<HTMLInputElement>) => void
  onDesignNameChange: (value: string) => void
  onDesignPromptChange: (value: string) => void
  onCreateDesignVoice: () => void
  onPreviewDesignVoice: () => void
  onPreviewCustomVoice: (voice: VoicePreset) => void
  onDeleteCustomVoice: (voiceId: string, label?: string) => void
  onCloseCloneRecordDialog: () => void
  onStartCloneRecording: () => void
  onStopCloneRecording: () => void
}

const CosyVoiceVoiceWorkbench = ({
  cloneName,
  cloneUrl,
  cloneLoading,
  cloneUploading,
  cloneRecording,
  cloneDeletingId,
  cloneError,
  cloneSuccess,
  cloneRecordDialogOpen,
  designName,
  designPrompt,
  designPreviewAudioUrl,
  designPreviewVoiceId,
  designLoading,
  designError,
  designSuccess,
  customVoicePreviewingId,
  customVoicePresets,
  onCloneNameChange,
  onCloneUrlChange,
  onCreateCloneVoice,
  onOpenCloneRecordDialog,
  onUploadCloneAudio,
  onDesignNameChange,
  onDesignPromptChange,
  onCreateDesignVoice,
  onPreviewDesignVoice,
  onPreviewCustomVoice,
  onDeleteCustomVoice,
  onCloseCloneRecordDialog,
  onStartCloneRecording,
  onStopCloneRecording,
}: CosyVoiceWorkbench) => {
  const { t } = useTranslation()
  const voiceCreationBusy = cloneLoading || cloneUploading || cloneRecording || designLoading
  const deleteDisabled = cloneLoading || cloneUploading || designLoading
  const [pendingDeleteVoice, setPendingDeleteVoice] = useState<PendingDeleteVoice | null>(null)

  const handleRequestDeleteVoice = (voiceId: string, label?: string) => {
    setPendingDeleteVoice({
      id: voiceId,
      label: label || voiceId,
    })
  }

  const handleCloseDeleteVoiceDialog = () => {
    if (cloneDeletingId) return
    setPendingDeleteVoice(null)
  }

  const handleConfirmDeleteVoice = () => {
    if (!pendingDeleteVoice || cloneDeletingId) return
    onDeleteCustomVoice(pendingDeleteVoice.id, pendingDeleteVoice.label)
    setPendingDeleteVoice(null)
  }

  return (
    <>
      <Paper variant="outlined" sx={{ mb: 1, p: 1.5 }}>
        <Typography variant="subtitle2" sx={{ mb: 0.5 }}>
          {t('audiobook.cosyVoiceVoiceWorkbench.title')}
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          {t('audiobook.cosyVoiceVoiceWorkbench.description')}
        </Typography>
        <Box sx={{ display: 'grid', gap: 1.25 }}>
          <CosyVoiceCloneVoicePanel
            cloneName={cloneName}
            cloneUrl={cloneUrl}
            cloneLoading={cloneLoading}
            cloneUploading={cloneUploading}
            busy={voiceCreationBusy}
            cloneError={cloneError}
            cloneSuccess={cloneSuccess}
            onCloneNameChange={onCloneNameChange}
            onCloneUrlChange={onCloneUrlChange}
            onCreateCloneVoice={onCreateCloneVoice}
            onOpenCloneRecordDialog={onOpenCloneRecordDialog}
            onUploadCloneAudio={onUploadCloneAudio}
          />

          <CosyVoiceDesignVoicePanel
            designName={designName}
            designPrompt={designPrompt}
            designPreviewAudioUrl={designPreviewAudioUrl}
            designPreviewVoiceId={designPreviewVoiceId}
            designLoading={designLoading}
            busy={voiceCreationBusy}
            designError={designError}
            designSuccess={designSuccess}
            onDesignNameChange={onDesignNameChange}
            onDesignPromptChange={onDesignPromptChange}
            onCreateDesignVoice={onCreateDesignVoice}
            onPreviewDesignVoice={onPreviewDesignVoice}
          />
        </Box>

        <CosyVoiceCustomVoiceList
          customVoicePresets={customVoicePresets}
          cloneDeletingId={cloneDeletingId}
          deleteDisabled={deleteDisabled}
          previewingVoiceId={customVoicePreviewingId}
          onPreviewCustomVoice={onPreviewCustomVoice}
          onRequestDeleteVoice={handleRequestDeleteVoice}
        />
      </Paper>

      <CosyVoiceCloneRecordDialog
        open={cloneRecordDialogOpen}
        cloneRecording={cloneRecording}
        cloneLoading={cloneLoading}
        cloneUploading={cloneUploading}
        onClose={onCloseCloneRecordDialog}
        onStartCloneRecording={onStartCloneRecording}
        onStopCloneRecording={onStopCloneRecording}
      />

      <CosyVoiceDeleteVoiceDialog
        pendingDeleteVoice={pendingDeleteVoice}
        cloneDeletingId={cloneDeletingId}
        onClose={handleCloseDeleteVoiceDialog}
        onConfirm={handleConfirmDeleteVoice}
      />
    </>
  )
}

export default CosyVoiceVoiceWorkbench
