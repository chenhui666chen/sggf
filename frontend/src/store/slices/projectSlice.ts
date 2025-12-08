import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

interface Project {
  id: number
  user_id: number
  title: string
  description?: string
  genre?: string
  
  // 🆕 题材与篇幅规划字段
  sub_genre?: string
  planned_length_type?: string  // short/mid/long/epic
  planned_chapters_min?: number
  planned_chapters_max?: number
  user_outline_plan?: string
  
  status: string
  word_count: number
  created_at: string
  updated_at: string
}

interface ProjectState {
  projects: Project[]
  currentProject: Project | null
  isLoading: boolean
  error: string | null
}

const initialState: ProjectState = {
  projects: [],
  currentProject: null,
  isLoading: false,
  error: null,
}

export const fetchProjects = createAsyncThunk(
  'project/fetchProjects',
  async () => {
    const response = await apiClient.getProjects()
    return response.data
  }
)

export const createProject = createAsyncThunk(
  'project/createProject',
  async (data: { 
    title: string; 
    description?: string; 
    genre?: string;
    sub_genre?: string;
    planned_length_type?: string;
    planned_chapters_min?: number;
    planned_chapters_max?: number;
    user_outline_plan?: string;
  }) => {
    const response = await apiClient.createProject(data)
    return response.data
  }
)

export const fetchProject = createAsyncThunk(
  'project/fetchProject',
  async (projectId: number) => {
    const response = await apiClient.getProject(projectId)
    return response.data
  }
)

export const updateProject = createAsyncThunk(
  'project/updateProject',
  async ({ projectId, data }: { projectId: number; data: any }) => {
    const response = await apiClient.updateProject(projectId, data)
    return response.data
  }
)

export const deleteProject = createAsyncThunk(
  'project/deleteProject',
  async (projectId: number) => {
    await apiClient.deleteProject(projectId)
    return projectId
  }
)

const projectSlice = createSlice({
  name: 'project',
  initialState,
  reducers: {
    clearCurrentProject: (state) => {
      state.currentProject = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchProjects.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(fetchProjects.fulfilled, (state, action) => {
        state.isLoading = false
        state.projects = action.payload
      })
      .addCase(fetchProjects.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Failed to fetch projects'
      })
      .addCase(createProject.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(createProject.fulfilled, (state, action) => {
        state.isLoading = false
        state.projects.push(action.payload)
      })
      .addCase(createProject.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Failed to create project'
      })
      .addCase(fetchProject.fulfilled, (state, action) => {
        state.currentProject = action.payload
      })
      .addCase(updateProject.fulfilled, (state, action) => {
        const index = state.projects.findIndex((p) => p.id === action.payload.id)
        if (index !== -1) {
          state.projects[index] = action.payload
        }
        if (state.currentProject?.id === action.payload.id) {
          state.currentProject = action.payload
        }
      })
      .addCase(deleteProject.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(deleteProject.fulfilled, (state, action) => {
        state.isLoading = false
        state.projects = state.projects.filter((p) => p.id !== action.payload)
      })
      .addCase(deleteProject.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Delete failed'
      })
  },
})

export const { clearCurrentProject } = projectSlice.actions
export default projectSlice.reducer

