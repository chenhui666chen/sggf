# 阿里云百炼模型快速上手指南

## 📚 文档导航

本目录包含阿里云百炼模型的完整配置和使用文档：

| 文档 | 说明 | 适用场景 |
|------|------|---------|
| **ALIYUN_MODEL_CONFIG_GUIDE.md** | 完整配置和使用指南 | 需要详细了解每个模型的配置和使用方法 |
| **ALIYUN_API_KEY_GUIDE.md** | API 密钥配置 | 获取与填写密钥 |
| **ALIYUN_MODEL_MAPPING_GUIDE.md** | 模型ID映射表 | 设置 `*_MODEL_ID` |
| **ALIYUN_QUICKSTART.md** (本文件) | 快速上手指南 | 快速开始使用阿里云百炼模型 |

---

## 🚀 快速开始（5分钟）

### 第一步：配置API密钥

1. **创建 .env 文件**
   ```bash
   cp .env.example .env
   ```

2. **获取API密钥**
   - 访问阿里云百炼控制台：https://bailian.console.aliyun.com/
   - 开通百炼服务并创建API-KEY
   - 将API-KEY复制到剪贴板

3. **编辑.env文件**
   - 打开项目根目录下的 `.env` 文件
   - 将所有 `your-dashscope-api-key-here` 替换为您的API-KEY
   - 保存文件

4. **验证配置**
   ```bash
   python -c "from adapters.model_adapters import ModelAdapterFactory; ModelAdapterFactory().get_adapter('wan_t2i'); print('ok')"
   ```
   如果看到 "ok"，说明配置可被适配器读取。

### 第二步：运行示例代码

```bash
python -c "from adapters.model_adapters import ModelAdapterFactory; a=ModelAdapterFactory().get_adapter('wan_t2i'); print(a.config.model_name)"
```

这将做一次适配器加载自检（不发起网络请求）。如需发起真实生成，请通过后端链路调用或在代码中调用适配器的 `generate()`。

### 第三步：集成到您的项目

参考以下代码片段，将阿里云百炼模型集成到您的项目中：

```python
from adapters.model_adapters import ModelAdapterFactory

# 创建适配器工厂
factory = ModelAdapterFactory()

# 获取文生图适配器（用于生成故事板帧）
wan_t2i_adapter = factory.get_adapter("wan_t2i")

# 生成图像
result = wan_t2i_adapter.generate(
    prompt="一个年轻女子站在夕阳下的海边，写实风格，电影质感",
    width=1280,
    height=720,
    num_inference_steps=30,
    guidance_scale=7.5
)

if result.success:
    print(f"生成的图像: {result.data['image_url']}")
else:
    print(f"生成失败: {result.error}")
```

---

## 🎯 模型ID速查表

根据您提供的控制台链接，以下是5个核心模型的快速参考：

| 模型ID | 模型名称 | 适配器别名 | 主要功能 | 典型用例 |
|--------|---------|-----------|---------|---------|
| **2862677** | 通义万相-文生图 | `wan_t2i` | 文本→图像 | 故事板帧生成、场景视觉化 |
| **2867393** | 通义万相-图生视频 | `wan_i2v` | 图像→视频 | 镜头视频生成、动画制作 |
| **3001146** | 通义万相-文生视频 | `wan_t2v` | 文本→视频 | 完整场景视频生成 |
| **2712576** | 通义万相-图像编辑 | `qwen_image_edit_plus` | 图像编辑 | 视觉优化、风格统一 |
| **2976416** | 通义万相-参考视频生成 | `wan_r2v` | 参考视频→新视频 | 风格迁移、角色一致性 |

---

## 💡 常用提示词模板

### 1. 故事板帧生成（模型ID: 2862677）

```python
prompt = """
{scene_description}

风格要求：
- 艺术风格：写实风格，电影质感
- 光照：黄金时刻的暖光，侧逆光
- 构图：三分法构图，主体位于右侧三分之一处
- 色调：暖色调，橙色、金色、蓝色渐变

技术参数：
- 分辨率：1280x720
- 质量等级：high
- 细节丰富度：高
"""
```

### 2. 镜头视频生成（模型ID: 2867393）

```python
prompt = """
{motion_description}

运动参数：
- 运动类型：缓慢旋转+细微动作
- 运动强度：中等
- 运动方向：从左到右
- 运动速度：慢速

技术参数：
 - 时长：5.0秒
 - 帧率：30fps
 - 运动桶ID：127
"""
```

### 3. 图像编辑（模型ID: 2712576）

```python
prompt = """
{edit_instruction}

编辑目标：
- 修改类型：质量修复
- 目标区域：人物面部
- 期望效果：五官清晰，表情自然
- 保持元素：发型、服装、背景

技术参数：
- 编辑强度：0.8
- 引导系数：7.5
"""
```

---

## 🎬 在织梦映心模块中的应用流程

### 完整工作流

```
章节文本（项目章节）
    ↓
[生成剧本草稿] → 文本→剧本（LLM 优先，失败回退规则）
    ↓
[人工审核/编辑] → DreamWeaver 剧本界面（通过后可继续）
    ↓
[实体抽取落库] → 角色/场景/道具写入项目库（project 级复用）
    ↓
[生成分镜/故事板] → 剧本→分镜（当前规则切分，可升级为 LLM）
    ↓
素材库Spec（角色/场景/道具，project级复用）
    ↓
[生成素材库图片] → 文生图模型 (2862677)
    ↓
[人工审核/重生成] → DreamWeaver 素材库界面（通过后可继续）
    ↓
[生成首帧] → 文生图模型 (2862677)
    ↓
[生成尾帧] → 文生图模型 (2862677)
    ↓
[生成视频] → 图生视频模型 (2867393)
    ↓
[质量评估] → 视觉语言模型 (qwen-vl-plus)
    ↓
[优化编辑] → 图像编辑模型 (2712576)
    ↓
[合并视频] → FFmpeg
    ↓
最终视频
```

### 剧本长期复用（审核门禁）

- 默认会停在 `waiting_script_approval`（必须审核通过才会进入分镜与素材库阶段）。
- 常用接口：`GET /api/v1/dreamweaver/runs/{run_id}/script`、`POST /api/v1/dreamweaver/runs/{run_id}/script`、`POST /api/v1/dreamweaver/runs/{run_id}/script/approve`、`POST /api/v1/dreamweaver/runs/{run_id}/resume-async`。

### 素材库长期复用（审核门禁）

- 素材库按 `project_id` 长期复用，首次生成会停在 `waiting_approval`（必须审核通过才会继续生成视频）。
- 素材库落盘目录：`runs/library/project_{project_id}/characters|scenes|props/`（每个实体 1 张基准图）。
- 常用接口：`GET /api/v1/dreamweaver/library/{project_id}`、`POST /api/v1/dreamweaver/library/{project_id}/approve`、`POST /api/v1/dreamweaver/library/{project_id}/regenerate`、`POST /api/v1/dreamweaver/runs/{run_id}/resume-async`。

### 风格预选（贯通一致性）

- UI 可选择 `style_preset`（例如：`cinematic_realistic`/`anime`/`ink_wash`/`cyberpunk`），贯通到素材库、分镜与关键帧生成，用于风格一致性。

### 代码示例

```python
from adapters.model_adapters import ModelAdapterFactory
import requests
from pathlib import Path


def download_to(url: str, out_path: Path) -> str:
    """将百炼返回的 URL 下载为本地文件路径（适配器通常读取本地文件并 base64 编码）。"""
    resp = requests.get(url, timeout=300)
    resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(resp.content)
    return str(out_path)

def generate_dreamweaver_video(storyboard):
    """生成织梦映心视频"""
    factory = ModelAdapterFactory()
    work_dir = Path("output/dreamweaver_demo")
    
    video_clips = []
    
    for shot in storyboard.shots:
        # 1. 生成首帧
        t2i_adapter = factory.get_adapter("wan_t2i")
        head_result = t2i_adapter.generate(
            prompt=shot.visual_description,
            width=1280,
            height=720
        )
        head_path = download_to(head_result.data["image_url"], work_dir / f"{shot.shot_id}_head.png")
        
        # 2. 生成尾帧
        tail_result = t2i_adapter.generate(
            prompt=shot.tail_visual_description,
            width=1280,
            height=720
        )
        tail_path = download_to(tail_result.data["image_url"], work_dir / f"{shot.shot_id}_tail.png")
        
         # 3. 生成视频
         i2v_adapter = factory.get_adapter("wan_i2v")
         video_result = i2v_adapter.generate(
             image_path=head_path,
             prompt=shot.motion_description,
            duration=5.0,
            fps=30
         )
         video_path = download_to(video_result.data["video_url"], work_dir / f"{shot.shot_id}.mp4")
         
        # 4. 质量评估
        vl_adapter = factory.get_adapter("qwen3_vl_plus")
        quality = vl_adapter.analyze_video(
            video_path=video_path,
            criteria=["clarity", "smoothness", "consistency"]
        )
        
        # 5. 如果质量不达标，使用图像编辑优化
        if quality.data["overall_score"] < 7.0:
            edit_adapter = factory.get_adapter("qwen_image_edit_plus")
            edit_adapter.generate(
                image_path=head_path,
                edit_prompt="优化图像质量，提升清晰度",
                strength=0.8
            )
        
        video_clips.append(video_path)
    
    # 6. 合并视频
    # 使用FFmpeg合并所有视频片段
    merged_video = merge_video_clips(video_clips)
    
    return merged_video
```

---

## 🔧 高级技巧

### 1. 批量生成与并发控制

```python
import asyncio
from asyncio import Semaphore

async def batch_generate(prompts, max_concurrent=3):
    """并发批量生成"""
    factory = ModelAdapterFactory()
    adapter = factory.get_adapter("wan_t2i")
    semaphore = Semaphore(max_concurrent)
    
    async def generate_with_semaphore(prompt):
        async with semaphore:
            return await adapter.generate_async(prompt=prompt)
    
    tasks = [generate_with_semaphore(p) for p in prompts]
    return await asyncio.gather(*tasks)
```

### 2. 缓存机制

```python
from functools import lru_cache
import hashlib

def get_cache_key(prompt, **kwargs):
    """生成缓存键"""
    key_str = f"{prompt}_{kwargs}"
    return hashlib.md5(key_str.encode()).hexdigest()

@lru_cache(maxsize=1000)
def generate_cached(cache_key, prompt, **kwargs):
    """带缓存的生成"""
    factory = ModelAdapterFactory()
    adapter = factory.get_adapter("wan_t2i")
    return adapter.generate(prompt=prompt, **kwargs)
```

### 3. 多候选生成与评选

```python
def generate_with_candidates(prompt, num_candidates=3):
    """生成多个候选并选择最佳"""
    factory = ModelAdapterFactory()
    adapter = factory.get_adapter("wan_t2i")
    vl_adapter = factory.get_adapter("qwen3_vl_plus")
    work_dir = Path("output/candidates_demo")
    
    candidates = []
    for _ in range(num_candidates):
        result = adapter.generate(prompt=prompt, seed=None)
        if result.success:
            candidates.append(result.data)
    
    # 评估并选择最佳
    best_candidate = None
    best_score = 0
    
    for idx, candidate in enumerate(candidates, 1):
        image_path = download_to(candidate["image_url"], work_dir / f"cand_{idx}.png")
        score = vl_adapter.analyze_image(
            image_path=image_path,
            criteria=["quality", "clarity", "composition"]
        )
        if score.data["overall_score"] > best_score:
            best_score = score.data["overall_score"]
            best_candidate = candidate
    
    return best_candidate
```

---

## 📊 性能优化建议

| 优化项 | 说明 | 预期效果 |
|--------|------|---------|
| **批量处理** | 一次性生成多个内容 | 减少50%的API调用次数 |
| **缓存机制** | 缓存重复的生成结果 | 减少80%的重复计算 |
| **并发控制** | 控制并发数量，避免超限 | 提高生成速度3-5倍 |
| **降级策略** | 主模型失败时使用备用模型 | 提高成功率至95%以上 |
| **参数调优** | 根据需求调整steps、guidance_scale | 平衡质量与速度 |

---

## 🆘 常见问题

### Q1: 如何选择合适的模型？

**A**: 
- **快速预览** → 使用文生图模型 (2862677)
- **高质量视频** → 使用图生视频模型 (2867393)
- **完整场景** → 使用文生视频模型 (3001146)
- **风格统一** → 使用参考视频生成模型 (2976416)
- **细节优化** → 使用图像编辑模型 (2712576)

### Q2: 如何降低API调用成本？

**A**:
1. 使用批量处理减少请求次数
2. 实现缓存机制避免重复调用
3. 合理设置生成参数（分辨率、时长等）
4. 使用降级策略，必要时使用低成本方案
5. 监控API配额，避免超限

### Q3: 如何提高生成质量？

**A**:
1. 优化提示词，提供更详细的描述
2. 使用参考图像或视频
3. 批量生成多个版本，选择最佳结果
4. 使用图像编辑模型进行后期优化
5. 调整技术参数（steps、guidance_scale等）

### Q4: 如何处理API调用失败？

**A**:
1. 实现重试机制（最多3次）
2. 记录详细的错误日志
3. 实现降级方案，使用备用模型
4. 监控API配额，避免超限
5. 设置合理的超时时间

---

## 📖 参考资源

### 官方文档
- [阿里云百炼平台](https://bailian.console.aliyun.com/)
- [通义万相API文档](https://help.aliyun.com/zh/model-studio/developer-reference/wanxiang-api)
- [文生图API参考](https://help.aliyun.com/zh/model-studio/developer-reference/text-to-image-api-reference)
- [图生视频API参考](https://help.aliyun.com/zh/model-studio/developer-reference/image-to-video-api-reference)

### 项目文档
- [ALIYUN_MODEL_CONFIG_GUIDE.md](./ALIYUN_MODEL_CONFIG_GUIDE.md) - 完整配置和使用指南
- [ALIYUN_MODEL_MAPPING_GUIDE.md](./ALIYUN_MODEL_MAPPING_GUIDE.md) - 模型ID映射表
- [DREAMWEAVER_TODO.md](./docs/DREAMWEAVER_TODO.md) - 织梦映心模块待办事项

---

## 🎉 开始使用

现在您已经了解了阿里云百炼模型的基本用法，可以开始构建您的漫剧生成系统了！

**下一步：**
1. 按 `.env.example` 配置 `.env`（填写所需 API Key/Base URL/Model ID）
2. 运行适配器自检命令，确认配置可读取（见本文“验证配置”步骤）
3. 阅读 [ALIYUN_MODEL_CONFIG_GUIDE.md](./ALIYUN_MODEL_CONFIG_GUIDE.md) 了解详细配置
4. 开始集成到您的项目中

**祝您使用愉快！** 🚀
