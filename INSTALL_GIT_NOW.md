# 📥 立即安装 Git - 完整步骤

**诊断结果**：Git 命令行工具未安装

**你有**：GitHub Desktop（图形界面）
**你需要**：Git for Windows（命令行工具）

---

## 🚀 快速安装（5 分钟）

### 步骤 1️⃣：下载 Git

**直接下载链接**：
```
https://git-scm.com/download/win
```

**或者点击这个链接**：
```
https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0.1-64-bit.exe
```

**推荐**：64 位版本

---

### 步骤 2️⃣：运行安装程序

1. 找到下载的 `Git-2.43.0.1-64-bit.exe` 文件
2. 双击运行
3. 点击 "Next" 继续

---

### 步骤 3️⃣：选择安装位置

**默认位置**：`C:\Program Files\Git`

✅ **保持默认，点击 "Next"**

---

### 步骤 4️⃣：选择组件

**确保勾选**：
- ✅ Git Bash Here
- ✅ Git GUI Here
- ✅ Git LFS (Large File Support)

点击 "Next"

---

### 步骤 5️⃣：选择开始菜单文件夹

**默认**：Git

✅ **保持默认，点击 "Next"**

---

### 步骤 6️⃣：选择默认编辑器

**推荐**：Use Vim (the ubiquitous text editor) as Git's default editor

点击 "Next"

---

### 步骤 7️⃣：调整 PATH 环境变量

**⚠️ 这一步很重要！**

**选择第二个选项**：
```
Git from the command line and also from 3rd-party software
```

这样 PowerShell 和 CMD 都能识别 git 命令

✅ **点击 "Next"**

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

### 方法 1：关闭所有 PowerShell 窗口

```
1. 关闭当前 PowerShell 窗口
2. 关闭所有其他 PowerShell 窗口
3. 重新打开 PowerShell
```

### 方法 2：验证 Git

```powershell
git --version
```

**应该看到**：
```
git version 2.43.0.windows.1
```

---

## 🎯 安装完成后

### 配置 Git 用户信息

```powershell
git config --global user.name "Your Name"
git config --global user.email "your.email@example.com"
```

### 验证配置

```powershell
git config --global user.name
git config --global user.email
```

---

## 📋 完整流程

```
1. 下载 Git
   ↓
2. 运行安装程序
   ↓
3. 按照步骤安装
   ↓
4. 重要：选择 "Git from the command line and also from 3rd-party software"
   ↓
5. 完成安装
   ↓
6. 关闭所有 PowerShell 窗口
   ↓
7. 打开新的 PowerShell 窗口
   ↓
8. 验证：git --version
   ↓
9. 配置用户信息
   ↓
10. 上传项目：.\upload_to_github_simple.ps1
```

---

## ⚠️ 常见问题

### Q1：安装后仍然显示 "git 无法被识别"

**A**：
1. 关闭所有 PowerShell 窗口
2. 重新打开 PowerShell
3. 再试一次

### Q2：安装时没有看到 "Add to PATH" 选项

**A**：
1. 重新运行安装程序
2. 选择 "Modify"
3. 确保选择 "Git from the command line and also from 3rd-party software"

### Q3：安装程序卡住了

**A**：
1. 等待 5-10 分钟
2. 如果仍然卡住，关闭并重新运行

### Q4：需要卸载旧版本吗？

**A**：不需要，新版本会覆盖旧版本

---

## 🔗 下载链接

| 版本 | 链接 |
|------|------|
| 64 位（推荐） | https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0.1-64-bit.exe |
| 32 位 | https://github.com/git-for-windows/git/releases/download/v2.43.0.windows.1/Git-2.43.0.1-32-bit.exe |
| 官方网站 | https://git-scm.com/download/win |

---

## 📚 相关文档

- `GIT_INSTALLATION_GUIDE.md` - 详细安装指南
- `GIT_NOT_FOUND_SOLUTION.md` - 故障排除
- `FINAL_UPLOAD_GUIDE.md` - 上传指南

---

## 🚀 现在就安装

1. **下载 Git**：https://git-scm.com/download/win
2. **运行安装程序**
3. **按照步骤安装**
4. **重启 PowerShell**
5. **验证**：`git --version`
6. **上传项目**：`.\upload_to_github_simple.ps1`

---

**准备好了吗？** 现在就下载并安装 Git 吧！ 🚀

**最后更新**：2025-11-12


