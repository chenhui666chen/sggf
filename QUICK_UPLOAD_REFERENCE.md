# ⚡ 快速上传参考卡

**最快的上传方式 - 只需 5 分钟！**

---

## 🎯 3 步快速上传

### 1️⃣ 打开 PowerShell
```
按 Win + E 打开文件管理器
↓
导航到：c:\Users\cuigu\novel_writing_agent
↓
右键点击空白处
↓
选择 "在此处打开 PowerShell 窗口"
```

### 2️⃣ 运行脚本
```powershell
.\upload_to_github.ps1
```
按 Enter

### 3️⃣ 输入 GitHub URL
```
https://github.com/你的用户名/novel_writing_agent.git
```
按 Enter

**完成！** 🎉

---

## 📍 脚本位置

```
c:\Users\cuigu\novel_writing_agent\
├── upload_to_github.ps1      ← PowerShell 脚本
├── upload_to_github.bat      ← CMD 脚本
└── ... 其他文件
```

---

## 🚀 三种运行方式

### 方式 1：PowerShell（推荐）
```powershell
# 在项目目录打开 PowerShell
.\upload_to_github.ps1
```

### 方式 2：CMD
```cmd
# 在项目目录打开 CMD
upload_to_github.bat
```

### 方式 3：VS Code
```bash
# 打开 VS Code
# 打开项目文件夹
# 按 Ctrl + ~
# 输入：.\upload_to_github.ps1
```

---

## 📝 脚本会做什么

```
✅ 检查 Git 是否安装
✅ 初始化 Git 仓库
✅ 配置 Git 用户信息
✅ 添加所有文件
✅ 创建首次提交
✅ 添加远程仓库
✅ 推送到 GitHub
```

---

## 🔑 需要的信息

- [ ] GitHub 账户已创建
- [ ] GitHub 仓库已创建（名称：novel_writing_agent）
- [ ] 知道你的 GitHub 用户名

---

## 📋 GitHub URL 格式

### HTTPS（推荐新手）
```
https://github.com/你的用户名/novel_writing_agent.git
```

### SSH（需要配置密钥）
```
git@github.com:你的用户名/novel_writing_agent.git
```

---

## ⚠️ 常见问题速解

### Q1：PowerShell 无法运行脚本
```powershell
# 以管理员身份运行 PowerShell，然后输入：
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
# 输入 Y 并按 Enter
```

### Q2：Git 未安装
```
下载：https://git-scm.com/download/win
安装时勾选 "Add to PATH"
重启 PowerShell
```

### Q3：找不到脚本
```
确保在正确的目录：c:\Users\cuigu\novel_writing_agent
输入 ls 查看文件列表
```

### Q4：推送失败
```
检查 GitHub URL 是否正确
检查网络连接
重新运行脚本
```

---

## ✅ 验证上传

### 方法 1：查看脚本输出
```
✅ 推送成功！
🎉 项目已上传到 GitHub
```

### 方法 2：访问 GitHub
```
https://github.com/你的用户名/novel_writing_agent
```

### 方法 3：查看提交历史
```powershell
git log --oneline
```

---

## 🎯 完整命令序列

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

# 6. 按 Enter 完成
```

---

## 📚 详细文档

| 文档 | 说明 |
|------|------|
| `RUN_UPLOAD_SCRIPT.md` | 详细的运行指南 |
| `VISUAL_UPLOAD_GUIDE.md` | 可视化步骤指南 |
| `GITHUB_UPLOAD_STEPS.md` | 分步上传指南 |
| `GITHUB_UPLOAD_GUIDE.md` | 完整的上传指南 |

---

## 🚀 现在就开始

```
1. 按 Win + E
2. 导航到项目目录
3. 右键打开 PowerShell
4. 输入：.\upload_to_github.ps1
5. 按 Enter
6. 输入 GitHub URL
7. 完成！
```

---

**最后更新**：2025-11-12


