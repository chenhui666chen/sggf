# 🚀 如何运行上传脚本 - 详细图文指南

**这是最重要的一步！** 按照以下步骤操作即可。

---

## 📍 脚本位置

上传脚本已经在你的项目目录中：

```
c:\Users\cuigu\novel_writing_agent\
├── upload_to_github.ps1      ← PowerShell 脚本（推荐）
├── upload_to_github.bat      ← CMD 脚本
└── ... 其他文件
```

---

## 🎯 方式 1：使用 PowerShell（推荐）⭐⭐⭐

### 步骤 1：打开 PowerShell

**方法 A：从文件管理器打开**
1. 打开文件管理器
2. 导航到 `c:\Users\cuigu\novel_writing_agent`
3. 在空白处右键点击
4. 选择 "在此处打开 PowerShell 窗口"

**方法 B：从开始菜单打开**
1. 按 `Win + R`
2. 输入 `powershell`
3. 按 Enter

**方法 C：从 VS Code 打开**
1. 打开 VS Code
2. 打开项目文件夹
3. 按 `Ctrl + ~` 打开终端
4. 确保终端在项目根目录

### 步骤 2：运行脚本

在 PowerShell 中输入以下命令：

```powershell
.\upload_to_github.ps1
```

然后按 Enter

### 步骤 3：按照提示操作

脚本会自动：
1. ✅ 检查 Git 是否安装
2. ✅ 初始化 Git 仓库（如果需要）
3. ✅ 配置 Git 用户信息（如果需要）
4. ✅ 添加所有文件
5. ✅ 创建首次提交
6. ✅ 要求输入 GitHub 仓库 URL

### 步骤 4：输入 GitHub 仓库 URL

脚本会提示：
```
请输入 GitHub 仓库 URL:
例如: git@github.com:username/novel_writing_agent.git
或: https://github.com/username/novel_writing_agent.git
```

**复制以下之一并粘贴**：

**HTTPS 方式**（简单，推荐新手）：
```
https://github.com/你的用户名/novel_writing_agent.git
```

**SSH 方式**（需要配置 SSH 密钥）：
```
git@github.com:你的用户名/novel_writing_agent.git
```

### 步骤 5：等待完成

脚本会自动推送到 GitHub，显示：
```
✅ 推送成功！

🎉 项目已上传到 GitHub

📍 访问你的仓库:
https://github.com/你的用户名/novel_writing_agent
```

---

## 🎯 方式 2：使用 CMD

### 步骤 1：打开 CMD

**方法 A：从文件管理器打开**
1. 打开文件管理器
2. 导航到 `c:\Users\cuigu\novel_writing_agent`
3. 在地址栏输入 `cmd`
4. 按 Enter

**方法 B：从开始菜单打开**
1. 按 `Win + R`
2. 输入 `cmd`
3. 按 Enter
4. 输入 `cd c:\Users\cuigu\novel_writing_agent`

### 步骤 2：运行脚本

在 CMD 中输入：

```cmd
upload_to_github.bat
```

然后按 Enter

### 步骤 3：按照提示操作

与 PowerShell 方式相同

---

## 🎯 方式 3：从 VS Code 打开

### 步骤 1：打开 VS Code

1. 打开 VS Code
2. 点击 "File" → "Open Folder"
3. 选择 `c:\Users\cuigu\novel_writing_agent`
4. 点击 "Select Folder"

### 步骤 2：打开终端

按 `Ctrl + ~` 或点击 "Terminal" → "New Terminal"

### 步骤 3：运行脚本

在终端中输入：

```powershell
.\upload_to_github.ps1
```

按 Enter

### 步骤 4：按照提示操作

与之前相同

---

## 📸 详细步骤截图说明

### 步骤 1：打开文件管理器
```
C:\Users\cuigu\novel_writing_agent
│
├── upload_to_github.ps1      ← 这个文件
├── upload_to_github.bat      ← 或这个文件
└── ... 其他文件
```

### 步骤 2：在此处打开 PowerShell
```
右键点击空白处
↓
选择 "在此处打开 PowerShell 窗口"
↓
PowerShell 窗口打开
```

### 步骤 3：运行脚本
```
PowerShell 窗口中输入：
.\upload_to_github.ps1
↓
按 Enter
↓
脚本开始运行
```

### 步骤 4：输入 GitHub URL
```
脚本提示输入 GitHub 仓库 URL
↓
粘贴：https://github.com/你的用户名/novel_writing_agent.git
↓
按 Enter
↓
自动上传
```

---

## ⚠️ 常见问题

### 问题 1：PowerShell 显示"无法加载脚本"

**错误信息**：
```
无法加载文件 C:\Users\cuigu\novel_writing_agent\upload_to_github.ps1，
因为在此系统上禁止运行脚本。
```

**解决方案**：
1. 以管理员身份打开 PowerShell
2. 输入以下命令：
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```
3. 输入 `Y` 并按 Enter
4. 重新运行脚本

### 问题 2：Git 命令不识别

**错误信息**：
```
git : 无法将"git"项识别为 cmdlet、函数、脚本文件或可运行程序的名称
```

**解决方案**：
1. 安装 Git：https://git-scm.com/download/win
2. 安装时勾选 "Add Git to PATH"
3. 重启 PowerShell/CMD
4. 重新运行脚本

### 问题 3：脚本找不到

**错误信息**：
```
无法找到文件 'upload_to_github.ps1'
```

**解决方案**：
1. 确保你在正确的目录：`c:\Users\cuigu\novel_writing_agent`
2. 输入 `ls` 或 `dir` 查看文件列表
3. 确保 `upload_to_github.ps1` 在列表中
4. 重新运行脚本

### 问题 4：推送失败

**错误信息**：
```
fatal: 'origin' does not appear to be a 'git' repository
```

**解决方案**：
1. 检查 GitHub 仓库 URL 是否正确
2. 确保仓库已在 GitHub 创建
3. 检查网络连接
4. 重新运行脚本

---

## ✅ 验证上传成功

### 方法 1：查看 PowerShell 输出

脚本完成后应该显示：
```
✅ 推送成功！

🎉 项目已上传到 GitHub

📍 访问你的仓库:
https://github.com/你的用户名/novel_writing_agent
```

### 方法 2：访问 GitHub

1. 打开浏览器
2. 访问 `https://github.com/你的用户名/novel_writing_agent`
3. 应该能看到你的代码

### 方法 3：查看提交历史

在 PowerShell 中输入：
```powershell
git log --oneline
```

应该显示你的提交

---

## 🎯 完整流程总结

```
1. 打开文件管理器
   ↓
2. 导航到 c:\Users\cuigu\novel_writing_agent
   ↓
3. 右键 → "在此处打开 PowerShell 窗口"
   ↓
4. 输入：.\upload_to_github.ps1
   ↓
5. 按 Enter
   ↓
6. 输入 GitHub 仓库 URL
   ↓
7. 按 Enter
   ↓
8. 等待完成
   ↓
9. 🎉 上传成功！
```

---

## 📝 需要的信息

运行脚本前，请准备好：

- [ ] GitHub 账户已创建
- [ ] GitHub 仓库已创建（名称：`novel_writing_agent`）
- [ ] 知道你的 GitHub 用户名
- [ ] 知道你的 GitHub 仓库 URL

---

## 🚀 现在就开始吧！

### 快速命令

**打开文件管理器**：
```
Win + E
```

**导航到项目目录**：
```
c:\Users\cuigu\novel_writing_agent
```

**右键打开 PowerShell**：
```
右键 → 在此处打开 PowerShell 窗口
```

**运行脚本**：
```
.\upload_to_github.ps1
```

---

## 💡 提示

- 🔑 如果没有配置 SSH 密钥，使用 HTTPS 方式
- 📝 提交信息可以自定义
- 🔄 脚本会自动处理所有 Git 操作
- ✅ 脚本完全安全，不会删除任何文件

---

**准备好了吗？** 现在就打开文件管理器，运行脚本吧！ 🚀

**最后更新**：2025-11-12


