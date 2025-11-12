import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

interface Review {
  id: number
  chapter_id: number
  overall_score: number
  story_score: number
  character_score: number
  language_score: number
  structure_score: number
  innovation_score: number
  feedback?: string
  suggestions?: string
  strengths?: string
  created_at: string
  updated_at: string
}

interface ReviewState {
  reviews: { [key: number]: Review }
  isLoading: boolean
  error: string | null
}

const initialState: ReviewState = {
  reviews: {},
  isLoading: false,
  error: null,
}

export const fetchReview = createAsyncThunk(
  'review/fetch',
  async (chapterId: number) => {
    const response = await apiClient.getReview(chapterId)
    return response.data
  }
)

export const createReview = createAsyncThunk(
  'review/create',
  async ({ chapterId, data }: { chapterId: number; data: any }) => {
    const response = await apiClient.createReview(chapterId, data)
    return response.data
  }
)

export const updateReview = createAsyncThunk(
  'review/update',
  async ({ chapterId, data }: { chapterId: number; data: any }) => {
    const response = await apiClient.updateReview(chapterId, data)
    return response.data
  }
)

export const deleteReview = createAsyncThunk(
  'review/delete',
  async (chapterId: number) => {
    await apiClient.deleteReview(chapterId)
    return chapterId
  }
)

const reviewSlice = createSlice({
  name: 'review',
  initialState,
  reducers: {
    clearError: (state) => {
      state.error = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(fetchReview.pending, (state) => {
        state.isLoading = true
      })
      .addCase(fetchReview.fulfilled, (state, action) => {
        state.isLoading = false
        state.reviews[action.payload.chapter_id] = action.payload
      })
      .addCase(fetchReview.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Failed to fetch review'
      })
      .addCase(createReview.fulfilled, (state, action) => {
        state.reviews[action.payload.chapter_id] = action.payload
      })
      .addCase(updateReview.fulfilled, (state, action) => {
        state.reviews[action.payload.chapter_id] = action.payload
      })
      .addCase(deleteReview.fulfilled, (state, action) => {
        delete state.reviews[action.payload]
      })
  },
})

export const { clearError } = reviewSlice.actions
export default reviewSlice.reducer

