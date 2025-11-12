# 📤 项目上传到 GitHub 完整指南

**最后更新**：2025-11-12

---

## 📋 前置要求

### 1. 安装 Git
- **Windows**：下载 [Git for Windows](https://git-scm.com/download/win)
- **Mac**：`brew install git`
- **Linux**：`sudo apt-get install git`

### 2. 配置 Git
```bash
git config --global user.name "你的名字"
git config --global user.email "你的邮箱@example.com"
```

### 3. 创建 GitHub 账户
- 访问 [GitHub.com](https://github.com)
- 注册账户（如果还没有）

### 4. 生成 SSH 密钥（推荐）
```bash
ssh-keygen -t ed25519 -C "你的邮箱@example.com"
# 或者使用 RSA
ssh-keygen -t rsa -b 4096 -C "你的邮箱@example.com"
```

然后将公钥添加到 GitHub：
1. 复制 `~/.ssh/id_ed25519.pub` 的内容
2. 访问 GitHub Settings → SSH and GPG keys
3. 点击 "New SSH key"，粘贴公钥

---

## 🚀 上传步骤

### 方式 1：从本地项目上传（推荐）

#### 步骤 1：初始化 Git 仓库
```bash
cd c:\Users\cuigu\novel_writing_agent
git init
```

#### 步骤 2：添加所有文件
```bash
git add .
```

#### 步骤 3：创建首次提交
```bash
git commit -m "Initial commit: Novel writing agent with AI trace reduction"
```

#### 步骤 4：在 GitHub 创建新仓库
1. 登录 GitHub
2. 点击右上角 "+" → "New repository"
3. 填写仓库信息：
   - **Repository name**：`novel_writing_agent`
   - **Description**：`AI-powered novel writing agent with AI trace reduction system`
   - **Public/Private**：选择 Public（公开）或 Private（私有）
   - **Initialize this repository with**：不勾选（因为我们已有本地代码）
4. 点击 "Create repository"

#### 步骤 5：添加远程仓库
```bash
git remote add origin git@github.com:你的用户名/novel_writing_agent.git
```

或者使用 HTTPS（如果没有配置 SSH）：
```bash
git remote add origin https://github.com/你的用户名/novel_writing_agent.git
```

#### 步骤 6：推送到 GitHub
```bash
git branch -M main
git push -u origin main
```

---

### 方式 2：使用 GitHub Desktop（图形界面）

#### 步骤 1：下载 GitHub Desktop
- 访问 [desktop.github.com](https://desktop.github.com)
- 下载并安装

#### 步骤 2：登录 GitHub
- 打开 GitHub Desktop
- 点击 "Sign in to GitHub.com"
- 输入用户名和密码

#### 步骤 3：创建本地仓库
- 点击 "File" → "New Repository"
- 填写信息：
  - **Name**：`novel_writing_agent`
  - **Local Path**：`c:\Users\cuigu\novel_writing_agent`
  - **Initialize this repository with a README**：可选
- 点击 "Create Repository"

#### 步骤 4：提交更改
- 在 "Changes" 标签中，所有文件应该显示为新增
- 在 "Summary" 中输入：`Initial commit`
- 点击 "Commit to main"

#### 步骤 5：发布到 GitHub
- 点击 "Publish repository"
- 选择 Public 或 Private
- 点击 "Publish Repository"

---

## 📝 .gitignore 配置

创建 `.gitignore` 文件来排除不需要上传的文件：

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
env/
venv/
ENV/
build/
develop-eggs/
dist/
downloads/
eggs/
.eggs/
lib/
lib64/
parts/
sdist/
var/
wheels/
*.egg-info/
.installed.cfg
*.egg

# Node.js
node_modules/
npm-debug.log
yarn-error.log
dist/
build/

# IDE
.vscode/
.idea/
*.swp
*.swo
*~
.DS_Store

# Environment
.env
.env.local
.env.*.local

# Database
*.db
*.sqlite
*.sqlite3

# Logs
logs/
*.log

# Temporary files
tmp/
temp/
*.tmp

# OS
.DS_Store
Thumbs.db
```

---

## 🔍 验证上传

### 检查远程仓库
```bash
git remote -v
```

应该显示：
```
origin  git@github.com:你的用户名/novel_writing_agent.git (fetch)
origin  git@github.com:你的用户名/novel_writing_agent.git (push)
```

### 查看提交历史
```bash
git log --oneline
```

### 访问 GitHub 仓库
- 打开浏览器
- 访问 `https://github.com/你的用户名/novel_writing_agent`
- 应该能看到你的代码

---

## 📚 项目结构说明

上传后，你的 GitHub 仓库应该包含：

```
novel_writing_agent/
├── backend/                          # 后端代码
│   ├── app/
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   └── main.py
│   ├── requirements.txt
│   └── .env.example
├── frontend/                         # 前端代码
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── services/
│   │   └── App.tsx
│   ├── package.json
│   └── vite.config.ts
├── novel_writing_agent/              # AI 痕迹降低模块
│   ├── ai_trace_reduction_processor.py
│   ├── author_voice_system.py
│   ├── dialogue_authenticity_module.py
│   └── agent_coordinator.py
├── README.md                         # 项目说明
├── .gitignore                        # Git 忽略文件
└── GITHUB_UPLOAD_GUIDE.md           # 本文件
```

---

## 📖 创建 README.md

创建一个好的 README 文件，让别人了解你的项目：

```markdown
# 🎭 Novel Writing Agent

AI-powered novel writing agent with advanced AI trace reduction system.

## ✨ Features

- 🤖 Multi-agent creative system
- 🎨 AI trace reduction (4-layer refinement)
- 📚 Chapter management
- 🔄 Real-time generation
- 💾 Knowledge base integration

## 🚀 Quick Start

### Backend
```bash
cd backend
pip install -r requirements.txt
python -m uvicorn app.main:app --reload
```

### Frontend
```bash
cd frontend
npm install
npm run dev
```

## 📋 Requirements

- Python 3.8+
- Node.js 16+
- PostgreSQL 12+

## 📝 License

MIT License

## 👤 Author

Your Name
```

---

## 🔐 安全建议

### 1. 不要上传敏感信息
- ❌ API 密钥
- ❌ 数据库密码
- ❌ 个人信息

### 2. 使用 .env 文件
```bash
# .env.example（上传这个）
DATABASE_URL=postgresql://user:password@localhost/dbname
API_KEY=your_api_key_here

# .env（不上传这个）
DATABASE_URL=postgresql://actual_user:actual_password@localhost/actual_db
API_KEY=actual_api_key
```

### 3. 添加到 .gitignore
```
.env
.env.local
*.key
*.pem
```

---

## 🆘 常见问题

### Q1：如何修改已上传的文件？
```bash
# 修改文件后
git add .
git commit -m "Update: description of changes"
git push origin main
```

### Q2：如何删除已上传的文件？
```bash
git rm filename
git commit -m "Remove: filename"
git push origin main
```

### Q3：如何回滚到之前的版本？
```bash
git log --oneline
git revert <commit-hash>
git push origin main
```

### Q4：如何克隆仓库？
```bash
git clone git@github.com:你的用户名/novel_writing_agent.git
# 或
git clone https://github.com/你的用户名/novel_writing_agent.git
```

### Q5：如何更新本地仓库？
```bash
git pull origin main
```

---

## 📊 推荐的 GitHub 设置

### 1. 添加 README.md
- 项目说明
- 快速开始指南
- 功能列表

### 2. 添加 LICENSE
- 选择合适的开源协议（MIT、Apache 2.0 等）

### 3. 添加 CONTRIBUTING.md
- 贡献指南
- 代码规范

### 4. 启用 GitHub Pages
- 用于项目文档
- 设置：Settings → Pages

### 5. 设置 Branch Protection
- 保护 main 分支
- 要求 Pull Request 审查

---

## 🎯 下一步

1. ✅ 安装 Git
2. ✅ 配置 Git 用户信息
3. ✅ 创建 GitHub 账户
4. ✅ 生成 SSH 密钥
5. ✅ 初始化本地仓库
6. ✅ 创建 GitHub 仓库
7. ✅ 推送代码
8. ✅ 验证上传

---

## 📞 需要帮助？

- [GitHub 官方文档](https://docs.github.com)
- [Git 官方文档](https://git-scm.com/doc)
- [GitHub 社区论坛](https://github.community)

---

**准备好了吗？让我们开始上传吧！** 🚀


