# 视频处理API

<cite>
**本文引用的文件**   
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)
- [adapters/vidu_platform/video.py](file://adapters/vidu_platform/video.py)
- [adapters/volcengine/video.py](file://adapters/volcengine/video.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)
- [agents/dreamweaver_agent_pkg/_slideshow.py](file://agents/dreamweaver_agent_pkg/_slideshow.py)
- [agents/storyboarder_pkg/_audio_sync.py](file://agents/storyboarder_pkg/_audio_sync.py)
- [backend/app/tasks/dreamweaver_tasks.py](file://backend/app/tasks/dreamweaver_tasks.py)
- [backend/app/services/batch_processor.py](file://backend/app/services/batch_processor.py)
- [backend/app/core/config.py](file://backend/app/core/config.py)
- [schemas/unified_model_spec.py](file://schemas/unified_model_spec.py)
- [core/unified_media_runtime.py](file://core/unified_media_runtime.py)
</cite>

## 目录
1. [简介](#简介)
2. [项目结构](#项目结构)
3. [核心组件](#核心组件)
4. [架构总览](#架构总览)
5. [详细组件分析](#详细组件分析)
6. [依赖关系分析](#依赖关系分析)
7. [性能考量](#性能考量)
8. [故障排查指南](#故障排查指南)
9. [结论](#结论)
10. [附录](#附录)

## 简介
本文件为“小说创作代理系统”的视频处理API文档，覆盖以下能力：
- AI视频生成（文本到视频、图像到视频）
- 分镜制作与镜头切换
- 特效添加与转码合成
- 格式转换、分辨率调整、帧率优化与压缩编码
- 视频剪辑、字幕叠加、音频同步与导出配置
- 批量处理、进度跟踪与错误恢复

该API通过后端FastAPI路由暴露，结合任务队列与FFmpeg媒体管线，提供稳定可靠的端到端视频处理能力。

## 项目结构
围绕视频处理的代码主要分布在以下模块：
- API层：dreamweaver相关路由定义对外接口
- 服务层：视频生成编排、任务调度、批处理
- 适配器层：对接不同AI视频模型供应商
- 媒体管线：FFmpeg封装用于转码、剪辑、合成
- Agent层：分镜、幻灯片、音视频同步等高级功能
- 配置与规范：统一模型规格、媒体运行时抽象

```mermaid
graph TB
Client["客户端"] --> API["Dreamweaver API路由"]
API --> Service["视频生成服务"]
Service --> Tasks["后台任务队列"]
Tasks --> Adapters["视频模型适配器<br/>T2V/I2V"]
Service --> FFmpeg["FFmpeg媒体管线"]
Service --> Agents["Agent: 分镜/幻灯片/音画同步"]
Adapters --> Providers["外部视频模型供应商"]
FFmpeg --> Outputs["输出视频/封面/字幕"]
```

**图表来源** 
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)
- [agents/dreamweaver_agent_pkg/_slideshow.py](file://agents/dreamweaver_agent_pkg/_slideshow.py)
- [agents/storyboarder_pkg/_audio_sync.py](file://agents/storyboarder_pkg/_audio_sync.py)

**章节来源**
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)

## 核心组件
- Dreamweaver API路由：提供视频生成、编辑、转码、合成的HTTP入口
- 视频生成服务：编排T2V/I2V调用、参数校验、结果聚合
- 模型适配器：统一不同供应商的T2V/I2V接口
- FFmpeg媒体管线：封装转码、裁剪、缩放、滤镜、字幕、合并
- Agent：分镜构建、幻灯片生成、音视频同步
- 任务与批处理：异步任务、进度上报、失败重试与恢复

**章节来源**
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)
- [agents/dreamweaver_agent_pkg/_slideshow.py](file://agents/dreamweaver_agent_pkg/_slideshow.py)
- [agents/storyboarder_pkg/_audio_sync.py](file://agents/storyboarder_pkg/_audio_sync.py)

## 架构总览
整体流程从API接收请求开始，经过服务层编排，调用模型适配器生成视频片段，再通过FFmpeg进行剪辑、转码、合成与导出；同时支持任务队列与进度追踪。

```mermaid
sequenceDiagram
participant C as "客户端"
participant A as "Dreamweaver API"
participant S as "视频生成服务"
participant T as "任务队列"
participant AD as "模型适配器(T2V/I2V)"
participant F as "FFmpeg媒体管线"
C->>A : "POST /api/v1/dreamweaver/generate"
A->>S : "创建生成任务(参数校验)"
S->>T : "入队异步任务"
T-->>S : "任务回调/状态更新"
S->>AD : "调用T2V/I2V生成片段"
AD-->>S : "返回片段URL/路径"
S->>F : "转码/剪辑/合成/字幕"
F-->>S : "输出最终视频"
S-->>A : "任务完成/结果地址"
A-->>C : "返回任务ID与下载链接"
```

**图表来源** 
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [backend/app/tasks/dreamweaver_tasks.py](file://backend/app/tasks/dreamweaver_tasks.py)

## 详细组件分析

### 视频生成API（文本到视频、图像到视频）
- 接口职责：接收文本或图像输入，选择合适模型，生成视频片段并返回任务ID与状态查询方式
- 关键参数：提示词、参考图、时长、分辨率、帧率、模型ID、质量预设
- 返回内容：任务ID、状态、预计完成时间、结果下载地址（完成后）

```mermaid
classDiagram
class VideoGenerationService {
+generate_text_to_video(params) TaskResult
+generate_image_to_video(params) TaskResult
-validate_params(params) bool
-select_model(spec) ModelAdapter
-aggregate_results(tasks) VideoOutput
}
class T2VAdapter {
+call(prompt, params) MediaResult
+poll_status(task_id) Status
}
class I2VAdapter {
+call(image_url, prompt, params) MediaResult
+poll_status(task_id) Status
}
VideoGenerationService --> T2VAdapter : "使用"
VideoGenerationService --> I2VAdapter : "使用"
```

**图表来源** 
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)

**章节来源**
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)

### 分镜制作与镜头切换
- 功能说明：根据脚本或故事大纲生成分镜序列，定义每个镜头的时长、转场效果、画面描述
- 实现要点：分镜实体建模、镜头属性管理、转场策略（淡入淡出、推拉摇移）
- 输出：分镜JSON、预览图、后续生成所需的提示词与参数

```mermaid
flowchart TD
Start(["开始"]) --> ParseScript["解析脚本/大纲"]
ParseScript --> BuildShots["构建分镜序列"]
BuildShots --> DefineDuration["设定镜头时长"]
DefineDuration --> ChooseTransition{"选择转场类型"}
ChooseTransition --> |淡入淡出| Fade["应用淡入淡出"]
ChooseTransition --> |推拉摇移| CameraMove["应用镜头运动"]
ChooseTransition --> |硬切| HardCut["硬切"]
Fade --> Output["输出分镜元数据"]
CameraMove --> Output
HardCut --> Output
Output --> End(["结束"])
```

**图表来源** 
- [agents/storyboarder_pkg/_entities.py](file://agents/storyboarder_pkg/_entities.py)
- [agents/storyboarder_pkg/_shot_profile.py](file://agents/storyboarder_pkg/_shot_profile.py)
- [agents/storyboarder_pkg/_video_subshots.py](file://agents/storyboarder_pkg/_video_subshots.py)

**章节来源**
- [agents/storyboarder_pkg/_entities.py](file://agents/storyboarder_pkg/_entities.py)
- [agents/storyboarder_pkg/_shot_profile.py](file://agents/storyboarder_pkg/_shot_profile.py)
- [agents/storyboarder_pkg/_video_subshots.py](file://agents/storyboarder_pkg/_video_subshots.py)

### 特效添加与转码合成
- 功能说明：在视频片段上叠加特效（如模糊、锐化、调色）、拼接多段素材、合成字幕与音频
- 实现要点：FFmpeg滤镜链、多路输入合并、时间轴对齐、编码参数优化

```mermaid
sequenceDiagram
participant S as "服务层"
participant F as "FFmpeg管线"
participant V as "视频片段集合"
participant A as "音频轨道"
participant Sub as "字幕轨道"
S->>F : "初始化滤镜链(特效/转场)"
S->>F : "加载视频片段V"
S->>F : "加载音频轨道A"
S->>F : "加载字幕轨道Sub"
F-->>S : "渲染合成结果"
S-->>S : "保存输出文件"
```

**图表来源** 
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)

**章节来源**
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)

### 格式转换、分辨率调整、帧率优化与压缩编码
- 支持的格式：MP4、WebM、MOV等常见容器
- 分辨率调整：按目标设备或平台要求缩放
- 帧率优化：根据内容动态调整帧率以平衡流畅度与体积
- 压缩编码：H.264/H.265、比特率控制、码率自适应

```mermaid
flowchart TD
In["输入视频"] --> Detect["检测格式/分辨率/帧率"]
Detect --> Scale{"需要缩放?"}
Scale --> |是| Resize["执行分辨率缩放"]
Scale --> |否| Keep["保持原分辨率"]
Resize --> FPS{"需要调整帧率?"}
Keep --> FPS
FPS --> |是| AdjustFPS["重采样帧率"]
FPS --> |否| Encode["进入编码阶段"]
AdjustFPS --> Encode
Encode --> Codec{"选择编码器(H.264/H.265)"}
Codec --> Bitrate["设置比特率/质量预设"]
Bitrate --> Container["封装输出容器(MP4/WebM)"]
Container --> Out["输出视频"]
```

**图表来源** 
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [core/unified_media_runtime.py](file://core/unified_media_runtime.py)

**章节来源**
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [core/unified_media_runtime.py](file://core/unified_media_runtime.py)

### 视频剪辑、字幕添加、音频同步与导出配置
- 视频剪辑：按时间轴裁剪、拼接、去黑边
- 字幕添加：SRT/ASS/VTT格式支持，样式与位置配置
- 音频同步：确保音画同步，处理延迟与偏移
- 导出配置：分辨率、帧率、编码、比特率、容器格式

```mermaid
sequenceDiagram
participant U as "用户"
participant API as "剪辑API"
participant P as "剪辑服务"
participant F as "FFmpeg管线"
participant S as "字幕服务"
participant A as "音频服务"
U->>API : "提交剪辑任务(时间范围/字幕/音频)"
API->>P : "解析参数与校验"
P->>F : "执行裁剪与拼接"
P->>S : "叠加字幕"
P->>A : "同步音频轨道"
F-->>P : "输出剪辑结果"
P-->>API : "返回下载链接"
API-->>U : "返回结果"
```

**图表来源** 
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)
- [agents/storyboarder_pkg/_audio_sync.py](file://agents/storyboarder_pkg/_audio_sync.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)

**章节来源**
- [agents/dreamweaver_agent_pkg/_write_video.py](file://agents/dreamweaver_agent_pkg/_write_video.py)
- [agents/storyboarder_pkg/_audio_sync.py](file://agents/storyboarder_pkg/_audio_sync.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)

### 批量视频处理、进度跟踪与错误恢复
- 批量处理：支持多任务并发、队列管理、资源限流
- 进度跟踪：任务状态机、事件上报、WebSocket/SSE推送
- 错误恢复：失败重试、断点续传、异常分类与告警

```mermaid
stateDiagram-v2
[*] --> 排队中
排队中 --> 处理中 : "分配资源"
处理中 --> 成功 : "完成"
处理中 --> 失败 : "异常"
失败 --> 重试中 : "自动重试"
重试中 --> 处理中 : "重试成功"
重试中 --> 失败 : "重试耗尽"
成功 --> [*]
失败 --> [*]
```

**图表来源** 
- [backend/app/tasks/dreamweaver_tasks.py](file://backend/app/tasks/dreamweaver_tasks.py)
- [backend/app/services/batch_processor.py](file://backend/app/services/batch_processor.py)

**章节来源**
- [backend/app/tasks/dreamweaver_tasks.py](file://backend/app/tasks/dreamweaver_tasks.py)
- [backend/app/services/batch_processor.py](file://backend/app/services/batch_processor.py)

## 依赖关系分析
- API层依赖服务层进行业务编排
- 服务层依赖适配器调用外部模型供应商
- 媒体管线依赖FFmpeg工具链
- Agent层依赖分镜与音视频同步逻辑
- 配置与规范层提供统一模型规格与媒体运行时抽象

```mermaid
graph LR
API["Dreamweaver API"] --> Service["视频生成服务"]
Service --> Adapter["模型适配器"]
Service --> FFmpeg["FFmpeg管线"]
Service --> Agent["分镜/幻灯片/音画同步"]
Adapter --> Provider["外部供应商"]
Config["配置与规范"] --> Service
Config --> Adapter
```

**图表来源** 
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [adapters/video_t2v.py](file://adapters/video_t2v.py)
- [adapters/video_i2v.py](file://adapters/video_i2v.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)
- [schemas/unified_model_spec.py](file://schemas/unified_model_spec.py)
- [core/unified_media_runtime.py](file://core/unified_media_runtime.py)

**章节来源**
- [backend/app/api/v1/dreamweaver.py](file://backend/app/api/v1/dreamweaver.py)
- [backend/app/services/dreamweaver/video_generation_service.py](file://backend/app/services/dreamweaver/video_generation_service.py)
- [schemas/unified_model_spec.py](file://schemas/unified_model_spec.py)
- [core/unified_media_runtime.py](file://core/unified_media_runtime.py)

## 性能考量
- 并发与限流：合理设置任务队列大小与并发度，避免资源争用
- 编码优化：选择合适的编码器与预设，平衡质量与速度
- 缓存策略：对重复生成的片段进行缓存，减少重复计算
- 内存管理：大文件处理时采用流式读写，避免内存溢出
- 监控与日志：记录关键指标与错误信息，便于问题定位

[本节为通用指导，不直接分析具体文件]

## 故障排查指南
- 常见问题：模型调用超时、FFmpeg命令失败、资源不足、参数校验错误
- 排查步骤：检查任务状态、查看日志、验证输入参数、确认环境依赖
- 恢复策略：重试机制、降级方案、人工干预

**章节来源**
- [backend/app/tasks/dreamweaver_tasks.py](file://backend/app/tasks/dreamweaver_tasks.py)
- [pipeline/ffmpeg_runner.py](file://pipeline/ffmpeg_runner.py)

## 结论
本API为小说创作代理系统提供了完整的视频处理能力，涵盖生成、编辑、转码、合成等关键环节。通过模块化设计与异步任务机制，实现了高可用与可扩展性。建议在生产环境中加强监控与日志记录，确保系统稳定运行。

[本节为总结性内容，不直接分析具体文件]

## 附录
- 配置项说明：模型选择、编码参数、队列配置
- 示例调用：API请求与响应格式
- 最佳实践：参数调优、错误处理、性能优化

[本节为补充信息，不直接分析具体文件]