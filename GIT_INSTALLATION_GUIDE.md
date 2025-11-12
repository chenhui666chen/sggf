# 📥 Git 安装指南

**Git 未安装。** 按照以下步骤安装 Git，然后就可以上传项目到 GitHub 了。

---

## 🚀 快速安装（5 分钟）

### 步骤 1️⃣：下载 Git

访问官方网站：
```
https://git-scm.com/download/win
```

**或者直接点击下载**：
- 64 位：https://github.com/git-for-windows/git/releases/download/v2.42.0.windows.2/Git-2.42.0.2-64-bit.exe
- 32 位：https://github.com/git-for-windows/git/releases/download/v2.42.0.windows.2/Git-2.42.0.2-32-bit.exe

**推荐**：下载 64 位版本

---

### 步骤 2️⃣：运行安装程序

1. 找到下载的 `Git-xxx-64-bit.exe` 文件
2. 双击运行
3. 点击 "Next" 继续

---

### 步骤 3️⃣：选择安装位置

**默认位置**：`C:\Program Files\Git`

✅ 保持默认，点击 "Next"

---

### 步骤 4️⃣：选择组件

**重要**：确保勾选以下项目：

- ✅ Git Bash Here
- ✅ Git GUI Here
- ✅ Git LFS (Large File Support)
- ✅ Associate .git* configuration files with the default text editor
- ✅ Associate .sh files to be run with Bash

点击 "Next"

---

### 步骤 5️⃣：选择开始菜单文件夹

**默认**：Git

✅ 保持默认，点击 "Next"

---

### 步骤 6️⃣：选择默认编辑器

**推荐**：Use Vim (the ubiquitous text editor) as Git's default editor

或者选择你喜欢的编辑器

点击 "Next"

---

### 步骤 7️⃣：调整 PATH 环境变量

**重要**：选择第二个选项

```
Git from the command line and also from 3rd-party software
```

这样 PowerShell 和 CMD 都能识别 git 命令

点击 "Next"

---

### 步骤 8️⃣：选择 HTTPS 传输后端

**推荐**：Use the native Windows Secure Channel library

点击 "Next"

---

### 步骤 9️⃣：配置行尾转换

**推荐**：Checkout as-is, commit as-is

点击 "Next"

---

### 步骤 🔟：选择终端模拟器

**推荐**：Use Windows' default console window

点击 "Next"

---

### 步骤 1️⃣1️⃣：选择 Git Pull 行为

**推荐**：Default (fast-forward or merge)

点击 "Next"

---

### 步骤 1️⃣2️⃣：选择凭证管理器

**推荐**：Git Credential Manager

点击 "Next"

---

### 步骤 1️⃣3️⃣：额外选项

**推荐**：
- ✅ Enable file system caching
- ✅ Enable symbolic links

点击 "Next"

---

### 步骤 1️⃣4️⃣：完成安装

点击 "Install"

等待安装完成...

---

## ✅ 验证安装

### 方法 1：PowerShell

```powershell
# 打开 PowerShell
git --version
```

应该看到：
```
git version 2.42.0.windows.2
```

### 方法 2：CMD

```cmd
# 打开 CMD
git --version
```

应该看到相同的版本信息

---

## ⚠️ 如果 Git 仍未被识别

### 原因
PATH 环境变量未更新

### 解决方案

**方法 1：重启计算机**
```
最简单的方法 - 重启后 PATH 会自动更新
```

**方法 2：重启 PowerShell**
```
关闭 PowerShell
重新打开 PowerShell
```

**方法 3：手动添加到 PATH**

1. 按 Win + X
2. 选择 "系统"
3. 点击 "高级系统设置"
4. 点击 "环境变量"
5. 在 "系统变量" 中找到 "Path"
6. 点击 "编辑"
7. 点击 "新建"
8. 输入：`C:\Program Files\Git\cmd`
9. 点击 "确定"
10. 重启 PowerShell

---

## 🎯 安装完成后

### 配置 Git 用户信息

```powershell
# 设置用户名
git config --global user.name "Your Name"

# 设置邮箱
git config --global user.email "your.email@example.com"
```

### 验证配置

```powershell
git config --global user.name
git config --global user.email
```

---

## 🚀 现在上传项目

安装完 Git 后，运行上传脚本：

```powershell
# 打开 PowerShell
# 导航到项目目录
cd c:\Users\cuigu\novel_writing_agent

# 运行脚本
.\upload_to_github_simple.ps1
```

---

## 📋 完整流程

```
1. 下载 Git
   ↓
2. 运行安装程序
   ↓
3. 按照步骤安装（保持默认设置）
   ↓
4. 重启 PowerShell
   ↓
5. 验证：git --version
   ↓
6. 配置用户信息
   ↓
7. 运行上传脚本
   ↓
8. 完成！
```

---

## 🔗 相关链接

- **Git 官方网站**：https://git-scm.com
- **Git 下载页面**：https://git-scm.com/download/win
- **GitHub**：https://github.com

---

## 💡 提示

- 安装时保持默认设置即可
- 最重要的是：选择 "Git from the command line and also from 3rd-party software"
- 安装后需要重启 PowerShell 或计算机

---

## ✨ 安装完成后

```
✅ Git 已安装
✅ 可以使用 git 命令
✅ 可以上传项目到 GitHub
✅ 准备就绪！
```

---

**现在就下载并安装 Git 吧！** 🚀

**最后更新**：2025-11-12


