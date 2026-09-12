import { configureStore } from '@reduxjs/toolkit'
import authReducer from './slices/authSlice'
import projectReducer from './slices/projectSlice'
import editorReducer from './slices/editorSlice'
import reviewReducer from './slices/reviewSlice'
import workflowReducer from './slices/workflowSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    project: projectReducer,
    editor: editorReducer,
    review: reviewReducer,
    workflow: workflowReducer,
  },
})

// P2-4.5 收尾：token 全部由 httpOnly cookie 承载，前端不再有 store token 同步 /
// 跨标签 token 同步（原先的 setTokenRefreshListener / setTokenLogoutListener /
// startCrossTabTokenSync 机制已随 body token 剥离一并移除）。

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch

