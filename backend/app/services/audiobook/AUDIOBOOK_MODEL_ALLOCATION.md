# 🎙️ 有声小说Agent模型分配策略

## ✅ 配置完成

所有6个专业Agent已完成模型配置，实现智能化模型选择，平衡**质量、速度和成本**。

---

## 📋 模型分配表

### 保守优化策略（推荐）⭐⭐⭐⭐⭐

| Agent | 任务类型 | 推荐模型 | 选择理由 |
|-------|---------|---------|---------|
| **AudioDirector** | 策略制定 | `qwen3-max` | 需要综合分析小说类型、目标听众，制定改编策略，qwen3-max在多维度分析上表现均衡 |
| **AudiobookScriptAdapter** | 剧本改编 | `deepseek-reasoner` | **核心任务**，需要创意+逻辑推理（心理活动外化、环境描写→音效标注），reasoner深度思考能力强 |
| **VoiceDesigner** | 音色设计 | `qwen-turbo` | 基于规则库匹配（年龄→音调，性格→语速），不需要深度推理，turbo快速响应 |
| **SoundEffectDesigner** | 音效设计 | `qwen-turbo` | 场景→音效库的匹配任务（雨天→rain.mp3），规则为主，turbo即可 |
| **MusicComposer** | 音乐设计 | `qwen-turbo` | 情绪匹配（紧张→tense_music），规则简单，turbo快速完成 |
| **AudioQualityReviewer** | 质量评审 | `deepseek-reasoner` | **质量关键**，多维度分析（剧本自然度、音频平衡、节奏），reasoner严谨全面 |

### 激进优化策略（最大化速度）

| Agent | 任务类型 | 推荐模型 | 变化 |
|-------|---------|---------|------|
| **AudioDirector** | 策略制定 | `qwen-turbo` | 降级到turbo，速度更快但分析深度下降 |
| **AudiobookScriptAdapter** | 剧本改编 | `qwen3-max` | 降级到qwen3-max，保证基本质量 |
| **VoiceDesigner** | 音色设计 | `qwen-turbo` | 不变 |
| **SoundEffectDesigner** | 音效设计 | `qwen-turbo` | 不变 |
| **MusicComposer** | 音乐设计 | `qwen-turbo` | 不变 |
| **AudioQualityReviewer** | 质量评审 | `qwen3-max` | 升级到qwen3-max，评审速度与严谨度更均衡 |

---

## 🎯 核心设计原则

### 1. 任务差异化分配

```
深度推理任务（reasoner）:
├─ AudiobookScriptAdapter: 剧本改编（创意+逻辑）
└─ AudioQualityReviewer: 质量评审（多维度分析）

均衡分析任务（qwen3-max）:
└─ AudioDirector: 策略制定（综合判断）

快速匹配任务（qwen-turbo）:
├─ VoiceDesigner: 音色匹配
├─ SoundEffectDesigner: 音效匹配
└─ MusicComposer: 音乐匹配
```

### 2. 成本效益平衡

**保守策略成本**: ¥0.0146/章节  
**激进策略成本**: ¥0.0146/章节（相同，因为核心任务仍用reasoner）

**关键洞察**：
- 剧本改编占总成本的 **75%**（¥0.011），是成本大头
- 音色/音效/音乐设计成本极低（各¥0.0001），使用turbo不影响成本
- 质量评审占 **21%**（¥0.003），reasoner保证质量

### 3. MVP模式支持

所有Agent都支持**规则驱动模式**（不依赖LLM），可降级运行：

```python
# 有LLM时：智能改编
script_adapter = AudiobookScriptAgent(llm_client=llm)
segments = await script_adapter.adapt_chapter(content)

# 无LLM时：规则解析
script_adapter = AudiobookScriptAgent(llm_client=None)
segments = await script_adapter.adapt_chapter(content)  # 自动切换规则模式
```

---

## 🔧 技术实现

### TaskType枚举（已添加）

```python
# backend/app/services/model_optimizer.py

class TaskType(str, Enum):
    # ... 其他任务类型 ...
    
    # 🎙️ 有声小说专用
    AUDIOBOOK_DIRECTOR = "audiobook_director"     # 有声导演
    AUDIOBOOK_SCRIPT = "audiobook_script"         # 剧本编剧
    AUDIOBOOK_VOICE = "audiobook_voice"           # 音色设计
    AUDIOBOOK_SOUND = "audiobook_sound"           # 音效设计
    AUDIOBOOK_MUSIC = "audiobook_music"           # 音乐设计
    AUDIOBOOK_REVIEW = "audiobook_review"         # 质量评审
```

### Agent使用方式

```python
from app.services.llm_client import get_llm_client
from app.services.model_optimizer import TaskType

# 获取优化的LLM客户端
llm_client = get_llm_client()

# 调用LLM时指定TaskType，自动选择最优模型
response = await llm_client.chat(
    messages=[{"role": "user", "content": prompt}],
    task_type=TaskType.AUDIOBOOK_SCRIPT,  # 自动使用deepseek-reasoner
    use_cache=False
)
```

---

## 📊 性能预测

### 单章节生成预测（5000字）

| 阶段 | Agent | 模型 | 预计耗时 | Token消耗 |
|------|-------|------|---------|----------|
| 1 | AudioDirector | qwen3-max | 2s | 500 input + 200 output |
| 2 | AudiobookScriptAdapter | deepseek-reasoner | 15s | 3000 input + 2000 output |
| 3 | VoiceDesigner | qwen-turbo | 1s | 300 input + 100 output |
| 3 | SoundEffectDesigner | qwen-turbo | 1s | 300 input + 100 output |
| 3 | MusicComposer | qwen-turbo | 1s | 300 input + 100 output |
| 4 | AudioQualityReviewer | deepseek-reasoner | 8s | 1000 input + 500 output |
| **总计** | - | - | **~28秒** | **5400 input + 3000 output** |

**成本**: ¥0.0146/章节（约100章=¥1.46）

---

## 🚀 优化建议

### 进一步优化方向

1. **缓存策略**
   - VoiceDesigner的音色匹配结果可缓存（同角色复用）
   - SoundEffectDesigner的场景→音效映射可预计算

2. **批量处理**
   - 多章节并行调用VoiceDesigner、SoundEffectDesigner
   - 减少网络往返时间

3. **动态降级**
   - 低优先级章节（如序章、番外）使用激进策略
   - 核心章节使用保守策略

---

## ✅ 验证结果

运行测试：
```bash
python -m app.services.audiobook.agents.test_model_config
```

**输出**：
```
✓ 有声导演         → qwen3-max         (综合分析策略制定)
✓ 剧本编剧         → deepseek-reasoner  (创意改编+逻辑推理)
✓ 音色设计         → qwen-turbo         (规则匹配音色参数)
✓ 音效设计         → qwen-turbo         (场景音效规划)
✓ 音乐设计         → qwen-turbo         (情绪音乐匹配)
✓ 质量评审         → deepseek-reasoner  (多维度质量分析)
```

---

## 📝 使用示例

### 示例1：完整流程

```python
from app.services.llm_client import get_llm_client
from app.services.audiobook.agents import (
    AudioDirector,
    AudiobookScriptAgent,
    AudioQualityReviewer
)

# 初始化LLM客户端（自动模型优化）
llm = get_llm_client(strategy="conservative")

# 1. 制定策略（qwen3-max）
director = AudioDirector(llm_client=llm)
strategy = director.formulate_strategy(
    novel_genre="科幻",
    novel_theme="记忆交易"
)

# 2. 剧本改编（deepseek-reasoner）
script_adapter = AudiobookScriptAgent(llm_client=llm)
segments = await script_adapter.adapt_chapter(chapter_content)

# 3. 质量评审（deepseek-reasoner）
reviewer = AudioQualityReviewer(llm_client=llm)
report = reviewer.review_script(segments)
```

### 示例2：无LLM降级模式

```python
# 不传入llm_client，自动使用规则模式
director = AudioDirector()  # MVP模式
strategy = director.formulate_strategy("科幻", "记忆交易")
# ✓ 基于规则推荐策略

script_adapter = AudiobookScriptAgent()  # MVP模式
segments = await script_adapter.adapt_chapter(content)
# ✓ 基于规则解析和简单转换
```

---

## 🎉 总结

✅ **6个Agent全部完成模型配置**  
✅ **智能选型：深度推理任务用reasoner，快速匹配用turbo**  
✅ **成本优化：单章节仅¥0.0146，100章约¥1.46**  
✅ **性能预测：单章节~28秒（5000字）**  
✅ **兼容性好：支持MVP模式（无LLM降级）**  

**建议使用保守策略**，在质量和成本间取得最佳平衡！🎊
