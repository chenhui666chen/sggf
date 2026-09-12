import { useTranslation } from 'react-i18next'

import {
  Alert,
  Box,
  Chip,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Tooltip,
  Typography,
} from '@mui/material'
import type {
  StoryExpansionMode,
  StoryPreserveWrittenMode,
} from '@/types/storyExpansion'
import type {
  StoryExpansionDialogFormHandlers,
  StoryExpansionDialogFormState,
} from '@/types/storyExpansionDialog'
import type {
  StoryExpansionDialogConfigBlock,
  StoryExpansionDialogFieldKey,
  StoryExpansionDialogFieldView,
  StoryExpansionDialogViewModel,
} from '@/utils/storyExpansionDialogView'
import { STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS } from '@/utils/storyExpansionLabels'
import {
  CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS,
  CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS,
} from '@/utils/storyExpansionPolicy'

const EXPANSION_MODE_OPTIONS: Array<{
  value: StoryExpansionMode
  labelKey: string
  descriptionKey: string
}> = [
  {
    value: 'total',
    labelKey: 'storyExpansion.mode.total',
    descriptionKey: 'storyExpansion.dialog.section.modeTotalDesc',
  },
  { value: 'epic_framework', labelKey: 'storyExpansion.mode.epicFramework', descriptionKey: 'storyExpansion.dialog.section.modeEpicDesc' },
  { value: 'volume_detail', labelKey: 'storyExpansion.mode.volumeDetail', descriptionKey: 'storyExpansion.dialog.section.modeVolumeDesc' },
]

const PRESERVE_WRITTEN_MODE_OPTIONS: Array<{
  value: StoryPreserveWrittenMode
  labelKey: string
  descriptionKey: string
}> = [
  {
    value: 'extract_extend',
    labelKey: STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS.extract_extend,
    descriptionKey: 'storyExpansion.dialog.section.preserveExtractDesc',
  },
  {
    value: 'preserve_written',
    labelKey: STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS.preserve_written,
    descriptionKey: 'storyExpansion.dialog.section.preserveWrittenDesc',
  },
  {
    value: 'regenerate_all',
    labelKey: STORY_PRESERVE_WRITTEN_MODE_LABEL_KEYS.regenerate_all,
    descriptionKey: 'storyExpansion.dialog.section.preserveRegenerateDesc',
  },
]

const EXPANSION_MODE_TOOLTIP_LINES = [
  'storyExpansion.dialog.section.modeTooltipTotal',
  'storyExpansion.dialog.section.modeTooltipEpic',
  'storyExpansion.dialog.section.modeTooltipVolume',
]

const PRESERVE_WRITTEN_TOOLTIP_LINES = [
  'storyExpansion.dialog.section.preserveTooltipExtract',
  'storyExpansion.dialog.section.preserveTooltipWritten',
  'storyExpansion.dialog.section.preserveTooltipRegenerate',
]

function parseNullableInteger(value: string): number | null {
  if (!value.trim()) {
    return null
  }

  const parsed = Number.parseInt(value, 10)
  return Number.isNaN(parsed) ? null : parsed
}

function toTextFieldValue(value: number | null | undefined): number | '' {
  return typeof value === 'number' ? value : ''
}

interface TooltipInfoContentProps {
  title: string
  lines: string[]
}

function TooltipInfoContent({ title, lines }: TooltipInfoContentProps) {
  return (
    <Box sx={{ p: 1 }}>
      <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 1 }}>
        {title}
      </Typography>
      {lines.map((line, index) => (
        <Typography key={`${line}-${index}`} variant="body2" sx={{ mb: index < lines.length - 1 ? 0.5 : 0 }}>
          {`• ${line}`}
        </Typography>
      ))}
    </Box>
  )
}

interface SelectOption<TValue extends string> {
  value: TValue
  label: string
  description?: string
}

interface TooltipSelectFieldProps<TValue extends string> {
  tooltipTitle: string
  tooltipLines: string[]
  label: string
  value: TValue
  onChange: (value: TValue) => void
  options: Array<SelectOption<TValue>>
  disabled?: boolean
  helperText?: string
  showOptionDescription?: boolean
}

function TooltipSelectField<TValue extends string>({
  tooltipTitle,
  tooltipLines,
  label,
  value,
  onChange,
  options,
  disabled,
  helperText,
  showOptionDescription = false,
}: TooltipSelectFieldProps<TValue>) {
  return (
    <Tooltip
      title={<TooltipInfoContent title={tooltipTitle} lines={tooltipLines} />}
      placement="right"
      arrow
    >
      <Box component="span" sx={{ display: 'block' }}>
        <TextField
          select
          label={label}
          fullWidth
          value={value}
          onChange={(e) => onChange(e.target.value as TValue)}
          disabled={disabled}
          helperText={helperText}
        >
          {options.map((item) => (
            <MenuItem key={item.value} value={item.value}>
              {showOptionDescription ? (
                <Box sx={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 0.5 }}>
                  <Typography variant="body2" fontWeight={600}>
                    {item.label}
                  </Typography>
                  {item.description ? (
                    <Typography variant="caption" color="text.secondary">
                      {item.description}
                    </Typography>
                  ) : null}
                </Box>
              ) : (
                item.label
              )}
            </MenuItem>
          ))}
        </TextField>
      </Box>
    </Tooltip>
  )
}

interface StoryExpansionConfigSectionProps {
  form: StoryExpansionDialogFormState
  handlers: StoryExpansionDialogFormHandlers
  view: StoryExpansionDialogViewModel
}

export function StoryExpansionConfigSection({
  form,
  handlers,
  view,
}: StoryExpansionConfigSectionProps) {
  const { t } = useTranslation()
  const expansionModeOptions = EXPANSION_MODE_OPTIONS.map((option) => ({
    value: option.value,
    label: t(option.labelKey),
    description: t(option.descriptionKey, {
      recommended: CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS,
      max: CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS,
    }),
  }))
  const preserveWrittenModeOptions = PRESERVE_WRITTEN_MODE_OPTIONS.map((option) => ({
    value: option.value,
    label: t(option.labelKey),
    description: t(option.descriptionKey),
  }))
  const expansionModeTooltipLines = EXPANSION_MODE_TOOLTIP_LINES.map((key) => t(key, {
    recommended: CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS,
    max: CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS,
  }))
  const preserveWrittenTooltipLines = PRESERVE_WRITTEN_TOOLTIP_LINES.map((key) => t(key))
  const {
    targetChapterCount,
    targetCharacterCount,
    expansionMode,
    totalVolumes,
    totalChaptersMin,
    totalChaptersMax,
    targetVolumeIndex,
    volumeChaptersMin,
    volumeChaptersMax,
    volumeCharacterIncrement,
    autoSupplementEnabled,
    preserveWrittenMode,
  } = form
  const fieldValueMap: Record<StoryExpansionDialogFieldKey, number | null | undefined> = {
    targetChapterCount,
    targetCharacterCount,
    totalVolumes,
    totalChaptersMin,
    totalChaptersMax,
    targetVolumeIndex,
    volumeChaptersMin,
    volumeChaptersMax,
    displayedTargetCharacterCount: view.displayedTargetCharacterCount,
    volumeCharacterIncrement,
  }

  const fieldChangeMap: Partial<Record<StoryExpansionDialogFieldKey, (value: number | null) => void>> = {
    targetChapterCount: handlers.onTargetChapterCountChange,
    targetCharacterCount: handlers.onTargetCharacterCountChange,
    totalVolumes: handlers.onTotalVolumesChange,
    totalChaptersMin: handlers.onTotalChaptersMinChange,
    totalChaptersMax: handlers.onTotalChaptersMaxChange,
    targetVolumeIndex: handlers.onTargetVolumeIndexChange,
    volumeChaptersMin: handlers.onVolumeChaptersMinChange,
    volumeChaptersMax: handlers.onVolumeChaptersMaxChange,
    volumeCharacterIncrement: (value) => handlers.onVolumeCharacterIncrementChange(value == null ? null : Math.max(0, value)),
  }

  const renderField = (field: StoryExpansionDialogFieldView) => {
    const handleChange = field.readOnly ? undefined : fieldChangeMap[field.key]
    const inputProps = field.min != null || field.max != null
      ? {
        min: field.min,
        max: field.max,
        inputMode: 'numeric' as const,
        pattern: '[0-9]*',
      }
      : {
        inputMode: 'numeric' as const,
        pattern: '[0-9]*',
      }
    const sx = field.fullWidth
      ? { width: '100%' }
      : field.flex
        ? { flex: field.flex }
        : undefined

    return (
      <TextField
        key={field.key}
        label={field.label}
        type="number"
        fullWidth={field.fullWidth}
        value={toTextFieldValue(fieldValueMap[field.key])}
        onChange={handleChange ? (e) => handleChange(parseNullableInteger(e.target.value)) : undefined}
        placeholder={field.placeholder}
        autoComplete="off"
        inputProps={inputProps}
        InputProps={field.readOnly ? { readOnly: true } : undefined}
        helperText={field.helperText}
        sx={sx}
      />
    )
  }

  const renderConfigBlock = (block: StoryExpansionDialogConfigBlock) => {
    if (block.kind === 'alert') {
      return (
        <Alert key={block.key} severity={block.alert.severity} variant={block.alert.variant}>
          {block.alert.text}
        </Alert>
      )
    }

    return (
      <Box key={block.key} sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
        {block.fields.map(renderField)}
      </Box>
    )
  }

  return (
    <Stack spacing={2.5}>
      <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
        <Chip label={view.currentChapterChipLabel} color="primary" variant="outlined" />
        <Chip label={view.currentCharacterChipLabel} color="secondary" variant="outlined" />
        <Chip label={`${view.chapterDeltaChipLabel} ${view.chapterDeltaLabel}`} color="success" />
        <Chip label={`${view.characterDeltaChipLabel} ${view.characterDeltaLabel}`} color="warning" />
      </Box>

      <Typography variant="caption" color="text.secondary">
        {view.currentCountHelperText}
      </Typography>

      <TooltipSelectField
        tooltipTitle={t('storyExpansion.dialog.section.modeInfoTitle')}
        tooltipLines={expansionModeTooltipLines}
        label={t('storyExpansion.dialog.section.modeLabel')}
        value={expansionMode}
        onChange={handlers.onExpansionModeChange}
        options={expansionModeOptions}
        disabled={view.isLockedToVolumeDetail}
        helperText={view.expansionModeHelperText || undefined}
        showOptionDescription
      />

      {view.lockedModeAlertText && (
        <Alert severity="info" sx={{ mt: -1 }}>
          {view.lockedModeAlertText}
        </Alert>
      )}

      {view.writtenModeInfoAlertText ? (
        <Alert severity="info" variant="outlined">
          {view.writtenModeInfoAlertText}
        </Alert>
      ) : (
        <TooltipSelectField
          tooltipTitle={t('storyExpansion.dialog.section.writtenInfoTitle')}
          tooltipLines={preserveWrittenTooltipLines}
          label={t('storyExpansion.dialog.section.writtenLabel')}
          value={preserveWrittenMode}
          onChange={handlers.onPreserveWrittenModeChange}
          options={preserveWrittenModeOptions}
        />
      )}

      {view.configBlocks.map(renderConfigBlock)}

      <FormControlLabel
        control={(
          <Switch
            checked={autoSupplementEnabled}
            onChange={(_, checked) => handlers.onAutoSupplementChange(checked)}
          />
        )}
        label={view.autoSupplementLabel}
      />
    </Stack>
  )
}

interface StoryExpansionPrecheckSectionProps {
  analysisLoading: boolean
  autoSupplementEnabled: boolean
  view: StoryExpansionDialogViewModel
}

export function StoryExpansionPrecheckSection({
  analysisLoading,
  autoSupplementEnabled,
  view,
}: StoryExpansionPrecheckSectionProps) {
  const { t } = useTranslation()
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        {t('storyExpansion.dialog.section.precheckTitle')}
      </Typography>
      {analysisLoading ? (
        <Typography variant="body2" color="text.secondary">
          {t('storyExpansion.dialog.section.precheckAnalyzing')}
        </Typography>
      ) : view.hasAnalysis ? (
        <Stack spacing={1.5}>
          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            {view.precheckChips.map((item) => (
              <Chip
                key={item.key}
                label={item.label}
                color={item.color}
                variant="outlined"
              />
            ))}
          </Box>

          {view.analysisSummaryText && (
            <Typography variant="body2">
              {view.analysisSummaryText}
            </Typography>
          )}

          {!!view.autoEstimateHints.length && (
            <Alert severity="info" variant="outlined">
              {view.autoEstimateHints.join('；')}
            </Alert>
          )}

          {view.modeSuitabilityView ? (
            <Box
              sx={{
                p: 1.5,
                borderRadius: 2,
                border: '1px solid',
                borderColor: 'divider',
                bgcolor: 'grey.100',
              }}
            >
              <Stack spacing={1.2}>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  {view.modeSuitabilityView.chips.map((item) => (
                    <Chip
                      key={item.key}
                      label={item.label}
                      color={item.color}
                      variant="outlined"
                    />
                  ))}
                </Box>

                {view.modeSuitabilityView.summary && (
                  <Typography variant="body2">
                    {view.modeSuitabilityView.summary}
                  </Typography>
                )}

                {view.modeSuitabilityView.reason && (
                  <Typography variant="body2" color="text.secondary">
                    {view.modeSuitabilityView.reason}
                  </Typography>
                )}

                {!!view.modeSuitabilityView.bands.length && (
                  <Stack spacing={0.8}>
                    {view.modeSuitabilityView.bands.map((item) => (
                      <Box
                        key={item.key}
                        sx={{
                          p: 1,
                          borderRadius: 1.5,
                          bgcolor: 'background.paper',
                          border: '1px solid',
                          borderColor: 'divider',
                        }}
                      >
                        <Typography variant="body2" sx={{ fontWeight: 600 }}>
                          {item.label}
                          {item.rangeText ? `：${item.rangeText}` : ''}
                        </Typography>
                        {item.detail ? (
                          <Typography variant="body2" color="text.secondary">
                            {item.detail}
                          </Typography>
                        ) : null}
                      </Box>
                    ))}
                  </Stack>
                )}
              </Stack>
            </Box>
          ) : null}

          {view.intentReasonText && (
            <Typography variant="body2" color="text.secondary">
              {view.intentReasonText}
            </Typography>
          )}

          {view.executionModeReasonText && (
            <Typography variant="body2" color="text.secondary">
              {view.executionModeReasonText}
            </Typography>
          )}

          {view.writtenContextText && (
            <Typography variant="body2" color="text.secondary">
              {view.writtenContextText}
            </Typography>
          )}

          {autoSupplementEnabled && view.autoSupplementText && (
            <Alert severity="info">
              {view.autoSupplementText}
            </Alert>
          )}

          {view.epicConfigText && (
            <Typography variant="body2" color="text.secondary">
              {view.epicConfigText}
            </Typography>
          )}

          {view.volumeDetailText && (
            <Typography variant="body2" color="text.secondary">
              {view.volumeDetailText}
            </Typography>
          )}

          {view.volumeCharacterPlanText && (
            <Typography variant="body2" color="text.secondary">
              {view.volumeCharacterPlanText}
            </Typography>
          )}

          {!!view.analysisWarnings.length && (
            <Alert severity="warning">
              {view.analysisWarnings.join(' ')}
            </Alert>
          )}

          {!!view.modelPlanLines.length && (
            <Box>
              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                {t('storyExpansion.dialog.section.modelPlanTitle')}
              </Typography>
              {view.modelPlanLines.map((line, index) => (
                <Typography key={`${line}-${index}`} variant="body2" color="text.secondary">
                  {line}
                </Typography>
              ))}
            </Box>
          )}
        </Stack>
      ) : (
        <Typography variant="body2" color="text.secondary">
          {t('storyExpansion.dialog.section.precheckEmpty')}
        </Typography>
      )}
    </Box>
  )
}
