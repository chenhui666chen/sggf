import { Outlet, useNavigate, useLocation } from 'react-router-dom'
import { useSelector } from 'react-redux'
import {
  Box,
  Drawer,
  AppBar,
  Toolbar,
  List,
  Typography,
  Divider,
  IconButton,
  ListItem,
  ListItemIcon,
  ListItemText,
  ListItemButton,
} from '@mui/material'
import DashboardIcon from '@mui/icons-material/Dashboard'
import HistoryIcon from '@mui/icons-material/History'
import HomeIcon from '@mui/icons-material/Home'
import PeopleIcon from '@mui/icons-material/People'
import ReceiptLongIcon from '@mui/icons-material/ReceiptLong'
import ScienceIcon from '@mui/icons-material/Science'
import SecurityIcon from '@mui/icons-material/Security'
import SettingsIcon from '@mui/icons-material/Settings'
import StorageIcon from '@mui/icons-material/Storage'
import { useTranslation } from 'react-i18next'
import type { TFunction } from 'i18next'
import { RootState } from '@/store/store'

const drawerWidth = 240

const buildMenuItems = (t: TFunction) => [
  { text: t('admin.layout.menu.dashboard'), icon: <DashboardIcon />, path: '/admin/dashboard' },
  { text: t('admin.layout.menu.users'), icon: <PeopleIcon />, path: '/admin/users' },
  { text: t('admin.layout.menu.billing'), icon: <ReceiptLongIcon />, path: '/admin/billing' },
  { text: t('admin.layout.menu.roles'), icon: <SecurityIcon />, path: '/admin/roles' },
  { text: t('admin.layout.menu.query'), icon: <StorageIcon />, path: '/admin/query' },
  { text: t('admin.layout.menu.promptEvolution'), icon: <ScienceIcon />, path: '/admin/prompt-evolution' },
  { text: 'AI Director OS', icon: <ScienceIcon />, path: '/admin/director-os' },
  { text: t('admin.layout.menu.logs'), icon: <HistoryIcon />, path: '/admin/logs' },
  { text: t('admin.layout.menu.system'), icon: <SettingsIcon />, path: '/admin/system', superAdminOnly: true },
]

export default function AdminLayout() {
  const { t } = useTranslation()
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useSelector((state: RootState) => state.auth)
  
  const isSuperAdmin = (user as any)?.roles?.some((r: any) => r.code === 'super_admin')
  const menuItems = buildMenuItems(t)

  return (
    <Box sx={{ display: 'flex' }}>
      <AppBar 
        position="fixed" 
        sx={{ 
          width: `calc(100% - ${drawerWidth}px)`, 
          ml: `${drawerWidth}px`,
          bgcolor: 'primary.dark'
        }}
      >
        <Toolbar>
          <Typography variant="h6" noWrap component="div" sx={{ flexGrow: 1 }}>
            {t('admin.layout.title')}
          </Typography>
          <IconButton color="inherit" onClick={() => navigate('/')}>
            <HomeIcon />
          </IconButton>
        </Toolbar>
      </AppBar>
      
      <Drawer
        variant="permanent"
        sx={{
          width: drawerWidth,
          flexShrink: 0,
          '& .MuiDrawer-paper': { 
            width: drawerWidth, 
            boxSizing: 'border-box',
            bgcolor: 'grey.50'
          },
        }}
      >
        <Toolbar>
          <Typography variant="h6" noWrap sx={{ color: 'primary.main', fontWeight: 'bold' }}>
            {t('app.name')}
          </Typography>
        </Toolbar>
        <Divider />
        <List>
          {menuItems.map((item) => {
            if (item.superAdminOnly && !isSuperAdmin) return null
            return (
              <ListItem 
                key={item.text} 
                disablePadding
              >
                <ListItemButton
                  onClick={() => navigate(item.path)}
                  selected={location.pathname === item.path}
                  sx={{
                    '&.Mui-selected': {
                      bgcolor: 'primary.light',
                      color: 'primary.contrastText',
                      '& .MuiListItemIcon-root': {
                        color: 'primary.contrastText',
                      },
                    },
                  }}
                >
                  <ListItemIcon>{item.icon}</ListItemIcon>
                  <ListItemText primary={item.text} />
                </ListItemButton>
              </ListItem>
            )
          })}
        </List>
      </Drawer>
      
      <Box 
        component="main" 
        sx={{ 
          flexGrow: 1, 
          bgcolor: 'background.default', 
          p: 3,
          minHeight: '100vh'
        }}
      >
        <Toolbar />
        <Outlet />
      </Box>
    </Box>
  )
}
