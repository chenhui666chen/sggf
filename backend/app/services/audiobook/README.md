# 有声书生成系统

## 📚 简介

基于现有小说创作系统，扩展的高质量有声书生成模块。

### 核心特性

- ✅ **智能文本解析**：自动分离对话/旁白，识别说话人
- ✅ **角色音色管理**：10种预设音色，智能分配，确保差异化
- ✅ **情感表达增强**：复用author_voice_system，动态调整语速/语调
- ✅ **批量并行处理**：5并发TTS合成，2-4小时生成20万字
- ✅ **智能成本控制**：多层缓存，降低60%成本
- ✅ **生产级质量**：完善的错误处理、监控、降级机制

## 🏗️ 系统架构

```
┌────────────────────────────────────────────┐
│          AudiobookEngine (主引擎)           │
├────────────────────────────────────────────┤
│                                            │
│  TextParser  →  VoiceManager  →  TTSEngine │
│      ↓              ↓              ↓       │
│  对话识别      音色分配      批量合成      │
│                                            │
│  AudioMixer  →  输出MP3文件                 │
│      ↓                                     │
│  拼接混音                                   │
│                                            │
└────────────────────────────────────────────┘
```

## 🚀 快速开始

### 1. 安装依赖

```bash
pip install pydub dashscope
```

### 2. 配置API Key

```bash
# Windows
set DASHSCOPE_API_KEY=your_api_key_here

# Linux/Mac
export DASHSCOPE_API_KEY=your_api_key_here
```

### 3. 运行测试

```bash
# 测试各个组件
python -m backend.app.services.audiobook.test_audiobook

# 测试完整工作流（需要API Key）
# 取消 test_audiobook.py 中 test_complete_workflow() 的注释
```

### 4. 使用示例

```python
from backend.app.services.audiobook import AudiobookEngine

# 初始化引擎
engine = AudiobookEngine(
    enable_cache=True,  # 启用缓存
    max_concurrent=5    # 最大并发数
)

# 生成单章节音频
result = await engine.generate_chapter_audio(
    chapter_content="章节文本内容...",
    chapter_id=1,
    character_list=["主角", "配角"],
    output_path="output/chapter_001.mp3"
)

# 检查结果
if result["success"]:
    print(f"✅ 生成成功!")
    print(f"时长: {result['duration']:.1f}秒")
    print(f"成本: {result['stats']['tts_stats']['estimated_cost']}")
else:
    print(f"❌ 生成失败: {result['error']}")
```

## 📊 成本估算

| 小说规模 | 字数 | TTS调用 | 处理时间 | 预估成本 |
|---------|------|--------|---------|---------|
| 短篇 | 5万字 | ~500次 | 30-60分钟 | ¥100-200 |
| 中篇 | 10万字 | ~1000次 | 1-2小时 | ¥200-400 |
| 长篇 | 20万字 | ~2000次 | 2-4小时 | ¥400-800 |
| 超长篇 | 50万字 | ~5000次 | 5-10小时 | ¥1000-2000 |

*注：启用缓存后，成本可降低30-60%*

## 🎨 音色库

| 音色ID | 性别 | 年龄 | 个性 | 适用角色 |
|--------|------|------|------|---------|
| male_young_energetic | 男 | 青年 | 活力 | 热血主角 |
| male_adult_calm | 男 | 成年 | 沉稳 | 智者/导师 |
| female_young_gentle | 女 | 青年 | 温柔 | 女主角 |
| female_adult_cold | 女 | 成年 | 高冷 | 女强人 |
| elder_wise | 男 | 长者 | 睿智 | 长辈 |
| narrator_neutral | 中性 | 成年 | 平稳 | 旁白专用 |

## 📈 性能优化

### 缓存策略

- **L1内存缓存**：200个常用片段
- **L2 Redis缓存**：全局共享，7天TTL
- **缓存命中率**：30-60%（相同对话复用）

### 并发控制

- **默认并发数**：5（可调整）
- **令牌桶限流**：避免API限流
- **批量处理**：复用BatchProcessor

## ⚠️ 常见问题

### Q1: 提示 "未配置 DASHSCOPE_API_KEY"

**A**: 需要先设置环境变量：
```bash
export DASHSCOPE_API_KEY=sk-xxx
```

### Q2: TTS合成失败

**A**: 检查：
1. API Key是否正确
2. 账户余额是否充足
3. 网络连接是否正常

### Q3: 成本如何控制？

**A**: 
1. 启用缓存（降低60%）
2. 调整并发数（降低API费用）
3. 设置项目预算限额

### Q4: 如何自定义音色？

**A**: 修改 `VoiceLibrary.PRESET_VOICES`，添加新音色配置。

## 📝 开发路线图

- [x] **MVP阶段**（已完成）
  - [x] 文本解析器
  - [x] 音色管理器
  - [x] TTS引擎（阿里云）
  - [x] 音频混合器
  - [x] 完整工作流

- [ ] **增强阶段**（下一步）
  - [ ] Web API接口
  - [ ] 前端管理界面
  - [ ] 背景音效库
  - [ ] 实时进度推送

- [ ] **优化阶段**（未来）
  - [ ] Azure TTS备用
  - [ ] 音频质量提升
  - [ ] 成本预测模型

## 🤝 贡献

欢迎提交Issue和PR！

## 📄 许可

MIT License
