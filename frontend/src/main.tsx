import React from 'react'
import ReactDOM from 'react-dom/client'
import { Provider } from 'react-redux'
import App from './App'
import { store } from './store/store'
import {
  runLegacyLocalAssetMigrationWithStatus,
  shouldRunLegacyLocalAssetMigration,
} from './utils/localAssetMigration'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <Provider store={store}>
      <App />
    </Provider>
  </React.StrictMode>,
)

// 在空闲时机触发 legacy IndexedDB → OPFS 的批量迁移，并把结果写入状态快照。
const scheduleLegacyMigration = () => {
  if (!shouldRunLegacyLocalAssetMigration()) {
    return
  }

  runLegacyLocalAssetMigrationWithStatus().then((status) => {
    if (status.phase === 'completed') {
      console.info('[localAssetVault] legacy 迁移完成', status)
      return
    }

    console.warn('[localAssetVault] legacy 迁移未完全成功', status)
  })
}

const ric = (window as unknown as { requestIdleCallback?: (cb: () => void) => number })
  .requestIdleCallback

if (typeof ric === 'function') {
  ric(scheduleLegacyMigration)
} else {
  setTimeout(scheduleLegacyMigration, 2000)
}
