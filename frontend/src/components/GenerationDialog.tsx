/**
 * 生成对话框组件
 * 用于选择生成任务类型和参数
 */

import { useState } from 'react'
import {
  Dialog,
  DialogTitle,
  DialogContent,
  DialogActions,
  Button,
  Box,
  TextField,
  FormControl,
  InputLabel,
  Select,
  MenuItem,
  Typography,
  Alert,
} from '@mui/material'

interface GenerationDialogProps {
  open: boolean
  // projectId 暂时未使用，保留以便未来扩展
  projectId: number
  onClose: () => void
  onGenerate: (taskType: string, params: Record<string, any>) => void
  isLoading?: boolean
}

export default function GenerationDialog(props: GenerationDialogProps) {
  const { open, onClose, onGenerate, isLoading = false } = props
  const [taskType, setTaskType] = useState('world')
  const [requirements, setRequirements] = useState('')

  const taskTypeOptions = [
    { value: 'world', label: '生成世界观', placeholder: '描述你想要的世界观特点...' },
    { value: 'character', label: '生成人物', placeholder: '描述你想要的人物特征...' },
    { value: 'plot', label: '生成情节', placeholder: '描述你想要的情节框架...' },
    { value: 'chapter', label: '生成章节', placeholder: '描述你想要的章节内容...' },
  ]

  const currentOption = taskTypeOptions.find((opt) => opt.value === taskType)

  const handleGenerate = () => {
    if (!requirements.trim()) {
      alert('请输入生成要求')
      return
    }

    const params: Record<string, any> = {
      requirements,
    }

    // 如果是生成章节，需要添加章节号
    if (taskType === 'chapter') {
      params.chapter_number = 1 // 默认第一章，可以后续改进
    }

    onGenerate(taskType, params)
    setRequirements('')
  }

  return (
    <Dialog open={open} onClose={onClose} maxWidth="sm" fullWidth>
      <DialogTitle>生成内容</DialogTitle>
      <DialogContent sx={{ pt: 2 }}>
        <Alert severity="info" sx={{ mb: 2 }}>
          选择要生成的内容类型，并提供详细的要求说明
        </Alert>

        <FormControl fullWidth margin="normal">
          <InputLabel>生成类型</InputLabel>
          <Select
            value={taskType}
            onChange={(e) => setTaskType(e.target.value)}
            label="生成类型"
            disabled={isLoading}
          >
            {taskTypeOptions.map((opt) => (
              <MenuItem key={opt.value} value={opt.value}>
                {opt.label}
              </MenuItem>
            ))}
          </Select>
        </FormControl>

        <TextField
          fullWidth
          label="生成要求"
          value={requirements}
          onChange={(e) => setRequirements(e.target.value)}
          margin="normal"
          multiline
          rows={5}
          placeholder={currentOption?.placeholder}
          disabled={isLoading}
          helperText="提供越详细的要求，生成的内容质量越好"
        />

        <Box sx={{ mt: 2, p: 2, backgroundColor: '#f5f5f5', borderRadius: 1 }}>
          <Typography variant="caption" color="textSecondary">
            💡 提示：
          </Typography>
          <Typography variant="caption" color="textSecondary" component="div" sx={{ mt: 0.5 }}>
            • 世界观：描述地理、文化、科技水平等
          </Typography>
          <Typography variant="caption" color="textSecondary" component="div">
            • 人物：描述性格、背景、动机等
          </Typography>
          <Typography variant="caption" color="textSecondary" component="div">
            • 情节：描述故事结构、冲突、转折等
          </Typography>
          <Typography variant="caption" color="textSecondary" component="div">
            • 章节：描述章节内容、场景、对话等
          </Typography>
        </Box>
      </DialogContent>

      <DialogActions>
        <Button onClick={onClose} disabled={isLoading}>
          取消
        </Button>
        <Button
          variant="contained"
          color="primary"
          onClick={handleGenerate}
          disabled={isLoading || !requirements.trim()}
        >
          {isLoading ? '生成中...' : '生成'}
        </Button>
      </DialogActions>
    </Dialog>
  )
}

