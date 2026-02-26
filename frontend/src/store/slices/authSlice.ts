import { createSlice, createAsyncThunk } from '@reduxjs/toolkit'
import { apiClient } from '@/services/api'

interface User {
  id: number
  username: string
  email: string
  full_name?: string
  avatar_url?: string
  is_active: boolean
  created_at: string
  updated_at: string
}

interface AuthState {
  user: User | null
  token: string | null
  isLoading: boolean
  error: string | null
  isAuthenticated: boolean
}

const initialState: AuthState = {
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  token: localStorage.getItem('access_token'),
  isLoading: false,
  error: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
}

export const register = createAsyncThunk(
  'auth/register',
  async (data: { username: string; email: string; password: string; full_name?: string }) => {
    const response = await apiClient.register(data)
    return response.data
  }
)

export const login = createAsyncThunk(
  'auth/login',
  async (data: { username: string; password: string }) => {
    const response = await apiClient.login(data)
    return response.data
  }
)

export const alipayLogin = createAsyncThunk(
  'auth/alipayLogin',
  async (code: string) => {
    const response = await apiClient.alipayCallback(code)
    return response.data
  }
)

export const wechatLogin = createAsyncThunk(
  'auth/wechatLogin',
  async (code: string) => {
    const response = await apiClient.wechatCallback(code)
    return response.data
  }
)

export const getCurrentUser = createAsyncThunk(
  'auth/getCurrentUser',
  async () => {
    const response = await apiClient.getCurrentUser()
    return response.data
  }
)

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    logout: (state) => {
      state.user = null
      state.token = null
      state.isAuthenticated = false
      localStorage.removeItem('access_token')
      localStorage.removeItem('user')
    },
    clearError: (state) => {
      state.error = null
    },
  },
  extraReducers: (builder) => {
    builder
      .addCase(register.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(register.fulfilled, (state, action) => {
        state.isLoading = false
        state.user = action.payload.user
        state.token = action.payload.access_token
        state.isAuthenticated = true
        localStorage.setItem('access_token', action.payload.access_token)
        localStorage.setItem('user', JSON.stringify(action.payload.user))
      })
      .addCase(register.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Registration failed'
      })
      .addCase(login.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(login.fulfilled, (state, action) => {
        state.isLoading = false
        state.user = action.payload.user
        state.token = action.payload.access_token
        state.isAuthenticated = true
        localStorage.setItem('access_token', action.payload.access_token)
        localStorage.setItem('user', JSON.stringify(action.payload.user))
      })
      .addCase(login.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Login failed'
      })
      .addCase(getCurrentUser.fulfilled, (state, action) => {
        state.user = action.payload
        localStorage.setItem('user', JSON.stringify(action.payload))
      })
      .addCase(alipayLogin.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(alipayLogin.fulfilled, (state, action) => {
        state.isLoading = false
        state.user = action.payload.user
        state.token = action.payload.access_token
        state.isAuthenticated = true
        localStorage.setItem('access_token', action.payload.access_token)
        localStorage.setItem('user', JSON.stringify(action.payload.user))
      })
      .addCase(alipayLogin.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'Alipay login failed'
      })
      .addCase(wechatLogin.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(wechatLogin.fulfilled, (state, action) => {
        state.isLoading = false
        state.user = action.payload.user
        state.token = action.payload.access_token
        state.isAuthenticated = true
        localStorage.setItem('access_token', action.payload.access_token)
        localStorage.setItem('user', JSON.stringify(action.payload.user))
      })
      .addCase(wechatLogin.rejected, (state, action) => {
        state.isLoading = false
        state.error = action.error.message || 'WeChat login failed'
      })
  },
})

export const { logout, clearError } = authSlice.actions
export default authSlice.reducer

