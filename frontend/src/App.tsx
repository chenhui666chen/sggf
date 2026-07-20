import { useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useDispatch, useSelector } from 'react-redux'
import { ThemeProvider, createTheme, CssBaseline, CircularProgress, Box, Typography } from '@mui/material'
import { CacheProvider } from '@emotion/react'
import createCache from '@emotion/cache'
import { RootState, AppDispatch } from '@/store/store'
import { getCurrentUser } from '@/store/slices/authSlice'
import ProtectedRoute from '@/components/ProtectedRoute'
import AdminProtectedRoute from '@/components/admin/AdminProtectedRoute'
import LocalAssetHealthBanner from '@/components/user-assets/LocalAssetHealthBanner'
import { loadAudiobookPageModule } from '@/pages/audiobook/audiobookPagePreload'

const cache = createCache({
  key: 'css',
  prepend: true,
})

// 懒加载页面组件
const LoginPage = lazy(() => import('@/pages/LoginPage'))
const LoginCallbackPage = lazy(() => import('@/pages/LoginCallbackPage'))
const ForgotPasswordPage = lazy(() => import('@/pages/ForgotPasswordPage'))
const RegisterPage = lazy(() => import('@/pages/RegisterPage'))
const CreationModulePage = lazy(() => import('@/pages/CreationModulePage'))
const AssetStudioPage = lazy(() => import('@/pages/AssetStudioPage'))
const DashboardPage = lazy(() => import('@/pages/DashboardPage'))
const EditorPage = lazy(() => import('@/pages/EditorPage'))
const KnowledgeBasePage = lazy(() => import('@/pages/KnowledgeBasePage'))
const ModelCatalogPage = lazy(() => import('@/pages/ModelCatalogPage'))
const ReviewPage = lazy(() => import('@/pages/ReviewPage'))
const SettingsPage = lazy(() => import('@/pages/SettingsPage'))
const UserCenterPage = lazy(() => import('@/pages/UserCenterPage'))
const WorkflowControlPage = lazy(() => import('@/pages/WorkflowControlPage'))
const AITracePage = lazy(() => import('@/pages/AITracePage'))
const AudiobookDashboardPage = lazy(() => import('@/pages/AudiobookDashboardPage'))  // 耳畔星河仪表盘
const TtsPromptTestPage = lazy(() => import('@/pages/TtsPromptTestPage'))
const AudiobookPage = lazy(loadAudiobookPageModule)  // 耳畔星河
const DreamWeaverPage = lazy(() => import('@/pages/DreamWeaverPage')) // 织梦映心
const DreamWeaverRunPage = lazy(() => import('@/pages/DreamWeaverRunPage')) // 织梦映心生成页
const DreamWeaverLibraryPage = lazy(() => import('@/pages/DreamWeaverLibraryPage')) // 织梦映心项目素材库
const TrashPage = lazy(() => import('@/pages/TrashPage')) // 回收站
const AICreationPlatformPage = lazy(() => import('@/pages/AICreationPlatformPage')) // AI 创作平台

// 管理控制台页面
const AdminLayout = lazy(() => import('@/pages/admin/AdminLayout'))
const AdminDashboardPage = lazy(() => import('@/pages/admin/DashboardPage'))
const AdminUsersPage = lazy(() => import('@/pages/admin/UsersPage'))
const PointsBillingPage = lazy(() => import('@/pages/admin/PointsBillingPage'))
const RolesPage = lazy(() => import('@/pages/admin/RolesPage'))
const LogsPage = lazy(() => import('@/pages/admin/LogsPage'))
const SystemPage = lazy(() => import('@/pages/admin/SystemPage'))
const DatabaseQueryPage = lazy(() => import('@/pages/admin/DatabaseQueryPage'))
const PromptEvolutionPage = lazy(() => import('@/pages/admin/PromptEvolutionPage'))

// 加载中组件
const LoadingFallback = () => {
  const location = useLocation()
  const isAudiobookProjectRoute = /^\/audiobook\/[^/]+/.test(location.pathname)

  return (
    <Box
      sx={{
        display: 'flex',
        flexDirection: 'column',
        justifyContent: 'center',
        alignItems: 'center',
        gap: 2,
        height: '100vh',
        px: 3,
        textAlign: 'center',
      }}
    >
      <CircularProgress />
      {isAudiobookProjectRoute ? (
        <Box>
          <Typography sx={{ fontWeight: 700, color: 'text.primary' }}>
            正在进入项目配置
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.75, color: 'text.secondary' }}>
            首次打开会加载页面资源和项目配置，请稍候。
          </Typography>
        </Box>
      ) : null}
    </Box>
  )
}

const theme = createTheme({
  components: {
    MuiCssBaseline: {
      styleOverrides: {
        body: {
          margin: 0,
        },
      },
    },
  },
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
    const loadUser = async () => {
      if (token && isAuthenticated) {
        try {
          await dispatch(getCurrentUser())
        } catch {
          // 加载用户失败
        }
      }
    }
    loadUser()
  }, [dispatch, token, isAuthenticated])

  return (
    <CacheProvider value={cache}>
      <ThemeProvider theme={theme}>
        <CssBaseline />
        <BrowserRouter
          future={{
            v7_startTransition: true,
            v7_relativeSplatPath: true,
          }}
        >
          <LocalAssetHealthBanner />
          <Suspense fallback={<LoadingFallback />}>
            <Routes>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/login/callback" element={<LoginCallbackPage />} />
              <Route path="/forgot-password" element={<ForgotPasswordPage />} />
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
                path="/asset-studio"
                element={
                  <ProtectedRoute>
                    <AssetStudioPage />
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
                path="/model-catalog"
                element={
                  <ProtectedRoute>
                    <ModelCatalogPage />
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
                path="/user-center"
                element={
                  <ProtectedRoute>
                    <UserCenterPage />
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
                path="/ai-trace"
                element={
                  <ProtectedRoute>
                    <AITracePage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audiobook-dashboard"
                element={
                  <ProtectedRoute>
                    <AudiobookDashboardPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audiobook-tts-test"
                element={
                  <ProtectedRoute>
                    <TtsPromptTestPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/audiobook/:projectId"
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
                path="/drama/:projectId"
                element={
                  <ProtectedRoute>
                    <DreamWeaverRunPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/drama/:projectId/library"
                element={
                  <ProtectedRoute>
                    <DreamWeaverLibraryPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/drama/run"
                element={
                  <ProtectedRoute>
                    <DreamWeaverRunPage />
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
              <Route
                path="/trash"
                element={
                  <ProtectedRoute>
                    <TrashPage />
                  </ProtectedRoute>
                }
              />
              <Route
                path="/ai-creation-platform"
                element={
                  <ProtectedRoute>
                    <AICreationPlatformPage />
                  </ProtectedRoute>
                }
              />

              {/* 管理控制台路由 */}
              <Route
                path="/admin"
                element={
                  <AdminProtectedRoute>
                    <AdminLayout />
                  </AdminProtectedRoute>
                }
              >
                <Route index element={<Navigate to="dashboard" replace />} />
                <Route path="dashboard" element={<AdminDashboardPage />} />
                <Route path="users" element={<AdminUsersPage />} />
                <Route path="billing" element={<PointsBillingPage />} />
                <Route path="roles" element={<RolesPage />} />
                <Route path="query" element={<DatabaseQueryPage />} />
                <Route path="prompt-evolution" element={<PromptEvolutionPage />} />
                <Route path="logs" element={<LogsPage />} />
                <Route path="system" element={<SystemPage />} />
              </Route>

              {/* 默认跳转到创作模块入口页 */}
              <Route path="/" element={<Navigate to="/home" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ThemeProvider>
    </CacheProvider>
  )
}

export default App
