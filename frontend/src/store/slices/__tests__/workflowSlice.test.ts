import { describe, expect, it } from 'vitest'
import workflowReducer, {
  resetWorkflow,
  setCurrentStage,
  setProjectId,
  startGenerateNextChapter,
  updateAgentStatus,
  updateStageStatus,
} from '../workflowSlice'

describe('workflowSlice project isolation', () => {
  it('clears stage, agent, and generate-next-chapter state when switching projects', () => {
    let state = workflowReducer(undefined, setProjectId(1))

    state = workflowReducer(state, setCurrentStage('structure'))
    state = workflowReducer(state, updateStageStatus({ stage: 'structure', status: 'active' }))
    state = workflowReducer(
      state,
      updateAgentStatus({
        stage: 'structure',
        agentId: 'plot_architect',
        status: 'working',
        progress: 64,
        message: 'planning chapter',
      }),
    )
    state = workflowReducer(
      state,
      startGenerateNextChapter({ taskId: 'old-task', chapterNumber: 12 }),
    )

    state = workflowReducer(state, setProjectId(2))

    expect(state.projectId).toBe(2)
    expect(state.currentStage).toBe('concept')
    expect(state.stages.structure.status).toBe('pending')
    expect(state.stages.structure.progress).toBe(0)
    expect(state.stages.structure.agents[0]).toMatchObject({
      status: 'idle',
      progress: 0,
      message: '',
    })
    expect(state.generateNextChapter).toEqual({
      taskId: null,
      chapterNumber: null,
      progress: 0,
      currentStep: 0,
      streamContent: '',
      isRunning: false,
    })
  })

  it('clears generate-next-chapter state when resetting workflow state', () => {
    let state = workflowReducer(undefined, setProjectId(1))
    state = workflowReducer(
      state,
      startGenerateNextChapter({ taskId: 'running-task', chapterNumber: 3 }),
    )

    state = workflowReducer(state, resetWorkflow())

    expect(state.generateNextChapter.taskId).toBeNull()
    expect(state.generateNextChapter.isRunning).toBe(false)
    expect(state.generateNextChapter.streamContent).toBe('')
  })
})
