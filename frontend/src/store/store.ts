import { configureStore } from '@reduxjs/toolkit'
import authReducer from './slices/authSlice'
import projectReducer from './slices/projectSlice'
import editorReducer from './slices/editorSlice'
import knowledgeBaseReducer from './slices/knowledgeBaseSlice'
import reviewReducer from './slices/reviewSlice'
import workflowReducer from './slices/workflowSlice'

export const store = configureStore({
  reducer: {
    auth: authReducer,
    project: projectReducer,
    editor: editorReducer,
    knowledgeBase: knowledgeBaseReducer,
    review: reviewReducer,
    workflow: workflowReducer,
  },
})

export type RootState = ReturnType<typeof store.getState>
export type AppDispatch = typeof store.dispatch

