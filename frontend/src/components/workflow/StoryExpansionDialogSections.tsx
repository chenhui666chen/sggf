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
import { STORY_PRESERVE_WRITTEN_MODE_LABELS } from '@/utils/storyExpansionLabels'
import {
  CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS,
  CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS,
} from '@/utils/storyExpansionPolicy'

const EXPANSION_MODE_OPTIONS: Array<{
  value: StoryExpansionMode
  label: string
  description: string
}> = [
  {
    value: 'total',
    label: '常规协同',
    description: `按目标细化章节数和人物数扩展，推荐总规模不超过${CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS}章；超过后建议切换长篇框架，${CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS}章后必须切换。`,
  },
  { value: 'epic_framework', label: '长篇框架协同', description: '优先生成总卷框架，再让人物体系与长篇结构对齐。' },
  { value: 'volume_detail', label: '单卷细化协同', description: '基于已有长篇框架细化某一卷，并同步补齐该卷相关人物。' },
]

const PRESERVE_WRITTEN_MODE_OPTIONS: Array<{
  value: StoryPreserveWrittenMode
  label: string
  description: string
}> = [
  {
    value: 'extract_extend',
    label: STORY_PRESERVE_WRITTEN_MODE_LABELS.extract_extend,
    description: '先从已写正文提取细纲，再基于提取结果协同扩展，质量最佳。',
  },
  {
    value: 'preserve_written',
    label: STORY_PRESERVE_WRITTEN_MODE_LABELS.preserve_written,
    description: '按已写章节摘要保护正文，不额外做细纲提取，速度更快。',
  },
  {
    value: 'regenerate_all',
    label: STORY_PRESERVE_WRITTEN_MODE_LABELS.regenerate_all,
    description: '不参考数据库中的已写章节，适合准备整体重构。',
  },
]

const EXPANSION_MODE_TOOLTIP_LINES = [
  `常规协同：推荐总规模不超过${CONVENTIONAL_COLLABORATION_RECOMMENDED_MAX_CHAPTERS}章，${CONVENTIONAL_COLLABORATION_MAX_TOTAL_CHAPTERS}章后必须切换`,
  '长篇框架协同：先规划总卷结构',
  '单卷细化协同：基于已有框架细化',
]

const PRESERVE_WRITTEN_TOOLTIP_LINES = [
  '提取后扩展：质量最佳，先提取细纲',
  '仅保护正文：速度更快，不提取细纲',
  '忽略已写正文：适合整体重构',
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
        tooltipTitle="扩展模式说明"
        tooltipLines={EXPANSION_MODE_TOOLTIP_LINES}
        label="扩展模式"
        value={expansionMode}
        onChange={handlers.onExpansionModeChange}
        options={EXPANSION_MODE_OPTIONS}
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
          tooltipTitle="已写章节处理说明"
          tooltipLines={PRESERVE_WRITTEN_TOOLTIP_LINES}
          label="已写章节处理"
          value={preserveWrittenMode}
          onChange={handlers.onPreserveWrittenModeChange}
          options={PRESERVE_WRITTEN_MODE_OPTIONS}
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
  return (
    <Box>
      <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
        系统预检
      </Typography>
      {analysisLoading ? (
        <Typography variant="body2" color="text.secondary">
          正在分析最佳执行方向与模型适配...
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
                bgcolor: 'rgba(15, 23, 42, 0.02)',
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
                          bgcolor: '#fff',
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
                模型计划
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
          调整目标后将自动给出推荐方向。
        </Typography>
      )}
    </Box>
  )
}
