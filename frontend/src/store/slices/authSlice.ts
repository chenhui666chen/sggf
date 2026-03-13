import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'
import { apiClient, extractApiErrorMessage } from '@/services/api'

interface Role {
  id: number
  code: string
  name: string
}

interface User {
  id: number
  username: string
  email: string
  phone?: string | null
  full_name?: string | null
  avatar_url?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  roles?: Role[]
}

interface AuthSuccessPayload {
  access_token: string
  token_type: string
  user: User
}

interface RegisterPayload {
  username: string
  email: string
  password: string
  phone?: string
  full_name?: string
}

interface LoginPayload {
  username: string
  password: string
}

interface AuthState {
  user: User | null
  token: string | null
  isLoading: boolean
  error: string | null
  isAuthenticated: boolean
}

const persistAuth = (payload: AuthSuccessPayload) => {
  localStorage.setItem('access_token', payload.access_token)
  localStorage.setItem('user', JSON.stringify(payload.user))
}

const clearPersistedAuth = () => {
  localStorage.removeItem('access_token')
  localStorage.removeItem('user')
}

const getRejectedMessage = (payload: unknown, fallback: string) =>
  typeof payload === 'string' && payload.trim() ? payload : fallback

const initialState: AuthState = {
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  token: localStorage.getItem('access_token'),
  isLoading: false,
  error: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
}

export const register = createAsyncThunk<AuthSuccessPayload, RegisterPayload, { rejectValue: string }>(
  'auth/register',
  async (data, { rejectWithValue }) => {
    try {
      const response = await apiClient.register(data)
      return response.data
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '注册失败'))
    }
  },
)

export const login = createAsyncThunk<AuthSuccessPayload, LoginPayload, { rejectValue: string }>(
  'auth/login',
  async (data, { rejectWithValue }) => {
    try {
      const response = await apiClient.login(data)
      return response.data
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '登录失败'))
    }
  },
)

export const alipayLogin = createAsyncThunk<AuthSuccessPayload, string, { rejectValue: string }>(
  'auth/alipayLogin',
  async (code, { rejectWithValue }) => {
    try {
      const response = await apiClient.alipayCallback(code)
      return response.data
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '支付宝登录失败'))
    }
  },
)

export const wechatLogin = createAsyncThunk<AuthSuccessPayload, string, { rejectValue: string }>(
  'auth/wechatLogin',
  async (code, { rejectWithValue }) => {
    try {
      const response = await apiClient.wechatCallback(code)
      return response.data
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '微信登录失败'))
    }
  },
)

export const getCurrentUser = createAsyncThunk<User, void, { rejectValue: string }>(
  'auth/getCurrentUser',
  async (_, { rejectWithValue }) => {
    try {
      const response = await apiClient.getCurrentUser()
      return response.data
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '获取当前用户失败'))
    }
  },
)

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    logout: (state) => {
      state.user = null
      state.token = null
      state.isAuthenticated = false
      state.error = null
      clearPersistedAuth()
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
        persistAuth(action.payload)
      })
      .addCase(register.rejected, (state, action) => {
        state.isLoading = false
        state.error = getRejectedMessage(action.payload, '注册失败')
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
        persistAuth(action.payload)
      })
      .addCase(login.rejected, (state, action) => {
        state.isLoading = false
        state.error = getRejectedMessage(action.payload, '登录失败')
      })
      .addCase(getCurrentUser.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(getCurrentUser.fulfilled, (state, action) => {
        state.isLoading = false
        state.user = action.payload
        state.isAuthenticated = true
        localStorage.setItem('user', JSON.stringify(action.payload))
      })
      .addCase(getCurrentUser.rejected, (state, action) => {
        state.isLoading = false
        state.user = null
        state.token = null
        state.isAuthenticated = false
        state.error = getRejectedMessage(action.payload, '登录状态已失效')
        clearPersistedAuth()
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
        persistAuth(action.payload)
      })
      .addCase(alipayLogin.rejected, (state, action) => {
        state.isLoading = false
        state.error = getRejectedMessage(action.payload, '支付宝登录失败')
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
        persistAuth(action.payload)
      })
      .addCase(wechatLogin.rejected, (state, action) => {
        state.isLoading = false
        state.error = getRejectedMessage(action.payload, '微信登录失败')
      })
  },
})

export const { logout, clearError } = authSlice.actions
export default authSlice.reducer
