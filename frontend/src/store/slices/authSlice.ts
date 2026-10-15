import { createAsyncThunk, createSlice } from '@reduxjs/toolkit'
import type { ConsentAcceptance } from '@/constants/consent'
import { apiClient, extractApiErrorMessage, type VerificationCodeResponse } from '@/services/api'

interface Role {
  id: number
  code: string
  name: string
}

interface User {
  id: number
  username: string
  // P1-3.8：OAuth 用户可不绑定邮箱，email 允许为空；email_verified 由后端 /me 回传
  email: string | null
  email_verified?: boolean
  phone?: string | null
  full_name?: string | null
  avatar_url?: string | null
  is_active: boolean
  created_at: string
  updated_at: string
  roles?: Role[]
  // P2-4.2/4.6：由后端 /me 派生回传（openid 永不下发）
  has_password?: boolean
  alipay_bound?: boolean
  wechat_bound?: boolean
}

interface AuthSuccessPayload {
  // P2-4.5 收尾：access/refresh 仅入 httpOnly cookie，body 不再返回 token
  user: User
}

// checking：启动恢复未落定，保护页既不该放行也不该重定向
// ready：/me 已返回（成功恢复或确认匿名），可以按 isAuthenticated 判定
export type SessionStatus = 'checking' | 'ready'

interface RegisterPayload {
  username: string
  email: string
  password: string
  phone?: string
  full_name?: string
  // P1-3.8：两步注册第二步需携带邮箱验证码
  code: string
  // 短信抢占：手机号已被其他账号绑定时携带短信验证码（未占用不传）
  phone_code?: string
  // P2-5.2：用户勾选的同意项（未勾选的项不传）
  consent?: ConsentAcceptance
}

interface LoginPayload {
  username: string
  password: string
}

interface AuthState {
  user: User | null
  isLoading: boolean
  error: string | null
  isAuthenticated: boolean
  // P2-4.5：会话由 httpOnly cookie 承载，isAuthenticated 只能靠启动时的 getCurrentUser 恢复。
  // 保护页必须等这次恢复落定再判定，否则硬刷新会把已登录用户弹到登录页。
  sessionStatus: SessionStatus
  // P1-3.2：OAuth 首次登录返回注册票据时暂存（不落持久存储），等待用户确认建号；不置登录态
  pendingRegistrationTicket: string | null
}

// P1-3.6：收窄 localStorage 中的用户信息——email/phone 属 PII，不落持久存储；
// 页面加载后由 App.tsx 的 getCurrentUser 从后端补全完整用户信息
const persistUser = (user: User) => {
  const persisted = {
    id: user.id,
    username: user.username,
    full_name: user.full_name,
    avatar_url: user.avatar_url,
    is_active: user.is_active,
    created_at: user.created_at,
    updated_at: user.updated_at,
    roles: user.roles,
  }
  localStorage.setItem('user', JSON.stringify(persisted))
}

const persistAuth = (payload: AuthSuccessPayload) => {
  // P2-4.5：access/refresh 只经 httpOnly cookie 传输，前端不再持久化任何令牌；
  // 顺带清理旧版本遗留的 localStorage token（登录成功即视为已迁移）
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  // 仅保留非 PII 的 user 快照用于首屏展示，完整信息由 /me 补全
  persistUser(payload.user)
}

const clearPersistedAuth = () => {
  localStorage.removeItem('access_token')
  localStorage.removeItem('refresh_token')
  localStorage.removeItem('user')
}

const getRejectedMessage = (payload: unknown, fallback: string) =>
  typeof payload === 'string' && payload.trim() ? payload : fallback

// P2-4.5：会话身份由 httpOnly cookie 决定，前端重启后 isAuthenticated 一律 false，
// 由 App.tsx 启动时 getCurrentUser()（cookie 自动携带）恢复登录态
const readPersistedAuth = (): Pick<AuthState, 'user' | 'isAuthenticated'> => {
  const rawUser = localStorage.getItem('user')

  if (!rawUser) {
    return {
      user: null,
      isAuthenticated: false,
    }
  }

  try {
    return {
      user: JSON.parse(rawUser) as User | null,
      isAuthenticated: false,
    }
  } catch {
    clearPersistedAuth()
    return {
      user: null,
      isAuthenticated: false,
    }
  }
}

const persistedAuth = readPersistedAuth()

const initialState: AuthState = {
  user: persistedAuth.user,
  isLoading: false,
  error: null,
  isAuthenticated: persistedAuth.isAuthenticated,
  sessionStatus: 'checking',
  pendingRegistrationTicket: null,
}

export const sendRegisterCode = createAsyncThunk<VerificationCodeResponse, string, { rejectValue: string }>(
  'auth/sendRegisterCode',
  async (email, { rejectWithValue }) => {
    try {
      const response = await apiClient.registerSendCode(email)
      return response.data
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '验证码发送失败'))
    }
  },
)

export const register = createAsyncThunk<AuthSuccessPayload, RegisterPayload, { rejectValue: string }>(
  'auth/register',
  async (data, { rejectWithValue }) => {
    try {
      const response = await apiClient.registerConfirm(data)
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

interface OAuthLoginPayload {
  code: string
  state: string
}

// P1-3.2 + P2-4.2：OAuth 回调联合响应的归一化结果——
//   ok=带 token；new_user=带注册票据等待确认；bind_pending=带绑定票据（登录态 /auth/bind/confirm 消费）
interface OAuthLoginResult {
  status: 'ok' | 'new_user' | 'bind_pending'
  // P2-4.5 收尾：ok 分支 user 由 body 返回，登录态由 httpOnly cookie 承载
  user: User | null
  registrationTicket: string | null
  bindTicket: string | null
}

const normalizeOAuthCallbackResult = (
  data: Awaited<ReturnType<typeof apiClient.alipayCallback>>['data'],
): OAuthLoginResult => {
  if (data.status === 'new_user') {
    return { status: 'new_user', user: null, registrationTicket: data.registration_ticket ?? null, bindTicket: null }
  }
  if (data.status === 'bind_pending') {
    return { status: 'bind_pending', user: null, registrationTicket: null, bindTicket: data.bind_ticket ?? null }
  }
  return { status: 'ok', user: (data.user ?? null) as User | null, registrationTicket: null, bindTicket: null }
}

export const alipayLogin = createAsyncThunk<OAuthLoginResult, OAuthLoginPayload, { rejectValue: string }>(
  'auth/alipayLogin',
  async ({ code, state }, { rejectWithValue }) => {
    try {
      const response = await apiClient.alipayCallback(code, state)
      return normalizeOAuthCallbackResult(response.data)
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '支付宝登录失败'))
    }
  },
)

export const wechatLogin = createAsyncThunk<OAuthLoginResult, OAuthLoginPayload, { rejectValue: string }>(
  'auth/wechatLogin',
  async ({ code, state }, { rejectWithValue }) => {
    try {
      const response = await apiClient.wechatCallback(code, state)
      return normalizeOAuthCallbackResult(response.data)
    } catch (error) {
      return rejectWithValue(await extractApiErrorMessage(error, '微信登录失败'))
    }
  },
)

// P1-3.2：用户确认/取消第三方首次建号；confirm 成功后置登录态，cancel 仅消费票据
export const confirmOAuthRegistration = createAsyncThunk<
  AuthSuccessPayload | null,
  { ticket: string; action: 'confirm' | 'cancel'; consent?: ConsentAcceptance },
  { rejectValue: string }
>('auth/confirmOAuthRegistration', async ({ ticket, action, consent }, { rejectWithValue }) => {
  try {
    const response = await apiClient.oauthConfirmRegistration({ ticket, action, consent })
    if (action === 'cancel') {
      return null
    }
    return response.data as AuthSuccessPayload
  } catch (error) {
    return rejectWithValue(await extractApiErrorMessage(error, '注册确认失败'))
  }
})

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

export const performLogout = createAsyncThunk<void, void>(
  'auth/performLogout',
  async (_, { dispatch }) => {
    // P2-4.5：登出令牌由 httpOnly cookie 携带，后端吊销 jti + refresh 并清除 cookie；
    // 前端不持有令牌，body 传空。网络失败不阻塞本地登出（best-effort），
    // 本地清理在 finally 中必达。
    try {
      await apiClient.logout({})
    } catch {
      // 忽略：后端不可达时本地登出仍要完成
    } finally {
      dispatch(logout())
    }
  },
)

const authSlice = createSlice({
  name: 'auth',
  initialState,
  reducers: {
    logout: (state) => {
      state.user = null
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
      .addCase(sendRegisterCode.pending, (state) => {
        state.error = null
      })
      .addCase(sendRegisterCode.rejected, (state, action) => {
        state.error = getRejectedMessage(action.payload, '验证码发送失败')
      })
      .addCase(register.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(register.fulfilled, (state, action) => {
        state.isLoading = false
        state.user = action.payload.user
        state.isAuthenticated = true
        state.pendingRegistrationTicket = null
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
        state.sessionStatus = 'ready'
        persistUser(action.payload)
      })
      // 会话恢复是后台动作，其 401（匿名访问公共页的必然结果）不写入 error：
      // 否则登录/注册等公共页首屏会误报红框（App.tsx 启动即 dispatch getCurrentUser）。
      // 用户主动操作的失败提示由各自 rejected case（login/register/oauth）负责。
      .addCase(getCurrentUser.rejected, (state) => {
        state.isLoading = false
        state.user = null
        state.isAuthenticated = false
        state.sessionStatus = 'ready'
        clearPersistedAuth()
      })
      .addCase(alipayLogin.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(alipayLogin.fulfilled, (state, action) => {
        state.isLoading = false
        // P1-3.2：new_user 时不置登录态，仅暂存注册票据等待确认页消费
        if (action.payload.status === 'ok' && action.payload.user) {
          state.user = action.payload.user
          state.isAuthenticated = true
          state.pendingRegistrationTicket = null
          persistAuth({ user: action.payload.user })
        } else {
          state.pendingRegistrationTicket = action.payload.registrationTicket
        }
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
        if (action.payload.status === 'ok' && action.payload.user) {
          state.user = action.payload.user
          state.isAuthenticated = true
          state.pendingRegistrationTicket = null
          persistAuth({ user: action.payload.user })
        } else {
          state.pendingRegistrationTicket = action.payload.registrationTicket
        }
      })
      .addCase(wechatLogin.rejected, (state, action) => {
        state.isLoading = false
        state.error = getRejectedMessage(action.payload, '微信登录失败')
      })
      .addCase(confirmOAuthRegistration.pending, (state) => {
        state.isLoading = true
        state.error = null
      })
      .addCase(confirmOAuthRegistration.fulfilled, (state, action) => {
        state.isLoading = false
        state.pendingRegistrationTicket = null
        if (action.payload) {
          state.user = action.payload.user
          state.isAuthenticated = true
          persistAuth(action.payload)
        }
      })
      .addCase(confirmOAuthRegistration.rejected, (state, action) => {
        state.isLoading = false
        state.error = getRejectedMessage(action.payload, '注册确认失败')
      })
  },
})

export const { logout, clearError } = authSlice.actions
export default authSlice.reducer
