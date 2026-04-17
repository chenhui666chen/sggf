# MiniMax 语音模型配置说明

## 📋 概述

本项目已集成阿里云百炼平台的 MiniMax 语音合成模型：
- **MiniMax Speech 2.8 Turbo** - 高质量快速语音合成
- **MiniMax Speech 2.8 HD** - 旗舰级电影级音质

## 🔑 API 密钥配置

### 重要提示
✅ **使用阿里云百炼平台的 API Key**  
❌ **不使用 MiniMax 官方 API Key**

### 获取 API Key 步骤

1. **登录阿里云百炼控制台**
   - 访问：https://bailian.console.aliyun.com/
   - 使用阿里云账号登录

2. **创建 API Key**
   - 点击右上角头像 → "API-KEY"
   - 或在左侧菜单选择 "API-Key"
   - 点击 "创建" 按钮
   - 复制并保存 API Key（只显示一次）

3. **配置环境变量**

   **方式一：.env 文件（推荐）**
   ```bash
   # .env 文件
   DASHSCOPE_API_KEY=sk-your-api-key-here
   ```

   **方式二：系统环境变量**
   ```bash
   # Windows PowerShell
   $env:DASHSCOPE_API_KEY="sk-your-api-key-here"
   
   # Linux/Mac
   export DASHSCOPE_API_KEY="sk-your-api-key-here"
   ```

   **方式三：代码中配置（不推荐，仅用于测试）**
   ```python
   import os
   os.environ["DASHSCOPE_API_KEY"] = "sk-your-api-key-here"
   ```

## 🌐 API 端点配置

### 中国内地部署
```
Base URL: https://dashscope.aliyuncs.com/api/v1
Endpoint: /api/v1/services/aigc/multimodal-generation/generation
```

### 国际部署（如需要）
```
Base URL: https://dashscope-intl.aliyuncs.com/api/v1
Endpoint: /api/v1/services/aigc/multimodal-generation/generation
```

## 💰 计费说明

### 计费方式
- **通过阿里云百炼平台计费**
- 按字符数计费（每 1000 字符为一个计费单位）
- 不同模型价格不同

### ⚠️ 重要提示
**配置文件中显示的价格仅供参考**，实际价格请以阿里云百炼平台实时价格为准。

**全量校验机制**：
- ✅ 系统会在模型中心全量校验时**从百炼官网实时获取最新价格**
- ✅ 配置文件中的价格仅作为参考值
- ✅ 所有价格信息都会标注来源

### 价格参考（2025 年，来自阿里云百炼官方价格文档）

| 模型 | 官方价格（元/万字符） | 音色复刻 | 来源 |
|------|---------------------|---------|------|
| MiniMax Speech 2.8 Turbo | ¥3.5 | - | [百炼价格文档](https://help.aliyun.com/zh/model-studio/pricing) |
| MiniMax Speech 2.8 HD | ¥3.5 | ¥9.9 | [百炼价格文档](https://help.aliyun.com/zh/model-studio/pricing) |

**📊 查看实时价格**：
- 百炼价格文档：https://help.aliyun.com/zh/model-studio/pricing
- 百炼控制台：https://bailian.console.aliyun.com/

### 免费额度
- 新用户通常有免费体验额度
- 在百炼控制台查看剩余额度
- 额度用完后自动按量计费

## 📚 使用示例

### Python 代码调用

```python
from adapters.adapter_helpers import generate_speech

# 使用 MiniMax Turbo
result = generate_speech(
    text="这是一个测试文本",
    voice_id="female-wenrou",  # 温柔女声
    speed=1.0,
    pitch=1.0,
    volume=1.0,
    emotion="warm",
    model_id="minimax-speech-2.8-turbo",
)

if result.success:
    audio_data = result.data  # base64 编码
    with open("output.mp3", "wb") as f:
        import base64
        f.write(base64.b64decode(audio_data))
    print(f"成功！音频保存到 output.mp3")
else:
    print(f"失败：{result.error}")
```

### 使用统一运行时

```python
from core.unified_media_runtime import media_runtime

# 同步调用
audio_bytes = media_runtime.synthesize_speech(
    text="章节内容...",
    voice_id="male-chenzhuo",
    model_id="minimax-speech-2.8-turbo",
)

with open("chapter_1.mp3", "wb") as f:
    f.write(audio_bytes)
```

## 🎨 音色库

### MiniMax Turbo 音色

#### 标准女声
- **female-shuangkuai** - 爽快女声（阳光活泼）
- **female-wenrou** - 温柔女声（温柔知性）

#### 标准男声
- **male-chenzhuo** - 沉稳男声（成熟稳重）
- **male-qingnian** - 青年男声（阳光青年）

### MiniMax HD 音色

#### 旗舰女声
- **hd-female-qingcheng** - 倾城女声（电影级质感）
- **hd-female-zhixing** - 知性女声（知性优雅）

#### 旗舰男声
- **hd-male-dihou** - 醇厚男声（电影级醇厚）
- **hd-male-ciyuan** - 磁性男声（磁性魅力）

## 🔧 参数说明

### 基础参数
| 参数 | 类型 | 范围 | 说明 |
|------|------|------|------|
| text | string | - | 要转换的文本（必填） |
| voice_id | string | - | 音色 ID（必填） |
| speed | float | 0.5-2.0 | 语速（默认 1.0） |
| pitch | float | 0.5-2.0 | 音调（默认 1.0） |
| volume | float | 0.0-1.0 | 音量（默认 1.0） |
| emotion | string | - | 情绪（可选） |

### 情绪参数
- **happy** - 开心
- **sad** - 悲伤
- **angry** - 生气
- **fearful** - 恐惧
- **warm** - 温暖
- **emotional** - 情感丰富
- **neutral** - 中性

## 📖 官方文档

- **API 参考**：https://help.aliyun.com/zh/model-studio/minimax-synchronous-speech-synthesis-api
- **模型介绍**：https://help.aliyun.com/zh/model-studio/minimax-speech
- **计费说明**：https://help.aliyun.com/zh/model-studio/pricing
- **百炼控制台**：https://bailian.console.aliyun.com/

## ⚠️ 常见问题

### Q1: 返回 "API Key 无效"
**A**: 请检查：
1. API Key 是否从阿里云百炼平台获取（不是 MiniMax 官方）
2. API Key 是否正确复制到环境变量
3. 环境变量名称是否为 `DASHSCOPE_API_KEY`

### Q2: 返回 "余额不足"
**A**: 
1. 登录百炼控制台查看剩余额度
2. 充值账户余额
3. 检查是否超出免费额度

### Q3: 返回 "模型不存在"
**A**: 
1. 检查模型 ID 是否正确：`minimax-speech-2.8-turbo` 或 `minimax-speech-2.8-hd`
2. 确认模型在百炼平台已开通

### Q4: 音质不如预期
**A**: 
1. 尝试使用 HD 模型：`minimax-speech-2.8-hd`
2. 调整音调和语速参数
3. 选择更适合的音色

## 🚀 下一步

1. ✅ 配置 API Key 到环境变量
2. ✅ 运行测试脚本验证配置
3. ✅ 在实际项目中调用 MiniMax 模型
4. ✅ 根据需求选择合适的音色和参数

## 📞 技术支持

- **阿里云百炼工单**：https://workorder.console.aliyun.com/
- **开发者社区**：https://developer.aliyun.com/
- **GitHub Demo**：https://github.com/aliyun/alibabacloud-bailian-speech-demo
