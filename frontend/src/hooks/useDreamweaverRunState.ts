import type { Project, Chapter, RunResult, LibraryPayload } from '../types/dreamweaver'

export type DreamWeaverStage =
  | 'init'
  | 'script'
  | 'waiting_script_approval'
  | 'storyboard'
  | 'asset_library'
  | 'waiting_approval'
  | 'keyframes'
  | 'midframes'
  | 'video'
  | 'waiting_video_confirmation'
  | 'edit'
  | 'review'
  | 'done'
  | 'rework'
  | 'failed'

export type DreamWeaverState =
  | 'PENDING'
  | 'RUNNING'
  | 'PAUSED'
  | 'DONE'
  | 'FAILED'

export interface DreamWeaverRunState {
  projects: Project[]
  chapters: Chapter[]
  selectedProjectId: number | null
  selectedChapterIds: number[]

  config: {
    highQuality: boolean
    qcAllowFail: boolean
    smartTuning: boolean
    videoRequireConfirmation: boolean
    promptReviewRequired: boolean
    abVariant: string
    stylePreset: string
    imageRatio: string
    imageResolution: string
  }

  loading: {
    chapters: boolean
    running: boolean
    resume: boolean
    restart: boolean
    script: boolean
    promptReview: boolean
    promptEdit: boolean
    library: boolean
  }

  task: {
    id: string | null
    runId: string | null
    status: string | null
    queue: string | null
    progress: number
    state: string | null
    stage: string | null
    artifacts: Record<string, unknown> | null
  }

  result: RunResult | null

  script: {
    text: string
    savedText: string
    approved: boolean
    requiresReview: boolean
    entities: Record<string, unknown> | null
    generation: { mode?: string; model?: string | null; error?: string | null } | null
    error: string | null
  }

  promptReview: {
    loading: boolean
    error: string | null
    showAll: boolean
    expanded: Record<string, boolean>
    editOpen: boolean
    editShot: unknown | null
    editHead: string
    editTail: string
    editVideo: string
    editSaving: boolean
    editError: string | null
  }

  library: {
    data: LibraryPayload | null
    loading: boolean
    error: string | null
    previews: Record<number, string>
    aspectRatios: Record<number, string>
    regen: {
      open: boolean
      role: string
      title: string
      prompt: string
      preferImageEdit: boolean
      stylePreset: string
      imageRatio: string
      submitting: boolean
      suggesting: boolean
      suggestError: string | null
      error: string | null
    }
    characterViews: {
      open: boolean
      entityId: number | null
    }
    collectStates: Record<number, { loading: boolean; feedback: { type: 'success' | 'error'; text: string } | null }>
  }

  video: {
    waitingApproval: boolean
    actionError: string | null
    confirmingShotId: string | null
  }

  restart: {
    anchorEl: HTMLElement | null
  }

  history: {
    open: boolean
    loading: boolean
    error: string | null
    runs: Array<{
      id: number
      run_id: string
      status: string
      state?: string | null
      stage?: string | null
      progress?: number | null
      error_type?: string | null
      error_message?: string | null
      created_at?: string | null
      updated_at?: string | null
    }>
    statusFilters: string[]
  }
}

export const initialDreamWeaverRunState: DreamWeaverRunState = {
  projects: [],
  chapters: [],
  selectedProjectId: null,
  selectedChapterIds: [],

  config: {
    highQuality: true,
    qcAllowFail: false,
    smartTuning: true,
    videoRequireConfirmation: true,
    promptReviewRequired: true,
    abVariant: '',
    stylePreset: 'cinematic_realistic',
    imageRatio: '16:9',
    imageResolution: '720p',
  },

  loading: {
    chapters: false,
    running: false,
    resume: false,
    restart: false,
    script: false,
    promptReview: false,
    promptEdit: false,
    library: false,
  },

  task: {
    id: null,
    runId: null,
    status: null,
    queue: null,
    progress: 0,
    state: null,
    stage: null,
    artifacts: null,
  },

  result: null,

  script: {
    text: '',
    savedText: '',
    approved: false,
    requiresReview: true,
    entities: null,
    generation: null,
    error: null,
  },

  promptReview: {
    loading: false,
    error: null,
    showAll: false,
    expanded: {},
    editOpen: false,
    editShot: null,
    editHead: '',
    editTail: '',
    editVideo: '',
    editSaving: false,
    editError: null,
  },

  library: {
    data: null,
    loading: false,
    error: null,
    previews: {},
    aspectRatios: {},
    regen: {
      open: false,
      role: '',
      title: '',
      prompt: '',
      preferImageEdit: false,
      stylePreset: 'cinematic_realistic',
      imageRatio: '16:9',
      submitting: false,
      suggesting: false,
      suggestError: null,
      error: null,
    },
    characterViews: {
      open: false,
      entityId: null,
    },
    collectStates: {},
  },

  video: {
    waitingApproval: false,
    actionError: null,
    confirmingShotId: null,
  },

  restart: {
    anchorEl: null,
  },

  history: {
    open: false,
    loading: false,
    error: null,
    runs: [],
    statusFilters: [],
  },
}

export type DreamWeaverRunAction =
  | { type: 'SET_PROJECTS'; payload: Project[] }
  | { type: 'SET_CHAPTERS'; payload: Chapter[] }
  | { type: 'SET_SELECTED_PROJECT'; payload: number | null }
  | { type: 'SET_SELECTED_CHAPTERS'; payload: number[] }
  | { type: 'SET_CONFIG'; payload: Partial<DreamWeaverRunState['config']> }
  | { type: 'SET_LOADING'; payload: Partial<DreamWeaverRunState['loading']> }
  | { type: 'SET_TASK'; payload: Partial<DreamWeaverRunState['task']> }
  | { type: 'SET_RESULT'; payload: RunResult | null }
  | { type: 'SET_SCRIPT'; payload: Partial<DreamWeaverRunState['script']> }
  | { type: 'SET_PROMPT_REVIEW'; payload: Partial<DreamWeaverRunState['promptReview']> }
  | { type: 'SET_LIBRARY'; payload: Partial<DreamWeaverRunState['library']> }
  | { type: 'SET_VIDEO'; payload: Partial<DreamWeaverRunState['video']> }
  | { type: 'SET_RESTART'; payload: Partial<DreamWeaverRunState['restart']> }
  | { type: 'SET_HISTORY'; payload: Partial<DreamWeaverRunState['history']> }
  | { type: 'RESET' }

export function dreamWeaverRunReducer(
  state: DreamWeaverRunState,
  action: DreamWeaverRunAction
): DreamWeaverRunState {
  switch (action.type) {
    case 'SET_PROJECTS':
      return { ...state, projects: action.payload }

    case 'SET_CHAPTERS':
      return { ...state, chapters: action.payload }

    case 'SET_SELECTED_PROJECT':
      return { ...state, selectedProjectId: action.payload }

    case 'SET_SELECTED_CHAPTERS':
      return { ...state, selectedChapterIds: action.payload }

    case 'SET_CONFIG':
      return { ...state, config: { ...state.config, ...action.payload } }

    case 'SET_LOADING':
      return { ...state, loading: { ...state.loading, ...action.payload } }

    case 'SET_TASK':
      return { ...state, task: { ...state.task, ...action.payload } }

    case 'SET_RESULT':
      return { ...state, result: action.payload }

    case 'SET_SCRIPT':
      return { ...state, script: { ...state.script, ...action.payload } }

    case 'SET_PROMPT_REVIEW':
      return { ...state, promptReview: { ...state.promptReview, ...action.payload } }

    case 'SET_LIBRARY':
      return { ...state, library: { ...state.library, ...action.payload } }

    case 'SET_VIDEO':
      return { ...state, video: { ...state.video, ...action.payload } }

    case 'SET_RESTART':
      return { ...state, restart: { ...state.restart, ...action.payload } }

    case 'SET_HISTORY':
      return { ...state, history: { ...state.history, ...action.payload } }

    case 'RESET':
      return initialDreamWeaverRunState

    default:
      return state
  }
}
