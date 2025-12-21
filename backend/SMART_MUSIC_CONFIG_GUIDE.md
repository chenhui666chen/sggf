# 🎚️ 智能背景音乐配置指南

## 📌 快速启用智能音量平衡

### 方式1：项目级配置（推荐）

在创建有声书项目时，在 `audio_config.audio_fx` 中添加以下配置：

```json
{
  "enable_music": true,
  "music_density": "medium",
  "intelligent_balance": true,  // 🆕 启用智能音量平衡
  "base_bgm_volume": -30  // 基础BGM音量（dB），默认-30dB
}
```

### 方式2：临时测试（API调用）

在调用有声书生成API时，传递配置参数：

```python
# 示例：Python调用
audiobook_config = {
    "novel_id": 1,
    "chapter_id": 1,
    "audio_config": {
        "audio_fx": {
            "enable_music": True,
            "intelligent_balance": True,  # 启用智能平衡
            "base_bgm_volume": -30
        }
    }
}

response = requests.post(
    "http://localhost:8000/api/v1/audiobook/projects",
    json=audiobook_config
)
```

---

## 🎯 智能音量调整规则

### 规则1：音乐类型调整

| 音乐类型 | 音量调整 | 说明 |
|---------|---------|------|
| **opening** (开场) | +5dB | 开场音乐可以更响亮，营造氛围 |
| **ending** (结尾) | +5dB | 结尾音乐同样可以提升，留下印象 |
| **theme** (主题) | +3dB | 角色主题音乐稍微突出 |
| **underscore** (背景) | 0dB | 保持基础音量，不抢对话 |

### 规则2：情绪调整

| 情绪 | 音量调整 | 适用场景 |
|-----|---------|---------|
| **tense** (紧张) | +8dB | 悬疑、追逐、危机场景 |
| **epic** (史诗) | +8dB | 高潮、战斗、震撼场景 |
| **joyful** (欢快) | +2dB | 日常、喜剧、轻松场景 |
| **romantic** (浪漫) | +2dB | 感情戏、温馨场景 |
| **peaceful** (平静) | -5dB | 安静、沉思场景 |
| **sad** (悲伤) | -5dB | 离别、伤感场景 |
| **mysterious** (神秘) | 0dB | 探索、未知场景 |

### 规则3：目标音量相对调整

- 以 `0.2` 为基准音量
- 如果 `target_volume = 0.3`，则额外 +3.5dB
- 如果 `target_volume = 0.15`，则额外 -2.5dB

---

## 📊 实际效果对比

### 示例1：高潮战斗场景

**场景参数**：
- `music_type`: "underscore"
- `mood`: "epic"
- `target_volume`: 0.3

**计算过程**：
```
基础音量: -30dB
+ 音乐类型调整: 0dB (underscore)
+ 情绪调整: +8dB (epic高潮)
+ 目标音量调整: +3.5dB (0.3相对于0.2)
= -18.5dB
```

**对比效果**：
- ❌ **未启用智能平衡**：固定-30dB，配乐被人声完全掩盖
- ✅ **启用智能平衡**：动态调整至-18.5dB，配乐有力烘托高潮氛围

---

### 示例2：平静沉思场景

**场景参数**：
- `music_type`: "underscore"
- `mood`: "peaceful"
- `target_volume`: 0.15

**计算过程**：
```
基础音量: -30dB
+ 音乐类型调整: 0dB (underscore)
+ 情绪调整: -5dB (peaceful)
+ 目标音量调整: -2.5dB (0.15相对于0.2)
= -37.5dB
```

**对比效果**：
- ❌ **未启用智能平衡**：固定-30dB，配乐稍显突兀
- ✅ **启用智能平衡**：动态降至-37.5dB，配乐轻柔不抢戏

---

### 示例3：开场音乐

**场景参数**：
- `music_type`: "opening"
- `mood`: "mysterious"
- `target_volume`: 0.3

**计算过程**：
```
基础音量: -30dB
+ 音乐类型调整: +5dB (opening)
+ 情绪调整: 0dB (mysterious)
+ 目标音量调整: +3.5dB (0.3相对于0.2)
= -21.5dB
```

**对比效果**：
- ❌ **未启用智能平衡**：开场音乐淹没在固定-30dB中
- ✅ **启用智能平衡**：提升至-21.5dB，开场气氛拉满

---

## 🔧 高级配置选项

### 调整基础BGM音量

如果发现整体BGM太响或太安静，可以调整 `base_bgm_volume`：

```json
{
  "intelligent_balance": true,
  "base_bgm_volume": -35  // 调低5dB，适合对话密集的作品
}
```

或

```json
{
  "intelligent_balance": true,
  "base_bgm_volume": -25  // 调高5dB，适合氛围音乐为主的作品
}
```

### 音乐密度控制

配合音乐密度参数，精细化控制配乐覆盖率：

```json
{
  "music_density": "low",  // 15%覆盖率
  "intelligent_balance": true,
  "base_bgm_volume": -28  // 低密度时可稍微提升音量
}
```

```json
{
  "music_density": "medium",  // 30%覆盖率（推荐）
  "intelligent_balance": true,
  "base_bgm_volume": -30  // 标准配置
}
```

```json
{
  "music_density": "high",  // 45%覆盖率
  "intelligent_balance": true,
  "base_bgm_volume": -32  // 高密度时适当降低音量，避免疲劳
}
```

---

## 📝 配置最佳实践

### 1. 不同类型作品的推荐配置

#### 悬疑/惊悚小说
```json
{
  "enable_music": true,
  "music_density": "medium",
  "intelligent_balance": true,
  "base_bgm_volume": -28  // 稍高，营造紧张氛围
}
```

#### 言情/都市小说
```json
{
  "enable_music": true,
  "music_density": "low",
  "intelligent_balance": true,
  "base_bgm_volume": -32  // 稍低，以对话为主
}
```

#### 玄幻/史诗小说
```json
{
  "enable_music": true,
  "music_density": "high",
  "intelligent_balance": true,
  "base_bgm_volume": -30  // 标准，需要丰富配乐
}
```

### 2. 启用日志调试

在开发环境中，可以查看详细的音量计算日志：

```python
# 设置日志级别为DEBUG
import logging
logging.getLogger("app.services.audiobook.engine").setLevel(logging.DEBUG)
```

日志输出示例：
```
🎚️ 智能音量: underscore/epic → -18.5dB
  🎬 开场/结尾音乐: +5dB
  🔥 高潮情绪(epic): +8dB
  🎶 最终音量: -30.0dB → -18.5dB (类型=underscore, 情绪=epic, 目标=0.30)
🎼 叠加BGM: suspense_1.mp3 (音量: -18.5dB)
```

---

## ⚠️ 注意事项

### 1. 音量范围限制

智能平衡系统会自动将BGM音量限制在 **-50dB 到 -10dB** 之间，避免：
- BGM过小（<-50dB）：听不见
- BGM过大（>-10dB）：盖过人声

### 2. 与pydub兼容性

确保已安装 `audioop-lts` 依赖（Python 3.13兼容）：
```bash
pip install audioop-lts>=0.2.1
```

### 3. AI音乐生成配合

如果启用了Mureka AI音乐生成，智能平衡会自动应用于AI生成的BGM：
```json
{
  "enable_music": true,
  "intelligent_balance": true,
  "ai_music_generation": true,  // 启用AI音乐生成
  "base_bgm_volume": -30
}
```

---

## 🚀 快速测试

### 测试脚本

创建一个简单的测试脚本来验证效果：

```python
# test_smart_music.py
import asyncio
from app.services.audiobook.engine import AudiobookEngine

async def test():
    engine = AudiobookEngine()
    
    # 启用智能平衡
    engine.apply_audio_fx_config({
        "enable_music": True,
        "intelligent_balance": True,
        "base_bgm_volume": -30
    })
    
    # 生成章节
    result = await engine.generate_chapter(
        novel_id=1,
        chapter_id=1,
        audiobook_project_id=1
    )
    
    print(f"✅ 生成完成！文件大小: {result['file_size']/1024/1024:.2f}MB")

asyncio.run(test())
```

运行：
```bash
cd backend
python test_smart_music.py
```

---

## 📊 效果评估指标

启用智能平衡后，可以从以下维度评估效果：

1. **人声清晰度**：对话是否清晰可辨？（目标：100%清晰）
2. **氛围营造**：BGM是否准确烘托情绪？（目标：情绪匹配度>85%）
3. **音量平衡**：高潮/平静场景音量差异是否明显？（目标：差异>10dB）
4. **听觉疲劳**：连续听30分钟是否感到不适？（目标：无疲劳感）

---

## ✨ 总结

智能音量平衡系统让背景音乐**随剧情自动呼吸**，高潮时澎湃有力，平静时柔和低调，打造专业级有声剧的听觉体验！

**一键启用，立享提升！** 🎉
