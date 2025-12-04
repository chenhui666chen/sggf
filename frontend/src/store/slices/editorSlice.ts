import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

interface Chapter {
  id: number
  project_id: number
  chapter_number: number
  title: string
  content?: string
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

interface EditorState {
  chapters: Chapter[]
  currentChapter: Chapter | null
  content: string
  isDirty: boolean
  isSaving: boolean
  isLoading: boolean
  error: string | null
}

const initialState: EditorState = {
  chapters: [],
  currentChapter: null,
  content: '',
  isDirty: false,
  isSaving: false,
  isLoading: false,
  error: null,
}

export const fetchChapters = createAsyncThunk(
  'editor/fetchChapters',
  async (projectId: number) => {
    const response = await apiClient.getChapters(projectId)
    return response.data
  }
)

export const fetchChapter = createAsyncThunk(
  'editor/fetchChapter',
  async ({ chapterId, projectId }: { chapterId: number; projectId: number }) => {
    const response = await apiClient.getChapter(chapterId)
    // 验证章节属于正确的项目
    if (response.data.project_id !== projectId) {
      throw new Error('Chapter does not belong to this project')
    }
    return response.data
  }
)

export const createChapter = createAsyncThunk(
  'editor/createChapter',
  async ({ projectId, data }: { projectId: number; data: any }) => {
    const response = await apiClient.createChapter(projectId, data)
    return response.data
  }
)

export const updateChapter = createAsyncThunk(
  'editor/updateChapter',
  async ({ chapterId, data }: { chapterId: number; data: any }) => {
    const response = await apiClient.updateChapter(chapterId, data)
    return response.data
  }
)

export const autoSaveChapter = createAsyncThunk(
  'editor/autoSaveChapter',
  async ({ chapterId, data }: { chapterId: number; data: any }) => {
    const response = await apiClient.autoSaveChapter(chapterId, data)
    return response.data.chapter
  }
)

export const deleteChapter = createAsyncThunk(
  'editor/deleteChapter',
  async (chapterId: number) => {
    await apiClient.deleteChapter(chapterId)
    return chapterId
  }
)

const editorSlice = createSlice({
  name: 'editor',
  initialState,
  reducers: {
    setContent: (state, action) => {
      state.content = action.payload
      state.isDirty = true
    },
    clearDirty: (state) => {
      state.isDirty = false
    },
    clearError: (state) => {
      state.error = null
    },
    // 清除所有编辑器状态（用于项目切换）
    clearEditorState: (state) => {
      state.chapters = []
      state.currentChapter = null
      state.content = ''
      state.isDirty = false
      state.isSaving = false
      state.isLoading = false
      state.error = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchChapters.pending, (state) => {
        state.isLoading = true
      })
      .addCase(fetchChapters.fulfilled, (state, action) => {
        state.chapters = action.payload
        state.isLoading = false
      })
      .addCase(fetchChapters.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Failed to fetch chapters'
      })
      .addCase(fetchChapter.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(fetchChapter.fulfilled, (state, action) => {
        state.isLoading = false
        state.currentChapter = action.payload
        state.content = action.payload.content || ''
        state.isDirty = false
      })
      .addCase(fetchChapter.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Failed to fetch chapter'
        state.currentChapter = null
        state.content = ''
        state.isDirty = false
      })
      .addCase(createChapter.fulfilled, (state, action) => {
        state.chapters.push(action.payload)
        state.currentChapter = action.payload
        state.content = action.payload.content || ''
      })
      .addCase(updateChapter.pending, (state) => {
        state.isSaving = true
      })
      .addCase(updateChapter.fulfilled, (state, action) => {
        state.isSaving = false
        const index = state.chapters.findIndex((c) => c.id === action.payload.id)
        if (index !== -1) {
          state.chapters[index] = action.payload
        }
        if (state.currentChapter?.id === action.payload.id) {
          state.currentChapter = action.payload
        }
        state.isDirty = false
      })
      .addCase(updateChapter.rejected, (state, action) => {
        state.isSaving = false
        state.error = action.error.message || 'Update failed'
      })
      .addCase(autoSaveChapter.pending, (state) => {
        state.isSaving = true
      })
      .addCase(autoSaveChapter.fulfilled, (state, action) => {
        state.isSaving = false
        state.isDirty = false
        if (state.currentChapter?.id === action.payload.id) {
          state.currentChapter = action.payload
        }
      })
      .addCase(autoSaveChapter.rejected, (state, action) => {
        state.isSaving = false
        state.error = action.error.message || 'Auto-save failed'
      })
      .addCase(deleteChapter.fulfilled, (state, action) => {
        state.chapters = state.chapters.filter((c) => c.id !== action.payload)
        if (state.currentChapter?.id === action.payload) {
          state.currentChapter = null
          state.content = ''
        }
      })
  },
})

export const { setContent, clearDirty, clearError, clearEditorState } = editorSlice.actions
export default editorSlice.reducer

