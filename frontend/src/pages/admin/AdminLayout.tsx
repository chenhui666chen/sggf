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
import {
  Dashboard as DashboardIcon,
  People as PeopleIcon,
  Security as SecurityIcon,
  History as HistoryIcon,
  Settings as SettingsIcon,
  Home as HomeIcon,
  Science as ScienceIcon,
  Storage as StorageIcon,
} from '@mui/icons-material'
import { RootState } from '@/store/store'

const drawerWidth = 240

const menuItems = [
  { text: '数据仪表盘', icon: <DashboardIcon />, path: '/admin/dashboard' },
  { text: '用户管理', icon: <PeopleIcon />, path: '/admin/users' },
  { text: '角色权限', icon: <SecurityIcon />, path: '/admin/roles' },
  { text: '数据库查询', icon: <StorageIcon />, path: '/admin/query' },
  { text: '提示词优化', icon: <ScienceIcon />, path: '/admin/prompt-evolution' },
  { text: '操作日志', icon: <HistoryIcon />, path: '/admin/logs' },
  { text: '系统配置', icon: <SettingsIcon />, path: '/admin/system', superAdminOnly: true },
]

export default function AdminLayout() {
  const navigate = useNavigate()
  const location = useLocation()
  const { user } = useSelector((state: RootState) => state.auth)
  
  const isSuperAdmin = (user as any)?.roles?.some((r: any) => r.code === 'super_admin')

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
            管理控制台
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
            拾光工坊
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
