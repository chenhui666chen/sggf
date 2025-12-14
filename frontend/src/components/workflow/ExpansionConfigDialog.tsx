import React from 'react'
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
  Chip,
  Tooltip,
  Popover,
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
  // 🖅 删除了 autoExpandAllVolumes 参数
  frameworkMetadata: any
  loadingFramework: boolean
  // 🆕 单卷扩展相关
  targetVolumeIndex: number
  volumeChaptersMin: number
  volumeChaptersMax: number
  // 💡 智能推荐数据
  recommendedMode?: 'total' | 'epic_framework' | 'incremental'
  recommendedVolumes?: number
  recommendedChaptersPerVolumeMin?: number
  recommendedChaptersPerVolumeMax?: number
  // 🖅 删除了 recommendedAutoExpandAllVolumes 参数
  recommendationReason?: string
  // 回调
  onExpansionModeChange: (mode: 'total' | 'volume' | 'incremental' | 'epic_framework' | 'volume_detail') => void
  onTargetChapterCountChange: (count: number) => void
  onIncrementalStepChange: (step: number) => void
  onTotalVolumesChange: (volumes: number) => void
  onTotalChaptersMinChange: (min: number) => void
  onTotalChaptersMaxChange: (max: number) => void
  // 🖅 删除了 onAutoExpandAllVolumesChange 参数
  onTargetVolumeIndexChange: (index: number) => void
  onVolumeChaptersMinChange: (min: number) => void
  onVolumeChaptersMaxChange: (max: number) => void
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
  // 🖅 删除了 autoExpandAllVolumes 参数
  frameworkMetadata,
  loadingFramework,
  targetVolumeIndex,
  volumeChaptersMin,
  volumeChaptersMax,
  recommendedMode,
  recommendedVolumes,
  recommendedChaptersPerVolumeMin,
  recommendedChaptersPerVolumeMax,
  // 🖅 删除了 recommendedAutoExpandAllVolumes 参数
  recommendationReason,
  onExpansionModeChange,
  onTargetChapterCountChange,
  onIncrementalStepChange,
  onTotalVolumesChange,
  onTotalChaptersMinChange,
  onTotalChaptersMaxChange,
  // 🖅 删除了 onAutoExpandAllVolumesChange 参数
  onTargetVolumeIndexChange,
  onVolumeChaptersMinChange,
  onVolumeChaptersMaxChange,
  onConfirm,
  genre = '',
}: ExpansionConfigDialogProps) {
  // 💡 Popover 状态
  const [anchorEl, setAnchorEl] = React.useState<HTMLElement | null>(null)

  const handlePopoverOpen = (event: React.MouseEvent<HTMLElement>) => {
    setAnchorEl(event.currentTarget)
  }

  const handlePopoverClose = () => {
    setAnchorEl(null)
  }

  const popoverOpen = Boolean(anchorEl)
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
    if (expansionMode === 'epic_framework') {
      return '仅生成框架：约1-2分钟'
    }
    return ''
  }
  // 用于显示估计时间，避免未使用警告
  void getEstimatedTime

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
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <span>📊 按总章数</span>
                  {recommendedMode === 'total' && (
                    <Tooltip title="根据题材和篇幅智能推荐" arrow>
                      <Chip 
                        label="💡 智能推荐" 
                        size="small" 
                        color="primary" 
                        onClick={handlePopoverOpen}
                        sx={{ cursor: 'help', height: 20, fontSize: '0.75rem' }}
                      />
                    </Tooltip>
                  )}
                </Box>
              }
            />
            <FormControlLabel 
              value="epic_framework" 
              control={<Radio />} 
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <span>🌟 史诗框架（超长篇）</span>
                  {recommendedMode === 'epic_framework' && (
                    <Tooltip title="根据题材和篇幅智能推荐" arrow>
                      <Chip 
                        label="💡 智能推荐" 
                        size="small" 
                        color="primary" 
                        onClick={handlePopoverOpen}
                        sx={{ cursor: 'help', height: 20, fontSize: '0.75rem' }}
                      />
                    </Tooltip>
                  )}
                </Box>
              }
            />
            <FormControlLabel 
              value="incremental" 
              control={<Radio />} 
              label={
                <Box sx={{ display: 'flex', alignItems: 'center', gap: 1 }}>
                  <span>⏭️ 渐进式扩展</span>
                  {recommendedMode === 'incremental' && (
                    <Tooltip title="根据题材和篇幅智能推荐" arrow>
                      <Chip 
                        label="💡 智能推荐" 
                        size="small" 
                        color="primary" 
                        onClick={handlePopoverOpen}
                        sx={{ cursor: 'help', height: 20, fontSize: '0.75rem' }}
                      />
                    </Tooltip>
                  )}
                </Box>
              }
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
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
                  💡 快速规划模式
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.3 }}>
                  ✅ 适合：短中篇小说（10-200章）、快速验证创意
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.3 }}>
                  ⚡ 优势：一键生成完整大纲，无需复杂配置，2分钟内完成
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                  📌 推荐用于：都市、言情、悬疑等常规体量作品
                </Typography>
              </Box>
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
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
                  💡 精细控制模式
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.3 }}>
                  ✅ 适合：追求极致质量、边写边规划的创作者
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.3 }}>
                  ⚡ 优势：每次扩展5-30章，可随时调整方向，降低试错成本
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                  📌 推荐用于：剧情复杂、多线并进、需反复打磨的作品
                </Typography>
              </Box>
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

            {/* 总卷数 - 已有框架时只读 */}
            <TextField
              label="总卷数"
              type="number"
              fullWidth
              size="small"
              value={frameworkMetadata?.has_framework 
                ? frameworkMetadata.metadata.total_volumes 
                : totalVolumes}
              disabled={frameworkMetadata?.has_framework}
              onChange={(e) => onTotalVolumesChange(parseInt(e.target.value) || 5)}
              inputProps={{ min: 5, max: 50 }}
              helperText={frameworkMetadata?.has_framework 
                ? "框架已固定，不可修改" 
                : "建议5-50卷"}
              sx={{ mb: 2 }}
            />

            {/* 总章节范围 - 已有框架时只读 */}
            <Box sx={{ display: 'flex', gap: 2, mb: 2 }}>
              <TextField
                label="总章节（最小）"
                type="number"
                fullWidth
                size="small"
                value={frameworkMetadata?.has_framework 
                  ? frameworkMetadata.metadata.total_chapters_range[0] 
                  : totalChaptersMin}
                disabled={frameworkMetadata?.has_framework}
                onChange={(e) => onTotalChaptersMinChange(parseInt(e.target.value) || 400)}
                inputProps={{ min: 400, max: 5000 }}
                helperText={frameworkMetadata?.has_framework ? "框架已固定" : ""}
              />
              <TextField
                label="总章节（最大）"
                type="number"
                fullWidth
                size="small"
                value={frameworkMetadata?.has_framework 
                  ? frameworkMetadata.metadata.total_chapters_range[1] 
                  : totalChaptersMax}
                disabled={frameworkMetadata?.has_framework}
                onChange={(e) => onTotalChaptersMaxChange(parseInt(e.target.value) || 450)}
                inputProps={{ min: 400, max: 5000 }}
                helperText={frameworkMetadata?.has_framework ? "框架已固定" : ""}
              />
            </Box>

            <Divider sx={{ my: 2 }} />

            {frameworkMetadata?.has_framework ? (
              // ===== 已有框架UI =====
              <Box>
                {/* 扩展操作标题 */}
                <Typography variant="subtitle2" sx={{ mb: 1, fontWeight: 'bold' }}>
                  扩展操作
                </Typography>

                {/* ✅ 框架信息展示 */}
                <Alert severity="success" sx={{ mb: 2 }}>
                  ✅ 已生成{frameworkMetadata.metadata.total_volumes}卷史诗框架
                </Alert>

                {/* 📝 已扩展卷标记 */}
                {frameworkMetadata.metadata.expanded_volumes && 
                 frameworkMetadata.metadata.expanded_volumes.length > 0 && (
                  <Box sx={{ mb: 2, p: 1.5, bgcolor: 'success.50', borderRadius: 1, border: '1px solid', borderColor: 'success.200' }}>
                    <Typography variant="caption" sx={{ display: 'block', mb: 0.5, fontWeight: 'bold', color: 'success.dark' }}>
                      已扩展卷：
                    </Typography>
                    <Box sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap' }}>
                      {frameworkMetadata.metadata.expanded_volumes.map((vol: number) => (
                        <Chip 
                          key={vol} 
                          label={`第${vol}卷 ✓`} 
                          size="small" 
                          color="success" 
                          variant="outlined"
                          sx={{ height: 22, fontSize: '0.75rem' }}
                        />
                      ))}
                    </Box>
                  </Box>
                )}

                {/* 📝 扩展指定卷输入框 */}
                <TextField
                  label="扩展指定卷（可选，留空将重生框架）"
                  type="number"
                  fullWidth
                  size="small"
                  value={targetVolumeIndex || ''}
                  onChange={(e) => onTargetVolumeIndexChange(parseInt(e.target.value) || 0)}
                  inputProps={{ min: 1, max: frameworkMetadata.metadata.total_volumes }}
                  helperText={`范围: 1-${frameworkMetadata.metadata.total_volumes} 卷`}
                  sx={{ mb: 2 }}
                />

                {/* ⚠️ 留空重生警告 */}
                {!targetVolumeIndex && (
                  <Alert severity="warning" sx={{ mb: 2 }}>
                    ⚠️ 留空将<strong>重新生成框架并清除所有已扩展的细纲</strong>！如不满意框架，建议前往「知识库」→「剧情大纲」删除后重新生成。
                  </Alert>
                )}

                {/* 本卷章节数量配置 */}
                {targetVolumeIndex > 0 && (
                  <Box sx={{ display: 'flex', gap: 2 }}>
                    <TextField
                      label="本卷章节数（最少）"
                      type="number"
                      fullWidth
                      size="small"
                      value={volumeChaptersMin}
                      onChange={(e) => onVolumeChaptersMinChange(parseInt(e.target.value) || 50)}
                      inputProps={{ min: 30, max: 80 }}
                      helperText="每卷生成多少章（上限80章），章节编号自动计算"
                    />
                    <TextField
                      label="本卷章节数（最多）"
                      type="number"
                      fullWidth
                      size="small"
                      value={volumeChaptersMax}
                      onChange={(e) => onVolumeChaptersMaxChange(Math.min(parseInt(e.target.value) || 80, 80))}
                      inputProps={{ min: 30, max: 80 }}
                      helperText="每卷最多80章，增加章数请增加卷数"
                    />
                  </Box>
                )}
              </Box>
            ) : (
              // ===== 无框架：首次扩展提示 =====
              <Alert severity="info" sx={{ mb: 2 }}>
                💡 首次扩展将生成史诗框架，生成后可分卷扩展
              </Alert>
            )}

            {/* 题材适配提示 */}
            {getGenreTip()}
            
            {/* 🆕 史诗框架模式统一说明 */}
            <Alert severity="info" sx={{ mt: 2 }}>
              <Box>
                <Typography variant="body2" sx={{ fontWeight: 'bold', mb: 0.5 }}>
                  💡 史诗框架模式
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.3 }}>
                  ✅ 适合：超长篇网文（400章+）、修仙/玄幻/都市等按卷创作
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', mb: 0.3 }}>
                  ⚡ 优势：分卷规划层次清晰，支持分阶段扩展，避免一次性生成过多内容
                </Typography>
                <Typography variant="caption" sx={{ display: 'block', color: 'text.secondary' }}>
                  📌 推荐用于：修仙（境界体系）、都市（事业发展）、玄幻（多卷史诗）
                </Typography>
              </Box>
            </Alert>
          </Box>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>取消</Button>
        <Button onClick={onConfirm} variant="contained" color="primary">
          {expansionMode === 'epic_framework' && frameworkMetadata?.has_framework 
            ? (targetVolumeIndex ? '开始扩展' : '重生框架')
            : (expansionMode === 'epic_framework' ? '生成框架' : '开始扩展')}
        </Button>
      </DialogActions>

      {/* 💡 智能推荐 Popover */}
      <Popover
        open={popoverOpen}
        anchorEl={anchorEl}
        onClose={handlePopoverClose}
        anchorOrigin={{
          vertical: 'bottom',
          horizontal: 'center',
        }}
        transformOrigin={{
          vertical: 'top',
          horizontal: 'center',
        }}
      >
        <Box sx={{ p: 2, maxWidth: 400 }}>
          <Typography variant="subtitle2" sx={{ fontWeight: 'bold', mb: 1, display: 'flex', alignItems: 'center', gap: 0.5 }}>
            💡 智能推荐理由
          </Typography>
          {recommendationReason ? (
            <Typography variant="body2" sx={{ whiteSpace: 'pre-line' }}>
              {recommendationReason}
            </Typography>
          ) : (
            <Box>
              <Typography variant="body2" sx={{ mb: 1 }}>
                <strong>推荐模式：</strong>
                {recommendedMode === 'total' && '按总章数扩展（快速规划）'}
                {recommendedMode === 'epic_framework' && '史诗框架（超长篇）'}
                {recommendedMode === 'incremental' && '渐进式扩展（精细控制）'}
              </Typography>
              {recommendedMode === 'epic_framework' && (
                <>
                  <Typography variant="body2" sx={{ mb: 0.5 }}>
                    <strong>推荐卷数：</strong>{recommendedVolumes || totalVolumes} 卷
                  </Typography>
                  <Typography variant="body2" sx={{ mb: 0.5 }}>
                    <strong>每卷章节：</strong>
                    {recommendedChaptersPerVolumeMin || 30}-{recommendedChaptersPerVolumeMax || 50} 章
                  </Typography>
                  {/* 🖅 删除了扩展方式推荐 */}
                </>
              )}
              <Typography variant="caption" sx={{ display: 'block', mt: 1, color: 'text.secondary', fontStyle: 'italic' }}>
                🔍 基于「{genre}」题材与篇幅智能计算
              </Typography>
            </Box>
          )}
        </Box>
      </Popover>
    </Dialog>
  )
}
