import { useEffect, useState } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import {
  Container,
  Box,
  Stepper,
  Step,
  StepLabel,
  Button,
  Card,
  CardContent,
  Typography,
  LinearProgress,
  Grid,
  Paper,
  Dialog,
  TextField,
  Alert,
  CircularProgress,
} from '@mui/material'
import PlayArrowIcon from '@mui/icons-material/PlayArrow'
import PauseIcon from '@mui/icons-material/Pause'
import RefreshIcon from '@mui/icons-material/Refresh'
import SaveIcon from '@mui/icons-material/Save'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import DescriptionIcon from '@mui/icons-material/Description'
import ArticleIcon from '@mui/icons-material/Article'
import EditNoteIcon from '@mui/icons-material/EditNote'
import CheckCircleIcon from '@mui/icons-material/CheckCircle'
import PublicIcon from '@mui/icons-material/Public'
import PeopleIcon from '@mui/icons-material/People'
import Snackbar from '@mui/material/Snackbar'
import MuiAlert from '@mui/material/Alert'
import { RootState, AppDispatch } from '@/store/store'
import {
  startWorkflow,
  executeStage,
  regenerateStage,
  setCurrentStage,
  completeWorkflowAndCreateProject,
  updateStageOutput,
  StageType,
} from '@/store/slices/workflowSlice'
import StageDetailPanel from '@/components/workflow/StageDetailPanel'
import AgentStatusIndicator from '@/components/workflow/AgentStatusIndicator'

const stages: StageType[] = ['concept', 'structure', 'content', 'review', 'iteration']
const stageNames = {
  concept: '概念开发',
  structure: '结构设计',
  content: '内容创作',
  review: '质量评审',
  iteration: '迭代优化',
}

export default function WorkflowControlPage() {
  const { projectId } = useParams<{ projectId: string }>()
  const navigate = useNavigate()
  const dispatch = useDispatch<AppDispatch>()
  const workflow = useSelector((state: RootState) => state.workflow)
  const [openDialog, setOpenDialog] = useState(false)
  const [requirement, setRequirement] = useState('')
  const [isRunning, setIsRunning] = useState(false)
  const [showSaveDialog, setShowSaveDialog] = useState(false)
  const [chapterTitle, setChapterTitle] = useState('')
  const [isAutoCreatingProject, setIsAutoCreatingProject] = useState(false)

  // 故事概念对话框状态
  const [showConceptDialog, setShowConceptDialog] = useState(false)
  const [conceptContent, setConceptContent] = useState('')
  const [editedContent, setEditedContent] = useState('')
  const [conceptLoading, setConceptLoading] = useState(false)
  const [conceptSaving, setConceptSaving] = useState(false)

  // 情节大纲对话框状态
  const [showStructureDialog, setShowStructureDialog] = useState(false)
  const [structureContent, setStructureContent] = useState('')
  const [editedStructureContent, setEditedStructureContent] = useState('')
  const [structureLoading, setStructureLoading] = useState(false)
  const [structureSaving, setStructureSaving] = useState(false)

  // 章节初稿对话框状态
  const [showContentDialog, setShowContentDialog] = useState(false)
  const [contentDraftContent, setContentDraftContent] = useState('')
  const [editedContentDraftContent, setEditedContentDraftContent] = useState('')
  const [contentLoading, setContentLoading] = useState(false)
  const [contentSaving, setContentSaving] = useState(false)

  // 最终版本对话框状态
  const [showFinalVersionDialog, setShowFinalVersionDialog] = useState(false)
  const [finalVersionContent, setFinalVersionContent] = useState('')
  const [editedFinalVersionContent, setEditedFinalVersionContent] = useState('')
  const [finalVersionLoading, setFinalVersionLoading] = useState(false)
  const [finalVersionSaving, setFinalVersionSaving] = useState(false)

  // 世界观设定对话框状态
  const [showWorldDialog, setShowWorldDialog] = useState(false)
  const [worldContent, setWorldContent] = useState('')
  const [editedWorldContent, setEditedWorldContent] = useState('')
  const [worldLoading, setWorldLoading] = useState(false)
  const [worldSaving, setWorldSaving] = useState(false)

  // 人物设定对话框状态
  const [showCharacterDialog, setShowCharacterDialog] = useState(false)
  const [characterContent, setCharacterContent] = useState('')
  const [editedCharacterContent, setEditedCharacterContent] = useState('')
  const [characterLoading, setCharacterLoading] = useState(false)
  const [characterSaving, setCharacterSaving] = useState(false)

  const [snackbarOpen, setSnackbarOpen] = useState(false)
  const [snackbarMessage, setSnackbarMessage] = useState('')
  const [snackbarSeverity, setSnackbarSeverity] = useState<'success' | 'error'>('success')

  useEffect(() => {
    if (projectId) {
      dispatch(setCurrentStage('concept'))
    }
  }, [projectId, dispatch])

  // 页面刷新时加载所有已保存的阶段内容
  useEffect(() => {
    if (!projectId) return

    const loadAllStageContents = async () => {
      try {
        console.log('📍 开始加载所有阶段内容...')

        // 第一步：加载按钮内容（使用STAGE_TO_COLUMN_MAP）
        const buttonStages = [
          { name: 'concept', setter: setConceptContent, label: '故事概念' },
          { name: 'world_builder', setter: setWorldContent, label: '世界观设定' },
          { name: 'character_designer', setter: setCharacterContent, label: '人物设定' },
          { name: 'structure', setter: setStructureContent, label: '情节大纲' },
          { name: 'content', setter: setContentDraftContent, label: '章节初稿' },
          { name: 'iteration', setter: setFinalVersionContent, label: '最终版本' },
        ]

        // 并行加载所有按钮内容
        const buttonPromises = buttonStages.map(stage =>
          fetch(`/api/workflow/${projectId}/stage/${stage.name}/content`, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            },
          })
            .then(res => res.ok ? res.json() : null)
            .then(data => ({ stage: stage.name, data, setter: stage.setter, label: stage.label }))
            .catch(error => {
              console.warn(`⚠️  加载${stage.label}失败:`, error)
              return { stage: stage.name, data: null, setter: stage.setter, label: stage.label }
            })
        )

        const buttonResults = await Promise.all(buttonPromises)

        // 设置按钮内容的状态变量
        buttonResults.forEach(result => {
          if (result.data && result.data.content) {
            result.setter(result.data.content)
            console.log(`✅ ${result.label}已加载，内容长度: ${result.data.content.length}`)
          } else {
            result.setter('')
            console.log(`📝 ${result.label}尚未生成`)
          }
        })

        // 第二步：加载输出预览内容（使用STAGE_OUTPUT_PREVIEW_MAP）
        // 输出预览只需要加载主要阶段的内容
        const previewStages: Array<{ stage: StageType; label: string }> = [
          { stage: 'concept', label: '概念开发' },
          { stage: 'structure', label: '结构设计' },
          { stage: 'content', label: '内容创作' },
          { stage: 'review', label: '质量评审' },
          { stage: 'iteration', label: '迭代优化' },
        ]

        const previewPromises = previewStages.map(({ stage, label }) =>
          fetch(`/api/workflow/${projectId}/stage/${stage}/content?type=preview`, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            },
          })
            .then(res => res.ok ? res.json() : null)
            .then(data => ({ stage, data, label }))
            .catch(error => {
              console.warn(`⚠️  加载${label}输出预览失败:`, error)
              return { stage, data: null, label }
            })
        )

        const previewResults = await Promise.all(previewPromises)

        // 更新Redux store的output字段，用于输出预览显示
        previewResults.forEach(result => {
          if (result.data && result.data.content) {
            dispatch(updateStageOutput({ stage: result.stage, output: result.data.content }))
            console.log(`✅ Redux store已更新: ${result.stage} output (输出预览)`)
          }
        })

        console.log('✅ 所有阶段内容加载完成')
      } catch (error) {
        console.error('❌ 加载阶段内容失败:', error)
        // 不显示错误提示，避免干扰用户体验
      }
    }

    loadAllStageContents()
  }, [projectId, dispatch])

  // 自动执行阶段的逻辑
  useEffect(() => {
    if (!isRunning || !projectId) return

    // 检查当前阶段是否已完成
    const currentStageData = workflow.stages[workflow.currentStage]
    if (currentStageData.status === 'completed') {
      // 🔧 新增: 阶段完成后，加载输出内容到Redux store
      const loadStageOutput = async () => {
        try {
          console.log(`🔄 加载阶段 ${workflow.currentStage} 的输出预览内容...`)

          // 加载输出预览内容（使用?type=preview参数）
          const response = await fetch(`/api/workflow/${projectId}/stage/${workflow.currentStage}/content?type=preview`, {
            headers: {
              'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
            },
          })

          if (response.ok) {
            const data = await response.json()
            if (data.content) {
              dispatch(updateStageOutput({
                stage: workflow.currentStage,
                output: data.content
              }))
              console.log(`✅ 阶段 ${workflow.currentStage} 的输出预览已加载到Redux store`)
            }
          }
        } catch (error) {
          console.error(`❌ 加载阶段 ${workflow.currentStage} 输出预览失败:`, error)
        }
      }
      
      loadStageOutput()
      
      // 如果当前阶段已完成，自动执行下一阶段
      const currentIndex = stages.indexOf(workflow.currentStage)
      if (currentIndex < stages.length - 1) {
        // 移动到下一阶段
        const nextStage = stages[currentIndex + 1]
        dispatch(setCurrentStage(nextStage))

        // 自动执行下一阶段
        setTimeout(() => {
          dispatch(
            executeStage({
              projectId: parseInt(projectId),
              stage: nextStage,
            })
          )
        }, 500)
      } else {
        // 所有阶段都已完成 - 显示保存对话框
        setIsRunning(false)
        setShowSaveDialog(true)
      }
    } else if (currentStageData.status === 'pending' && !workflow.loading) {
      // 如果当前阶段是pending状态且没有在加载，自动执行
      dispatch(
        executeStage({
          projectId: parseInt(projectId),
          stage: workflow.currentStage,
        })
      )
    }
  }, [isRunning, workflow.currentStage, workflow.stages, workflow.loading, projectId, dispatch])

  const handleStartWorkflow = async () => {
    if (!projectId || !requirement.trim()) {
      alert('请输入创作需求')
      return
    }

    try {
      await dispatch(
        startWorkflow({
          projectId: parseInt(projectId),
          requirement,
        })
      ).unwrap()
      setOpenDialog(false)
      setIsRunning(true)
    } catch (error) {
      console.error('Failed to start workflow:', error)
    }
  }

  const handleRegenerateStage = async () => {
    if (!projectId) return

    try {
      await dispatch(
        regenerateStage({
          projectId: parseInt(projectId),
          stage: workflow.currentStage,
        })
      ).unwrap()
    } catch (error) {
      console.error('Failed to regenerate stage:', error)
    }
  }

  const handleNextStage = () => {
    const currentIndex = stages.indexOf(workflow.currentStage)
    if (currentIndex < stages.length - 1) {
      dispatch(setCurrentStage(stages[currentIndex + 1]))
    }
  }

  const handlePreviousStage = () => {
    const currentIndex = stages.indexOf(workflow.currentStage)
    if (currentIndex > 0) {
      dispatch(setCurrentStage(stages[currentIndex - 1]))
    }
  }

  const handleSaveAsChapter = async () => {
    if (!projectId) {
      console.error('❌ 项目ID不存在')
      setSnackbarMessage('项目ID不存在')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
      return
    }

    try {
      console.log('📍 开始保存章节，projectId:', projectId)

      // 获取最后一个阶段（迭代优化）的输出内容
      const iterationOutput = workflow.stages.iteration.output
      const content = typeof iterationOutput === 'string' ? iterationOutput : JSON.stringify(iterationOutput, null, 2)
      
      if (!content || content.trim() === '') {
        console.error('❌ 章节内容为空')
        setSnackbarMessage('没有可保存的章节内容')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
        return
      }

      console.log('📍 章节内容长度:', content.length)

      // 如果用户没有输入标题，后端会自动生成
      const titleToSave = chapterTitle.trim() || ''
      console.log('📍 章节标题:', titleToSave || '(自动生成)')

      // 1. 先保存到工作流（project_settings）
      console.log('📍 步骤1: 保存到工作流...')
      await fetch(`/api/workflow/${projectId}/stage/iteration/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: content,
          continue_workflow: false,
        }),
      })

      // 2. 创建独立章节记录
      console.log('📍 步骤2: 创建章节记录...')
      const response = await fetch('/api/v1/chapters', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          project_id: parseInt(projectId),
          content: content,
          title: titleToSave || undefined, // 如果为空则自动生成
        }),
      })

      if (response.ok) {
        const chapter = await response.json()
        console.log('✅ 章节创建成功:', chapter)
        
        setSnackbarMessage(`✅ 章节已保存：${chapter.title} (${chapter.word_count} 字)`)
        setSnackbarSeverity('success')
        setSnackbarOpen(true)
        
        // 关闭对话框，清空标题
        setShowSaveDialog(false)
        setChapterTitle('')

        // 1.5秒后跳转到项目详情页面
        console.log('📍 1.5秒后跳转到项目详情页面...')
        setTimeout(() => {
          console.log('📍 跳转到:', `/project/${projectId}`)
          navigate(`/project/${projectId}`)
        }, 1500)
      } else {
        const errorData = await response.json()
        console.error('❌ 创建章节失败:', errorData)
        
        setSnackbarMessage(errorData.error || '保存章节失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 保存章节异常:', error)
      setSnackbarMessage('保存章节失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    }
  }

  // 处理工作流程完成后自动创建项目
  const handleAutoCreateProject = async () => {
    if (!projectId || !requirement) {
      console.error('❌ 项目ID或创作需求不存在')
      return
    }

    setIsAutoCreatingProject(true)

    try {
      console.log('📍 开始自动创建项目...')

      // 获取所有阶段的输出
      const conceptOutput = workflow.stages.concept.output || ''
      const structureOutput = workflow.stages.structure.output || ''
      const contentOutput = workflow.stages.content.output || ''
      const reviewOutput = workflow.stages.review.output || ''
      const iterationOutput = workflow.stages.iteration.output || ''

      // 调用创建项目的 thunk
      const result = await dispatch(
        completeWorkflowAndCreateProject({
          requirement,
          conceptOutput,
          structureOutput,
          contentOutput,
          reviewOutput,
          iterationOutput,
        })
      ).unwrap()

      console.log('✅ 项目创建成功，新项目ID:', result.projectId)

      setSnackbarMessage(`✅ 项目"${result.projectTitle}"已创建成功！`)
      setSnackbarSeverity('success')
      setSnackbarOpen(true)

      // 2秒后跳转回首页
      setTimeout(() => {
        console.log('📍 跳转回首页...')
        navigate('/dashboard')
      }, 2000)
    } catch (error) {
      console.error('❌ 创建项目失败:', error)
      setSnackbarMessage('创建项目失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setIsAutoCreatingProject(false)
    }
  }

  // 打开故事概念对话框
  const handleOpenConceptDialog = async () => {
    setShowConceptDialog(true)
    setConceptLoading(true)

    try {
      // 优先使用已加载到state中的内容（页面刷新后由useEffect加载）
      if (conceptContent && conceptContent.trim()) {
        console.log('📍 使用已加载的概念内容，长度:', conceptContent.length)
        setEditedContent(conceptContent)
        setConceptLoading(false)
        return
      }

      // 其次尝试从Redux store获取
      const conceptOutput = workflow.stages.concept.output
      if (conceptOutput) {
        console.log('📍 从Redux store读取概念内容')
        setConceptContent(conceptOutput)
        setEditedContent(conceptOutput)
        setConceptLoading(false)
        return
      }

      // 如果Redux store中没有，则从API获取
      console.log('📍 从API获取概念内容')
      const response = await fetch(`/api/workflow/${projectId}/stage/concept/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setConceptContent(data.content || '')
        setEditedContent(data.content || '')
      } else {
        console.error('❌ 获取故事概念失败，状态码:', response.status)
        setSnackbarMessage('获取故事概念失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取故事概念异常:', error)
      setSnackbarMessage('获取故事概念失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptLoading(false)
    }
  }

  // 关闭故事概念对话框
  const handleCloseConceptDialog = () => {
    setShowConceptDialog(false)
    // 不清空 conceptContent，保持已保存的内容
    setEditedContent('')  // 只清空编辑状态
  }

  // 保存并继续
  const handleSaveAndContinue = async () => {
    if (!projectId) return

    setConceptSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/concept/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContent,
          continue_workflow: true,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setConceptContent(editedContent)
        
        setSnackbarMessage('内容已保存，继续执行下一阶段...')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 关闭对话框
        handleCloseConceptDialog()

        // 触发下一阶段执行
        setTimeout(() => {
          handleNextStage()
        }, 1000)
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save concept:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptSaving(false)
    }
  }

  // 仅保存
  const handleSaveOnly = async () => {
    if (!projectId) return

    setConceptSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/concept/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setConceptContent(editedContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        // 关闭对话框
        handleCloseConceptDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save concept:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setConceptSaving(false)
    }
  }

  // 打开情节大纲对话框
  const handleOpenStructureDialog = async () => {
    setShowStructureDialog(true)
    setStructureLoading(true)

    try {
      // 优先使用已加载到state中的内容
      if (structureContent && structureContent.trim()) {
        console.log('📍 使用已加载的情节大纲，长度:', structureContent.length)
        setEditedStructureContent(structureContent)
        setStructureLoading(false)
        return
      }

      // 其次尝试从Redux store获取
      const structureOutput = workflow.stages.structure.output
      if (structureOutput) {
        console.log('📍 从Redux store读取结构内容')
        setStructureContent(structureOutput)
        setEditedStructureContent(structureOutput)
        setStructureLoading(false)
        return
      }

      // 如果Redux store中没有，则从API获取
      console.log('📍 从API获取结构内容')
      const response = await fetch(`/api/workflow/${projectId}/stage/structure/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setStructureContent(data.content || '')
        setEditedStructureContent(data.content || '')
      } else {
        console.error('❌ 获取情节大纲失败，状态码:', response.status)
        setSnackbarMessage('获取情节大纲失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取情节大纲异常:', error)
      setSnackbarMessage('获取情节大纲失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureLoading(false)
    }
  }

  // 关闭情节大纲对话框
  const handleCloseStructureDialog = () => {
    setShowStructureDialog(false)
    // 不清空 structureContent，保持已保存的内容
    setEditedStructureContent('')  // 只清空编辑状态
  }

  // 保存并继续（情节大纲）
  const handleSaveAndContinueStructure = async () => {
    if (!projectId) return

    setStructureSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/structure/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedStructureContent,
          continue_workflow: true,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setStructureContent(editedStructureContent)
        
        setSnackbarMessage('内容已保存，继续执行下一阶段...')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseStructureDialog()

        setTimeout(() => {
          handleNextStage()
        }, 1000)
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save structure:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureSaving(false)
    }
  }

  // 仅保存（情节大纲）
  const handleSaveOnlyStructure = async () => {
    if (!projectId) return

    setStructureSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/structure/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedStructureContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setStructureContent(editedStructureContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseStructureDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save structure:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setStructureSaving(false)
    }
  }

  // 打开章节初稿对话框
  const handleOpenContentDialog = async () => {
    setShowContentDialog(true)
    setContentLoading(true)

    try {
      // 优先使用已加载到state中的内容
      if (contentDraftContent && contentDraftContent.trim()) {
        console.log('📍 使用已加载的章节初稿，长度:', contentDraftContent.length)
        setEditedContentDraftContent(contentDraftContent)
        setContentLoading(false)
        return
      }

      // 其次尝试从Redux store获取
      const contentOutput = workflow.stages.content.output
      if (contentOutput) {
        console.log('📍 从Redux store读取内容')
        setContentDraftContent(contentOutput)
        setEditedContentDraftContent(contentOutput)
        setContentLoading(false)
        return
      }

      // 如果Redux store中没有，则从API获取
      console.log('📍 从API获取内容')
      const response = await fetch(`/api/workflow/${projectId}/stage/content/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setContentDraftContent(data.content || '')
        setEditedContentDraftContent(data.content || '')
      } else {
        console.error('❌ 获取章节初稿失败，状态码:', response.status)
        setSnackbarMessage('获取章节初稿失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取章节初稿异常:', error)
      setSnackbarMessage('获取章节初稿失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentLoading(false)
    }
  }

  // 关闭章节初稿对话框
  const handleCloseContentDialog = () => {
    setShowContentDialog(false)
    // 不清空 contentDraftContent，保持已保存的内容
    setEditedContentDraftContent('')  // 只清空编辑状态
  }

  // 保存并继续（章节初稿）
  const handleSaveAndContinueContent = async () => {
    if (!projectId) return

    setContentSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/content/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContentDraftContent,
          continue_workflow: true,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setContentDraftContent(editedContentDraftContent)
        
        setSnackbarMessage('内容已保存，继续执行下一阶段...')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseContentDialog()

        setTimeout(() => {
          handleNextStage()
        }, 1000)
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save content:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }

  // 仅保存（章节初稿）
  const handleSaveOnlyContent = async () => {
    if (!projectId) return

    setContentSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/content/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedContentDraftContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setContentDraftContent(editedContentDraftContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseContentDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save content:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setContentSaving(false)
    }
  }

  // 打开世界观设定对话框
  const handleOpenWorldDialog = async () => {
    setShowWorldDialog(true)
    setWorldLoading(true)

    try {
      // 优先使用已加载到state中的内容
      if (worldContent && worldContent.trim()) {
        console.log('📍 使用已加载的世界观设定，长度:', worldContent.length)
        setEditedWorldContent(worldContent)
        setWorldLoading(false)
        return
      }

      // 如果没有，则从API获取
      console.log('📍 从API获取世界观设定')
      const response = await fetch(`/api/workflow/${projectId}/stage/world_builder/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setWorldContent(data.content || '')
        setEditedWorldContent(data.content || '')
      } else {
        console.error('❌ 获取世界观设定失败，状态码:', response.status)
        setSnackbarMessage('获取世界观设定失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取世界观设定异常:', error)
      setSnackbarMessage('获取世界观设定失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldLoading(false)
    }
  }

  // 关闭世界观设定对话框
  const handleCloseWorldDialog = () => {
    setShowWorldDialog(false)
    // 不清空 worldContent，保持已保存的内容
    setEditedWorldContent('')  // 只清空编辑状态
  }

  // 保存并继续（世界观设定）
  const handleSaveAndContinueWorld = async () => {
    if (!projectId) return

    setWorldSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/world_builder/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedWorldContent,
          continue_workflow: true,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setWorldContent(editedWorldContent)
        
        setSnackbarMessage('内容已保存，继续执行下一阶段...')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseWorldDialog()

        setTimeout(() => {
          handleNextStage()
        }, 1000)
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save world setting:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldSaving(false)
    }
  }

  // 仅保存（世界观设定）
  const handleSaveOnlyWorld = async () => {
    if (!projectId) return

    setWorldSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/world_builder/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedWorldContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setWorldContent(editedWorldContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseWorldDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save world setting:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setWorldSaving(false)
    }
  }

  // 打开人物设定对话框
  const handleOpenCharacterDialog = async () => {
    setShowCharacterDialog(true)
    setCharacterLoading(true)

    try {
      // 优先使用已加载到state中的内容
      if (characterContent && characterContent.trim()) {
        console.log('📍 使用已加载的人物设定，长度:', characterContent.length)
        setEditedCharacterContent(characterContent)
        setCharacterLoading(false)
        return
      }

      // 如果没有，则从API获取
      console.log('📍 从API获取人物设定')
      const response = await fetch(`/api/workflow/${projectId}/stage/character_designer/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setCharacterContent(data.content || '')
        setEditedCharacterContent(data.content || '')
      } else {
        console.error('❌ 获取人物设定失败，状态码:', response.status)
        setSnackbarMessage('获取人物设定失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取人物设定异常:', error)
      setSnackbarMessage('获取人物设定失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterLoading(false)
    }
  }

  // 关闭人物设定对话框
  const handleCloseCharacterDialog = () => {
    setShowCharacterDialog(false)
    // 不清空 characterContent，保持已保存的内容
    setEditedCharacterContent('')  // 只清空编辑状态
  }

  // 保存并继续（人物设定）
  const handleSaveAndContinueCharacter = async () => {
    if (!projectId) return

    setCharacterSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/character_designer/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedCharacterContent,
          continue_workflow: true,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setCharacterContent(editedCharacterContent)
        
        setSnackbarMessage('内容已保存，继续执行下一阶段...')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseCharacterDialog()

        setTimeout(() => {
          handleNextStage()
        }, 1000)
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save character:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterSaving(false)
    }
  }

  // 仅保存（人物设定）
  const handleSaveOnlyCharacter = async () => {
    if (!projectId) return

    setCharacterSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/character_designer/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedCharacterContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setCharacterContent(editedCharacterContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseCharacterDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save character:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setCharacterSaving(false)
    }
  }

  // 打开最终版本对话框
  const handleOpenFinalProduct = async () => {
    setShowFinalVersionDialog(true)
    setFinalVersionLoading(true)

    try {
      // 优先使用已加载到state中的内容
      if (finalVersionContent && finalVersionContent.trim()) {
        console.log('📏 使用已加载的最终版本，长度:', finalVersionContent.length)
        setEditedFinalVersionContent(finalVersionContent)
        setFinalVersionLoading(false)
        return
      }

      // 其次尝试从 Redux store 获取
      const iterationOutput = workflow.stages.iteration.output
      if (iterationOutput) {
        console.log('📏 从 Redux store 读取最终版本')
        setFinalVersionContent(iterationOutput)
        setEditedFinalVersionContent(iterationOutput)
        setFinalVersionLoading(false)
        return
      }

      // 如果 Redux store 中没有，则从 API 获取
      console.log('📏 从 API 获取最终版本')
      const response = await fetch(`/api/workflow/${projectId}/stage/iteration/content`, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
        },
      })

      if (response.ok) {
        const data = await response.json()
        setFinalVersionContent(data.content || '')
        setEditedFinalVersionContent(data.content || '')
      } else {
        console.error('❌ 获取最终版本失败，状态码:', response.status)
        setSnackbarMessage('获取最终版本失败')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('❌ 获取最终版本异常:', error)
      setSnackbarMessage('获取最终版本失败')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setFinalVersionLoading(false)
    }
  }

  // 关闭最终版本对话框
  const handleCloseFinalVersionDialog = () => {
    setShowFinalVersionDialog(false)
    // 不清空 finalVersionContent，保持已保存的内容
    setEditedFinalVersionContent('')  // 只清空编辑状态
  }

  // 仅保存（最终版本）
  const handleSaveOnlyFinalVersion = async () => {
    if (!projectId) return

    setFinalVersionSaving(true)

    try {
      const response = await fetch(`/api/workflow/${projectId}/stage/iteration/content`, {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('access_token')}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          content: editedFinalVersionContent,
          continue_workflow: false,
        }),
      })

      if (response.ok) {
        // ✅ 更新state，保持已保存的内容
        setFinalVersionContent(editedFinalVersionContent)
        
        setSnackbarMessage('内容已保存')
        setSnackbarSeverity('success')
        setSnackbarOpen(true)

        handleCloseFinalVersionDialog()
      } else {
        setSnackbarMessage('保存失败，请重试')
        setSnackbarSeverity('error')
        setSnackbarOpen(true)
      }
    } catch (error) {
      console.error('Failed to save final version:', error)
      setSnackbarMessage('保存失败，请重试')
      setSnackbarSeverity('error')
      setSnackbarOpen(true)
    } finally {
      setFinalVersionSaving(false)
    }
  }

  const currentStageIndex = stages.indexOf(workflow.currentStage)

  return (
    <Container maxWidth="lg" sx={{ py: 4 }}>
      {/* 返回按钮 */}
      <Box sx={{ mb: 3 }}>
        <Button
          startIcon={<ArrowBackIcon />}
          onClick={() => navigate('/dashboard')}
          variant="outlined"
        >
          返回仪表板
        </Button>
      </Box>

      {/* 标题和进度 */}
      <Box sx={{ mb: 4 }}>
        <Typography variant="h4" sx={{ mb: 2 }}>
          🚀 多Agent小说创作工作流程
        </Typography>
        <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', mb: 2 }}>
          <Typography variant="body1">
            总体进度: {workflow.overallProgress}%
          </Typography>
          <Box sx={{ display: 'flex', gap: 1 }}>
            {!isRunning && (
              <Button
                variant="contained"
                color="primary"
                startIcon={<PlayArrowIcon />}
                onClick={() => setOpenDialog(true)}
              >
                开始创作
              </Button>
            )}
            {isRunning && (
              <Button
                variant="contained"
                color="error"
                startIcon={<PauseIcon />}
                onClick={() => setIsRunning(false)}
              >
                暂停
              </Button>
            )}
          </Box>
        </Box>
        <LinearProgress variant="determinate" value={workflow.overallProgress} />
      </Box>

      {/* 错误提示 */}
      {workflow.error && (
        <Alert severity="error" sx={{ mb: 3 }}>
          {workflow.error}
        </Alert>
      )}

      {/* 阶段导航 */}
      <Paper sx={{ p: 3, mb: 4 }}>
        <Stepper activeStep={currentStageIndex}>
          {stages.map((stage) => (
            <Step key={stage} completed={workflow.stages[stage].status === 'completed'}>
              <StepLabel>{stageNames[stage]}</StepLabel>
            </Step>
          ))}
        </Stepper>
      </Paper>

      {/* 主内容区域 */}
      <Grid container spacing={3}>
        {/* 左侧：阶段详情 */}
        <Grid item xs={12} md={8}>
          <StageDetailPanel stage={workflow.currentStage} />
        </Grid>

        {/* 右侧：Agent状态 */}
        <Grid item xs={12} md={4}>
          <Card>
            <CardContent>
              <Typography variant="h6" sx={{ mb: 2 }}>
                📊 Agent状态
              </Typography>
              {workflow.stages[workflow.currentStage].agents.map((agent) => (
                <AgentStatusIndicator key={agent.id} agent={agent} />
              ))}
            </CardContent>
          </Card>
        </Grid>
      </Grid>

      {/* 控制按钮 */}
      <Box sx={{ mt: 4, display: 'flex', gap: 2, justifyContent: 'center' }}>
        {/* 概念开发阶段不显示"上一步"按钮 */}
        {workflow.currentStage !== 'concept' && (
          <Button
            variant="outlined"
            onClick={handlePreviousStage}
            disabled={currentStageIndex === 0 || workflow.loading || isRunning}
          >
            上一步
          </Button>
        )}

        {/* 概念开发阶段：显示“故事概念”、“世界观设定”、“人物设定”按钮 */}
        {workflow.currentStage === 'concept' ? (
          <Box sx={{ display: 'flex', gap: 1 }}>
            <Button
              variant="outlined"
              onClick={handleOpenConceptDialog}
              disabled={!conceptContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<DescriptionIcon />}
            >
              故事概念
            </Button>
            <Button
              variant="outlined"
              onClick={handleOpenWorldDialog}
              disabled={!worldContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<PublicIcon />}
            >
              世界观设定
            </Button>
            <Button
              variant="outlined"
              onClick={handleOpenCharacterDialog}
              disabled={!characterContent && workflow.stages.concept.status !== 'completed'}
              startIcon={<PeopleIcon />}
            >
              人物设定
            </Button>
          </Box>
        ) : workflow.currentStage === 'structure' ? (
          /* 结构设计阶段：显示“情节大纲”按钮 */
          <Button
            variant="outlined"
            onClick={handleOpenStructureDialog}
            disabled={!structureContent && workflow.stages.structure.status !== 'completed'}
            startIcon={<ArticleIcon />}
          >
            情节大纲
          </Button>
        ) : workflow.currentStage === 'content' ? (
          /* 内容创作阶段：显示“章节初稿”按钮 */
          <Button
            variant="outlined"
            onClick={handleOpenContentDialog}
            disabled={!contentDraftContent && workflow.stages.content.status !== 'completed'}
            startIcon={<EditNoteIcon />}
          >
            章节初稿
          </Button>
        ) : workflow.currentStage === 'review' ? (
          /* 质量评审阶段：不显示任何按钮 */
          null
        ) : workflow.currentStage === 'iteration' ? (
          /* 迭代优化阶段：只显示"最终成品"按钮 */
          <Button
            variant="outlined"
            onClick={handleOpenFinalProduct}
            disabled={!finalVersionContent && workflow.stages.iteration.status !== 'completed'}
            startIcon={<CheckCircleIcon />}
          >
            最终成品
          </Button>
        ) : (
          /* 其他阶段：显示"重新生成"按钮 */
          <Button
            variant="outlined"
            onClick={handleRegenerateStage}
            disabled={workflow.loading || !isRunning}
            startIcon={<RefreshIcon />}
          >
            重新生成
          </Button>
        )}

        {currentStageIndex !== stages.length - 1 && (
          <Button
            variant="outlined"
            onClick={handleNextStage}
            disabled={workflow.loading || isRunning}
          >
            下一步
          </Button>
        )}
      </Box>

      {/* 开始创作对话框 */}
      <Dialog open={openDialog} onClose={() => setOpenDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            输入创作需求
          </Typography>
          <TextField
            fullWidth
            multiline
            rows={4}
            placeholder="请输入您的创作需求，例如：创作一部关于时空旅行的科幻小说..."
            value={requirement}
            onChange={(e) => setRequirement(e.target.value)}
            sx={{ mb: 2 }}
          />
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
            <Button onClick={() => setOpenDialog(false)}>取消</Button>
            <Button
              variant="contained"
              color="primary"
              onClick={handleStartWorkflow}
              disabled={workflow.loading}
            >
              开始
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 保存章节对话框 */}
      <Dialog open={showSaveDialog} onClose={() => setShowSaveDialog(false)} maxWidth="sm" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            🎉 工作流程已完成！
          </Typography>
          <Alert severity="success" sx={{ mb: 2 }}>
            所有5个阶段已成功完成，现在可以将生成的内容保存为新项目。
          </Alert>
          <TextField
            fullWidth
            label="章节标题（可选）"
            placeholder="例如：冒险开始（留空则自动生成）"
            value={chapterTitle}
            onChange={(e) => setChapterTitle(e.target.value)}
            sx={{ mb: 1 }}
            disabled={workflow.isSavingChapter || isAutoCreatingProject}
            helperText="如果不输入标题，系统会根据章节内容自动生成标题，格式为：第一章 {AI生成的标题}"
          />
          {workflow.saveChapterError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {workflow.saveChapterError}
            </Alert>
          )}
          {workflow.createProjectError && (
            <Alert severity="error" sx={{ mb: 2 }}>
              {workflow.createProjectError}
            </Alert>
          )}
          <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end', mt: 3 }}>
            <Button
              onClick={() => {
                setShowSaveDialog(false)
                setChapterTitle('')
              }}
              disabled={workflow.isSavingChapter || isAutoCreatingProject}
            >
              稍后保存
            </Button>
            <Button
              variant="outlined"
              onClick={handleSaveAsChapter}
              disabled={workflow.isSavingChapter || isAutoCreatingProject}
              startIcon={workflow.isSavingChapter ? <CircularProgress size={20} /> : <SaveIcon />}
            >
              {workflow.isSavingChapter ? '保存中...' : '保存为章节'}
            </Button>
            <Button
              variant="contained"
              color="success"
              onClick={handleAutoCreateProject}
              disabled={workflow.isSavingChapter || isAutoCreatingProject}
              startIcon={isAutoCreatingProject ? <CircularProgress size={20} /> : <SaveIcon />}
            >
              {isAutoCreatingProject ? '创建中...' : '✨ 创建新项目'}
            </Button>
          </Box>
        </Box>
      </Dialog>

      {/* 故事概念对话框 */}
      <Dialog open={showConceptDialog} onClose={handleCloseConceptDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📖 故事概念文档
          </Typography>

          {conceptLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedContent}
                onChange={(e) => setEditedContent(e.target.value)}
                placeholder="故事概念文本内容..."
                sx={{ mb: 2 }}
                disabled={conceptSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseConceptDialog}
                  disabled={conceptSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnly}
                  disabled={conceptSaving}
                  startIcon={conceptSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {conceptSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinue}
                  disabled={conceptSaving}
                  startIcon={conceptSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {conceptSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 情节大纲对话框 */}
      <Dialog open={showStructureDialog} onClose={handleCloseStructureDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            📋 情节大纲文档
          </Typography>

          {structureLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedStructureContent}
                onChange={(e) => setEditedStructureContent(e.target.value)}
                placeholder="情节大纲文本内容..."
                sx={{ mb: 2 }}
                disabled={structureSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseStructureDialog}
                  disabled={structureSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyStructure}
                  disabled={structureSaving}
                  startIcon={structureSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {structureSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueStructure}
                  disabled={structureSaving}
                  startIcon={structureSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {structureSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 章节初稿对话框 */}
      <Dialog open={showContentDialog} onClose={handleCloseContentDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            ✍️ 章节初稿文档
          </Typography>

          {contentLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedContentDraftContent}
                onChange={(e) => setEditedContentDraftContent(e.target.value)}
                placeholder="章节初稿文本内容..."
                sx={{ mb: 2 }}
                disabled={contentSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseContentDialog}
                  disabled={contentSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyContent}
                  disabled={contentSaving}
                  startIcon={contentSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {contentSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueContent}
                  disabled={contentSaving}
                  startIcon={contentSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {contentSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 世界观设定对话框 */}
      <Dialog open={showWorldDialog} onClose={handleCloseWorldDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            🌍 世界观设定文档
          </Typography>

          {worldLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedWorldContent}
                onChange={(e) => setEditedWorldContent(e.target.value)}
                placeholder="世界观设定文本内容..."
                sx={{ mb: 2 }}
                disabled={worldSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseWorldDialog}
                  disabled={worldSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyWorld}
                  disabled={worldSaving}
                  startIcon={worldSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {worldSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueWorld}
                  disabled={worldSaving}
                  startIcon={worldSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {worldSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 人物设定对话框 */}
      <Dialog open={showCharacterDialog} onClose={handleCloseCharacterDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            👥 人物设定文档
          </Typography>

          {characterLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedCharacterContent}
                onChange={(e) => setEditedCharacterContent(e.target.value)}
                placeholder="人物设定文本内容..."
                sx={{ mb: 2 }}
                disabled={characterSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseCharacterDialog}
                  disabled={characterSaving}
                >
                  取消
                </Button>
                <Button
                  variant="outlined"
                  onClick={handleSaveOnlyCharacter}
                  disabled={characterSaving}
                  startIcon={characterSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {characterSaving ? '保存中...' : '仅保存'}
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveAndContinueCharacter}
                  disabled={characterSaving}
                  startIcon={characterSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {characterSaving ? '保存中...' : '保存并继续'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 最终版本对话框 */}
      <Dialog open={showFinalVersionDialog} onClose={handleCloseFinalVersionDialog} maxWidth="md" fullWidth>
        <Box sx={{ p: 3 }}>
          <Typography variant="h6" sx={{ mb: 2 }}>
            ✨ 最终版本文档
          </Typography>

          {finalVersionLoading ? (
            <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', py: 4 }}>
              <CircularProgress />
            </Box>
          ) : (
            <>
              <TextField
                fullWidth
                multiline
                rows={12}
                value={editedFinalVersionContent}
                onChange={(e) => setEditedFinalVersionContent(e.target.value)}
                placeholder="最终版本文本内容..."
                sx={{ mb: 2 }}
                disabled={finalVersionSaving}
              />

              <Box sx={{ display: 'flex', gap: 2, justifyContent: 'flex-end' }}>
                <Button
                  onClick={handleCloseFinalVersionDialog}
                  disabled={finalVersionSaving}
                >
                  取消
                </Button>
                <Button
                  variant="contained"
                  color="primary"
                  onClick={handleSaveOnlyFinalVersion}
                  disabled={finalVersionSaving}
                  startIcon={finalVersionSaving ? <CircularProgress size={20} /> : <SaveIcon />}
                >
                  {finalVersionSaving ? '保存中...' : '保存'}
                </Button>
              </Box>
            </>
          )}
        </Box>
      </Dialog>

      {/* 提示信息 */}
      <Snackbar
        open={snackbarOpen}
        autoHideDuration={4000}
        onClose={() => setSnackbarOpen(false)}
        anchorOrigin={{ vertical: 'top', horizontal: 'right' }}
      >
        <MuiAlert
          onClose={() => setSnackbarOpen(false)}
          severity={snackbarSeverity}
          sx={{ width: '100%' }}
        >
          {snackbarMessage}
        </MuiAlert>
      </Snackbar>
    </Container>
  )
}

