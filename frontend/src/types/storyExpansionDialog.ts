import type {
  StoryExpansionAnalysis,
  StoryExpansionFrameworkMetadata,
  StoryExpansionIntent,
  StoryExpansionMode,
  StoryPreserveWrittenMode,
  StoryExpansionStrategy,
} from '@/types/storyExpansion'

export interface StoryExpansionDialogContextState {
  analysis: StoryExpansionAnalysis | null
  analysisLoading: boolean
  currentChapterCount: number
  currentCharacterCount: number
  recommendedMode: StoryExpansionMode
}

export interface StoryExpansionDialogFormState {
  targetChapterCount: number | null
  targetCharacterCount: number | null
  expansionMode: StoryExpansionMode
  totalVolumes: number | null
  totalChaptersMin: number | null
  totalChaptersMax: number | null
  frameworkMetadata?: StoryExpansionFrameworkMetadata | null
  targetVolumeIndex: number | null
  volumeChaptersMin: number | null
  volumeChaptersMax: number | null
  volumeCharacterIncrement: number | null
  autoSupplementEnabled: boolean
  preserveWrittenMode: StoryPreserveWrittenMode
}

export interface StoryExpansionDialogFormHandlers {
  onTargetChapterCountChange: (count: number | null) => void
  onTargetCharacterCountChange: (count: number | null) => void
  onExpansionModeChange: (mode: StoryExpansionMode) => void
  onTotalVolumesChange: (volumes: number | null) => void
  onTotalChaptersMinChange: (count: number | null) => void
  onTotalChaptersMaxChange: (count: number | null) => void
  onTargetVolumeIndexChange: (index: number | null) => void
  onVolumeChaptersMinChange: (count: number | null) => void
  onVolumeChaptersMaxChange: (count: number | null) => void
  onVolumeCharacterIncrementChange: (count: number | null) => void
  onAutoSupplementChange: (enabled: boolean) => void
  onPreserveWrittenModeChange: (mode: StoryPreserveWrittenMode) => void
}

export interface StoryExpansionDialogHandlers extends StoryExpansionDialogFormHandlers {
  onClose: () => void
  onConfirm: () => void
}

export interface StoryExpansionRequestControls {
  strategy: StoryExpansionStrategy
  intent: StoryExpansionIntent
}
