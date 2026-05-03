import type { ChangeEvent } from 'react'

import {
  Alert,
  Box,
  Button,
  Typography,
} from '@mui/material'

import CosyVoiceVoiceWorkbench from './CosyVoiceVoiceWorkbench'
import type {
  VoiceCatalogMeta,
  VoicePreset,
} from './types'

type VoiceCatalogNoticeSeverity = 'success' | 'warning' | 'info'

interface VoiceCatalogStatusPanelProps {
  voiceCatalogMeta?: VoiceCatalogMeta | null
  voiceCatalogSummary: string
  voiceCatalogNotice: string
  voiceCatalogNoticeSeverity: VoiceCatalogNoticeSeverity
  showCustomVoiceWorkbench: boolean
  voiceError: string | null
  voiceLoading: boolean
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
  onFetchVoiceCatalog: () => void
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

const VoiceCatalogStatusPanel = ({
  voiceCatalogMeta,
  voiceCatalogSummary,
  voiceCatalogNotice,
  voiceCatalogNoticeSeverity,
  showCustomVoiceWorkbench,
  voiceError,
  voiceLoading,
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
  onFetchVoiceCatalog,
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
}: VoiceCatalogStatusPanelProps) => (
  <Box sx={{ flex: 1, minWidth: 260 }}>
    {voiceCatalogMeta && (
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1 }}>
        {voiceCatalogSummary}
      </Typography>
    )}
    <Alert severity={voiceCatalogNoticeSeverity} sx={{ mb: 1 }}>
      {voiceCatalogNotice}
    </Alert>
    {showCustomVoiceWorkbench && (
      <CosyVoiceVoiceWorkbench
        cloneName={cloneName}
        cloneUrl={cloneUrl}
        cloneLoading={cloneLoading}
        cloneUploading={cloneUploading}
        cloneRecording={cloneRecording}
        cloneDeletingId={cloneDeletingId}
        cloneError={cloneError}
        cloneSuccess={cloneSuccess}
        cloneRecordDialogOpen={cloneRecordDialogOpen}
        designName={designName}
        designPrompt={designPrompt}
        designPreviewText={designPreviewText}
        designLoading={designLoading}
        designError={designError}
        designSuccess={designSuccess}
        customVoicePresets={customVoicePresets}
        onCloneNameChange={onCloneNameChange}
        onCloneUrlChange={onCloneUrlChange}
        onCreateCloneVoice={onCreateCloneVoice}
        onOpenCloneRecordDialog={onOpenCloneRecordDialog}
        onUploadCloneAudio={onUploadCloneAudio}
        onDesignNameChange={onDesignNameChange}
        onDesignPromptChange={onDesignPromptChange}
        onDesignPreviewTextChange={onDesignPreviewTextChange}
        onCreateDesignVoice={onCreateDesignVoice}
        onDeleteCustomVoice={onDeleteCustomVoice}
        onCloseCloneRecordDialog={onCloseCloneRecordDialog}
        onStartCloneRecording={onStartCloneRecording}
        onStopCloneRecording={onStopCloneRecording}
      />
    )}
    {voiceError && (
      <Alert
        severity="warning"
        action={
          <Button size="small" onClick={onFetchVoiceCatalog} disabled={voiceLoading}>
            {voiceLoading ? '同步中...' : '重新同步'}
          </Button>
        }
        sx={{ mb: 1 }}
      >
        {voiceError}
      </Alert>
    )}
  </Box>
)

export default VoiceCatalogStatusPanel
