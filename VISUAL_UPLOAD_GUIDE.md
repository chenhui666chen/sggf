# 📸 可视化上传指南 - 一步一步

**用最简单的方式上传你的项目到 GitHub**

---

## 🎯 总体流程

```
┌─────────────────────────────────────────────────────────────┐
│  第1步：打开文件管理器                                        │
│  第2步：导航到项目目录                                        │
│  第3步：打开 PowerShell                                       │
│  第4步：运行上传脚本                                          │
│  第5步：输入 GitHub URL                                       │
│  第6步：等待完成                                              │
│  第7步：验证上传                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📍 第 1 步：打开文件管理器

### 方法 A：使用快捷键
```
按 Win + E
↓
文件管理器打开
```

### 方法 B：从开始菜单
```
点击开始菜单
↓
搜索 "文件管理器"
↓
点击打开
```

### 方法 C：从任务栏
```
点击任务栏上的文件夹图标
↓
文件管理器打开
```

---

## 📂 第 2 步：导航到项目目录

### 在地址栏输入路径

```
┌─────────────────────────────────────────────────────────┐
│ 此电脑 > 本地磁盘 (C:) > Users > cuigu > novel_writing_agent │
└─────────────────────────────────────────────────────────┘
```

**或者直接在地址栏输入**：
```
c:\Users\cuigu\novel_writing_agent
```

### 你应该看到这些文件

```
📁 novel_writing_agent/
├── 📄 upload_to_github.ps1      ← 这个文件！
├── 📄 upload_to_github.bat
├── 📄 README.md
├── 📄 .gitignore
├── 📁 backend/
├── 📁 frontend/
└── ... 其他文件
```

---

## 🖥️ 第 3 步：打开 PowerShell

### 方法 A：右键菜单（推荐）

```
1. 在文件管理器中右键点击空白处
   ↓
2. 看到菜单
   ↓
3. 选择 "在此处打开 PowerShell 窗口"
   ↓
4. PowerShell 窗口打开
```

**菜单样子**：
```
┌─────────────────────────────────┐
│ 新建                             │
│ 粘贴                             │
│ 粘贴快捷方式                     │
│ 刷新                             │
│ 在此处打开 PowerShell 窗口 ← 点这个 │
│ 在此处打开 CMD 窗口              │
│ 属性                             │
└─────────────────────────────────┘
```

### 方法 B：从 VS Code

```
1. 打开 VS Code
   ↓
2. File → Open Folder
   ↓
3. 选择 c:\Users\cuigu\novel_writing_agent
   ↓
4. 按 Ctrl + ~
   ↓
5. 终端打开
```

### 方法 C：从开始菜单

```
1. 按 Win + R
   ↓
2. 输入 powershell
   ↓
3. 按 Enter
   ↓
4. 输入：cd c:\Users\cuigu\novel_writing_agent
   ↓
5. 按 Enter
```

---

## ⚙️ 第 4 步：运行上传脚本

### 在 PowerShell 中输入

```powershell
.\upload_to_github.ps1
```

**然后按 Enter**

### PowerShell 窗口样子

```
┌──────────────────────────────────────────────────────────┐
│ Windows PowerShell                                        │
│ 版权所有 (C) Microsoft Corporation。保留所有权利。        │
│                                                          │
│ PS C:\Users\cuigu\novel_writing_agent> .\upload_to_github.ps1
│                                                          │
│ ========================================                 │
│   Novel Writing Agent - GitHub Upload                   │
│ ========================================                 │
│                                                          │
│ ✅ Git 已安装                                            │
│ ✅ Git 仓库已存在                                        │
│                                                          │
│ 📊 当前 Git 状态:                                        │
│ On branch main                                           │
│ ...                                                      │
└──────────────────────────────────────────────────────────┘
```

---

## 📝 第 5 步：输入 GitHub 仓库 URL

### 脚本会提示

```
请输入 GitHub 仓库 URL:
例如: git@github.com:username/novel_writing_agent.git
或: https://github.com/username/novel_writing_agent.git
GitHub 仓库 URL: _
```

### 复制以下之一

**HTTPS 方式**（推荐新手）：
```
https://github.com/你的用户名/novel_writing_agent.git
```

**例如**：
```
https://github.com/cuigu/novel_writing_agent.git
```

### 粘贴到 PowerShell

```
1. 复制上面的 URL
   ↓
2. 在 PowerShell 中右键点击
   ↓
3. 选择 "粘贴"
   ↓
4. 按 Enter
```

---

## ⏳ 第 6 步：等待完成

### 脚本会自动执行

```
📍 初始化 Git 仓库...
✅ Git 仓库已初始化

📍 添加所有文件...
✅ 文件已添加

📍 创建提交...
请输入提交信息 (默认: Initial commit): _
```

**按 Enter 接受默认提交信息**

### 继续等待

```
✅ 提交已创建

📍 检查远程仓库...
⚠️  远程仓库未配置

请输入 GitHub 仓库 URL:
https://github.com/你的用户名/novel_writing_agent.git

✅ 远程仓库已添加

📍 检查分支...
✅ 分支已设置为 main

📍 推送到 GitHub...
```

---

## ✅ 第 7 步：验证上传成功

### 脚本显示成功信息

```
✅ 推送成功！

🎉 项目已上传到 GitHub

📍 访问你的仓库:
https://github.com/你的用户名/novel_writing_agent

按 Enter 键退出
```

### 访问 GitHub 验证

```
1. 打开浏览器
   ↓
2. 访问 https://github.com/你的用户名/novel_writing_agent
   ↓
3. 应该能看到你的代码
   ↓
4. 🎉 成功！
```

---

## 🎯 快速参考

### 完整命令序列

```bash
# 1. 打开文件管理器
Win + E

# 2. 导航到项目目录
c:\Users\cuigu\novel_writing_agent

# 3. 右键打开 PowerShell
右键 → 在此处打开 PowerShell 窗口

# 4. 运行脚本
.\upload_to_github.ps1

# 5. 输入 GitHub URL
https://github.com/你的用户名/novel_writing_agent.git

# 6. 等待完成
```

---

## ⚠️ 如果出错

### 错误 1：PowerShell 无法运行脚本

```
错误：无法加载文件 upload_to_github.ps1，
因为在此系统上禁止运行脚本。

解决：
1. 右键点击 PowerShell
2. 选择 "以管理员身份运行"
3. 输入：Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
4. 输入 Y 并按 Enter
5. 重新运行脚本
```

### 错误 2：Git 未安装

```
错误：git : 无法将"git"项识别为 cmdlet

解决：
1. 下载 Git：https://git-scm.com/download/win
2. 安装 Git（勾选 "Add to PATH"）
3. 重启 PowerShell
4. 重新运行脚本
```

### 错误 3：找不到脚本

```
错误：无法找到文件 'upload_to_github.ps1'

解决：
1. 确保在正确的目录
2. 输入 ls 查看文件列表
3. 确保 upload_to_github.ps1 存在
4. 重新运行脚本
```

---

## 📋 检查清单

在运行脚本前，确保：

- [ ] 已安装 Git
- [ ] 已创建 GitHub 账户
- [ ] 已创建 GitHub 仓库（名称：novel_writing_agent）
- [ ] 知道你的 GitHub 用户名
- [ ] 在正确的目录（c:\Users\cuigu\novel_writing_agent）

---

## 🎉 完成！

### 上传后你可以：

1. ✅ 访问 GitHub 仓库
2. ✅ 分享项目链接
3. ✅ 邀请朋友 Star
4. ✅ 继续开发和更新

### 后续更新

```bash
# 修改代码后
git add .
git commit -m "Update: description"
git push origin main
```

---

## 🚀 现在就开始吧！

**按照以下步骤操作**：

1. 按 `Win + E` 打开文件管理器
2. 导航到 `c:\Users\cuigu\novel_writing_agent`
3. 右键打开 PowerShell
4. 输入 `.\upload_to_github.ps1`
5. 按 Enter
6. 输入 GitHub URL
7. 等待完成

**就这么简单！** 🎉

---

**最后更新**：2025-11-12


