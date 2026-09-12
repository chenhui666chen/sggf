import type { ReactNode } from 'react'

import CloseIcon from '@mui/icons-material/Close'
import RefreshIcon from '@mui/icons-material/Refresh'
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  FormControlLabel,
  Grid,
  IconButton,
  InputLabel,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'
import { useTranslation } from 'react-i18next'

type DreamweaverConfigDialogTitleProps = {
  title: string
  subtitle: string
  onClose: () => void
}

export function DreamweaverConfigDialogTitle({
  title,
  subtitle,
  onClose,
}: DreamweaverConfigDialogTitleProps) {
  const { t } = useTranslation()
  return (
    <DialogTitle sx={{ pb: 1 }}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" spacing={1}>
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h6" sx={{ fontWeight: 800 }}>
            {title}
          </Typography>
          <Typography variant="caption" color="text.secondary">
            {subtitle}
          </Typography>
        </Box>
        <IconButton onClick={onClose} size="small" aria-label={t('common.close')}>
          <CloseIcon fontSize="small" />
        </IconButton>
      </Stack>
    </DialogTitle>
  )
}

type DreamweaverConfigDialogProjectSectionProps = {
  lockedProjectId?: number | null
  projectTitle?: string | null
  action?: ReactNode
}

export function DreamweaverConfigDialogProjectSection({
  lockedProjectId,
  projectTitle,
  action,
}: DreamweaverConfigDialogProjectSectionProps) {
  const { t } = useTranslation()
  if (lockedProjectId) {
    return (
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          border: '1px solid',
          borderColor: 'divider',
          bgcolor: 'grey.100',
        }}
      >
        <Typography variant="caption" color="text.secondary" display="block">
          {t('dreamweaverRun.configCurrentProject')}
        </Typography>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          {projectTitle || t('dreamweaverRun.configProjectId', { id: lockedProjectId })}
        </Typography>
      </Box>
    )
  }

  return (
    <Alert severity="info" action={action ?? undefined}>
      {t('dreamweaverRun.configSelectProjectFirst')}
    </Alert>
  )
}

type DreamweaverConfigDialogProjectAlertActionProps = {
  onClick: () => void
}

export function DreamweaverConfigDialogProjectAlertAction({
  onClick,
}: DreamweaverConfigDialogProjectAlertActionProps) {
  const { t } = useTranslation()
  return (
    <Button size="small" variant="outlined" onClick={onClick}>
      {t('dreamweaverRun.configGotoProjectList')}
    </Button>
  )
}

type DreamweaverConfigDialogCardProps = {
  title: string
  children: ReactNode
  footer?: ReactNode
}

function DreamweaverConfigDialogCard({
  title,
  children,
  footer,
}: DreamweaverConfigDialogCardProps) {
  return (
    <Paper variant="outlined" sx={{ p: 2, borderRadius: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 800, mb: 1 }}>
        {title}
      </Typography>
      {children}
      {footer ?? null}
    </Paper>
  )
}

type DreamweaverConfigDialogChapterSelectionCardProps = {
  toolbarActions: ReactNode
  listContent: ReactNode
  helperText: string
  maxHeight: string | number
}

export function DreamweaverConfigDialogChapterSelectionCard({
  toolbarActions,
  listContent,
  helperText,
  maxHeight,
}: DreamweaverConfigDialogChapterSelectionCardProps) {
  const { t } = useTranslation()
  return (
    <DreamweaverConfigDialogCard title={t('dreamweaverRun.configChapterSection')} footer={<Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>{helperText}</Typography>}>
      <Stack direction="row" alignItems="center" justifyContent="space-between" sx={{ mb: 1 }}>
        <Box />
        <Stack direction="row" spacing={1} alignItems="center" useFlexGap flexWrap="wrap">
          {toolbarActions}
        </Stack>
      </Stack>

      <Box
        sx={{
          maxHeight,
          overflow: 'auto',
          border: '1px solid',
          borderColor: 'divider',
          borderRadius: 2,
        }}
      >
        {listContent}
      </Box>
    </DreamweaverConfigDialogCard>
  )
}

type DreamweaverConfigDialogChapterToolbarProps = {
  toggleAllLabel: string
  onToggleAll: () => void
  toggleAllDisabled: boolean
  onRefresh: () => void
  refreshDisabled: boolean
  refreshStartIcon?: ReactNode
}

export function DreamweaverConfigDialogChapterToolbar({
  toggleAllLabel,
  onToggleAll,
  toggleAllDisabled,
  onRefresh,
  refreshDisabled,
  refreshStartIcon,
}: DreamweaverConfigDialogChapterToolbarProps) {
  const { t } = useTranslation()
  return (
    <>
      <Button size="small" onClick={onToggleAll} disabled={toggleAllDisabled}>
        {toggleAllLabel}
      </Button>
      <Button size="small" startIcon={refreshStartIcon ?? undefined} onClick={onRefresh} disabled={refreshDisabled}>
        {t('dreamweaverRun.libraryRefresh')}
      </Button>
    </>
  )
}

type DreamweaverConfigDialogChapterItemProps = {
  chapterId: number
  title: string
  snippet: string
  checked: boolean
  disabled: boolean
  onToggle: (chapterId: number) => void
}

export function DreamweaverConfigDialogChapterItem({
  chapterId,
  title,
  snippet,
  checked,
  disabled,
  onToggle,
}: DreamweaverConfigDialogChapterItemProps) {
  return (
    <ListItem
      disablePadding
      secondaryAction={
        <Checkbox edge="end" size="small" disabled={disabled} checked={checked} onChange={() => onToggle(chapterId)} />
      }
    >
      <ListItemButton onClick={() => onToggle(chapterId)} disabled={disabled} sx={{ pr: 6 }}>
        <ListItemText primary={title} secondary={snippet} />
      </ListItemButton>
    </ListItem>
  )
}

type DreamweaverConfigDialogChapterListProps = {
  loading: boolean
  children: ReactNode
}

export function DreamweaverConfigDialogChapterList({
  loading,
  children,
}: DreamweaverConfigDialogChapterListProps) {
  if (loading) {
    return <LinearProgress />
  }

  return <List dense disablePadding>{children}</List>
}

type DreamweaverConfigDialogChapterListItemsProps = {
  chapters: Array<{
    id: number
    chapter_number: number | string
    title?: string | null
    content?: string | null
  }>
  selectedChapterIds: number[]
  disabled: boolean
  onToggle: (chapterId: number) => void
}

export function DreamweaverConfigDialogChapterListItems({
  chapters,
  selectedChapterIds,
  disabled,
  onToggle,
}: DreamweaverConfigDialogChapterListItemsProps) {
  const { t } = useTranslation()
  return (
    <>
      {chapters.map((chapter) => {
        const raw = String(chapter.content || '').replace(/\s+/g, ' ').trim()
        const snippet = raw ? (raw.length > 64 ? raw.slice(0, 64) + '…' : raw) : t('dreamweaverRun.configSnippetEmpty')

        return (
          <DreamweaverConfigDialogChapterItem
            key={chapter.id}
            chapterId={chapter.id}
            title={`${chapter.chapter_number}. ${chapter.title || t('dreamweaverRun.configUntitledChapter')}`}
            snippet={snippet}
            checked={selectedChapterIds.includes(chapter.id)}
            disabled={disabled}
            onToggle={onToggle}
          />
        )
      })}
    </>
  )
}

type DreamweaverConfigDialogStrategyCardProps = {
  content: ReactNode
  helperText: string
}

export function DreamweaverConfigDialogStrategyCard({
  content,
  helperText,
}: DreamweaverConfigDialogStrategyCardProps) {
  const { t } = useTranslation()
  return (
    <DreamweaverConfigDialogCard
      title={t('dreamweaverRun.configStrategySection')}
      footer={
        <Typography variant="caption" color="text.secondary" display="block" sx={{ mt: 1 }}>
          {helperText}
        </Typography>
      }
    >
      <Stack spacing={1.5}>{content}</Stack>
    </DreamweaverConfigDialogCard>
  )
}

type DreamweaverConfigDialogStrategyToggleFieldProps = {
  title: string
  checked: boolean
  onChange: (checked: boolean) => void
  enabledLabel: string
  disabledLabel: string
  description: string
  disabled?: boolean
}

export function DreamweaverConfigDialogStrategyToggleField({
  title,
  checked,
  onChange,
  enabledLabel,
  disabledLabel,
  description,
  disabled = false,
}: DreamweaverConfigDialogStrategyToggleFieldProps) {
  return (
    <Stack spacing={0.5}>
      <Stack direction="row" alignItems="center" justifyContent="space-between">
        <Typography variant="body2" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        <FormControlLabel
          sx={{ mr: 0 }}
          control={<Switch checked={checked} onChange={(e) => onChange(e.target.checked)} disabled={disabled} />}
          label={checked ? enabledLabel : disabledLabel}
        />
      </Stack>
      <Typography variant="caption" color="text.secondary">
        {description}
      </Typography>
    </Stack>
  )
}

type DreamweaverConfigDialogStrategyFieldsProps = {
  fields: Array<{
    key: string
    title: string
    checked: boolean
    onChange: (checked: boolean) => void
    enabledLabel: string
    disabledLabel: string
    description: string
  }>
  abVariant: string
  onChangeAbVariant: (value: string) => void
  disabled?: boolean
}

export function DreamweaverConfigDialogStrategyFields({
  fields,
  abVariant,
  onChangeAbVariant,
  disabled = false,
}: DreamweaverConfigDialogStrategyFieldsProps) {
  return (
    <>
      {fields.map((field) => (
        <DreamweaverConfigDialogStrategyToggleField
          key={field.key}
          title={field.title}
          checked={field.checked}
          onChange={field.onChange}
          enabledLabel={field.enabledLabel}
          disabledLabel={field.disabledLabel}
          description={field.description}
          disabled={disabled}
        />
      ))}
      <DreamweaverConfigDialogExperimentField value={abVariant} onChange={onChangeAbVariant} disabled={disabled} />
    </>
  )
}

type DreamweaverConfigDialogExperimentFieldProps = {
  value: string
  onChange: (value: string) => void
  disabled?: boolean
}

export function DreamweaverConfigDialogExperimentField({
  value,
  onChange,
  disabled = false,
}: DreamweaverConfigDialogExperimentFieldProps) {
  const { t } = useTranslation()
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2" sx={{ fontWeight: 700 }}>
        {t('dreamweaverRun.configExperimentLabel')}
      </Typography>
      <TextField
        size="small"
        fullWidth
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder={t('dreamweaverRun.configExperimentPlaceholder')}
        inputProps={{ maxLength: 32 }}
      />
      <Typography variant="caption" color="text.secondary">
        {t('dreamweaverRun.configExperimentHint')}
      </Typography>
    </Stack>
  )
}

type DreamweaverConfigDialogSelectFieldProps = {
  labelId: string
  label: string
  value: string
  onChange: (value: string) => void
  options: Array<{ value: string; label: string }>
  disabled?: boolean
}

export function DreamweaverConfigDialogSelectField({
  labelId,
  label,
  value,
  onChange,
  options,
  disabled = false,
}: DreamweaverConfigDialogSelectFieldProps) {
  const { t } = useTranslation()
  return (
    <FormControl fullWidth size="small" disabled={disabled}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select labelId={labelId} value={value} label={label} onChange={(e) => onChange(String(e.target.value))}>
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {t(option.label)}
          </MenuItem>
        ))}
      </Select>
    </FormControl>
  )
}

type DreamweaverConfigDialogVisualSettingsCardProps = {
  notices?: ReactNode
  fields: ReactNode
  helperText: string
}

export function DreamweaverConfigDialogVisualSettingsCard({
  notices,
  fields,
  helperText,
}: DreamweaverConfigDialogVisualSettingsCardProps) {
  const { t } = useTranslation()
  return (
    <DreamweaverConfigDialogCard
      title={t('dreamweaverRun.configVisualSection')}
      footer={
        <Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>
          {helperText}
        </Typography>
      }
    >
      {notices ?? null}
      {fields}
    </DreamweaverConfigDialogCard>
  )
}

type DreamweaverConfigDialogVisualFieldGridProps = {
  stylePresetValue: string
  onStylePresetChange: (value: string) => void
  stylePresetOptions: Array<{ value: string; label: string }>
  imageRatioValue: string
  onImageRatioChange: (value: string) => void
  imageRatioOptions: Array<{ value: string; label: string }>
  imageResolutionValue: string
  onImageResolutionChange: (value: string) => void
  imageResolutionOptions: Array<{ value: string; label: string }>
  disabled?: boolean
}

export function DreamweaverConfigDialogVisualFieldGrid({
  stylePresetValue,
  onStylePresetChange,
  stylePresetOptions,
  imageRatioValue,
  onImageRatioChange,
  imageRatioOptions,
  imageResolutionValue,
  onImageResolutionChange,
  imageResolutionOptions,
  disabled = false,
}: DreamweaverConfigDialogVisualFieldGridProps) {
  const { t } = useTranslation()
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={12}>
        <DreamweaverConfigDialogSelectField
          labelId="style-preset-label"
          label={t('dreamweaverRun.regenStylePresetLabel')}
          value={stylePresetValue}
          onChange={onStylePresetChange}
          disabled={disabled}
          options={stylePresetOptions}
        />
      </Grid>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="image-ratio-label"
          label={t('dreamweaverRun.regenImageRatioLabel')}
          value={imageRatioValue}
          onChange={onImageRatioChange}
          disabled={disabled}
          options={imageRatioOptions}
        />
      </Grid>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="image-resolution-label"
          label={t('dreamweaverRun.configImageResolution')}
          value={imageResolutionValue}
          onChange={onImageResolutionChange}
          disabled={disabled}
          options={imageResolutionOptions}
        />
      </Grid>
    </Grid>
  )
}

type DreamweaverConfigDialogModelFieldGridProps = {
  imageModelValue: string
  onImageModelChange: (value: string) => void
  imageModelOptions: Array<{ value: string; label: string }>
  videoModelValue: string
  onVideoModelChange: (value: string) => void
  videoModelOptions: Array<{ value: string; label: string }>
  videoEditModelValue: string
  onVideoEditModelChange: (value: string) => void
  videoEditModelOptions: Array<{ value: string; label: string }>
  visionModelValue: string
  onVisionModelChange: (value: string) => void
  visionModelOptions: Array<{ value: string; label: string }>
  enableVideoEdit: boolean
  onEnableVideoEditChange: (value: boolean) => void
  enableVisionReview: boolean
  onEnableVisionReviewChange: (value: boolean) => void
  enableSafetyAudit: boolean
  onEnableSafetyAuditChange: (value: boolean) => void
  safetyFailPolicyValue: string
  onSafetyFailPolicyChange: (value: string) => void
  safetyFailPolicyOptions: Array<{ value: string; label: string }>
  disabled?: boolean
}

export function DreamweaverConfigDialogModelFieldGrid({
  imageModelValue,
  onImageModelChange,
  imageModelOptions,
  videoModelValue,
  onVideoModelChange,
  videoModelOptions,
  videoEditModelValue,
  onVideoEditModelChange,
  videoEditModelOptions,
  visionModelValue,
  onVisionModelChange,
  visionModelOptions,
  enableVideoEdit,
  onEnableVideoEditChange,
  enableVisionReview,
  onEnableVisionReviewChange,
  enableSafetyAudit,
  onEnableSafetyAuditChange,
  safetyFailPolicyValue,
  onSafetyFailPolicyChange,
  safetyFailPolicyOptions,
  disabled = false,
}: DreamweaverConfigDialogModelFieldGridProps) {
  const { t } = useTranslation()
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="image-model-label"
          label={t('dreamweaverRun.configImageGenModelLabel')}
          value={imageModelValue}
          onChange={onImageModelChange}
          disabled={disabled}
          options={imageModelOptions}
        />
      </Grid>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="video-model-label"
          label={t('dreamweaverRun.configVideoGenModelLabel')}
          value={videoModelValue}
          onChange={onVideoModelChange}
          disabled={disabled}
          options={videoModelOptions}
        />
      </Grid>
      {/* 合规修订：第三方生成引擎服务方提示（生成内容/提示词/素材由所选服务商处理） */}
      <Grid item xs={12}>
        <Typography variant="caption" color="text.secondary" display="block" sx={{ lineHeight: 1.8 }}>
          {t('dreamweaverRun.configModelProviderHint')}
        </Typography>
      </Grid>
      <Grid item xs={12}>
        <DreamweaverConfigDialogStrategyToggleField
          title={t('dreamweaverRun.configVideoEditTitle')}
          checked={enableVideoEdit}
          onChange={onEnableVideoEditChange}
          enabledLabel={t('dreamweaverRun.configSwitchEnabled')}
          disabledLabel={t('dreamweaverRun.configSwitchDisabled')}
          description={t('dreamweaverRun.configVideoEditDesc')}
        />
      </Grid>
      {enableVideoEdit && (
        <Grid item xs={12} sm={6}>
          <DreamweaverConfigDialogSelectField
            labelId="video-edit-model-label"
            label={t('dreamweaverRun.configVideoEditModel')}
            value={videoEditModelValue}
            onChange={onVideoEditModelChange}
            disabled={disabled}
            options={videoEditModelOptions}
          />
        </Grid>
      )}
      <Grid item xs={12}>
        <DreamweaverConfigDialogStrategyToggleField
          title={t('dreamweaverRun.configVisionReviewTitle')}
          checked={enableVisionReview}
          onChange={onEnableVisionReviewChange}
          enabledLabel={t('dreamweaverRun.configSwitchEnabled')}
          disabledLabel={t('dreamweaverRun.configSwitchDisabled')}
          description={t('dreamweaverRun.configVisionReviewDesc')}
        />
      </Grid>
      <Grid item xs={12}>
        <DreamweaverConfigDialogStrategyToggleField
          title={t('dreamweaverRun.configSafetyAuditTitle')}
          checked={enableSafetyAudit}
          onChange={onEnableSafetyAuditChange}
          enabledLabel={t('dreamweaverRun.configSwitchEnabled')}
          disabledLabel={t('dreamweaverRun.configSwitchDisabled')}
          description={t('dreamweaverRun.configSafetyAuditDesc')}
        />
      </Grid>
      {(enableVisionReview || enableSafetyAudit) && (
        <Grid item xs={12} sm={6}>
          <DreamweaverConfigDialogSelectField
            labelId="vision-model-label"
            label={enableVisionReview && enableSafetyAudit ? t('dreamweaverRun.configVisionModeVision') : enableSafetyAudit ? t('dreamweaverRun.configVisionModeSafety') : t('dreamweaverRun.configVisionModel')}
            value={visionModelValue}
            onChange={onVisionModelChange}
            disabled={disabled}
            options={visionModelOptions}
          />
        </Grid>
      )}
      {enableSafetyAudit && (
        <Grid item xs={12} sm={6}>
          <DreamweaverConfigDialogSelectField
            labelId="safety-fail-policy-label"
            label={t('dreamweaverRun.configSafetyFailPolicy')}
            value={safetyFailPolicyValue}
            onChange={onSafetyFailPolicyChange}
            disabled={disabled}
            options={safetyFailPolicyOptions}
          />
        </Grid>
      )}
    </Grid>
  )
}

type DreamweaverConfigDialogMainGridProps = {
  chapterSelection: ReactNode
  sidePanel: ReactNode
}

export function DreamweaverConfigDialogMainGrid({
  chapterSelection,
  sidePanel,
}: DreamweaverConfigDialogMainGridProps) {
  return (
    <Grid container spacing={2}>
      <Grid item xs={12} md={7}>
        {chapterSelection}
      </Grid>

      <Grid item xs={12} md={5}>
        <Stack spacing={2}>{sidePanel}</Stack>
      </Grid>
    </Grid>
  )
}

type DreamweaverConfigDialogContentProps = {
  errorNotice?: ReactNode
  projectSection: ReactNode
  mainGrid: ReactNode
}

export function DreamweaverConfigDialogContent({
  errorNotice,
  projectSection,
  mainGrid,
}: DreamweaverConfigDialogContentProps) {
  return (
    <DialogContent dividers sx={{ pt: 2 }}>
      {errorNotice ?? null}
      <Stack spacing={2}>
        {projectSection}
        {mainGrid}
      </Stack>
    </DialogContent>
  )
}

type DreamweaverConfigDialogActionsProps = {
  onClose: () => void
  onRun: () => void
  runDisabled: boolean
}

export function DreamweaverConfigDialogActions({
  onClose,
  onRun,
  runDisabled,
}: DreamweaverConfigDialogActionsProps) {
  const { t } = useTranslation()
  return (
    <DialogActions>
      <Button onClick={onClose}>{t('common.close')}</Button>
      <Button variant="contained" onClick={onRun} disabled={runDisabled}>
        {t('dreamweaverRun.configStartGenerating')}
      </Button>
    </DialogActions>
  )
}

type DreamweaverConfigDialogShellProps = {
  open: boolean
  onClose: () => void
  fullScreen: boolean
  title: ReactNode
  content: ReactNode
  actions: ReactNode
}

export function DreamweaverConfigDialogShell({
  open,
  onClose,
  fullScreen,
  title,
  content,
  actions,
}: DreamweaverConfigDialogShellProps) {
  return (
    <Dialog open={open} onClose={onClose} fullScreen={fullScreen} maxWidth="md" fullWidth>
      {title}
      {content}
      {actions}
    </Dialog>
  )
}

type DreamweaverConfigDialogProps = {
  open: boolean
  onClose: () => void
  fullScreen: boolean
  title: string
  subtitle: string
  errorNotice?: ReactNode
  lockedProjectId?: number | null
  projectTitle?: string | null
  onOpenProjectList: () => void
  chapterToolbar: ReactNode
  chapterList: ReactNode
  chapterHelperText: string
  chapterMaxHeight: string | number
  strategyContent: ReactNode
  strategyHelperText: string
  visualNotices?: ReactNode
  visualFields: ReactNode
  visualHelperText: string
  onRun: () => void
  runDisabled: boolean
}

export function DreamweaverConfigDialog({
  open,
  onClose,
  fullScreen,
  title,
  subtitle,
  errorNotice,
  lockedProjectId,
  projectTitle,
  onOpenProjectList,
  chapterToolbar,
  chapterList,
  chapterHelperText,
  chapterMaxHeight,
  strategyContent,
  strategyHelperText,
  visualNotices,
  visualFields,
  visualHelperText,
  onRun,
  runDisabled,
}: DreamweaverConfigDialogProps) {
  return (
    <DreamweaverConfigDialogShell
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      title={<DreamweaverConfigDialogTitle title={title} subtitle={subtitle} onClose={onClose} />}
      content={
        <DreamweaverConfigDialogContent
          errorNotice={errorNotice}
          projectSection={
            <DreamweaverConfigDialogProjectSection
              lockedProjectId={lockedProjectId}
              projectTitle={projectTitle}
              action={<DreamweaverConfigDialogProjectAlertAction onClick={onOpenProjectList} />}
            />
          }
          mainGrid={
            <DreamweaverConfigDialogMainGrid
              chapterSelection={
                <DreamweaverConfigDialogChapterSelectionCard
                  toolbarActions={chapterToolbar}
                  listContent={chapterList}
                  helperText={chapterHelperText}
                  maxHeight={chapterMaxHeight}
                />
              }
              sidePanel={
                <>
                  <DreamweaverConfigDialogStrategyCard content={strategyContent} helperText={strategyHelperText} />
                  <DreamweaverConfigDialogVisualSettingsCard
                    notices={visualNotices}
                    fields={visualFields}
                    helperText={visualHelperText}
                  />
                </>
              }
            />
          }
        />
      }
      actions={<DreamweaverConfigDialogActions onClose={onClose} onRun={onRun} runDisabled={runDisabled} />}
    />
  )
}

type DreamweaverRunConfigDialogProps = {
  open: boolean
  onClose: () => void
  fullScreen: boolean
  subtitle: string
  errorNotice?: ReactNode
  lockedProjectId?: number | null
  projectTitle?: string | null
  onOpenProjectList: () => void
  selectedChapterIds: number[]
  chapters: Array<{
    id: number
    chapter_number: number | string
    title?: string | null
    content?: string | null
  }>
  loadingChapters: boolean
  running: boolean
  onToggleAll: () => void
  onRefreshChapters: () => void
  refreshDisabled: boolean
  onToggleChapter: (chapterId: number) => void
  strategyFields: Array<{
    key: string
    title: string
    checked: boolean
    onChange: (checked: boolean) => void
    enabledLabel: string
    disabledLabel: string
    description: string
  }>
  abVariant: string
  onChangeAbVariant: (value: string) => void
  lockedGenerationConfigError?: string | null
  generationConfigLocked: boolean
  lockedGenerationConfigSourceRunId?: string | null
  stylePresetValue: string
  onStylePresetChange: (value: string) => void
  stylePresetOptions: Array<{ value: string; label: string }>
  imageRatioValue: string
  onImageRatioChange: (value: string) => void
  imageRatioOptions: Array<{ value: string; label: string }>
  imageResolutionValue: string
  onImageResolutionChange: (value: string) => void
  imageResolutionOptions: Array<{ value: string; label: string }>
  visualFieldsDisabled: boolean
  imageModelValue: string
  onImageModelChange: (value: string) => void
  imageModelOptions: Array<{ value: string; label: string }>
  videoModelValue: string
  onVideoModelChange: (value: string) => void
  videoModelOptions: Array<{ value: string; label: string }>
  videoEditModelValue: string
  onVideoEditModelChange: (value: string) => void
  videoEditModelOptions: Array<{ value: string; label: string }>
  visionModelValue: string
  onVisionModelChange: (value: string) => void
  visionModelOptions: Array<{ value: string; label: string }>
  enableVideoEdit: boolean
  onEnableVideoEditChange: (value: boolean) => void
  enableVisionReview: boolean
  onEnableVisionReviewChange: (value: boolean) => void
  enableSafetyAudit: boolean
  onEnableSafetyAuditChange: (value: boolean) => void
  safetyFailPolicyValue: string
  onSafetyFailPolicyChange: (value: string) => void
  safetyFailPolicyOptions: Array<{ value: string; label: string }>
  onRun: () => void
  runDisabled: boolean
}

export function DreamweaverRunConfigDialog({
  open,
  onClose,
  fullScreen,
  subtitle,
  errorNotice,
  lockedProjectId,
  projectTitle,
  onOpenProjectList,
  selectedChapterIds,
  chapters,
  loadingChapters,
  running,
  onToggleAll,
  onRefreshChapters,
  refreshDisabled,
  onToggleChapter,
  strategyFields,
  abVariant,
  onChangeAbVariant,
  lockedGenerationConfigError,
  generationConfigLocked,
  lockedGenerationConfigSourceRunId,
  stylePresetValue,
  onStylePresetChange,
  stylePresetOptions,
  imageRatioValue,
  onImageRatioChange,
  imageRatioOptions,
  imageResolutionValue,
  onImageResolutionChange,
  imageResolutionOptions,
  visualFieldsDisabled,
  imageModelValue,
  onImageModelChange,
  imageModelOptions,
  videoModelValue,
  onVideoModelChange,
  videoModelOptions,
  videoEditModelValue,
  onVideoEditModelChange,
  videoEditModelOptions,
  visionModelValue,
  onVisionModelChange,
  visionModelOptions,
  enableVideoEdit,
  onEnableVideoEditChange,
  enableVisionReview,
  onEnableVisionReviewChange,
  enableSafetyAudit,
  onEnableSafetyAuditChange,
  safetyFailPolicyValue,
  onSafetyFailPolicyChange,
  safetyFailPolicyOptions,
  onRun,
  runDisabled,
}: DreamweaverRunConfigDialogProps) {
  const { t } = useTranslation()
  return (
    <DreamweaverConfigDialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      title={t('dreamweaverRun.configTitle')}
      subtitle={subtitle}
      errorNotice={errorNotice}
      lockedProjectId={lockedProjectId}
      projectTitle={projectTitle}
      onOpenProjectList={onOpenProjectList}
      chapterToolbar={
        <DreamweaverConfigDialogChapterToolbar
          toggleAllLabel={t(selectedChapterIds.length === chapters.length ? 'dreamweaverRun.configClearAll' : 'dreamweaverRun.configSelectAll')}
          onToggleAll={onToggleAll}
          toggleAllDisabled={loadingChapters || !chapters.length || running}
          refreshStartIcon={<RefreshIcon fontSize="small" />}
          onRefresh={onRefreshChapters}
          refreshDisabled={refreshDisabled}
        />
      }
      chapterList={
        <DreamweaverConfigDialogChapterList loading={loadingChapters}>
          <DreamweaverConfigDialogChapterListItems
            chapters={chapters}
            selectedChapterIds={selectedChapterIds}
            disabled={running}
            onToggle={onToggleChapter}
          />
        </DreamweaverConfigDialogChapterList>
      }
      chapterHelperText={t('dreamweaverRun.configChapterHelper')}
      chapterMaxHeight={fullScreen ? '55vh' : 360}
      strategyContent={
        <DreamweaverConfigDialogStrategyFields
          fields={strategyFields}
          abVariant={abVariant}
          onChangeAbVariant={onChangeAbVariant}
          disabled={running}
        />
      }
      strategyHelperText={t('dreamweaverRun.configStrategyHelper')}
      visualNotices={
        <>
          {lockedGenerationConfigError && (
            <Alert severity="warning" sx={{ mb: 1 }}>
              {lockedGenerationConfigError}
            </Alert>
          )}
          {generationConfigLocked && (
            <Alert severity="info" sx={{ mb: 1 }}>
              {t('dreamweaverRun.configLockedLongNotice')}
              {lockedGenerationConfigSourceRunId ? t('dreamweaverRun.configLockedSource', { runId: lockedGenerationConfigSourceRunId }) : ''}
            </Alert>
          )}
        </>
      }
      visualFields={
        <>
          <DreamweaverConfigDialogVisualFieldGrid
            stylePresetValue={stylePresetValue}
            onStylePresetChange={onStylePresetChange}
            stylePresetOptions={stylePresetOptions}
            imageRatioValue={imageRatioValue}
            onImageRatioChange={onImageRatioChange}
            imageRatioOptions={imageRatioOptions}
            imageResolutionValue={imageResolutionValue}
            onImageResolutionChange={onImageResolutionChange}
            imageResolutionOptions={imageResolutionOptions}
            disabled={visualFieldsDisabled}
          />
          <Box sx={{ mt: 2 }} />
          <DreamweaverConfigDialogModelFieldGrid
            imageModelValue={imageModelValue}
            onImageModelChange={onImageModelChange}
            imageModelOptions={imageModelOptions}
            videoModelValue={videoModelValue}
            onVideoModelChange={onVideoModelChange}
            videoModelOptions={videoModelOptions}
            videoEditModelValue={videoEditModelValue}
            onVideoEditModelChange={onVideoEditModelChange}
            videoEditModelOptions={videoEditModelOptions}
            visionModelValue={visionModelValue}
            onVisionModelChange={onVisionModelChange}
            visionModelOptions={visionModelOptions}
            enableVideoEdit={enableVideoEdit}
            onEnableVideoEditChange={onEnableVideoEditChange}
            enableVisionReview={enableVisionReview}
            onEnableVisionReviewChange={onEnableVisionReviewChange}
            enableSafetyAudit={enableSafetyAudit}
            onEnableSafetyAuditChange={onEnableSafetyAuditChange}
            safetyFailPolicyValue={safetyFailPolicyValue}
            onSafetyFailPolicyChange={onSafetyFailPolicyChange}
            safetyFailPolicyOptions={safetyFailPolicyOptions}
            disabled={visualFieldsDisabled}
          />
        </>
      }
      visualHelperText={t('dreamweaverRun.configVisualHelper')}
      onRun={onRun}
      runDisabled={runDisabled}
    />
  )
}
