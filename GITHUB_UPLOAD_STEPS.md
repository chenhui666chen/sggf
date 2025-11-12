# 📤 GitHub 上传 - 分步指南

**快速上传你的项目到 GitHub**

---

## 🎯 5 分钟快速上传

### 步骤 1：安装 Git（如果还没有）
- 下载：https://git-scm.com/download/win
- 安装时选择默认选项即可

### 步骤 2：配置 Git 用户信息
打开 PowerShell 或 CMD，运行：
```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱@example.com"
```

### 步骤 3：创建 GitHub 仓库
1. 登录 [GitHub.com](https://github.com)
2. 点击右上角 "+" → "New repository"
3. 填写信息：
   - **Repository name**: `novel_writing_agent`
   - **Description**: `AI-powered novel writing agent with AI trace reduction`
   - **Public**: 选择公开或私有
4. 点击 "Create repository"

### 步骤 4：运行上传脚本
在项目目录打开 PowerShell，运行：
```bash
.\upload_to_github.ps1
```

或者使用 CMD：
```bash
upload_to_github.bat
```

### 步骤 5：输入 GitHub 仓库 URL
脚本会提示输入仓库 URL，复制以下之一：

**SSH 方式**（推荐，需要配置 SSH 密钥）：
```
git@github.com:你的用户名/novel_writing_agent.git
```

**HTTPS 方式**（简单，但每次需要输入密码）：
```
https://github.com/你的用户名/novel_writing_agent.git
```

### 步骤 6：完成！
脚本会自动：
- ✅ 初始化 Git 仓库
- ✅ 添加所有文件
- ✅ 创建首次提交
- ✅ 推送到 GitHub

---

## 🔑 SSH 密钥配置（可选但推荐）

### 生成 SSH 密钥
```bash
ssh-keygen -t ed25519 -C "你的邮箱@example.com"
```

按 Enter 接受默认位置，不设置密码（或设置密码）

### 添加公钥到 GitHub
1. 复制公钥内容：
```bash
cat ~/.ssh/id_ed25519.pub
```

2. 访问 GitHub Settings → SSH and GPG keys
3. 点击 "New SSH key"
4. 粘贴公钥内容
5. 点击 "Add SSH key"

### 测试连接
```bash
ssh -T git@github.com
```

应该看到：
```
Hi username! You've successfully authenticated, but GitHub does not provide shell access.
```

---

## 📋 手动上传步骤（如果脚本不工作）

### 步骤 1：初始化仓库
```bash
cd c:\Users\cuigu\novel_writing_agent
git init
```

### 步骤 2：添加文件
```bash
git add .
```

### 步骤 3：创建首次提交
```bash
git commit -m "Initial commit: Novel writing agent with AI trace reduction"
```

### 步骤 4：添加远程仓库
```bash
git remote add origin https://github.com/你的用户名/novel_writing_agent.git
```

### 步骤 5：重命名分支
```bash
git branch -M main
```

### 步骤 6：推送到 GitHub
```bash
git push -u origin main
```

---

## 🆘 常见问题解决

### 问题 1：Git 命令不识别
**解决方案**：
1. 重新安装 Git
2. 安装时勾选 "Add Git to PATH"
3. 重启 PowerShell/CMD

### 问题 2：SSH 连接失败
**解决方案**：
1. 检查 SSH 密钥是否生成
2. 检查公钥是否添加到 GitHub
3. 使用 HTTPS 方式代替

### 问题 3：HTTPS 推送需要密码
**解决方案**：
1. 使用 GitHub Personal Access Token
2. 或配置 SSH 密钥
3. 或使用 GitHub Desktop

### 问题 4：推送被拒绝
**解决方案**：
```bash
# 拉取最新更改
git pull origin main

# 解决冲突后重新推送
git push origin main
```

### 问题 5：文件太大无法推送
**解决方案**：
1. 检查 .gitignore 是否正确
2. 删除大文件：
```bash
git rm --cached large_file
git commit -m "Remove large file"
```

---

## 📊 验证上传

### 检查本地仓库
```bash
# 查看远程仓库
git remote -v

# 查看提交历史
git log --oneline

# 查看当前分支
git branch -a
```

### 检查 GitHub 仓库
1. 访问 https://github.com/你的用户名/novel_writing_agent
2. 应该能看到你的代码
3. 检查文件是否完整

---

## 🔄 后续操作

### 更新代码
```bash
# 修改文件后
git add .
git commit -m "Update: description"
git push origin main
```

### 创建新分支
```bash
git checkout -b feature/new-feature
# 做一些修改
git add .
git commit -m "Add new feature"
git push origin feature/new-feature
```

### 克隆仓库
```bash
git clone https://github.com/你的用户名/novel_writing_agent.git
```

---

## 📝 .gitignore 说明

项目已包含 `.gitignore` 文件，会自动排除：
- ✅ `node_modules/` - Node 依赖
- ✅ `venv/` - Python 虚拟环境
- ✅ `.env` - 环境变量（敏感信息）
- ✅ `__pycache__/` - Python 缓存
- ✅ `.DS_Store` - macOS 文件
- ✅ `*.log` - 日志文件

---

## 🎯 推荐的 GitHub 设置

### 1. 添加 README.md
✅ 已包含 - 项目说明和快速开始

### 2. 添加 LICENSE
建议添加 MIT 许可证：
```bash
# 创建 LICENSE 文件
# 内容：https://opensource.org/licenses/MIT
```

### 3. 添加 .gitignore
✅ 已包含 - 排除不需要的文件

### 4. 启用 GitHub Pages（可选）
- Settings → Pages
- 选择 main 分支
- 选择 /root 或 /docs 文件夹

### 5. 设置分支保护（可选）
- Settings → Branches
- 添加规则保护 main 分支

---

## 📚 相关文件

| 文件 | 说明 |
|------|------|
| `GITHUB_UPLOAD_GUIDE.md` | 详细的上传指南 |
| `upload_to_github.bat` | Windows CMD 脚本 |
| `upload_to_github.ps1` | PowerShell 脚本 |
| `.gitignore` | Git 忽略文件配置 |
| `README.md` | 项目说明 |

---

## ✅ 检查清单

- [ ] 安装 Git
- [ ] 配置 Git 用户信息
- [ ] 创建 GitHub 账户
- [ ] 创建 GitHub 仓库
- [ ] 配置 SSH 密钥（可选）
- [ ] 运行上传脚本
- [ ] 验证 GitHub 仓库
- [ ] 添加 LICENSE（可选）
- [ ] 启用 GitHub Pages（可选）

---

## 🚀 现在就开始吧！

### 快速命令
```bash
# 进入项目目录
cd c:\Users\cuigu\novel_writing_agent

# 运行上传脚本
.\upload_to_github.ps1
```

或者使用 CMD：
```bash
upload_to_github.bat
```

---

**需要帮助？** 查看 [GITHUB_UPLOAD_GUIDE.md](GITHUB_UPLOAD_GUIDE.md) 获取更详细的信息。

**最后更新**：2025-11-12


