import { useMemo, useRef } from 'react'
import {
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Grid,
  Paper,
  Stack,
  Typography,
} from '@mui/material'
import ContentCopyIcon from '@mui/icons-material/ContentCopy'
import FormattedContent from '../common/FormattedContent'
import {
  formatStoryExpansionDocument,
  type StoryExpansionContentKind,
} from '@/utils/storyExpansionResultFormatter'

interface StoryExpansionSummary {
  label: string
  text: string
}

interface StoryExpansionResultDialogProps {
  open: boolean
  result: any
  expansionModeLabel: string
  strategyLabel: string
  intentLabel: string
  preserveWrittenModeLabel: string
  writtenContextLabel?: string
  summary: StoryExpansionSummary | null
  onClose: () => void
  onCopied: (message: string) => void
}

interface MetricCardProps {
  label: string
  value: string
  helperText?: string
  accentColor?: string
}

interface TextSectionCardProps {
  title: string
  content: string
  emptyText?: string
  contentKind?: StoryExpansionContentKind
  minHeight?: number
  onCopy?: () => void
}

interface QuickJumpItem {
  key: string
  label: string
  targetRef: React.RefObject<HTMLDivElement | null>
}

function MetricCard({
  label,
  value,
  helperText,
  accentColor = '#0f766e',
}: MetricCardProps) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 1.75,
        height: '100%',
        borderRadius: 2,
        borderColor: 'rgba(15, 118, 110, 0.16)',
        background:
          'linear-gradient(180deg, rgba(255,255,255,0.98) 0%, rgba(248,250,252,0.98) 100%)',
      }}
    >
      <Typography variant="caption" color="text.secondary">
        {label}
      </Typography>
      <Typography
        variant="h6"
        sx={{
          mt: 0.6,
          fontWeight: 700,
          color: accentColor,
          lineHeight: 1.25,
          wordBreak: 'break-word',
        }}
      >
        {value}
      </Typography>
      {helperText ? (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
          {helperText}
        </Typography>
      ) : null}
    </Paper>
  )
}

function TextSectionCard({
  title,
  content,
  emptyText = '内容为空',
  contentKind = 'generic',
  minHeight = 220,
  onCopy,
}: TextSectionCardProps) {
  const formattedContent = useMemo(
    () => formatStoryExpansionDocument(content || '', contentKind),
    [content, contentKind],
  )

  return (
    <Paper
      elevation={0}
      sx={{
        p: 2,
        height: '100%',
        borderRadius: 2.5,
        border: '1px solid',
        borderColor: 'divider',
        backgroundColor: 'background.paper',
      }}
    >
      <Box
        sx={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          gap: 1,
          mb: 1.5,
        }}
      >
        <Typography variant="subtitle1" sx={{ fontWeight: 700 }}>
          {title}
        </Typography>
        {onCopy ? (
          <Button
            size="small"
            variant="outlined"
            startIcon={<ContentCopyIcon fontSize="small" />}
            onClick={onCopy}
            sx={{ borderRadius: 1.5, textTransform: 'none' }}
          >
            复制
          </Button>
        ) : null}
      </Box>

      <Box
        sx={{
          maxHeight: minHeight,
          minHeight: Math.min(minHeight, 180),
          overflow: 'auto',
          p: 2,
          borderRadius: 2,
          border: '1px solid',
          borderColor: 'divider',
          bgcolor: '#fbfcfe',
        }}
      >
        {formattedContent ? (
          <FormattedContent
            content={formattedContent}
            sx={{
              fontSize: '0.92rem',
              lineHeight: 1.8,
              '& p:first-of-type': {
                marginTop: 0,
              },
              '& p:last-of-type': {
                marginBottom: 0,
              },
            }}
          />
        ) : (
          <Typography variant="body2" color="text.secondary">
            {emptyText}
          </Typography>
        )}
      </Box>
    </Paper>
  )
}

function getOutlineOperationLabel(op: any): string {
  if (op?.action === 'insert_after') {
    return `插入到第 ${op.after_chapter ?? '?'} 章后`
  }
  return '追加到大纲末尾'
}

function getExecutionRoundTitle(round: any, index: number): string {
  if (typeof round?.round === 'number') {
    return `第 ${round.round} 轮协同`
  }
  if (typeof round?.stage === 'string') {
    const stageMap: Record<string, string> = {
      character_expand: '人物扩展',
      epic_framework: '长篇框架生成',
      volume_detail: '单卷细化',
    }
    return `${stageMap[round.stage] || round.stage} ${index + 1}`
  }
  return `执行轮次 ${index + 1}`
}

function formatCountDelta(before: number, after: number, target: number): string {
  const base = `${before} → ${after}`
  if (target > 0) {
    return `${base} / 目标 ${target}`
  }
  return base
}

export default function StoryExpansionResultDialog({
  open,
  result,
  expansionModeLabel,
  strategyLabel,
  intentLabel,
  preserveWrittenModeLabel,
  writtenContextLabel,
  summary,
  onClose,
  onCopied,
}: StoryExpansionResultDialogProps) {
  const chapterBefore = result?.validation_before?.chapter_count ?? 0
  const chapterAfter = result?.current_chapter_count ?? 0
  const chapterTarget = result?.target_chapter_count ?? chapterAfter
  const characterBefore = result?.validation_before?.character_count ?? 0
  const characterAfter = result?.current_character_count ?? 0
  const characterTarget = result?.target_character_count ?? characterAfter
  const scoreBefore = result?.validation_before?.score ?? 0
  const scoreAfter = result?.validation_after?.score ?? 0
  const executionModeLabel =
    result?.execution_mode === 'iterative'
      ? '分轮协同'
      : result?.execution_mode === 'delta'
        ? '增量协同'
        : result?.execution_mode || '自动协同'
  const executionRounds = Array.isArray(result?.execution_rounds) ? result.execution_rounds : []
  const outlineOps = Array.isArray(result?.outline_ops) ? result.outline_ops : []
  const newCharacters = Array.isArray(result?.new_characters) ? result.new_characters : []
  const stopReasons = Array.isArray(result?.stop_reasons)
    ? result.stop_reasons.filter((reason: string) => typeof reason === 'string' && reason.trim())
    : []
  const executionModeReason =
    typeof result?.execution_mode_reason === 'string' ? result.execution_mode_reason.trim() : ''
  const summaryRef = useRef<HTMLDivElement | null>(null)
  const changesRef = useRef<HTMLDivElement | null>(null)
  const roundsRef = useRef<HTMLDivElement | null>(null)
  const deltaRef = useRef<HTMLDivElement | null>(null)
  const outlineRef = useRef<HTMLDivElement | null>(null)
  const charactersRef = useRef<HTMLDivElement | null>(null)
  const addedChapterCount = Math.max(0, chapterAfter - chapterBefore)
  const addedCharacterCount = Math.max(0, characterAfter - characterBefore)

  const quickJumpItems = useMemo<QuickJumpItem[]>(() => {
    const items: QuickJumpItem[] = []
    if (summary) {
      items.push({ key: 'summary', label: summary.label, targetRef: summaryRef })
    }
    if (newCharacters.length > 0 || outlineOps.length > 0 || stopReasons.length > 0) {
      items.push({ key: 'changes', label: '本轮变更', targetRef: changesRef })
    }
    if (executionRounds.length > 0) {
      items.push({ key: 'rounds', label: '协同轮次', targetRef: roundsRef })
    }
    if (result?.outline_delta || result?.character_delta || result?.character_relationships) {
      items.push({ key: 'delta', label: '增量内容', targetRef: deltaRef })
    }
    if (result?.expanded_outline) {
      items.push({ key: 'outline', label: '更新后大纲', targetRef: outlineRef })
    }
    if (result?.all_characters) {
      items.push({ key: 'characters', label: '更新后人物', targetRef: charactersRef })
    }
    return items
  }, [
    executionRounds.length,
    newCharacters.length,
    outlineOps.length,
    result?.all_characters,
    result?.character_delta,
    result?.character_relationships,
    result?.expanded_outline,
    result?.outline_delta,
    stopReasons.length,
    summary,
  ])

  const handleCopy = async (text: string, message: string) => {
    if (!text?.trim()) {
      return
    }
    await navigator.clipboard.writeText(text)
    onCopied(message)
  }

  const scrollToSection = (sectionRef: React.RefObject<HTMLDivElement | null>) => {
    sectionRef.current?.scrollIntoView({
      behavior: 'smooth',
      block: 'start',
    })
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="xl" fullWidth>
      <DialogTitle sx={{ pb: 1.5 }}>协同拓展结果</DialogTitle>
      <DialogContent dividers sx={{ bgcolor: '#f8fafc' }}>
        {result ? (
          <Stack spacing={2.25}>
            <Paper
              elevation={0}
              sx={{
                p: 2.25,
                borderRadius: 3,
                border: '1px solid',
                borderColor: 'rgba(15, 118, 110, 0.18)',
                background:
                  'linear-gradient(135deg, rgba(240,253,250,0.95) 0%, rgba(248,250,252,0.98) 52%, rgba(255,255,255,0.98) 100%)',
              }}
            >
              <Stack spacing={1.5}>
                <Box
                  sx={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'flex-start',
                    gap: 2,
                    flexWrap: 'wrap',
                  }}
                >
                  <Box>
                    <Typography variant="overline" sx={{ color: '#0f766e', letterSpacing: 1.4 }}>
                      协同总览
                    </Typography>
                    <Typography variant="h5" sx={{ fontWeight: 800, mt: 0.5 }}>
                      {expansionModeLabel}
                    </Typography>
                    <Typography variant="body2" color="text.secondary" sx={{ mt: 0.75 }}>
                      {executionModeReason || '本次结果已按可扫描的摘要、增量和最终内容分区展示。'}
                    </Typography>
                  </Box>

                  <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                    <Chip label={`策略：${strategyLabel}`} color="primary" variant="outlined" />
                    <Chip label={`意图：${intentLabel}`} color="secondary" variant="outlined" />
                    <Chip label={`正文处理：${preserveWrittenModeLabel}`} variant="outlined" />
                    <Chip label={`执行方式：${executionModeLabel}`} variant="outlined" />
                  </Stack>
                </Box>

                <Grid container spacing={1.5}>
                  <Grid item xs={12} sm={6} lg={3}>
                    <MetricCard
                      label="章节变化"
                      value={formatCountDelta(chapterBefore, chapterAfter, chapterTarget)}
                      accentColor="#0f766e"
                    />
                  </Grid>
                  <Grid item xs={12} sm={6} lg={3}>
                    <MetricCard
                      label="人物变化"
                      value={formatCountDelta(characterBefore, characterAfter, characterTarget)}
                      accentColor="#15803d"
                    />
                  </Grid>
                  <Grid item xs={12} sm={6} lg={3}>
                    <MetricCard
                      label="协同评分"
                      value={`${scoreBefore} → ${scoreAfter}`}
                      helperText={scoreAfter >= scoreBefore ? '本轮评分保持或提升。' : '建议复查新增内容的一致性。'}
                      accentColor="#b45309"
                    />
                  </Grid>
                  <Grid item xs={12} sm={6} lg={3}>
                    <MetricCard
                      label="执行轮次"
                      value={`${executionRounds.length || outlineOps.length || 1} 轮`}
                      helperText={
                        writtenContextLabel
                          ? `正文处理策略：${writtenContextLabel}`
                          : '未额外覆盖正文处理策略。'
                      }
                      accentColor="#1d4ed8"
                    />
                  </Grid>
                </Grid>

                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  <Chip
                    label={`本轮新增章节 ${addedChapterCount} 章`}
                    color={addedChapterCount > 0 ? 'success' : 'default'}
                    variant="outlined"
                  />
                  <Chip
                    label={`本轮新增人物 ${addedCharacterCount} 人`}
                    color={addedCharacterCount > 0 ? 'secondary' : 'default'}
                    variant="outlined"
                  />
                  {executionRounds.length > 0 ? (
                    <Chip label={`共执行 ${executionRounds.length} 轮`} variant="outlined" />
                  ) : null}
                </Stack>
              </Stack>
            </Paper>

            {quickJumpItems.length > 1 ? (
              <Paper
                elevation={0}
                sx={{
                  p: 1.5,
                  borderRadius: 2.5,
                  border: '1px solid',
                  borderColor: 'divider',
                  backgroundColor: 'rgba(248, 250, 252, 0.92)',
                  backdropFilter: 'blur(8px)',
                  position: 'sticky',
                  top: -17,
                  zIndex: 2,
                }}
              >
                <Typography variant="caption" color="text.secondary" sx={{ display: 'block', mb: 1 }}>
                  快速定位
                </Typography>
                <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap">
                  {quickJumpItems.map((item) => (
                    <Chip
                      key={item.key}
                      label={item.label}
                      clickable
                      onClick={() => scrollToSection(item.targetRef)}
                      variant="outlined"
                      sx={{ borderRadius: 1.5 }}
                    />
                  ))}
                </Stack>
              </Paper>
            ) : null}

            {summary ? (
              <Box ref={summaryRef}>
                <Paper
                  elevation={0}
                  sx={{
                    p: 2,
                    borderRadius: 2.5,
                    border: '1px solid',
                    borderColor: 'divider',
                    backgroundColor: 'background.paper',
                  }}
                >
                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1 }}>
                    {summary.label}
                  </Typography>
                  <FormattedContent
                    content={summary.text}
                    sx={{
                      fontSize: '0.95rem',
                      lineHeight: 1.8,
                      '& p': { margin: 0 },
                    }}
                  />
                </Paper>
              </Box>
            ) : null}

            {(newCharacters.length > 0 || outlineOps.length > 0 || stopReasons.length > 0) ? (
              <Box ref={changesRef}>
                <Grid container spacing={2}>
                  {newCharacters.length > 0 ? (
                    <Grid item xs={12} md={4}>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2,
                          height: '100%',
                          borderRadius: 2.5,
                          border: '1px solid',
                          borderColor: 'divider',
                          backgroundColor: 'background.paper',
                        }}
                      >
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.25 }}>
                          本轮新增角色
                        </Typography>
                        <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
                          {newCharacters.map((name: string) => (
                            <Chip key={name} label={name} color="secondary" variant="outlined" />
                          ))}
                        </Box>
                      </Paper>
                    </Grid>
                  ) : null}

                  {stopReasons.length > 0 ? (
                    <Grid item xs={12} md={4}>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2,
                          height: '100%',
                          borderRadius: 2.5,
                          border: '1px solid',
                          borderColor: 'divider',
                          backgroundColor: 'background.paper',
                        }}
                      >
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.25 }}>
                          停止原因
                        </Typography>
                        <Stack spacing={1}>
                          {stopReasons.map((reason: string, index: number) => (
                            <Paper
                              key={`${reason}-${index}`}
                              variant="outlined"
                              sx={{ p: 1.25, borderRadius: 2, bgcolor: '#fffdf5' }}
                            >
                              <Typography variant="body2" color="text.secondary">
                                {reason}
                              </Typography>
                            </Paper>
                          ))}
                        </Stack>
                      </Paper>
                    </Grid>
                  ) : null}

                  {outlineOps.length > 0 ? (
                    <Grid item xs={12} md>
                      <Paper
                        elevation={0}
                        sx={{
                          p: 2,
                          height: '100%',
                          borderRadius: 2.5,
                          border: '1px solid',
                          borderColor: 'divider',
                          backgroundColor: 'background.paper',
                        }}
                      >
                        <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.25 }}>
                          本轮章节操作
                        </Typography>
                        <Stack spacing={1.25}>
                          {outlineOps.map((op: any, index: number) => (
                            <Paper
                              key={`${op.action || 'append'}-${index}`}
                              variant="outlined"
                              sx={{ p: 1.5, borderRadius: 2 }}
                            >
                              <Stack
                                direction="row"
                                spacing={1}
                                useFlexGap
                                flexWrap="wrap"
                                alignItems="center"
                                sx={{ mb: op?.goal ? 0.75 : 0 }}
                              >
                                <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                                  {getOutlineOperationLabel(op)}
                                </Typography>
                                <Chip
                                  size="small"
                                  label={`计划 ${op?.requested_count ?? 0} 章`}
                                  variant="outlined"
                                />
                                <Chip
                                  size="small"
                                  label={`实际 ${op?.generated_count ?? 0} 章`}
                                  color="success"
                                  variant="outlined"
                                />
                              </Stack>
                              {op?.goal ? (
                                <Typography variant="body2" color="text.secondary">
                                  {op.goal}
                                </Typography>
                              ) : null}
                              {Array.isArray(op?.generated_titles) && op.generated_titles.length > 0 ? (
                                <Box sx={{ display: 'flex', gap: 0.75, flexWrap: 'wrap', mt: 1 }}>
                                  {op.generated_titles.map((title: string) => (
                                    <Chip key={title} label={title} size="small" />
                                  ))}
                                </Box>
                              ) : null}
                            </Paper>
                          ))}
                        </Stack>
                      </Paper>
                    </Grid>
                  ) : null}
                </Grid>
              </Box>
            ) : null}

            {executionRounds.length > 0 ? (
              <Box ref={roundsRef}>
                <Paper
                  elevation={0}
                  sx={{
                    p: 2,
                    borderRadius: 2.5,
                    border: '1px solid',
                    borderColor: 'divider',
                    backgroundColor: 'background.paper',
                  }}
                >
                  <Typography variant="subtitle1" sx={{ fontWeight: 700, mb: 1.25 }}>
                    协同轮次详情
                  </Typography>
                  <Grid container spacing={1.5}>
                    {executionRounds.map((round: any, index: number) => (
                      <Grid item xs={12} md={6} xl={4} key={`${round?.round || round?.stage || 'round'}-${index}`}>
                        <Paper variant="outlined" sx={{ p: 1.5, borderRadius: 2, height: '100%' }}>
                          <Stack direction="row" spacing={1} useFlexGap flexWrap="wrap" sx={{ mb: 1 }}>
                            <Typography variant="subtitle2" sx={{ fontWeight: 700 }}>
                              {getExecutionRoundTitle(round, index)}
                            </Typography>
                            {round?.strategy ? (
                              <Chip size="small" label={`策略：${round.strategy}`} variant="outlined" />
                            ) : null}
                          </Stack>

                          <Stack spacing={0.6}>
                            <Typography variant="body2" color="text.secondary">
                              章节：{round?.before_chapter_count ?? chapterBefore} → {round?.after_chapter_count ?? chapterAfter}
                            </Typography>
                            <Typography variant="body2" color="text.secondary">
                              人物：{round?.before_character_count ?? characterBefore} → {round?.after_character_count ?? characterAfter}
                            </Typography>
                            {round?.plot?.increment_requested ? (
                              <Typography variant="body2" color="text.secondary">
                                本轮新增章节目标：{round.plot.increment_requested}
                              </Typography>
                            ) : null}
                            {round?.character?.increment_requested ? (
                              <Typography variant="body2" color="text.secondary">
                                本轮新增人物目标：{round.character.increment_requested}
                              </Typography>
                            ) : null}
                            {round?.character?.post_validation_score ? (
                              <Typography variant="body2" color="text.secondary">
                                人物匹配评分：{round.character.post_validation_score}
                              </Typography>
                            ) : null}
                          </Stack>
                        </Paper>
                      </Grid>
                    ))}
                  </Grid>
                </Paper>
              </Box>
            ) : null}

            {(result?.outline_delta || result?.character_delta || result?.character_relationships) ? (
              <Box ref={deltaRef}>
                <Grid container spacing={2}>
                  {result?.outline_delta ? (
                    <Grid item xs={12} lg={4}>
                      <TextSectionCard
                        title="章节增量"
                        content={result.outline_delta}
                        contentKind="delta"
                        minHeight={260}
                        onCopy={() => handleCopy(result.outline_delta, '已复制章节增量')}
                      />
                    </Grid>
                  ) : null}
                  {result?.character_delta ? (
                    <Grid item xs={12} lg={4}>
                      <TextSectionCard
                        title="人物增量"
                        content={result.character_delta}
                        contentKind="character"
                        minHeight={260}
                        onCopy={() => handleCopy(result.character_delta, '已复制人物增量')}
                      />
                    </Grid>
                  ) : null}
                  {result?.character_relationships ? (
                    <Grid item xs={12} lg={4}>
                      <TextSectionCard
                        title="关系补丁"
                        content={result.character_relationships}
                        contentKind="relationship"
                        minHeight={260}
                        onCopy={() => handleCopy(result.character_relationships, '已复制关系补丁')}
                      />
                    </Grid>
                  ) : null}
                </Grid>
              </Box>
            ) : null}

            <Grid container spacing={2}>
              <Grid item xs={12} lg={7}>
                <Box ref={outlineRef} sx={{ height: '100%' }}>
                  <TextSectionCard
                    title="更新后大纲"
                    content={result?.expanded_outline || ''}
                    contentKind="outline"
                    minHeight={560}
                    onCopy={() => handleCopy(result?.expanded_outline || '', '已复制更新后大纲')}
                  />
                </Box>
              </Grid>
              <Grid item xs={12} lg={5}>
                <Box ref={charactersRef} sx={{ height: '100%' }}>
                  <TextSectionCard
                    title="更新后人物"
                    content={result?.all_characters || ''}
                    contentKind="character"
                    minHeight={560}
                    onCopy={() => handleCopy(result?.all_characters || '', '已复制更新后人物')}
                  />
                </Box>
              </Grid>
            </Grid>
          </Stack>
        ) : (
          <Typography color="text.secondary">暂无协同结果</Typography>
        )}
      </DialogContent>
      <DialogActions sx={{ px: 3, py: 2 }}>
        <Button onClick={onClose} variant="contained" sx={{ borderRadius: 2 }}>
          关闭
        </Button>
      </DialogActions>
    </Dialog>
  )
}
