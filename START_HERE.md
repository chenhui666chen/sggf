。# 🚀 从这里开始 - 多Agent小说写作框架

欢迎使用**多Agent小说写作框架**！这是一个完整的、生产级别的AI协作系统，用于创作小说。

---

## ⚡ 30秒快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置API密钥
cp .env.example .env
# 编辑 .env 文件，填入你的 OPENAI_API_KEY

# 3. 运行示例
python multi_agent_example.py

# 4. 开始创作
python -c "from multi_agent_framework import MultiAgentNovelWritingFramework; \
framework = MultiAgentNovelWritingFramework(); \
framework.interactive_session()"
```

---

## 📚 选择你的学习路径

### 🟢 初级用户（5分钟）
**目标**: 快速了解框架能做什么

1. 阅读本文件的"核心概念"部分
2. 运行 `python multi_agent_example.py`
3. 查看 [MULTI_AGENT_QUICKSTART.md](MULTI_AGENT_QUICKSTART.md)

**预计时间**: 5-10分钟

### 🟡 中级用户（30分钟）
**目标**: 学会使用框架创作小说

1. 阅读 [MULTI_AGENT_GUIDE.md](MULTI_AGENT_GUIDE.md)
2. 运行 `python advanced_example.py`
3. 尝试 `framework.interactive_session()`
4. 查看 [API_REFERENCE.md](API_REFERENCE.md)

**预计时间**: 30-60分钟

### 🔴 高级用户（2小时）
**目标**: 掌握框架的所有功能，能够自定义和扩展

1. 阅读 [ARCHITECTURE.md](ARCHITECTURE.md)
2. 阅读 [API_REFERENCE.md](API_REFERENCE.md)
3. 查看源代码中的注释
4. 创建自定义Agent
5. 自定义工作流程

**预计时间**: 2-4小时

---

## 🎯 核心概念

### 什么是多Agent框架？

这个框架包含**9个专业化的AI Agent**，每个Agent都有特定的角色：

| Agent | 角色 | 职责 |
|-------|------|------|
| 💼 **创意总监** | CreativeDirectorAgent | 主题开发、流程管理、决策整合 |
| 🌍 **世界观架构师** | WorldArchitectAgent | 设计世界观、逻辑验证 |
| 👥 **人物设计师** | CharacterDesignerAgent | 创建和分析人物 |
| 📚 **情节架构师** | PlotArchitectAgent | 设计故事结构和情节 |
| ✍️ **内容创作师** | ContentCreatorAgent | 撰写具体内容 |
| 🔍 **质量评审官** | QualityReviewerAgent | 审核和评审内容 |
| ✅ **事件验证官** | EventValidatorAgent | 验证事件合理性 |
| 🎨 **文风优化师** | StyleOptimizerAgent | 优化语言表达 |
| 🔄 **迭代协调官** | IterationCoordinatorAgent | 协调迭代优化 |

### 工作流程（五阶段）

```
你的请求
    ↓
【阶段1：概念开发】
创意总监分析需求
    ├─── 世界观架构师
    └─── 人物设计师
    ↓
【阶段2：结构设计】
情节架构师 + 事件验证官
    ↓
【阶段3：内容创作】
内容创作师 + 文风优化师
    ↓
【阶段4：质量评审】
质量评审官
    ↓
【阶段5：迭代优化】（如需要）
迭代协调官
    ↓
返回最终结果
```

### 核心特性

✅ **多Agent协作** - 9个Agent协同工作
✅ **五阶段流程** - 概念开发 → 结构设计 → 内容创作 → 质量评审 → 迭代优化
✅ **智能分解** - 自动分析任务并分配给合适的Agent
✅ **项目管理** - 完整的项目生命周期管理
✅ **质量控制** - 多维度质量评估，自动迭代优化
✅ **知识库** - 向量数据库支持语义搜索
✅ **记忆管理** - 保持对话历史和上下文
✅ **Web界面** - 前后端分离架构，支持可视化操作

---

## 🎮 常见使用场景

### 场景1: 从零开始创作小说

```python
from multi_agent_framework import MultiAgentNovelWritingFramework

framework = MultiAgentNovelWritingFramework()

# 启动项目
framework.start_project(
    project_title="我的科幻小说",
    genre="科幻冒险",
    initial_concept="一个关于未来的故事"
)

# 构建世界观
framework.build_world("请设计一个科幻世界")

# 创建人物
framework.create_characters("创建主角和配角")

# 设计情节
framework.design_plot("设计三幕剧大纲")

# 撰写章节
framework.write_chapter(1, "撰写第一章")
```

### 场景2: 改进现有内容

```python
# 审阅内容
feedback = framework.review_content("之前生成的内容")

# 根据反馈修改
revised = framework.revise_content("原始内容", feedback)
```

### 场景3: 交互式创作

```python
# 自由对话模式
framework.interactive_session()

# 然后你可以自由提问：
# 你: 我想写一个关于魔法学院的奇幻小说
# 主编: [协调各Agent提供建议]
# 你: 主角应该是什么样的人物?
# 主编: [人物设计师提供详细设计]
```

### 场景4: 项目管理

```python
from project_manager import ProjectManager, TaskStatus

pm = ProjectManager()
project = pm.create_project("novel_001", "我的小说", "作者", "科幻")

# 添加任务
task_id = project.add_task(
    name="设计世界观",
    description="详细设计世界观",
    assigned_to="世界观架构师",
    priority=1
)

# 查看进度
progress = project.get_project_progress()
print(f"进度: {progress['progress_percent']:.1f}%")
```

---

## 📖 文档导航

### 快速参考
- ⚡ [5分钟快速开始](MULTI_AGENT_QUICKSTART.md) - 最快上手
- 📖 [完整使用指南](MULTI_AGENT_GUIDE.md) - 详细说明
- 🏗️ [架构设计](ARCHITECTURE.md) - 系统设计
- 🔌 [API参考](API_REFERENCE.md) - 完整API
- 📋 [项目总结](MULTI_AGENT_SUMMARY.md) - 项目概览
- 📚 [完整索引](INDEX.md) - 快速查找

### 其他文档
- ✅ [实现完成](IMPLEMENTATION_COMPLETE.md) - 实现说明
- 📊 [最终总结](FINAL_SUMMARY.md) - 项目统计
- ✓ [完成检查清单](CHECKLIST.md) - 完成情况

---

## 🔧 安装和配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制示例配置
cp .env.example .env

# 编辑 .env 文件
# 填入你的 OPENAI_API_KEY
```

### 3. 验证安装

```bash
# 运行基础示例
python multi_agent_example.py

# 如果看到输出，说明安装成功！
```

---

## 🎓 推荐学习顺序

### 第1天：快速上手（1小时）
1. ✅ 阅读本文件
2. ✅ 运行 `python multi_agent_example.py`
3. ✅ 阅读 [MULTI_AGENT_QUICKSTART.md](MULTI_AGENT_QUICKSTART.md)
4. ✅ 尝试 `framework.interactive_session()`

### 第2天：深入理解（1小时）
1. ✅ 阅读 [MULTI_AGENT_GUIDE.md](MULTI_AGENT_GUIDE.md)
2. ✅ 阅读 [ARCHITECTURE.md](ARCHITECTURE.md)
3. ✅ 运行 `python advanced_example.py`

### 第3天：掌握API（1小时）
1. ✅ 阅读 [API_REFERENCE.md](API_REFERENCE.md)
2. ✅ 查看源代码中的注释
3. ✅ 尝试自定义Agent

### 第4天及以后：实践应用
1. ✅ 创建自己的项目
2. ✅ 自定义工作流程
3. ✅ 扩展功能

---

## 💡 常见问题

### Q: 我需要什么才能开始？
A: 你需要：
- Python 3.8+
- OpenAI API密钥（或本地模型）
- 5分钟的时间

### Q: 这个框架能做什么？
A: 它可以帮助你：
- 创作小说
- 设计世界观和人物
- 规划情节
- 改进内容
- 管理创作项目

### Q: 我可以使用本地模型吗？
A: 可以！在 `.env` 中配置：
``env
LOCAL_MODEL_URL=http://localhost:11434
MODEL_NAME=qwen2:latest
```

### Q: 如何自定义Agent？
A: 查看 [MULTI_AGENT_GUIDE.md](MULTI_AGENT_GUIDE.md) 中的"高级功能"部分。

### Q: 遇到问题怎么办？
A: 查看 [MULTI_AGENT_GUIDE.md](MULTI_AGENT_GUIDE.md) 中的"故障排除"部分。

---

## 🚀 立即开始

### 选项1: 运行示例（推荐）
```bash
python multi_agent_example.py
```

### 选项2: 交互式创作
```bash
python -c "from multi_agent_framework import MultiAgentNovelWritingFramework; \
framework = MultiAgentNovelWritingFramework(); \
framework.interactive_session()"
```

### 选项3: 高级示例
```bash
python advanced_example.py
```

---

## 📞 获取帮助

1. **查看文档** - 从 [MULTI_AGENT_QUICKSTART.md](MULTI_AGENT_QUICKSTART.md) 开始
2. **查看示例** - 运行 `python multi_agent_example.py`
3. **查看API** - 参考 [API_REFERENCE.md](API_REFERENCE.md)
4. **查看源代码** - 查看源文件中的注释

---

## 🎉 准备好了吗？

### 下一步：
1. 安装依赖: `pip install -r requirements.txt`
2. 配置API: `cp .env.example .env` 并编辑
3. 运行示例: `python multi_agent_example.py`
4. 开始创作: `framework.interactive_session()`

**祝你创作愉快！** 🚀

---

## 📚 完整文档列表

- 📖 [完整使用指南](MULTI_AGENT_GUIDE.md)
- ⚡ [5分钟快速开始](MULTI_AGENT_QUICKSTART.md)
- 🏗️ [架构设计](ARCHITECTURE.md)
- 🔌 [API参考](API_REFERENCE.md)
- 📋 [项目总结](MULTI_AGENT_SUMMARY.md)
- ✅ [实现完成](IMPLEMENTATION_COMPLETE.md)
- 📊 [最终总结](FINAL_SUMMARY.md)
- 📚 [完整索引](INDEX.md)
- ✓ [完成检查清单](CHECKLIST.md)

---

**版本**: 1.0.0  
**最后更新**: 2024年  
**许可证**: MIT

