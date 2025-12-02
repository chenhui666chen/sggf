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

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch

