# 剪影（Jianying）MCP 配置指南

## 📋 目录
- [项目简介](#项目简介)
- [获取API密钥](#获取api密钥)
- [配置步骤](#配置步骤)
- [环境变量配置](#环境变量配置)
- [验证配置](#验证配置)
- [使用示例](#使用示例)
- [常见问题](#常见问题)

---

## 项目简介

**剪影MCP** (Model Context Protocol) 是一个开源的剪映/Jianying API解决方案，让开发者能够通过编程方式完全控制AI生成的媒体资产，包括图像、音频、视频和文本。<mcreference link="https://blog.csdn.net/j8267643/article/details/151724877" index="1">1</mcreference>

### 主要功能
- 🎬 视频剪辑与合成
- 🎵 音频处理与混音
- 🖼️ 图像编辑与特效
- 📝 文本字幕生成
- 🔄 批量媒体处理

### 在本项目中的作用

剪影 API 为可选能力，适用于需要模板/转场/素材库等高级剪辑能力的场景；默认链路仍推荐使用本地 FFmpeg 自动合成。

1. **视频剪辑**：对镜头片段做拼接/裁剪/转场
2. **音频处理**：音频对齐、混音、背景音乐
3. **字幕与特效**：字幕、滤镜、特效
4. **最终输出**：生成最终视频文件

---

## 获取API密钥

### 方法一：通过CapCutAPI开源项目获取

**CapCutAPI** 是一个强大的开源编辑API，让开发者能够通过编程方式完全控制AI生成的媒体资产，包括图像、音频、视频和文本。<mcreference link="https://blog.csdn.net/j8267643/article/details/151724877" index="1">1</mcreference>

#### 1. 访问项目仓库

**GitHub仓库**：
```
https://github.com/hey-jian-wei/jianying-mcp
```

**Gitee镜像**（如果GitHub访问困难）：
```
https://gitee.com/yangshare/CapCutAPI
```

#### 2. 克隆项目

```bash
# 使用GitHub
git clone https://github.com/hey-jian-wei/jianying-mcp.git
cd jianying-mcp

# 或使用Gitee
git clone https://gitee.com/yangshare/CapCutAPI.git
cd CapCutAPI
```

#### 3. 查看项目文档

项目通常包含以下文档：
- `README.md` - 项目介绍和快速开始
- `docs/` - 详细API文档
- `examples/` - 使用示例代码

#### 4. 获取API密钥

根据项目文档，通常有以下方式：

**方式A：使用剪映官方API**
- 访问剪映开放平台申请开发者权限
- 获取API Key和Secret
- 配置Base URL为官方API地址

**方式B：使用本地MCP服务器**
- 按照文档部署本地MCP服务器
- 使用本地服务器地址作为Base URL
- 可能不需要API密钥或使用测试密钥

**方式C：使用第三方服务**
- 查看项目是否有提供在线服务
- 注册账号获取API密钥

### 方法二：通过剪映开放平台获取

#### 1. 访问剪映开放平台

**剪映网页版**：http://capcut.cn/<mcreference link="https://m.php.cn/faq/1889818.html" index="4">4</mcreference>

**开发者平台**：需要申请开发者权限

#### 2. 创建应用

- 注册开发者账号
- 创建新应用
- 获取API Key和Secret

#### 3. 配置权限

申请以下权限：
- 视频编辑权限
- 音频处理权限
- 媒体导出权限
- 草稿管理权限

#### 4. API接口示例

剪映官方API接口示例：<mcreference link="https://blog.csdn.net/weixin_42238097/article/details/152228995" index="3">3</mcreference>

```python
import requests

# 创建剪映草稿
api_url = "https://api.capcut.com/openapi/capcut-mate/v1/create_draft"
params = {
    "width": 1080,
    "height": 1920,
    "fps": 30
}

response = requests.post(api_url, json=params)
draft_id = response.json()["draft_id"]
```

### 方法三：使用CapCutAPI开源库

**CapCutAPI** 是一个基于Python开发的开源项目，可通过代码自动化控制剪映/CapCut剪辑视频。<mcreference link="https://gitee.com/yangshare/CapCutAPI" index="5">5</mcreference>

#### 功能特性

- ✅ 自动创建和管理剪映草稿文件
- ✅ 支持批量操作
- ✅ 添加多种素材类型
- ✅ 应用转场和特效
- ✅ 自动化视频剪辑流程

#### 安装和使用

```bash
# 安装依赖
pip install -r requirements.txt

# 运行示例
python examples/create_draft.py
```

---

## 配置步骤

### 步骤1：选择API获取方式

根据你的需求选择：
- **快速测试**：使用CapCutAPI开源库
- **生产环境**：申请剪映官方API
- **本地部署**：部署MCP服务器

### 步骤2：获取API密钥信息

根据选择的方式获取：
- **API Key**：用于身份验证的密钥
- **Base URL**：API服务的基础URL
- **其他配置**：可能需要的额外参数

### 步骤3：配置环境变量

在项目根目录的 `.env` 文件中添加配置：

```bash
# 剪影API配置
JIANYING_API_KEY=your-jianying-api-key-here
JIANYING_BASE_URL=https://api.jianying.com/v1
```

### 步骤4：验证配置

运行自检命令确认配置可读取：

```bash
python -c "from adapters.model_adapters import ModelAdapterFactory; a=ModelAdapterFactory().get_adapter('jianying'); print(a.config.base_url)"
```

---

## 环境变量配置

### .env文件配置示例

```bash
# ========================================
# 剪影（Jianying）API配置
# ========================================

# 剪影API密钥（必需）
JIANYING_API_KEY=your-jianying-api-key-here

# 剪影API基础URL（必需）
JIANYING_BASE_URL=https://api.jianying.com/v1

# ========================================
# 不同API方式的配置示例
# ========================================

# 方式1：使用剪映官方API
# JIANYING_API_KEY=sk-your-official-api-key
# JIANYING_BASE_URL=https://api.capcut.com/openapi/capcut-mate/v1

# 方式2：使用本地MCP服务器
# JIANYING_API_KEY=
# JIANYING_BASE_URL=http://localhost:8080/api/v1

# 方式3：使用第三方服务
# JIANYING_API_KEY=your-third-party-key
# JIANYING_BASE_URL=https://your-service.com/api/v1

# ========================================
# 其他相关配置（示例）
# ========================================

# DeepSeek V4 文本模型走官方 API
DEEPSEEK_API_KEY=your-deepseek-api-key-here
DEEPSEEK_API_BASE=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-pro

# 阿里云百炼API（用于 Qwen / Wan / Embedding / TTS 等 DashScope 能力）
DASHSCOPE_API_KEY=your-dashscope-api-key-here
DASHSCOPE_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1

# 通义万相模型配置
WAN_T2I_API_KEY=your-dashscope-api-key-here
WAN_T2I_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
WAN_T2I_MODEL_ID=2862677

WAN_I2V_API_KEY=your-dashscope-api-key-here
WAN_I2V_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
WAN_I2V_MODEL_ID=2867393

WAN_T2V_API_KEY=your-dashscope-api-key-here
WAN_T2V_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
WAN_T2V_MODEL_ID=3001146

WAN_R2V_API_KEY=your-dashscope-api-key-here
WAN_R2V_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
WAN_R2V_MODEL_ID=2976416

WAN_IMAGE_EDIT_API_KEY=your-dashscope-api-key-here
WAN_IMAGE_EDIT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
WAN_IMAGE_EDIT_MODEL_ID=2712576

# Qwen系列模型配置
QWEN_IMAGE_EDIT_API_KEY=your-dashscope-api-key-here
QWEN_IMAGE_EDIT_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

QWEN_VL_PLUS_API_KEY=your-dashscope-api-key-here
QWEN_VL_PLUS_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1

# Embedding模型配置
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_API_KEY=your-dashscope-api-key-here
EMBEDDING_API_BASE=https://dashscope.aliyuncs.com/compatible-mode/v1
```

### 命令行临时设置（测试用）

```bash
# Windows PowerShell
$env:JIANYING_API_KEY="your-jianying-api-key-here"
$env:JIANYING_BASE_URL="https://api.jianying.com/v1"

# Linux/Mac
export JIANYING_API_KEY="your-jianying-api-key-here"
export JIANYING_BASE_URL="https://api.jianying.com/v1"
```

---

## 验证配置

### 运行自检命令

```bash
python -c "from adapters.model_adapters import ModelAdapterFactory; a=ModelAdapterFactory().get_adapter('jianying'); print(a.config.base_url)"
```

### 验证结果示例

```
================================================================================
📦 剪影API配置（用于视频剪辑与合成）
================================================================================
✅ JIANYING_API_KEY: 格式正确
   密钥前缀: sk-your-jian...key-here
   密钥长度: 35 字符
✅ JIANYING_BASE_URL: 格式正确
   Base URL: https://api.jianying.com/v1

================================================================================
📊 配置总结
================================================================================
已配置: 24/24 项
完成度: 100.0%

🎉 恭喜！所有配置项都已正确配置！

下一步：
  1. 启动后端服务：cd backend && python -m uvicorn app.main:app --reload --port 8000
  2. 测试API调用是否正常
  3. 如需高级剪辑能力，可接入剪影 API（可选）
```

---

## 使用示例

### Python 调用示例

```python
import os

from adapters.model_adapters import ModelAdapterFactory, ModelConfig

api_key = os.getenv("JIANYING_API_KEY", "")
base_url = os.getenv("JIANYING_BASE_URL", "")

config = ModelConfig(
    api_key=api_key,
    base_url=base_url,
    model_name="jianying",
    timeout=120,
)

adapter = ModelAdapterFactory.create_adapter("jianying", config)
result = adapter.generate(
    video_paths=["path/to/clip1.mp4", "path/to/clip2.mp4"],
    output_path="path/to/output/final_video.mp4",
)

print(result.success)
print(result.data)
print(result.error)
```

### 创建剪映草稿示例

```python
import requests

def create_jianying_draft(api_key: str, base_url: str, video_config: dict):
    """
    创建剪映草稿
    
    Args:
        api_key: API密钥
        base_url: 基础URL
        video_config: 视频配置（宽度、高度、帧率等）
    
    Returns:
        草稿ID
    """
    url = f"{base_url}/create_draft"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    response = requests.post(url, headers=headers, json=video_config)
    result = response.json()
    
    if response.status_code == 200:
        return result["draft_id"]
    else:
        raise Exception(f"创建草稿失败: {result}")

# 使用示例
api_key = "your-jianying-api-key-here"
base_url = "https://api.jianying.com/v1"
video_config = {
    "width": 1080,
    "height": 1920,
    "fps": 30,
    "name": "剪影生成视频"
}

draft_id = create_jianying_draft(api_key, base_url, video_config)
print(f"草稿创建成功，ID: {draft_id}")
```

### 视频剪辑示例（默认 FFmpeg）

本项目默认使用本地 FFmpeg 完成镜头拼接、字幕叠加与合音频（无需剪影配置），详见 `FFMPEG_VIDEO_EDIT_GUIDE.md`。

如需接入剪影 API，可参考上一节的适配器调用示例。

### 批量处理示例

```python
from pathlib import Path

def batch_process_videos(
    api_key: str,
    base_url: str,
    input_dir: str,
    output_dir: str
):
    """
    批量处理视频
    
    Args:
        api_key: API密钥
        base_url: 基础URL
        input_dir: 输入目录
        output_dir: 输出目录
    """
    input_path = Path(input_dir)
    output_path = Path(output_dir)
    output_path.mkdir(exist_ok=True)
    
    # 获取所有视频文件
    video_files = list(input_path.glob("*.mp4"))
    
    for i, video_file in enumerate(video_files):
        print(f"处理第 {i+1}/{len(video_files)} 个视频: {video_file.name}")
        
        # 调用剪辑API
        output_file = output_path / f"edited_{video_file.name}"
        # ... 调用剪辑逻辑
        
        print(f"完成: {output_file}")

# 使用示例
batch_process_videos(
    api_key="your-jianying-api-key-here",
    base_url="https://api.jianying.com/v1",
    input_dir="path/to/input",
    output_dir="path/to/output"
)
```

---

## 常见问题

### Q1: 剪影API密钥从哪里获取？

**A:** 有多种获取方式：

1. **开源项目**：访问 https://github.com/hey-jian-wei/jianying-mcp 或 https://gitee.com/yangshare/CapCutAPI 查看项目文档
2. **官方API**：访问剪映开放平台申请开发者权限
3. **第三方服务**：查看是否有提供在线MCP服务

### Q2: 剪影API是免费的吗？

**A:** 具体费用取决于使用方式：
- **开源库**：免费，但需要自己部署
- **官方API**：可能有免费额度和付费套餐
- **第三方服务**：根据服务商定价

### Q3: 可以不配置剪影API吗？

**A:** 可以不配置剪影API：
- ✅ 可以生成视频和音频
- ✅ 可用本地 FFmpeg 完成基础剪辑（合入音频、字幕烧录），见 FFMPEG_VIDEO_EDIT_GUIDE.md
- ❌ 不支持剪映模板/素材库/高级特效等能力（需要时再接入剪影API）
- ✅ 可批量处理（脚本/工作流层调用）

是否配置剪影 API 取决于是否需要模板/转场等高级剪辑能力；默认链路无需配置。

### Q4: 配置后如何测试？

**A:** 推荐分两步：

```bash
# 验证配置（需要已配置 JIANYING_*）
python -c "from adapters.model_adapters import ModelAdapterFactory; a=ModelAdapterFactory().get_adapter('jianying'); print(a.config.base_url)"
```

如需验证真实 API 调用，请使用上文的 Python 适配器示例（需要有效的 `JIANYING_*` 配置与可访问的服务端点）。

### Q5: 剪影API支持哪些视频格式？

**A:** 通常支持：
- **输入格式**：MP4, MOV, AVI, MKV等
- **输出格式**：MP4 (推荐), MOV, AVI等
- **编码格式**：H.264, H.265, ProRes等
- **分辨率**：支持多种分辨率，推荐1080x1920（竖屏）

### Q6: 如何查看剪影API的详细文档？

**A:** 
1. 查看GitHub仓库的README和Wiki
2. 查看项目的docs目录
3. 运行示例代码学习用法
4. 查看CapCutAPI开源项目的文档

### Q7: 本地部署MCP服务器需要什么环境？

**A:** 通常需要：
- Python 3.8+
- 必要的Python依赖包
- 足够的存储空间
- 稳定的网络连接

具体要求请参考项目文档。

### Q8: 剪影API支持哪些操作？

**A:** 根据CapCutAPI开源项目，支持：<mcreference link="https://gitee.com/yangshare/CapCutAPI" index="5">5</mcreference>
- 创建和管理草稿文件
- 添加视频、音频、图像素材
- 应用转场和特效
- 添加字幕和文本
- 调整时间轴
- 导出最终视频
- 批量处理多个项目

### Q9: API调用失败怎么办？

**A:** 检查以下几点：
1. 确认API密钥和Base URL配置正确
2. 检查网络连接
3. 查看API返回的错误信息
4. 确认API服务是否正常运行
5. 检查请求参数是否符合要求

### Q10: 如何获取技术支持？

**A:** 
1. 查看本文档的常见问题部分
2. 访问 https://github.com/hey-jian-wei/jianying-mcp 提交Issue
3. 查看CapCutAPI开源项目的文档和示例
4. 参考项目其他文档

---

## 相关文档

- [本地 FFmpeg 剪辑方案](FFMPEG_VIDEO_EDIT_GUIDE.md)
- [阿里云API密钥配置指南](ALIYUN_API_KEY_GUIDE.md)
- [模型ID映射指南](ALIYUN_MODEL_MAPPING_GUIDE.md)
- [多智能体协作指南](MULTI_AGENT_GUIDE.md)

---

## 技术支持

如有问题，请：
1. 查看本文档的常见问题部分
2. 访问 https://github.com/hey-jian-wei/jianying-mcp 提交Issue
3. 访问 https://gitee.com/yangshare/CapCutAPI 查看开源项目
4. 查看项目其他文档

---

## 参考资料

1. CapCutAPI开源项目介绍 <mcreference link="https://blog.csdn.net/j8267643/article/details/151724877" index="1">1</mcreference>
2. 剪映API接口文档 <mcreference link="https://blog.csdn.net/weixin_42238097/article/details/152228995" index="3">3</mcreference>
3. 剪映网页版官网 <mcreference link="https://m.php.cn/faq/1889818.html" index="4">4</mcreference>
4. CapCutAPI Gitee项目 <mcreference link="https://gitee.com/yangshare/CapCutAPI" index="5">5</mcreference>

---

**最后更新时间：** 2025-01-09
**文档版本：** v2.0
