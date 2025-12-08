import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  Typography,
  FormControl,
  RadioGroup,
  FormControlLabel,
  Radio,
  TextField,
  Alert,
  CircularProgress,
  Divider,
} from '@mui/material'

interface ExpansionConfigDialogProps {
  open: boolean
  onClose: () => void
  expansionMode: 'total' | 'volume' | 'incremental' | 'epic_framework' | 'volume_detail'
  // 按总章数模式
  targetChapterCount: number
  // 渐进式扩展模式
  incrementalStep: number
  // 史诗框架相关
  totalVolumes: number
  totalChaptersMin: number
  totalChaptersMax: number
  autoExpandAllVolumes: boolean
  frameworkMetadata: any
  loadingFramework: boolean
  // 回调
  onExpansionModeChange: (mode: 'total' | 'volume' | 'incremental' | 'epic_framework' | 'volume_detail') => void
  onTargetChapterCountChange: (count: number) => void
  onIncrementalStepChange: (step: number) => void
  onTotalVolumesChange: (volumes: number) => void
  onTotalChaptersMinChange: (min: number) => void
  onTotalChaptersMaxChange: (max: number) => void
  onAutoExpandAllVolumesChange: (auto: boolean) => void
  onConfirm: () => void
  // 题材信息（用于智能提示）
  genre?: string
}

export default function ExpansionConfigDialog({
  open,
  onClose,
  expansionMode,
  targetChapterCount,
  incrementalStep,
  totalVolumes,
  totalChaptersMin,
  totalChaptersMax,
  autoExpandAllVolumes,
  frameworkMetadata,
  loadingFramework,
  onExpansionModeChange,
  onTargetChapterCountChange,
  onIncrementalStepChange,
  onTotalVolumesChange,
  onTotalChaptersMinChange,
  onTotalChaptersMaxChange,
  onAutoExpandAllVolumesChange,
  onConfirm,
  genre = '',
}: ExpansionConfigDialogProps) {
  // 🎯 题材适配的智能提示
  const getGenreTip = () => {
    if (expansionMode !== 'epic_framework') return null

    const avgChapters = Math.floor((totalChaptersMin + totalChaptersMax) / 2)
    const avgPerVolume = Math.floor(avgChapters / totalVolumes)

    if (genre === '修仙' || genre === '玄幻') {
      return (
        <Alert severity="info" sx={{ mt: 2 }}>
          💡 <strong>{genre}{totalVolumes}卷建议：</strong>每卷{avgPerVolume}章左右，适合修炼体系分阶段推进
        </Alert>
      )
    } else if (genre === '都市') {
      return (
        <Alert severity="info" sx={{ mt: 2 }}>
          💡 <strong>都市{totalVolumes}卷建议：</strong>每卷{avgPerVolume}章，适合事业发展和人际关系递进
        </Alert>
      )
    }
    return null
  }

  // 🎯 估算耗时
  const getEstimatedTime = () => {
    if (expansionMode === 'epic_framework' && autoExpandAllVolumes) {
      const minutes = Math.floor(totalVolumes * 2) // 假设每卷2分钟
      return `预计耗时：${minutes}-${minutes + 2}分钟`
    } else if (expansionMode === 'epic_framework' && !autoExpandAllVolumes) {
      return '仅生成框架：约1-2分钟'
    }
    return ''
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>
        📖 大纲扩展配置
      </DialogTitle>
      <DialogContent dividers>
        {/* 扩展模式选择 */}
        <FormControl component="fieldset" fullWidth sx={{ mb: 3 }}>
          <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
            扩展模式
          </Typography>
          <RadioGroup
            value={expansionMode}
            onChange={(e) => onExpansionModeChange(e.target.value as any)}
          >
            <FormControlLabel 
              value="total" 
              control={<Radio />} 
              label="📊 按总章数" 
            />
            <FormControlLabel 
              value="epic_framework" 
              control={<Radio />} 
              label="🌟 史诗框架（超长篇）" 
            />
            <FormControlLabel 
              value="incremental" 
              control={<Radio />} 
              label="⏭️ 渐进式扩展" 
            />
          </RadioGroup>
        </FormControl>

        {/* 📋 按总章数模式配置 */}
        {expansionMode === 'total' && (
          <Box sx={{ 
            p: 2, 
            bgcolor: 'grey.50', 
            borderRadius: 2, 
            border: '1px solid', 
            borderColor: 'grey.300' 
          }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 2 }}>
              📋 按总章数
            </Typography>

            <TextField
              label="目标总章节数"
              type="number"
              fullWidth
              size="small"
              value={targetChapterCount}
              onChange={(e) => onTargetChapterCountChange(parseInt(e.target.value) || 100)}
              inputProps={{ min: 10, max: 200 }}
              helperText="范围: 10-200 章"
            />

            <Alert severity="info" sx={{ mt: 2 }}>
              💡 快速规划模式：直接设定目标章节数，AI 将自动生成对应的大纲结构
            </Alert>
          </Box>
        )}

        {/* ⏭️ 渐进式扩展模式配置 */}
        {expansionMode === 'incremental' && (
          <Box sx={{ 
            p: 2, 
            bgcolor: 'info.50', 
            borderRadius: 2, 
            border: '1px solid', 
            borderColor: 'info.200' 
          }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 2 }}>
              ⏭️ 渐进式扩展
            </Typography>

            <TextField
              label="每次扩展章节数"
              type="number"
              fullWidth
              size="small"
              value={incrementalStep}
              onChange={(e) => onIncrementalStepChange(parseInt(e.target.value) || 10)}
              inputProps={{ min: 5, max: 30 }}
              helperText="范围: 5-30 章"
            />

            <Alert severity="info" sx={{ mt: 2 }}>
              💡 精细控制模式：每次扩展少量章节，适合迭代优化和精细打磨
            </Alert>
          </Box>
        )}

        {/* 🌟 史诗框架模式配置 */}
        {expansionMode === 'epic_framework' && (
          <Box sx={{ 
            p: 2, 
            bgcolor: 'primary.50', 
            borderRadius: 2, 
            border: '1px solid', 
            borderColor: 'primary.200' 
          }}>
            <Typography variant="subtitle1" sx={{ fontWeight: 'bold', mb: 2 }}>
              🌟 史诗框架
            </Typography>

            {/* 已有框架提示 */}
            {frameworkMetadata && frameworkMetadata.has_framework && !loadingFramework && (
              <Alert severity="success" sx={{ mb: 2 }}>
                ✅ 已找到史诗框架：{frameworkMetadata.metadata.total_volumes}卷，
                {frameworkMetadata.metadata.total_chapters_range[0]}-
                {frameworkMetadata.metadata.total_chapters_range[1]}章
              </Alert>
            )}

            {/* 加载中 */}
            {loadingFramework && (
              <Box sx={{ display: 'flex', alignItems: 'center', gap: 1, mb: 2 }}>
                <CircularProgress size={20} />
                <Typography variant="body2">正在检查史诗框架...</Typography>
              </Box>
            )}

            {/* 总卷数 */}
            <TextField
              label="总卷数"
              type="number"
              fullWidth
              size="small"
              value={totalVolumes}
              onChange={(e) => onTotalVolumesChange(parseInt(e.target.value) || 5)}
              inputProps={{ min: 5, max: 50 }}
              helperText="建议5-50卷"
              sx={{ mb: 2 }}
            />

            {/* 总章节范围 */}
            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <TextField
                label="总章节（最小）"
                type="number"
                fullWidth
                size="small"
                value={totalChaptersMin}
                onChange={(e) => onTotalChaptersMinChange(parseInt(e.target.value) || 400)}
                inputProps={{ min: 400, max: 5000 }}
              />
              <TextField
                label="总章节（最大）"
                type="number"
                fullWidth
                size="small"
                value={totalChaptersMax}
                onChange={(e) => onTotalChaptersMaxChange(parseInt(e.target.value) || 450)}
                inputProps={{ min: 400, max: 5000 }}
              />
            </Box>

            <Divider sx={{ my: 2 }} />

            {/* 扩展方式选择 */}
            <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
              扩展方式（可切换）
            </Typography>
            <RadioGroup
              value={autoExpandAllVolumes ? 'auto' : 'manual'}
              onChange={(e) => onAutoExpandAllVolumesChange(e.target.value === 'auto')}
            >
              <FormControlLabel
                value="auto"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                      ● 自动扩展全部卷（推荐）
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      ✅ 确认框架后自动扩展{totalVolumes}卷
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      ⏱️ {getEstimatedTime()}
                    </Typography>
                  </Box>
                }
              />
              <FormControlLabel
                value="manual"
                control={<Radio />}
                label={
                  <Box>
                    <Typography variant="body2" sx={{ fontWeight: 'bold' }}>
                      ○ 手动选择扩展某卷
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      📋 仅生成框架，后续手动扩展
                    </Typography>
                    <Typography variant="caption" color="text.secondary" sx={{ display: 'block' }}>
                      🎯 适合超长篇或分阶段创作
                    </Typography>
                  </Box>
                }
              />
            </RadioGroup>

            {/* 题材适配提示 */}
            {getGenreTip()}
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button onClick={onConfirm} variant="contained" color="primary">
          开始扩展
        </Button>
      </DialogActions>
    </Dialog>
  )
}
