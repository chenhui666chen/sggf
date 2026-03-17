import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material'

export type StoryExpansionStrategy = 'auto' | 'balanced' | 'plot_first' | 'character_first'

interface StoryExpansionDialogProps {
  open: boolean
  loading: boolean
  currentChapterCount: number
  currentCharacterCount: number
  targetChapterCount: number
  targetCharacterCount: number
  strategy: StoryExpansionStrategy
  onClose: () => void
  onTargetChapterCountChange: (count: number) => void
  onTargetCharacterCountChange: (count: number) => void
  onStrategyChange: (strategy: StoryExpansionStrategy) => void
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

export default function StoryExpansionDialog({
  open,
  loading,
  currentChapterCount,
  currentCharacterCount,
  targetChapterCount,
  targetCharacterCount,
  strategy,
  onClose,
  onTargetChapterCountChange,
  onTargetCharacterCountChange,
  onStrategyChange,
  onConfirm,
}: StoryExpansionDialogProps) {
  const chapterDelta = Math.max(0, targetChapterCount - currentChapterCount)
  const characterDelta = Math.max(0, targetCharacterCount - currentCharacterCount)
  const hasDelta = chapterDelta > 0 || characterDelta > 0

  return (
    <Dialog open={open} onClose={loading ? undefined : onClose} maxWidth="sm" fullWidth>
      <DialogTitle>协同拓展</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2.5}>
          <Alert severity="info">
            这次会走真正的 delta 策略：
            旧章节默认锁定，只扩写新增区间；旧人物默认保留，只新增角色、关系和章节职责。
          </Alert>

          <Box sx={{ display: 'flex', gap: 1, flexWrap: 'wrap' }}>
            <Chip label={`当前章节 ${currentChapterCount}`} color="primary" variant="outlined" />
            <Chip label={`当前人物 ${currentCharacterCount}`} color="secondary" variant="outlined" />
            <Chip label={`本轮新增章节 ${chapterDelta}`} color="success" />
            <Chip label={`本轮新增人物 ${characterDelta}`} color="warning" />
          </Box>

          <TextField
            label="目标章节数"
            type="number"
            fullWidth
            value={targetChapterCount || ''}
            onChange={(e) => onTargetChapterCountChange(parseInt(e.target.value, 10) || 0)}
            inputProps={{ min: Math.max(1, currentChapterCount), max: currentChapterCount + 30 }}
            helperText={`建议单轮新增 6-12 章，当前最多支持新增 30 章。`}
          />

          <TextField
            label="目标人物数"
            type="number"
            fullWidth
            value={targetCharacterCount || ''}
            onChange={(e) => onTargetCharacterCountChange(parseInt(e.target.value, 10) || 0)}
            inputProps={{ min: Math.max(1, currentCharacterCount), max: currentCharacterCount + 10 }}
            helperText={`建议单轮新增 2-4 人，当前最多支持新增 10 人。`}
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
