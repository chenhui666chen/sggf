import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

interface KnowledgeBaseItem {
  id: number
  project_id: number
  type: 'world' | 'character' | 'plot'
  name: string
  content: string
  created_at: string
  updated_at: string
}

interface KnowledgeBaseState {
  worldSettings: KnowledgeBaseItem[]
  characters: KnowledgeBaseItem[]
  plotOutline: KnowledgeBaseItem[]
  isLoading: boolean
  error: string | null
}

const initialState: KnowledgeBaseState = {
  worldSettings: [],
  characters: [],
  plotOutline: [],
  isLoading: false,
  error: null,
}

export const fetchKnowledgeBase = createAsyncThunk(
  'knowledgeBase/fetch',
  async (projectId: number) => {
    const response = await apiClient.getKnowledgeBase(projectId)
    return response.data
  }
)

export const addWorldSetting = createAsyncThunk(
  'knowledgeBase/addWorldSetting',
  async ({ projectId, data }: { projectId: number; data: any }) => {
    const response = await apiClient.addWorldSetting(projectId, data)
    return response.data
  }
)

export const addCharacter = createAsyncThunk(
  'knowledgeBase/addCharacter',
  async ({ projectId, data }: { projectId: number; data: any }) => {
    const response = await apiClient.addCharacter(projectId, data)
    return response.data
  }
)

export const addPlotOutline = createAsyncThunk(
  'knowledgeBase/addPlotOutline',
  async ({ projectId, data }: { projectId: number; data: any }) => {
    const response = await apiClient.addPlotOutline(projectId, data)
    return response.data
  }
)

export const updateKnowledgeBase = createAsyncThunk(
  'knowledgeBase/update',
  async ({ projectId, kbId, data }: { projectId: number; kbId: number; data: any }) => {
    const response = await apiClient.updateKnowledgeBase(projectId, kbId, data)
    return response.data
  }
)

export const deleteKnowledgeBase = createAsyncThunk(
  'knowledgeBase/delete',
  async ({ projectId, kbId }: { projectId: number; kbId: number }) => {
    await apiClient.deleteKnowledgeBase(projectId, kbId)
    return kbId
  }
)

const knowledgeBaseSlice = createSlice({
  name: 'knowledgeBase',
  initialState,
  reducers: {
    clearError: (state) => {
      state.error = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchKnowledgeBase.pending, (state) => {
        state.isLoading = true
      })
      .addCase(fetchKnowledgeBase.fulfilled, (state, action) => {
        state.isLoading = false
        state.worldSettings = action.payload.world_settings || []
        state.characters = action.payload.characters || []
        state.plotOutline = action.payload.plot_outline || []
      })
      .addCase(fetchKnowledgeBase.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Failed to fetch knowledge base'
      })
      .addCase(addWorldSetting.fulfilled, (state, action) => {
        state.worldSettings.push(action.payload)
      })
      .addCase(addCharacter.fulfilled, (state, action) => {
        state.characters.push(action.payload)
      })
      .addCase(addPlotOutline.fulfilled, (state, action) => {
        state.plotOutline.push(action.payload)
      })
      .addCase(updateKnowledgeBase.fulfilled, (state, action) => {
        const item = action.payload
        if (item.type === 'world') {
          const index = state.worldSettings.findIndex((i) => i.id === item.id)
          if (index !== -1) state.worldSettings[index] = item
        } else if (item.type === 'character') {
          const index = state.characters.findIndex((i) => i.id === item.id)
          if (index !== -1) state.characters[index] = item
        } else if (item.type === 'plot') {
          const index = state.plotOutline.findIndex((i) => i.id === item.id)
          if (index !== -1) state.plotOutline[index] = item
        }
      })
      .addCase(deleteKnowledgeBase.fulfilled, (state, action) => {
        state.worldSettings = state.worldSettings.filter((i) => i.id !== action.payload)
        state.characters = state.characters.filter((i) => i.id !== action.payload)
        state.plotOutline = state.plotOutline.filter((i) => i.id !== action.payload)
      })
  },
})

export const { clearError } = knowledgeBaseSlice.actions
export default knowledgeBaseSlice.reducer

