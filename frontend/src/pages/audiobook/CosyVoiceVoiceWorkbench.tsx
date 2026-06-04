import { useState, type ChangeEvent } from 'react'
import {
  Box,
  Paper,
  Typography,
} from '@mui/material'

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
  designPreviewText: string
  designLoading: boolean
  designError: string | null
  designSuccess: string | null
  customVoicePresets: VoicePreset[]
  onCloneNameChange: (value: string) => void
  onCloneUrlChange: (value: string) => void
  onCreateCloneVoice: () => void
  onOpenCloneRecordDialog: () => void
  onUploadCloneAudio: (event: ChangeEvent<HTMLInputElement>) => void
  onDesignNameChange: (value: string) => void
  onDesignPromptChange: (value: string) => void
  onDesignPreviewTextChange: (value: string) => void
  onCreateDesignVoice: () => void
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
  designPreviewText,
  designLoading,
  designError,
  designSuccess,
  customVoicePresets,
  onCloneNameChange,
  onCloneUrlChange,
  onCreateCloneVoice,
  onOpenCloneRecordDialog,
  onUploadCloneAudio,
  onDesignNameChange,
  onDesignPromptChange,
  onDesignPreviewTextChange,
  onCreateDesignVoice,
  onDeleteCustomVoice,
  onCloseCloneRecordDialog,
  onStartCloneRecording,
  onStopCloneRecording,
}: CosyVoiceWorkbench) => {
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
          自定义音色管理（CosyVoice v3.5-plus）
        </Typography>
        <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
          CosyVoice v3.5-plus 不提供系统音色。你可以通过“声音复刻”导入真实样本，也可以通过“声音设计”用文字描述生成新声线；创建完成后会出现在下方音色列表中。
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
            designPreviewText={designPreviewText}
            designLoading={designLoading}
            busy={voiceCreationBusy}
            designError={designError}
            designSuccess={designSuccess}
            onDesignNameChange={onDesignNameChange}
            onDesignPromptChange={onDesignPromptChange}
            onDesignPreviewTextChange={onDesignPreviewTextChange}
            onCreateDesignVoice={onCreateDesignVoice}
          />
        </Box>

        <CosyVoiceCustomVoiceList
          customVoicePresets={customVoicePresets}
          cloneDeletingId={cloneDeletingId}
          deleteDisabled={deleteDisabled}
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
