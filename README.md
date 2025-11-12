﻿# 小说写作Agent - 多Agent协作框架

一个**完整的、生产级别的多Agent协作系统**，用于智能小说创作。使用LangChain框架构建，集成了向量数据库（Chroma）进行知识管理。

> 🚀 **新手？[从这里开始！](START_HERE.md)** ← 5分钟快速上手
> 📚 **完整文档** - [快速开始](MULTI_AGENT_QUICKSTART.md) | [完整指南](MULTI_AGENT_GUIDE.md) | [API参考](API_REFERENCE.md) | [完整索引](INDEX.md)

## 🎯 核心特性

### 单Agent模式（原始功能）
- **知识库管理**：使用向量数据库存储和检索小说设定、人物档案、已写章节
- **记忆管理**：维护对话上下文，理解当前写作状态
- **智能检索**：根据用户请求自动检索相关信息
- **增强生成**：将检索到的信息与用户请求结合，生成高质量内容

### 多Agent模式（新增功能）✨
- **9个专业化Agent**：创意总监、世界观架构师、人物设计师、情节架构师、内容创作师、质量评审官、事件验证官、文风优化师、迭代协调官
- **五阶段工作流程**：概念开发 → 结构设计 → 内容创作 → 质量评审 → 迭代优化
- **智能任务分解**：自动分析需求，分配给合适的Agent
- **Agent通信系统**：支持Agent间的消息传递和协作
- **项目管理**：完整的项目生命周期管理、任务分配、进度追踪
- **质量控制**：多维度质量评估系统，自动检测问题并迭代优化
- **前后端分离架构**：Vite + TypeScript前端 + Python后端，支持Web界面操作

### 技术栈
- **编程语言**：Python 3.8+
- **后端框架**：LangChain
- **向量数据库**：ChromaDB
- **LLM**：支持OpenAI API或本地模型（Qwen2, Llama3等）
- **Embedding**：支持阿里云百炼、OpenAI或本地模型
- **前端框架**：TypeScript + Vite + React + Redux Toolkit + Material-UI
- **数据库**：SQLite（开发环境）
- **API服务**：RESTful API + 异步任务队列

## 项目结构

```
novel_writing_agent/
├── 核心框架（新增）
│   ├── agents.py                    # 6个专业化Agent定义
│   ├── agent_coordinator.py         # 主编Agent协调器
│   ├── multi_agent_framework.py     # 多Agent框架核心
│   ├── agent_communication.py       # Agent通信系统
│   └── project_manager.py           # 项目管理系统
│
├── 原始文件
│   ├── config.py                   # 配置管理
│   ├── knowledge_base.py            # 知识库管理（向量数据库）
│   ├── memory_manager.py            # 记忆管理器
│   ├── novel_agent.py               # 单Agent实现 
│   └── requirements.txt             # 依赖包
│
├── 示例代码（新增）
│   ├── multi_agent_example.py       # 基础示例（4个场景）
│   └── advanced_example.py          # 高级示例（5个场景）
│
├── 文档（新增）
│   ├── MULTI_AGENT_GUIDE.md        # 完整使用指南
│   ├── MULTI_AGENT_QUICKSTART.md   # 5分钟快速开始
│   ├── ARCHITECTURE.md              # 详细架构设计
│   ├── API_REFERENCE.md             # 完整API参考
│   ├── MULTI_AGENT_SUMMARY.md      # 项目总结
│   └── IMPLEMENTATION_COMPLETE.md   # 实现完成说明
│
└── 其他
    ├── .env.example                 # 环境变量示例
    ├── example.py                   # 原始示例
    └── README.md                    # 本文件
```

## 🚀 快速开始

### ⚡ 一键启动（强烈推荐）

**Windows用户**：
```bash
dev.bat
```

**系统会自动**：
1. ✅ 检查 Python 和 Node.js 是否安装
2. ✅ 检查并安装后端依赖（requirements.txt）
3. ✅ 检查并安装前端依赖（npm install）
4. ✅ 验证配置文件（.env）
5. ✅ 启动后端服务（端口 8000）
6. ✅ 启动前端服务（端口 5173）

**访问地址**：
- 🌐 前端：http://localhost:5173
- 🔧 后端：http://localhost:8000
- 📚 API文档：http://localhost:8000/docs

---

### 🛠️ 手动启动（高级用户）

#### 1. 安装依赖

```bash
# 安装后端依赖
pip install -r requirements.txt

# 安装后端服务依赖
cd backend
pip install -r requirements.txt
cd ..

# 安装前端依赖
cd frontend
npm install
cd ..
```

#### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env
cp backend/.env.example backend/.env

# 编辑 .env 文件，填入你的 API Key
# 编辑 backend/.env 文件，填入你的 API Key
```

#### 3. 启动服务

```bash
# 启动后端服务
python simple_backend_server.py

# 在另一个终端启动前端服务
cd frontend
npm run dev
```

---

## 🔧 配置说明

### LLM配置

项目支持多种大语言模型：

1. **DeepSeek**（默认）：
   ```env
   DEEPSEEK_API_KEY=your_deepseek_api_key
   MODEL_NAME=deepseek-reasoner
   ```

2. **OpenAI**：
   ```env
   DEEPSEEK_API_KEY=your_openai_api_key
   MODEL_NAME=gpt-4
   ```

3. **本地模型**（如Ollama）：
   ```env
   LOCAL_MODEL_URL=http://localhost:11434
   MODEL_NAME=qwen2:latest
   ```

### Embedding配置

项目支持多种Embedding模型：

1. **阿里云百炼**（推荐）：
   ```env
   DASHSCOPE_API_KEY=your_dashscope_api_key
   EMBEDDING_MODEL=text-embedding-v4
   ```

2. **OpenAI**：
   ```env
   EMBEDDING_API_KEY=your_openai_api_key
   EMBEDDING_MODEL=text-embedding-ada-002
   ```

3. **本地模型**：
   ```env
   EMBEDDING_MODEL=local
   ```

---

## 📖 文档导航

- 🚀 [快速开始指南](START_HERE.md)
- 📚 [多Agent完整指南](MULTI_AGENT_GUIDE.md)
- 🏗️ [架构设计文档](ARCHITECTURE.md)
- 🔌 [API参考文档](API_REFERENCE.md)
- 🧪 [测试脚本](test_*.py)

---

## 🎯 最佳实践

### 1. 使用阿里云百炼Embedding

阿里云百炼的text-embedding-v4模型具有以下优势：
- 支持100+种语言
- 2048维向量，语义表达更丰富
- 高性能，低延迟
- 价格合理

### 2. 项目隔离

每个小说项目都有独立的知识库，确保：
- 不同项目的数据完全隔离
- 可以并行创作多个小说
- 避免内容混淆

### 3. 知识库优化

系统包含多种优化机制：
- 智能缓存：避免重复计算
- 相关性过滤：提高搜索质量
- 动态k值：根据内容类型调整返回结果数

---

## 🐛 故障排除

### 1. Embedding API调用失败

如果看到以下警告：
```
Warning: Aliyun Embedding API call failed, using fallback vector
```

请检查：
- DASHSCOPE_API_KEY是否正确配置
- 网络连接是否正常
- API配额是否充足

### 2. 启动失败

如果服务启动失败，请检查：
- 端口是否被占用
- 依赖是否完整安装
- 环境变量是否正确配置

---

## 📞 获取帮助

1. **查看文档** - 从 [START_HERE.md](START_HERE.md) 开始
2. **运行示例** - `python multi_agent_example.py`
3. **查看API** - [API_REFERENCE.md](API_REFERENCE.md)
4. **查看源代码** - 查看源文件中的注释

---

## 📄 许可证

MIT License

---

**版本**: 1.0.0  
**最后更新**: 2025年