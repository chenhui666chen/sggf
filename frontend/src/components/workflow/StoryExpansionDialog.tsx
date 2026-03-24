import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  TextField,
  Typography,
} from '@mui/material'

export type StoryExpansionStrategy = 'auto' | 'balanced' | 'plot_first' | 'character_first'
export type StoryExpansionIntent = 'auto' | 'outline_led' | 'character_led' | 'balanced'
export type StoryExpansionMode = 'total' | 'epic_framework' | 'volume_detail'
export type StoryPreserveWrittenMode = 'extract_extend' | 'preserve_written' | 'regenerate_all'

export interface StoryExpansionAnalysis {
  execution_mode?: string
  execution_mode_reason?: string
  recommended_strategy?: StoryExpansionStrategy | string
  effective_strategy?: StoryExpansionStrategy | string
  recommended_intent?: StoryExpansionIntent | string
  effective_intent?: StoryExpansionIntent | string
  intent_reason?: string
  effective_target_chapter_count?: number | null
  effective_target_character_count?: number | null
  requested_target_chapter_count?: number | null
  requested_target_character_count?: number | null
  requested_expansion_mode?: StoryExpansionMode | string
  effective_expansion_mode?: StoryExpansionMode | string
  estimated_rounds?: number
  auto_supplement_applied?: boolean
  analysis_summary?: string
  warnings?: string[]
  epic_config?: {
    total_volumes?: number | null
    chapter_range?: number[] | null
  }
  written_chapter_context?: {
    applied?: boolean
    written_chapter_count?: number
    preserve_written_mode?: StoryPreserveWrittenMode | string
  }
  volume_detail?: {
    target_volume_index?: number | null
    chapter_range?: number[] | null
    existing_detail?: boolean
  }
  validation?: {
    score?: number
    coverage_ratio?: number
    unreferenced_characters?: string[]
  }
  auto_supplement?: {
    chapter_delta?: number
    character_delta?: number
    reasons?: string[]
  }
  model_plan?: {
    coordinator_planner_model?: string
    coordinator_writer_model?: string
    outline_expansion_model?: string
    character_expansion_model?: string
    estimated_rounds?: number
    notes?: string[]
  }
  mode_suitability?: {
    mode?: string
    request_band?: string
    request_band_label?: string
    request_band_reason?: string
    current_total_chapters?: number
    target_total_chapters?: number
    chapters_needed?: number
    execution_mode?: string
    recommended_total_chapters_max?: number
    caution_total_chapters_min?: number
    caution_total_chapters_max?: number
    framework_preferred_total_from?: number
    epic_auto_switch_total_from?: number
    preferred_iterative_step?: number
    single_round_delta_limit?: number
    summary?: string
    bands?: Array<{
      key?: string
      label?: string
      range_text?: string
      detail?: string
    }>
  }
}

interface StoryExpansionDialogProps {
  open: boolean
  loading: boolean
  analysisLoading: boolean
  currentChapterCount: number
  currentCharacterCount: number
  targetChapterCount: number
  targetCharacterCount: number
  expansionMode: StoryExpansionMode
  totalVolumes: number
  totalChaptersMin: number
  totalChaptersMax: number
  frameworkMetadata?: {
    has_framework?: boolean
    metadata?: {
      total_volumes?: number
      expanded_volumes?: number[]
    }
  } | null
  targetVolumeIndex: number
  volumeChaptersMin: number
  volumeChaptersMax: number
  strategy: StoryExpansionStrategy
  intent: StoryExpansionIntent
  autoSupplementEnabled: boolean
  preserveWrittenMode: StoryPreserveWrittenMode
  analysis: StoryExpansionAnalysis | null
  onClose: () => void
  onTargetChapterCountChange: (count: number) => void
  onTargetCharacterCountChange: (count: number) => void
  onExpansionModeChange: (mode: StoryExpansionMode) => void
  onTotalVolumesChange: (volumes: number) => void
  onTotalChaptersMinChange: (count: number) => void
  onTotalChaptersMaxChange: (count: number) => void
  onTargetVolumeIndexChange: (index: number) => void
  onVolumeChaptersMinChange: (count: number) => void
  onVolumeChaptersMaxChange: (count: number) => void
  onStrategyChange: (strategy: StoryExpansionStrategy) => void
  onIntentChange: (intent: StoryExpansionIntent) => void
  onAutoSupplementChange: (enabled: boolean) => void
  onPreserveWrittenModeChange: (mode: StoryPreserveWrittenMode) => void
  onConfirm: () => void
}

const STRATEGY_OPTIONS: Array<{
  value: StoryExpansionStrategy
  label: string
  description: string
}> = [
  { value: 'auto', label: '自动协同', description: '由系统根据缺口自动决定先补剧情还是先补人物。' },
  { value: 'balanced', label: '平衡推进', description: '章节与人物同步补强，适合常规扩写。' },
  { value: 'plot_first', label: '剧情优先', description: '优先补章节结构，再按缺口补角色与关系。' },
  { value: 'character_first', label: '人物优先', description: '先补功能角色和关系，再生成新增章节。' },
]

const INTENT_OPTIONS: Array<{
  value: StoryExpansionIntent
  label: string
  description: string
}> = [
  { value: 'auto', label: '自动判断', description: '系统根据缺口和匹配度推荐本轮主导方向。' },
  { value: 'outline_led', label: '大纲主导', description: '以章节扩展为主，必要时自动补少量配套人物。' },
  { value: 'character_led', label: '人物主导', description: '以人物扩展为主，必要时自动补少量承接情节。' },
  { value: 'balanced', label: '平衡协同', description: '人物与大纲一起推进，适合常规补强。' },
]

const INTENT_LABELS: Record<string, string> = {
  auto: '自动判断',
  outline_led: '大纲主导',
  character_led: '人物主导',
  balanced: '平衡协同',
}

const MODE_LABELS: Record<string, string> = {
  delta: '单轮增量',
  iterative: '分轮协同',
  epic: '长篇框架',
  volume_detail: '单卷细化',
}

function getSuitabilityChipColor(band?: string): 'success' | 'warning' | 'info' | 'error' | 'default' {
  if (band === 'recommended') {
    return 'success'
  }
  if (band === 'caution') {
    return 'warning'
  }
  if (band === 'framework_preferred') {
    return 'info'
  }
  if (band === 'epic') {
    return 'error'
  }
  return 'default'
}

const EXPANSION_MODE_OPTIONS: Array<{
  value: StoryExpansionMode
  label: string
  description: string
}> = [
  { value: 'total', label: '常规协同', description: '按目标章节数和人物数扩展，系统自动切单轮或分轮。' },
  { value: 'epic_framework', label: '长篇框架协同', description: '优先生成总卷框架，再让人物体系与长篇结构对齐。' },
  { value: 'volume_detail', label: '单卷细化协同', description: '基于已有史诗框架细化某一卷，并同步补齐该卷相关人物。' },
]

const PRESERVE_WRITTEN_MODE_OPTIONS: Array<{
  value: StoryPreserveWrittenMode
  label: string
  description: string
}> = [
  { value: 'extract_extend', label: '提取后扩展', description: '先从已写正文提取细纲，再基于提取结果协同扩展，质量最佳。' },
  { value: 'preserve_written', label: '仅保护正文', description: '按已写章节摘要保护正文，不额外做细纲提取，速度更快。' },
  { value: 'regenerate_all', label: '忽略已写正文', description: '不参考数据库中的已写章节，适合准备整体重构。' },
]

export default function StoryExpansionDialog({
  open,
  loading,
  analysisLoading,
  currentChapterCount,
  currentCharacterCount,
  targetChapterCount,
  targetCharacterCount,
  expansionMode,
  totalVolumes,
  totalChaptersMin,
  totalChaptersMax,
  frameworkMetadata,
  targetVolumeIndex,
  volumeChaptersMin,
  volumeChaptersMax,
  strategy,
  intent,
  autoSupplementEnabled,
  preserveWrittenMode,
  analysis,
  onClose,
  onTargetChapterCountChange,
  onTargetCharacterCountChange,
  onExpansionModeChange,
  onTotalVolumesChange,
  onTotalChaptersMinChange,
  onTotalChaptersMaxChange,
  onTargetVolumeIndexChange,
  onVolumeChaptersMinChange,
  onVolumeChaptersMaxChange,
  onStrategyChange,
  onIntentChange,
  onAutoSupplementChange,
  onPreserveWrittenModeChange,
  onConfirm,
}: StoryExpansionDialogProps) {
  const effectiveTargetChapterCount = expansionMode === 'epic_framework'
    ? totalChaptersMax
    : (expansionMode === 'volume_detail' ? volumeChaptersMax : targetChapterCount)
  const chapterDelta = Math.max(0, effectiveTargetChapterCount - currentChapterCount)
  const characterDelta = Math.max(0, targetCharacterCount - currentCharacterCount)
  const hasFramework = !!frameworkMetadata?.has_framework
  const willResetEpicFramework = hasFramework && expansionMode === 'total' && chapterDelta > 0
  const hasDelta = expansionMode === 'volume_detail'
    ? (targetVolumeIndex > 0 && hasFramework)
    : (chapterDelta > 0 || characterDelta > 0)
  const analysisWarnings = analysis?.warnings || []
  const supplementChapterDelta = analysis?.auto_supplement?.chapter_delta || 0
  const supplementCharacterDelta = analysis?.auto_supplement?.character_delta || 0
  const modeSuitability = analysis?.mode_suitability

  return (
    <Dialog open={open} onClose={loading ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>协同拓展</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2.5}>
          <Alert severity="info">
            这次会走真正的 delta 策略：
            旧章节默认锁定，只扩写新增区间；旧人物默认保留，只新增角色、关系和章节职责。
          </Alert>

          {willResetEpicFramework ? (
            <Alert severity="warning">
              当前项目已存在史诗框架。若继续使用“常规协同”补章节，执行时会清空旧框架与卷细纲状态，后续以新的章节大纲为准。
            </Alert>
          ) : null}

          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Chip label={`当前章节 ${currentChapterCount}`} color="primary" variant="outlined" />
            <Chip label={`当前人物 ${currentCharacterCount}`} color="secondary" variant="outlined" />
            <Chip label={`本轮新增章节 ${chapterDelta}`} color="success" />
            <Chip label={`本轮新增人物 ${characterDelta}`} color="warning" />
          </Box>

          <TextField
            select
            label="扩展模式"
            fullWidth
            value={expansionMode}
            onChange={(e) => onExpansionModeChange(e.target.value as StoryExpansionMode)}
            helperText={EXPANSION_MODE_OPTIONS.find((item) => item.value === expansionMode)?.description || ''}
          >
            {EXPANSION_MODE_OPTIONS.map((item) => (
              <MenuItem key={item.value} value={item.value}>
                {item.label}
              </MenuItem>
            ))}
          </TextField>

          <TextField
            select
            label="已写章节处理"
            fullWidth
            value={preserveWrittenMode}
            onChange={(e) => onPreserveWrittenModeChange(e.target.value as StoryPreserveWrittenMode)}
            disabled={expansionMode === 'volume_detail'}
            helperText={
              expansionMode === 'volume_detail'
                ? '单卷细化当前主要基于卷框架和目标卷细纲协同，此设置暂不生效。'
                : (PRESERVE_WRITTEN_MODE_OPTIONS.find((item) => item.value === preserveWrittenMode)?.description || '')
            }
          >
            {PRESERVE_WRITTEN_MODE_OPTIONS.map((item) => (
              <MenuItem key={item.value} value={item.value}>
                {item.label}
              </MenuItem>
            ))}
          </TextField>

          {expansionMode === 'epic_framework' ? (
            <Stack spacing={1.5}>
              <Alert severity="info">
                长篇框架协同会优先走长上下文模型，先规划总卷框架，再让人物体系与长线主冲突对齐。
              </Alert>
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <TextField
                  label="总卷数"
                  type="number"
                  value={totalVolumes || ''}
                  onChange={(e) => onTotalVolumesChange(parseInt(e.target.value, 10) || 0)}
                  inputProps={{ min: 5, max: 50 }}
                  helperText="建议 5-50 卷"
                  sx={{ flex: '1 1 160px' }}
                />
                <TextField
                  label="总章范围最小值"
                  type="number"
                  value={totalChaptersMin || ''}
                  onChange={(e) => onTotalChaptersMinChange(parseInt(e.target.value, 10) || 0)}
                  inputProps={{ min: 400, max: 5000 }}
                  helperText="建议 400-5000 章"
                  sx={{ flex: '1 1 180px' }}
                />
                <TextField
                  label="总章范围最大值"
                  type="number"
                  value={totalChaptersMax || ''}
                  onChange={(e) => onTotalChaptersMaxChange(parseInt(e.target.value, 10) || 0)}
                  inputProps={{ min: 400, max: 5000 }}
                  helperText="会作为框架规模上限"
                  sx={{ flex: '1 1 180px' }}
                />
              </Box>
            </Stack>
          ) : expansionMode === 'volume_detail' ? (
            <Stack spacing={1.5}>
              {hasFramework ? (
                <Alert severity="info">
                  已检测到史诗框架，可直接细化单卷。当前框架共 {frameworkMetadata?.metadata?.total_volumes || '未识别'} 卷，
                  已展开卷：{frameworkMetadata?.metadata?.expanded_volumes?.length ? frameworkMetadata.metadata.expanded_volumes.join('、') : '暂无'}。
                </Alert>
              ) : (
                <Alert severity="warning">
                  单卷细化协同需要先存在史诗框架。若当前项目还没有框架，请先使用“长篇框架协同”生成总卷框架。
                </Alert>
              )}
              <Box sx={{ display: 'flex', gap: 2, flexWrap: 'wrap' }}>
                <TextField
                  label="目标卷编号"
                  type="number"
                  value={targetVolumeIndex || ''}
                  onChange={(e) => onTargetVolumeIndexChange(parseInt(e.target.value, 10) || 0)}
                  inputProps={{ min: 1, max: Math.max(1, frameworkMetadata?.metadata?.total_volumes || 50) }}
                  helperText={`范围 1-${frameworkMetadata?.metadata?.total_volumes || 50}`}
                  sx={{ flex: '1 1 160px' }}
                />
                <TextField
                  label="本卷最少章节"
                  type="number"
                  value={volumeChaptersMin || ''}
                  onChange={(e) => onVolumeChaptersMinChange(parseInt(e.target.value, 10) || 0)}
                  inputProps={{ min: 30, max: 80 }}
                  helperText="建议 30-80 章"
                  sx={{ flex: '1 1 180px' }}
                />
                <TextField
                  label="本卷最多章节"
                  type="number"
                  value={volumeChaptersMax || ''}
                  onChange={(e) => onVolumeChaptersMaxChange(parseInt(e.target.value, 10) || 0)}
                  inputProps={{ min: 30, max: 80 }}
                  helperText="用于控制单卷输出规模"
                  sx={{ flex: '1 1 180px' }}
                />
              </Box>
            </Stack>
          ) : (
            <TextField
              label="目标章节数"
              type="number"
              fullWidth
              value={targetChapterCount || ''}
              onChange={(e) => onTargetChapterCountChange(parseInt(e.target.value, 10) || 0)}
              inputProps={{ min: Math.max(1, currentChapterCount), max: Math.max(5000, currentChapterCount) }}
              helperText="小规模请求通常 1 轮完成；较大规模会自动切换为分轮协同或长篇框架模式。"
            />
          )}

          <TextField
            label="目标人物数"
            type="number"
            fullWidth
            value={targetCharacterCount || ''}
            onChange={(e) => onTargetCharacterCountChange(parseInt(e.target.value, 10) || 0)}
            inputProps={{ min: Math.max(1, currentCharacterCount), max: Math.max(200, currentCharacterCount) }}
            helperText="少量角色会直接补齐；较大规模角色扩展会自动改走多轮协同。"
          />

          <TextField
            select
            label="执行意图"
            fullWidth
            value={intent}
            onChange={(e) => onIntentChange(e.target.value as StoryExpansionIntent)}
            helperText={INTENT_OPTIONS.find((item) => item.value === intent)?.description || ''}
          >
            {INTENT_OPTIONS.map((item) => (
              <MenuItem key={item.value} value={item.value}>
                {item.label}
              </MenuItem>
            ))}
          </TextField>

          <FormControlLabel
            control={
              <Switch
                checked={autoSupplementEnabled}
                onChange={(_, checked) => onAutoSupplementChange(checked)}
              />
            }
            label="允许系统自动补足配套人物或承接章节"
          />

          <TextField
            select
            label="协同策略"
            fullWidth
            value={strategy}
            onChange={(e) => onStrategyChange(e.target.value as StoryExpansionStrategy)}
            helperText={STRATEGY_OPTIONS.find((item) => item.value === strategy)?.description || ''}
          >
            {STRATEGY_OPTIONS.map((item) => (
              <MenuItem key={item.value} value={item.value}>
                {item.label}
              </MenuItem>
            ))}
          </TextField>

          <Divider />

          <Box>
            <Typography variant="subtitle2" sx={{ fontWeight: 700, mb: 1 }}>
              系统预检
            </Typography>
            {analysisLoading ? (
              <Typography variant="body2" color="text.secondary">
                正在分析最佳执行方向与模型适配...
              </Typography>
            ) : analysis ? (
              <Stack spacing={1.5}>
                <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                  <Chip
                    label={`推荐意图 ${INTENT_LABELS[analysis.recommended_intent || ''] || (analysis.recommended_intent || '未提供')}`}
                    color="primary"
                    variant="outlined"
                  />
                  <Chip
                    label={`执行模式 ${MODE_LABELS[analysis.execution_mode || ''] || (analysis.execution_mode || '未提供')}`}
                    color="secondary"
                    variant="outlined"
                  />
                  <Chip
                    label={`扩展形态 ${analysis.effective_expansion_mode === 'epic_framework' ? '长篇框架协同' : '常规协同'}`}
                    color="info"
                    variant="outlined"
                  />
                  <Chip
                    label={`预计轮次 ${analysis.estimated_rounds || analysis.model_plan?.estimated_rounds || 1}`}
                    color="default"
                    variant="outlined"
                  />
                  <Chip
                    label={`协同评分 ${analysis.validation?.score ?? 0}`}
                    color="warning"
                    variant="outlined"
                  />
                </Box>

                {analysis.analysis_summary && (
                  <Typography variant="body2">
                    {analysis.analysis_summary}
                  </Typography>
                )}

                {modeSuitability?.mode === 'total' && (
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
                        <Chip
                          label={`适用结论 ${modeSuitability.request_band_label || '未评估'}`}
                          color={getSuitabilityChipColor(modeSuitability.request_band)}
                          variant="outlined"
                        />
                        {!!modeSuitability.preferred_iterative_step && (
                          <Chip
                            label={`建议步长 ${modeSuitability.preferred_iterative_step} 章`}
                            color="default"
                            variant="outlined"
                          />
                        )}
                        {!!modeSuitability.single_round_delta_limit && (
                          <Chip
                            label={`单轮上限 ${modeSuitability.single_round_delta_limit} 章`}
                            color="default"
                            variant="outlined"
                          />
                        )}
                      </Box>

                      {modeSuitability.summary && (
                        <Typography variant="body2">
                          {modeSuitability.summary}
                        </Typography>
                      )}

                      {modeSuitability.request_band_reason && (
                        <Typography variant="body2" color="text.secondary">
                          {modeSuitability.request_band_reason}
                        </Typography>
                      )}

                      {!!modeSuitability.bands?.length && (
                        <Stack spacing={0.8}>
                          {modeSuitability.bands.map((item, index) => (
                            <Box
                              key={`${item.key || item.label || 'band'}-${index}`}
                              sx={{
                                p: 1,
                                borderRadius: 1.5,
                                bgcolor: '#fff',
                                border: '1px solid',
                                borderColor: 'divider',
                              }}
                            >
                              <Typography variant="body2" sx={{ fontWeight: 600 }}>
                                {item.label || '区间'}
                                {item.range_text ? `：${item.range_text}` : ''}
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
                )}

                {analysis.intent_reason && (
                  <Typography variant="body2" color="text.secondary">
                    {analysis.intent_reason}
                  </Typography>
                )}

                {!!analysis.execution_mode_reason && (
                  <Typography variant="body2" color="text.secondary">
                    {analysis.execution_mode_reason}
                  </Typography>
                )}

                {analysis.written_chapter_context?.applied && (
                  <Typography variant="body2" color="text.secondary">
                    已检测到 {analysis.written_chapter_context.written_chapter_count || 0} 章正文，
                    当前按“{PRESERVE_WRITTEN_MODE_OPTIONS.find((item) => item.value === analysis.written_chapter_context?.preserve_written_mode)?.label || analysis.written_chapter_context?.preserve_written_mode || '未知模式'}”参与协同。
                  </Typography>
                )}

                {autoSupplementEnabled && (supplementChapterDelta > 0 || supplementCharacterDelta > 0) && (
                  <Alert severity="info">
                    {supplementChapterDelta > 0 && `建议额外补足 ${supplementChapterDelta} 章承接情节。 `}
                    {supplementCharacterDelta > 0 && `建议额外补足 ${supplementCharacterDelta} 个配套人物。`}
                  </Alert>
                )}

                {!!analysis.epic_config?.chapter_range?.length && (
                  <Typography variant="body2" color="text.secondary">
                    长篇框架规模：{analysis.epic_config.total_volumes || '未定'} 卷 /
                    {analysis.epic_config.chapter_range[0]}-{analysis.epic_config.chapter_range[1]} 章
                  </Typography>
                )}

                {!!analysis.volume_detail?.chapter_range?.length && (
                  <Typography variant="body2" color="text.secondary">
                    单卷细化目标：第{analysis.volume_detail.target_volume_index || '未定'}卷 /
                    第{analysis.volume_detail.chapter_range[0]}-{analysis.volume_detail.chapter_range[1]}章
                    {analysis.volume_detail.existing_detail ? '（将覆盖原有细纲）' : ''}
                  </Typography>
                )}

                {!!analysisWarnings.length && (
                  <Alert severity="warning">
                    {analysisWarnings.join(' ')}
                  </Alert>
                )}

                <Box>
                  <Typography variant="body2" sx={{ fontWeight: 600 }}>
                    模型计划
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    编排规划：{analysis.model_plan?.coordinator_planner_model || 'unknown'} / 执行写作：{analysis.model_plan?.coordinator_writer_model || 'unknown'}
                  </Typography>
                  <Typography variant="body2" color="text.secondary">
                    大纲扩展：{analysis.model_plan?.outline_expansion_model || 'unknown'} / 人物扩展：{analysis.model_plan?.character_expansion_model || 'unknown'}
                  </Typography>
                  {!!analysis.model_plan?.notes?.length && (
                    <Typography variant="body2" color="text.secondary">
                      {analysis.model_plan.notes.join(' ')}
                    </Typography>
                  )}
                </Box>
              </Stack>
            ) : (
              <Typography variant="body2" color="text.secondary">
                调整目标后将自动给出推荐方向。
              </Typography>
            )}
          </Box>

          {!hasDelta && (
            <Typography variant="body2" color="error.main">
              目标章节数或目标人物数至少要有一项大于当前值，协同拓展才会执行。
            </Typography>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={loading}>
          取消
        </Button>
        <Button onClick={onConfirm} variant="contained" disabled={!hasDelta || loading}>
          {loading ? '协同拓展中...' : '开始协同拓展'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
