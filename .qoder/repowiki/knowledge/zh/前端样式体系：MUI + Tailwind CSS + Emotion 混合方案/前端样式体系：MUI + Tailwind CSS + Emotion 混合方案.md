---
kind: frontend_style
name: 前端样式体系：MUI + Tailwind CSS + Emotion 混合方案
category: frontend_style
scope:
    - '**'
source_files:
    - frontend/src/App.tsx
    - frontend/tailwind.config.js
    - frontend/src/index.css
    - frontend/src/styles/responsive.css
    - frontend/postcss.config.js
    - frontend/package.json
---

## 1. 系统与方法

前端采用 **Material-UI (MUI v5) + Tailwind CSS + Emotion** 的混合样式方案：
- **MUI 作为主要组件库与主题系统**，通过 `createTheme` 定义全局主题（颜色、字体、组件覆盖），所有页面和组件广泛使用 `@mui/material` 的 Box、Typography、Paper 等原子组件，并通过 `sx` prop 进行内联样式定制。
- **Tailwind CSS 作为原子化样式补充**，在 `index.css` 中引入 `@tailwind base/components/utilities`，并在 `tailwind.config.js` 中扩展了品牌色（primary: #1976d2, secondary: #dc3545 等）和字体族。
- **Emotion 作为 CSS-in-JS 引擎**，通过 `CacheProvider` 提供缓存机制，配合 `@emotion/react` 和 `@emotion/styled` 实现组件级样式。
- **PostCSS + Autoprefixer** 处理 CSS 前缀，构建流程由 Vite 驱动。

## 2. 核心文件与包

- **主题配置**：`frontend/src/App.tsx` 中的 `createTheme` 定义主色调、次色调、字体族
- **Tailwind 配置**：`frontend/tailwind.config.js` 扩展颜色系统和字体
- **全局样式入口**：`frontend/src/index.css` 引入响应式样式和 Tailwind 指令
- **响应式设计**：`frontend/src/styles/responsive.css` 提供完整的响应式工具类系统
- **构建配置**：`frontend/postcss.config.js`、`frontend/vite.config.ts`
- **依赖声明**：`frontend/package.json` 中 MUI、Tailwind、Emotion、Vite 等关键依赖

## 3. 架构与约定

### 主题系统设计
- 全局主题在 `App.tsx` 中通过 `ThemeProvider` 提供，包含自定义的 primary (#1976d2) 和 secondary (#dc3545) 颜色
- 字体统一使用 Segoe UI/Roboto/Oxygen/Ubuntu/Cantarell 字体栈
- 组件样式主要通过 MUI 的 `sx` prop 进行内联定制，而非传统 CSS 类名

### 响应式策略
- 采用 **移动优先** 的响应式设计，断点定义为：手机 (<768px)、平板 (768-1024px)、桌面 (>1025px)、大屏 (>1920px)
- 使用 CSS 变量 (`--font-size-*`, `--spacing-*`) 配合 `clamp()` 函数实现流体排版
- 提供丰富的响应式工具类如 `.container-responsive`、`.grid-responsive-*`、`.flex-responsive-*` 等
- 移动端触摸目标最小 44x44px，符合无障碍标准

### 样式组织模式
- **组件级样式**：优先使用 MUI 的 `sx` prop 和组件属性
- **全局样式**：集中在 `src/styles/responsive.css` 中管理响应式工具类
- **编辑器样式**：独立的 `.editor-container`、`.editor-toolbar`、`.editor-content` 类用于富文本编辑器
- **滚动条定制**：统一的 WebKit 滚动条样式，支持深色主题适配

### 构建与开发
- Vite 作为构建工具，支持热重载和快速开发
- PostCSS 处理 CSS 预处理，Autoprefixer 自动添加浏览器前缀
- ESLint 确保代码质量，TypeScript 提供类型安全
- 支持 CSS Modules 和 CSS-in-JS 混合使用

## 4. 约定与约束

### 样式编写约定
- **优先使用 MUI 组件**：所有 UI 元素应基于 `@mui/material` 组件构建，避免手写基础样式
- **内联样式优先**：组件样式通过 `sx` prop 定义，保持样式与组件逻辑的紧密耦合
- **响应式断点统一**：严格遵循 768px、1025px、1920px 三个断点，不随意新增断点
- **颜色系统规范**：使用 MUI 主题的颜色变量（`primary.main`、`text.primary` 等），避免硬编码颜色值
- **字体大小规范**：使用 MUI 的 typography 变体（`variant="h1"`、`variant="body1"` 等）

### 响应式设计约束
- **移动端优先**：所有布局必须首先考虑移动端显示效果
- **触摸友好**：移动端交互元素最小尺寸 44x44px，确保可触摸性
- **内容自适应**：图片和容器使用 `max-width: 100%` 确保在小屏幕上正常显示
- **性能优化**：使用 `prefers-reduced-motion` 媒体查询尊重用户的动画偏好设置

### 可访问性要求
- 所有交互元素必须有明确的语义标签和 ARIA 属性
- 颜色对比度符合 WCAG 2.1 AA 标准
- 支持键盘导航和屏幕阅读器
- 提供足够的焦点指示器

### 构建与部署约束
- 生产环境启用代码压缩和 Tree Shaking
- CSS 自动添加浏览器兼容性前缀
- 支持 CSS 模块化和按需加载
- 开发环境支持热重载和错误提示