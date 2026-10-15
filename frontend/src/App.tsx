import { useEffect, lazy, Suspense } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useDispatch } from 'react-redux'
import { useTranslation } from 'react-i18next'
import { CircularProgress, Box, Typography } from '@mui/material'
import { CacheProvider } from '@emotion/react'
import createCache from '@emotion/cache'
import { AppDispatch } from '@/store/store'
import { getCurrentUser } from '@/store/slices/authSlice'
import ProtectedRoute from '@/components/ProtectedRoute'
import AdminProtectedRoute from '@/components/admin/AdminProtectedRoute'
import LocalAssetHealthBanner from '@/components/user-assets/LocalAssetHealthBanner'
import { ThemeModeProvider } from '@/theme'
import { useAppLanguage } from '@/i18n'
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
const PrivacyPolicyPage = lazy(() => import('@/pages/PrivacyPolicyPage'))
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

// 全站共享外壳（顶栏 + <main> 路由出口），受保护主应用页面的 layout route
const AppShell = lazy(() => import('@/components/layout/AppShell'))

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
const DirectorOSAdminPage = lazy(() => import('@/pages/admin/DirectorOSAdminPage'))
const VideoGatewayPage = lazy(() => import('@/pages/admin/VideoGatewayPage'))

// 加载中组件
const LoadingFallback = () => {
  const location = useLocation()
  const { t } = useTranslation()
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
            {t('appEntry.loadingProjectConfig')}
          </Typography>
          <Typography variant="body2" sx={{ mt: 0.75, color: 'text.secondary' }}>
            {t('appEntry.loadingFirstOpenHint')}
          </Typography>
        </Box>
      ) : null}
    </Box>
  )
}

// 主题不再在本文件构造：全站唯一的事实源是 ThemeModeProvider 内部的
// createAppTheme，它同时负责深浅色、持久化与 <html data-theme> 同步。
// 语言在这里取一次传下去：MUI 自带的那批文案（Alert 的关闭按钮、
// Autocomplete 的空选项提示）不走 i18next，只能由主题注入，而主题层不该
// 反过来读 i18n 的 context。

function App() {
  const dispatch = useDispatch<AppDispatch>()
  const { language } = useAppLanguage()

  useEffect(() => {
    // P2-4.5：会话身份由 httpOnly cookie 决定，启动时无条件 getCurrentUser 恢复登录态；
    // 未登录/会话失效时由该接口 401 路径静默处理（公共页面不会跳登录）
    const loadUser = async () => {
      try {
        await dispatch(getCurrentUser())
      } catch {
        // 未登录：保持匿名
      }
    }
    loadUser()
  }, [dispatch])

  return (
    <CacheProvider value={cache}>
      <ThemeModeProvider language={language}>
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
              {/* 5.5：隐私政策展示页（公开路由，供同意勾选处跳转查阅） */}
              <Route path="/privacy" element={<PrivacyPolicyPage />} />
              {/* 主应用外壳：顶栏（拾光字标 + 语言/主题 + 账户菜单）+ <main> 路由出口。
                  /home 与 /modules 是同一页的两个入口，一并收进外壳——删掉
                  CreationModulePage 内联用户菜单后，两条路径都靠 AppShell 提供账户入口。 */}
              <Route
                element={
                  <ProtectedRoute>
                    <AppShell />
                  </ProtectedRoute>
                }
              >
                <Route path="/home" element={<CreationModulePage />} />
                <Route path="/modules" element={<CreationModulePage />} />
              </Route>
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
                <Route path="director-os" element={<DirectorOSAdminPage />} />
                <Route path="logs" element={<LogsPage />} />
                <Route path="system" element={<SystemPage />} />
                <Route path="video-gateway" element={<AdminProtectedRoute requiredRole="super_admin"><VideoGatewayPage /></AdminProtectedRoute>} />
              </Route>

              {/* 默认跳转到创作模块入口页 */}
              <Route path="/" element={<Navigate to="/home" replace />} />
            </Routes>
          </Suspense>
        </BrowserRouter>
      </ThemeModeProvider>
    </CacheProvider>
  )
}

export default App
