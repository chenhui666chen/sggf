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
        <IconButton onClick={onClose} size="small" aria-label="关闭">
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
  if (lockedProjectId) {
    return (
      <Box
        sx={{
          p: 1.5,
          borderRadius: 2,
          border: '1px solid rgba(0,0,0,0.08)',
          bgcolor: 'rgba(0,0,0,0.04)',
        }}
      >
        <Typography variant="caption" color="text.secondary" display="block">
          当前项目
        </Typography>
        <Typography variant="subtitle1" sx={{ fontWeight: 800 }}>
          {projectTitle || `项目 #${lockedProjectId}`}
        </Typography>
      </Box>
    )
  }

  return (
    <Alert severity="info" action={action ?? undefined}>
      请先在项目列表选择一个项目，再进入生成配置。
    </Alert>
  )
}

type DreamweaverConfigDialogProjectAlertActionProps = {
  onClick: () => void
}

export function DreamweaverConfigDialogProjectAlertAction({
  onClick,
}: DreamweaverConfigDialogProjectAlertActionProps) {
  return (
    <Button size="small" variant="outlined" onClick={onClick}>
      去项目列表
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
  return (
    <DreamweaverConfigDialogCard title="章节选择" footer={<Typography variant="caption" color="text.secondary" sx={{ mt: 1, display: 'block' }}>{helperText}</Typography>}>
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
          border: '1px solid rgba(0,0,0,0.08)',
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
  return (
    <>
      <Button size="small" onClick={onToggleAll} disabled={toggleAllDisabled}>
        {toggleAllLabel}
      </Button>
      <Button size="small" startIcon={refreshStartIcon ?? undefined} onClick={onRefresh} disabled={refreshDisabled}>
        刷新
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
  return (
    <>
      {chapters.map((chapter) => {
        const raw = String(chapter.content || '').replace(/\s+/g, ' ').trim()
        const snippet = raw ? (raw.length > 64 ? raw.slice(0, 64) + '…' : raw) : '（无正文）'

        return (
          <DreamweaverConfigDialogChapterItem
            key={chapter.id}
            chapterId={chapter.id}
            title={`${chapter.chapter_number}. ${chapter.title || '未命名章节'}`}
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
  return (
    <DreamweaverConfigDialogCard
      title="生成策略"
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
  return (
    <Stack spacing={0.5}>
      <Typography variant="body2" sx={{ fontWeight: 700 }}>
        实验标签（可选）
      </Typography>
      <TextField
        size="small"
        fullWidth
        value={value}
        onChange={(e) => onChange(e.target.value)}
        disabled={disabled}
        placeholder="例如 A / B / control / treatment"
        inputProps={{ maxLength: 32 }}
      />
      <Typography variant="caption" color="text.secondary">
        仅用于标记并对比不同策略效果，不会自动改变生成逻辑。
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
  return (
    <FormControl fullWidth size="small" disabled={disabled}>
      <InputLabel id={labelId}>{label}</InputLabel>
      <Select labelId={labelId} value={value} label={label} onChange={(e) => onChange(String(e.target.value))}>
        {options.map((option) => (
          <MenuItem key={option.value} value={option.value}>
            {option.label}
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
  return (
    <DreamweaverConfigDialogCard
      title="画面设置"
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
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={12}>
        <DreamweaverConfigDialogSelectField
          labelId="style-preset-label"
          label="风格预设"
          value={stylePresetValue}
          onChange={onStylePresetChange}
          disabled={disabled}
          options={stylePresetOptions}
        />
      </Grid>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="image-ratio-label"
          label="画面比例"
          value={imageRatioValue}
          onChange={onImageRatioChange}
          disabled={disabled}
          options={imageRatioOptions}
        />
      </Grid>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="image-resolution-label"
          label="分辨率"
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
  disabled = false,
}: DreamweaverConfigDialogModelFieldGridProps) {
  return (
    <Grid container spacing={1.5}>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="image-model-label"
          label="图像生成模型"
          value={imageModelValue}
          onChange={onImageModelChange}
          disabled={disabled}
          options={imageModelOptions}
        />
      </Grid>
      <Grid item xs={12} sm={6}>
        <DreamweaverConfigDialogSelectField
          labelId="video-model-label"
          label="视频生成模型"
          value={videoModelValue}
          onChange={onVideoModelChange}
          disabled={disabled}
          options={videoModelOptions}
        />
      </Grid>
      <Grid item xs={12}>
        <DreamweaverConfigDialogStrategyToggleField
          title="视频编辑功能"
          checked={enableVideoEdit}
          onChange={onEnableVideoEditChange}
          enabledLabel="已启用"
          disabledLabel="未启用"
          description="启用后可使用视频编辑模型进行分镜精剪、风格迁移和多片段融合。"
        />
      </Grid>
      {enableVideoEdit && (
        <Grid item xs={12} sm={6}>
          <DreamweaverConfigDialogSelectField
            labelId="video-edit-model-label"
            label="视频编辑模型"
            value={videoEditModelValue}
            onChange={onVideoEditModelChange}
            disabled={disabled}
            options={videoEditModelOptions}
          />
        </Grid>
      )}
      <Grid item xs={12}>
        <DreamweaverConfigDialogStrategyToggleField
          title="视觉理解审查"
          checked={enableVisionReview}
          onChange={onEnableVisionReviewChange}
          enabledLabel="已启用"
          disabledLabel="未启用"
          description="启用后在生成过程中自动使用视觉模型评估图像/视频质量，并给出改进建议。"
        />
      </Grid>
      {enableVisionReview && (
        <Grid item xs={12} sm={6}>
          <DreamweaverConfigDialogSelectField
            labelId="vision-model-label"
            label="视觉理解模型"
            value={visionModelValue}
            onChange={onVisionModelChange}
            disabled={disabled}
            options={visionModelOptions}
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
  return (
    <DialogActions>
      <Button onClick={onClose}>关闭</Button>
      <Button variant="contained" onClick={onRun} disabled={runDisabled}>
        开始生成
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
  onRun,
  runDisabled,
}: DreamweaverRunConfigDialogProps) {
  return (
    <DreamweaverConfigDialog
      open={open}
      onClose={onClose}
      fullScreen={fullScreen}
      title="生成配置"
      subtitle={subtitle}
      errorNotice={errorNotice}
      lockedProjectId={lockedProjectId}
      projectTitle={projectTitle}
      onOpenProjectList={onOpenProjectList}
      chapterToolbar={
        <DreamweaverConfigDialogChapterToolbar
          toggleAllLabel={selectedChapterIds.length === chapters.length ? '清空' : '全选'}
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
      chapterHelperText="至少选择 1 个章节；默认全选可直接开始生成。"
      chapterMaxHeight={fullScreen ? '55vh' : 360}
      strategyContent={
        <DreamweaverConfigDialogStrategyFields
          fields={strategyFields}
          abVariant={abVariant}
          onChangeAbVariant={onChangeAbVariant}
          disabled={running}
        />
      }
      strategyHelperText="性能提示：关键帧镜头级并发由后端环境变量 `DREAMWEAVER_KEYFRAMES_PARALLELISM` 控制，建议先从 `2` 开始，避免把上游 QPS 打满。"
      visualNotices={
        <>
          {lockedGenerationConfigError && (
            <Alert severity="warning" sx={{ mb: 1 }}>
              {lockedGenerationConfigError}
            </Alert>
          )}
          {generationConfigLocked && (
            <Alert severity="info" sx={{ mb: 1 }}>
              当前项目的风格/比例/分辨率已锁定，生成过程中不允许切换；如需变更请新建项目或先清理该项目的 DreamWeaver runs。
              {lockedGenerationConfigSourceRunId ? `（锁定来源：${lockedGenerationConfigSourceRunId}）` : ''}
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
            disabled={visualFieldsDisabled}
          />
        </>
      }
      visualHelperText="比例决定横/竖屏；分辨率影响素材库、关键帧与合成视频输出尺寸。"
      onRun={onRun}
      runDisabled={runDisabled}
    />
  )
}
