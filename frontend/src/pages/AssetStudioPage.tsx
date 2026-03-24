import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Box, Button, Container, Typography } from '@mui/material'
import ArrowBackIcon from '@mui/icons-material/ArrowBack'
import LogoutIcon from '@mui/icons-material/Logout'
import AdminPanelSettingsIcon from '@mui/icons-material/AdminPanelSettings'
import PermMediaOutlinedIcon from '@mui/icons-material/PermMediaOutlined'
import { useDispatch, useSelector } from 'react-redux'

import AssetStudioWorkbench from '@/components/home/AssetStudioWorkbench'
import ModelUseEntryStrip from '@/components/home/ModelUseEntryStrip'
import { modelUseEntries } from '@/components/home/modelEntryData'
import type { AssetStudioTabId } from '@/components/home/modelEntryData'
import { logout } from '@/store/slices/authSlice'
import type { RootState } from '@/store/store'

export default function AssetStudioPage() {
  const navigate = useNavigate()
  const dispatch = useDispatch()
  const { user } = useSelector((state: RootState) => state.auth)
  const [activeModelEntryId, setActiveModelEntryId] = useState<AssetStudioTabId>(modelUseEntries[0]?.id || 'image')

  const hasAdminRole = user?.roles?.some((role: any) => role.code === 'admin' || role.code === 'super_admin')

  const handleLogout = () => {
    dispatch(logout())
    navigate('/login')
  }

  return (
    <Box
      sx={{
        minHeight: '100dvh',
        background: 'linear-gradient(135deg, #667eea 0%, #764ba2 100%)',
        py: { xs: 2, sm: 3, md: 4 },
        px: { xs: 1, sm: 2 },
      }}
    >
      <Container
        maxWidth="lg"
        sx={{
          px: { xs: 0, sm: 2 },
        }}
      >
        <Box
          sx={{
            display: 'flex',
            flexDirection: { xs: 'column', sm: 'row' },
            justifyContent: 'space-between',
            alignItems: { xs: 'flex-start', sm: 'center' },
            mb: { xs: 2, sm: 3 },
            gap: { xs: 1.5, sm: 0 },
          }}
        >
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 1.25 }}>
            <Box
              sx={{
                width: 48,
                height: 48,
                borderRadius: 2.5,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                backgroundColor: 'rgba(255,255,255,0.14)',
                color: 'white',
              }}
            >
              <PermMediaOutlinedIcon />
            </Box>
            <Box>
              <Typography
                variant="h4"
                sx={{
                  color: 'white',
                  fontWeight: 700,
                  fontSize: { xs: '1.5rem', sm: '1.75rem', md: '2rem' },
                }}
              >
                资产生成工作台
              </Typography>
            </Box>
          </Box>

          <Box
            sx={{
              display: 'flex',
              gap: { xs: 1, sm: 1.5 },
              alignItems: 'center',
              flexWrap: 'wrap',
            }}
          >
            <Button
              variant="outlined"
              size="small"
              startIcon={<ArrowBackIcon />}
              onClick={() => navigate('/home')}
              sx={{
                color: 'white',
                borderColor: 'rgba(255,255,255,0.5)',
                minHeight: { xs: 44, sm: 36 },
                fontSize: { xs: '0.875rem', sm: '0.875rem' },
                '&:hover': {
                  borderColor: 'white',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                },
              }}
            >
              返回创作工坊
            </Button>
            {hasAdminRole && (
              <Button
                variant="outlined"
                size="small"
                startIcon={<AdminPanelSettingsIcon />}
                onClick={() => navigate('/admin')}
                sx={{
                  color: 'white',
                  borderColor: 'rgba(255,255,255,0.5)',
                  minHeight: { xs: 44, sm: 36 },
                  fontSize: { xs: '0.875rem', sm: '0.875rem' },
                  '&:hover': {
                    borderColor: 'white',
                    backgroundColor: 'rgba(255,255,255,0.1)',
                  },
                }}
              >
                管理控制台
              </Button>
            )}
            <Button
              variant="outlined"
              size="small"
              startIcon={<LogoutIcon />}
              onClick={handleLogout}
              sx={{
                color: 'white',
                borderColor: 'rgba(255,255,255,0.5)',
                minHeight: { xs: 44, sm: 36 },
                fontSize: { xs: '0.875rem', sm: '0.875rem' },
                '&:hover': {
                  borderColor: 'white',
                  backgroundColor: 'rgba(255,255,255,0.1)',
                },
              }}
            >
              退出登录
            </Button>
          </Box>
        </Box>

        <Box
          sx={{
            p: { xs: 1.5, sm: 2, md: 2.5 },
            borderRadius: { xs: 3, sm: 4 },
            background: 'linear-gradient(135deg, rgba(8,20,52,0.28), rgba(13,27,62,0.16))',
            border: '1px solid rgba(255,255,255,0.14)',
            backdropFilter: 'blur(16px)',
          }}
        >
          <ModelUseEntryStrip
            activeEntryId={activeModelEntryId}
            entries={modelUseEntries}
            onSelect={setActiveModelEntryId}
          />

          <Box sx={{ mt: 2 }}>
            <AssetStudioWorkbench
              activeTabId={activeModelEntryId}
              entries={modelUseEntries}
              onRequestTabChange={setActiveModelEntryId}
            />
          </Box>
        </Box>
      </Container>
    </Box>
  )
}
