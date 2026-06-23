# 模型档案总览
日期：`2026-03-15`

## 1. 说明

本文件汇总项目当前已接入或已在代码路径中实际使用的主要模型档案，重点补充：

- 模型定位
- 适用场景
- 已知限制
- 项目接入备注
- 官方资料入口

说明：

- 文本大模型档案已同步写入 `config/llm_models.yaml`
- 图像 / 视频 / TTS / 多模态模型档案已同步写入 `config/models.yaml`
- 其中部分“项目内部模型 id 与官方模型家族的映射关系”来自项目现有适配层与官方文档的综合判断，属于工程映射，不等同于官方命名

## 2. 文本模型

### qwen3-max

- 定位：项目中文创作主力模型，对应阿里云通义千问 Max 系列接入
- 适用：故事概念生成、章节正文、角色对话、风格保持、结构化 JSON 输出
- 限制：纯推理审校不如 `deepseek-v4-pro`；整书级长上下文不如 `qwen-long`
- 项目备注：当前 `chapter / concept / dialogue` 等任务默认优先路由到该模型
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/getting-started/models
  - https://help.aliyun.com/zh/model-studio/text-generation

### qwen-long

- 定位：项目超长上下文模型
- 适用：大纲扩展、整书汇总、长文档理解、RAG 结果聚合后二次加工
- 限制：延迟高于 `qwen3-max` 与 `qwen-turbo`，不适合作为高频低延迟对话模型
- 项目备注：当前 `outline_expand / book_synthesis` 默认优先路由到该模型
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/long-context
  - https://help.aliyun.com/zh/model-studio/getting-started/models

### qwen-turbo

- 定位：项目轻量快速文本模型
- 适用：实体提取、轻量摘要、格式化、低成本预处理
- 限制：复杂创作质量不如 `qwen3-max`，严谨推理不如 `deepseek-v4-pro`
- 项目备注：当前 `entity_extract / summarize / fast` 等任务会优先命中
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/getting-started/models
  - https://help.aliyun.com/zh/model-studio/text-generation

### deepseek-v4-pro

- 定位：项目高强度推理与审校模型
- 适用：世界观逻辑、人物动机、结构评审、质量复审、有声剧本逻辑检查
- 限制：延迟高；当前项目接入层不向其开放 `temperature / timeout / max_retries`
- 项目备注：当前通过 DeepSeek 官方 API 接入，项目运行时会剥离推理痕迹标签，只保留最终可消费文本
- 官方资料：
  - https://api-docs.deepseek.com/zh-cn/
  - https://api-docs.deepseek.com/zh-cn/quick_start/pricing

### deepseek-v4-flash

- 定位：项目通用对话与快速改写模型
- 适用：AI 痕迹处理、快速润色、低延迟交互、轻量创作辅助
- 限制：深度逻辑与多步分析不如 `deepseek-v4-pro`
- 项目备注：当前 `rewrite / ai_trace / chat` 优先使用该模型
- 官方资料：
  - https://api-docs.deepseek.com/zh-cn/
  - https://api-docs.deepseek.com/zh-cn/quick_start/pricing

## 3. 图像与多模态模型

### wan2.6-t2i

- 定位：项目主图像生成模型，统一使用实际调用名 `wan2.6-t2i`
- 适用：封面草图、角色概念图、分镜概念图、带参考图的风格生成
- 限制：多轮一致性仍依赖提示词与参考图
- 项目备注：项目内统一使用正式调用名称 `wan2.6-t2i`
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/text-to-image-v1-api-reference
  - https://help.aliyun.com/zh/model-studio/getting-started/models

### qwen3-vl-plus

- 定位：项目中的图像 / 视频理解与多模态分析模型
- 适用：图像质检、视频内容分析、视觉资产审核、多模态问答
- 限制：它是分析模型，不是资产生成模型
- 项目备注：项目适配器提供 `chat / analyze_image / analyze_video` 三类入口
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/vision
  - https://help.aliyun.com/zh/model-studio/getting-started/models

### qwen-image-edit-plus

- 定位：项目主图像编辑模型
- 适用：角色图精修、指令式重绘、多参考图编辑
- 限制：请求 schema 比普通 chat 模式更严格，多图时需要兼容性回退
- 项目备注：项目里已经为多图内容顺序和回退做了兼容处理
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/image-edit-api-reference
  - https://help.aliyun.com/zh/model-studio/getting-started/models

### qwen-image-edit-max

- 定位：高质量图像编辑升级路径
- 适用：最终交付素材、复杂构图编辑、高要求精修
- 限制：更慢，成本也更高
- 项目备注：适合作为 `qwen-image-edit-plus` 失败或质量不足时的升级选项
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/image-edit-api-reference

## 4. 视频模型

### wan2.6-t2v

- 定位：项目主文本生视频模型
- 适用：短视频镜头生成、预告片片段、DreamWeaver 镜头生成
- 限制：延迟高，短时长片段更稳；不直接承担对白音频生成
- 项目备注：项目默认偏向 5 秒短片以换取更稳定的输出
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/video-synthesis
  - https://help.aliyun.com/zh/model-studio/getting-started/models

### wan2.6-t2v-fast

- 定位：主视频模型的速度优先降级路径
- 适用：预览片段、超时降级、早期分镜验证
- 限制：画质与稳定性弱于 `wan2.6-t2v`
- 项目备注：不建议作为最终视频主路径
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/video-synthesis

### wan2.6-i2v

- 定位：项目图生视频路径
- 适用：将关键帧、角色卡或静态分镜动画化
- 限制：动作控制仍需要较保守的提示结构
- 项目备注：当前通过项目适配桥接使用，适合单主体短片
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/image-to-video
  - https://help.aliyun.com/zh/model-studio/video-synthesis

### wan2.6-r2v

- 定位：项目参考驱动的视频生成路径
- 适用：保持风格一致、参考图 / 参考视频约束下的视频生成
- 限制：对参考素材质量要求更高，不适合完全开放式探索
- 项目备注：更适合“有明确素材基底”的视频生成流程
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/video-synthesis
  - https://help.aliyun.com/zh/model-studio/getting-started/models

## 5. TTS 与语音模型

### qwen3-tts-instruct-flash

- 定位：项目默认 TTS 模型
- 适用：批量有声书合成、日更章节合成、低成本稳定朗读、需要自然语言 instructions 的标准旁白
- 限制：当前项目链路重点支持 instructions，不建议输出 SSML
- 项目备注：项目里的音色目录、speaker 归一化、instructions 映射和时间戳保留都围绕该模型实现
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/text-to-speech-syn
  - https://help.aliyun.com/zh/model-studio/getting-started/models

### cosyvoice-v3.5-plus

- 定位：项目高表现力 TTS / 音色复刻模型
- 适用：精品有声书、强情绪场景、角色差异化旁白、复刻音色
- 限制：成本和操作复杂度高于 `qwen3-tts-instruct-flash`
- 项目备注：项目已提供 clone 创建、查询、删除等专用接口
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/text-to-speech-syn
  - https://help.aliyun.com/zh/model-studio/timbre-list

## 2026-03-16 更新

- `adapters/model_adapters.py` 现在会把 `wan_t2i/wan_i2v/wan_t2v/wan_r2v`、`qwen_image_edit_*`、`wan_image_edit`、`qwen_multiperson_fusion`、`qwen3_vl_plus` 等历史 adapter 类的公开入口薄代理到 runtime wrapper。
- 上述历史媒体 adapter 在 `adapters/model_adapters.py` 中原有的旧 HTTP / DashScope 实现已继续物理清理，当前保留的是兼容入口与统一委托逻辑，而不是双份实现并存。
- 业务侧的 DreamWeaver / Painter / Asset Library / AutoQC / DreamWeaver API 调用面已继续收口：其中 DreamWeaver / AutoQC / DreamWeaver API 已直接走统一 helper，`agents/asset_library.py` 仍通过 `create_runtime_client(...)` 直接创建 runtime wrapper 客户端，而 `agents/painter.py` 已改为完全由字符串 `model_id` 驱动候选生成与多人物融合链路，不再在业务层使用 `SimpleAdapterFactory`。
- `adapters.adapter_helpers.match_scene(...)` 已作为统一多人物融合场景匹配 helper 接入，`qwen_multiperson_fusion` 也已加入统一模型别名归一化；`agents/painter.py` 又进一步前移了一层，其 keyframe / midframe 的 T2I、image-edit、VLM、multiperson-fusion 主链路现在都支持直接传入字符串 `model_id`，连并行候选 clone 兼容路径也不再需要 `create_runtime_client(...)`。
- `legacy_runtime_wrappers.py` 也已继续收口到统一 helper：当前 `qwen3_vl_plus`、`wan_t2i`、`wan_t2v`、`wan_i2v`、`wan_r2v`、`qwen_image_edit_*`、`wan_image_edit`、`qwen_multiperson_fusion` 等 wrapper 的内部执行优先复用 `adapter_helpers`，wrapper 本身更多只保留旧签名兼容职责；与此同时，统一 helper 已补齐 `generate_video.negative_prompt` 与 `edit_image.seed` 的标准字段透传。
- `adapters.adapter_helpers.build_legacy_tts_request(...)` 已作为统一旧 TTS 参数归一化入口接入，`SimpleAdapter`、`Qwen3TTSRuntimeWrapper`、`Qwen3TTSAdapter` 现在会共用同一套 `voice_style/speed/pitch/volume` 转换规则。
- 项目新增 `tests/test_model_adapters_legacy_delegate.py`，专门覆盖“直接实例化历史媒体 adapter”这一类过去缺少回归保护的调用面。
- 项目同时新增 `tests/test_adapter_helpers_media_runtime.py`、`tests/test_vlm_model_id_compat.py` 与 `tests/test_painter_model_id_runtime.py`，用于覆盖统一 helper 媒体入口、VLM 直接传 `model_id`、Painter 底层候选生成与并行路径直接传 `model_id`，以及多人物融合场景匹配继续走统一 helper 的兼容调用面。
- `Qwen3TTSAdapter` 新增对 `backend/app/services/audiobook/constants.py` 的轻量 fallback 加载，确保在隔离测试环境里也能继续完成旧 CosyVoice speaker ID 到 Qwen3-TTS speaker 的归一化。
- 2026-03-16 定向回归结果：`38 passed`。
- 2026-03-16 最新回归结果：`91 passed, 2 warnings`。

## 6. 当前差距与状态

这次补充后，项目已经具备两层模型知识记录：

- 程序可读配置：
  - `config/llm_models.yaml`
  - `config/models.yaml`
- 人可读档案文档：
  - 当前文件

当前工程状态：

- 文本模型已经由 `ModelHub` 统一加载、选型与调用
- 图像 / 视频 / 图像编辑 / 视觉分析 / TTS 已新增统一多模态运行时 `core/unified_media_runtime.py`
- `adapters/adapter_helpers.py` 现在统一委托给多模态运行时，显式 `model_id` 会真正参与路由
- `SimpleAdapterFactory` 已支持对 runtime wrapper 的懒代理，旧方法如 `chat/analyze_image/match_scene` 在历史 Agent 中也能继续落到新机制
- 有声书业务中的 TTS 试听接口与 `AudiobookEngine` 初始化已改走统一多模态运行时 / TTS 工厂
- `config/models.yaml` 继续作为图像 / 视频 / TTS / 多模态模型档案中心，运行时会读取这些档案做模型选择
- `qwen3-vl-plus`、`qwen-image-edit-plus`、`qwen-image-edit-max`、`wan2.6-t2i`、`wan2.6-t2v`、`wan2.6-i2v`、`wan2.6-r2v` 已具备 registry-backed adapter，可直接由统一运行时通过 registry 获取
- `wan_t2i/wan26_t2i`、`wan_t2v/wan26_t2v`、`qwen3_tts` 等历史 key 已优先接入 runtime wrapper，不再默认回退到旧 media adapter 链路

仍然保留的工程边界：

- 仍有部分历史 Agent 代码直接使用 `adapters/model_adapters.py` 里的 `ModelAdapterFactory`，这些调用点尚未全部迁到新的 registry/runtime facade
- `legacy_bridge` 目前仅保留少量非统一媒体路径的旧式兜底，媒体模型侧的旧 fallback 已基本清空
- 如果后续继续推进，建议继续把各个 Agent 内部直接 new / get 旧式 `ModelAdapterFactory` 的位置逐步改成调用统一多模态运行时
