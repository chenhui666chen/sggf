import { useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { ThemeProvider, createTheme, CssBaseline, CircularProgress, Box } from '@mui/material'
import { RootState, AppDispatch } from '@/store/store'
import { getCurrentUser } from '@/store/slices/authSlice'
import ProtectedRoute from '@/components/ProtectedRoute'

// 懒加载页面组件
const LoginPage = lazy(() => import('@/pages/LoginPage'))
const RegisterPage = lazy(() => import('@/pages/RegisterPage'))
const CreationModulePage = lazy(() => import('@/pages/CreationModulePage'))
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const EditorPage = lazy(() => import('@/pages/EditorPage'))
const KnowledgeBasePage = lazy(() => import('@/pages/KnowledgeBasePage'))
const ReviewPage = lazy(() => import('@/pages/ReviewPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const WorkflowControlPage = lazy(() => import('@/pages/WorkflowControlPage'))
const PromptEvolutionPage = lazy(() => import('@/pages/PromptEvolutionPage'))
const AITracePage = lazy(() => import('@/pages/AITracePage'))
const BookParserPage = lazy(() => import('@/pages/BookParserPage'))
const AudiobookPage = lazy(() => import('@/pages/AudiobookPage'))  // 耳畔星河
const DreamWeaverPage = lazy(() => import('@/pages/DreamWeaverPage')) // 织梦映心
const DreamWeaverMockPage = lazy(() => import('@/pages/DreamWeaverMockPage')) // 织梦映心 Mock

// 加载中组件
const LoadingFallback = () => (
  <Box sx={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '100vh' }}>
    <CircularProgress />
  </Box>
)

const theme = createTheme({
  palette: {
    primary: {
      main: '#1976d2',
    },
    secondary: {
      main: '#dc3545',
    },
  },
  typography: {
    fontFamily: '"Segoe UI", "Roboto", "Oxygen", "Ubuntu", "Cantarell", sans-serif',
  },
})

function App() {
  const dispatch = useDispatch<AppDispatch>()
  const { isAuthenticated, token } = useSelector((state: RootState) => state.auth)

  useEffect(() => {
    if (token && isAuthenticated) {
      dispatch(getCurrentUser())
    }
  }, [dispatch, token, isAuthenticated])

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <BrowserRouter
        future={{
          v7_startTransition: true,
          v7_relativeSplatPath: true,
        }}
      >
        <Suspense fallback={<LoadingFallback />}>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route path="/register" element={<RegisterPage />} />
          {/* 创作模块入口页 */}
          <Route
            path="/home"
            element={
              <ProtectedRoute>
                <CreationModulePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/dashboard"
            element={
              <ProtectedRoute>
                <DashboardPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/editor/:projectId/:chapterId"
            element={
              <ProtectedRoute>
                <EditorPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/knowledge-base/:projectId"
            element={
              <ProtectedRoute>
                <KnowledgeBasePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/review/:chapterId"
            element={
              <ProtectedRoute>
                <ReviewPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/settings"
            element={
              <ProtectedRoute>
                <SettingsPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/workflow/:projectId"
            element={
              <ProtectedRoute>
                <WorkflowControlPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/prompt-evolution"
            element={
              <ProtectedRoute>
                <PromptEvolutionPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/ai-trace"
            element={
              <ProtectedRoute>
                <AITracePage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/book-parser"
            element={
              <ProtectedRoute>
                <BookParserPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/audiobook"
            element={
              <ProtectedRoute>
                <AudiobookPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/drama"
            element={
              <ProtectedRoute>
                <DreamWeaverPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/drama/mock"
            element={
              <ProtectedRoute>
                <DreamWeaverMockPage />
              </ProtectedRoute>
            }
          />
          <Route
            path="/modules"
            element={
              <ProtectedRoute>
                <CreationModulePage />
              </ProtectedRoute>
            }
          />
            {/* 默认跳转到创作模块入口页 */}
            <Route path="/" element={<Navigate to="/home" replace />} />
          </Routes>
        </Suspense>
      </BrowserRouter>
    </ThemeProvider>
  )
}

export default App
