# 模型档案总览
日期：`2026-03-15`
最近更新：`2026-10-09`（第 2～6 节按当前注册中心重写为现役内部 ID；带日期的小节保留当时的取证记录）

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

内部 ID 采用不含版本号的中性名，升级换代不换 ID；发给上游的真名由 `config/llm_models.yaml` 的
`default_params.request_model` 钉死，因此下列"上游线名"与内部 ID 不同属设计使然。

### qwen-plus

- 上游线名：`qwen3.7-plus`
- 定位：项目中文创作主力模型，对应阿里云通义千问 Plus 系列接入
- 适用：故事概念生成、章节正文、角色对话、风格保持、结构化 JSON 输出
- 限制：纯推理审校不如 `deepseek-pro`；超长整书级任务仍需分层摘要策略
- 项目备注：当前 `chapter / concept / dialogue` 等任务默认优先路由到该模型
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/getting-started/models
  - https://help.aliyun.com/zh/model-studio/text-generation

### deepseek-pro

- 上游线名：`deepseek-v4-pro`
- 定位：项目高强度推理与审校模型
- 适用：世界观逻辑、人物动机、结构评审、质量复审、有声剧本逻辑检查
- 限制：延迟高；当前项目接入层不向其开放 `temperature / timeout / max_retries`
- 项目备注：当前通过 DeepSeek 官方 API 接入，项目运行时会剥离推理痕迹标签，只保留最终可消费文本
- 官方资料：
  - https://api-docs.deepseek.com/zh-cn/
  - https://api-docs.deepseek.com/zh-cn/quick_start/pricing

### deepseek-flash

- 定位：项目通用对话与快速改写模型
- 适用：AI 痕迹处理、快速润色、低延迟交互、轻量创作辅助
- 限制：深度逻辑与多步分析不如 `deepseek-pro`
- 项目备注：当前 `rewrite / ai_trace / chat` 优先使用该模型
- 现状（2026-10-09 更新）：上游已把旧线名从官方模型列表移除，请求旧名会被 DeepSeek 静默改写为本模型
  （响应 `model` 字段可证）。项目内 `deepseek-flash` 是唯一入口（上下文 1048576、最大输出 393216），
  旧线名既不是注册 ID、也不再出现在 `core/model_resolution.py` 的 `MODEL_ALIASES` 里：
  传旧名会直接失败并被看见，而不是被悄悄换成另一个模型。
- 官方资料：
  - https://api-docs.deepseek.com/zh-cn/
  - https://api-docs.deepseek.com/zh-cn/quick_start/pricing

## 3. 图像与多模态模型

### qwen-image-3.0

- 定位：项目主图像生成模型（资产工作台 `asset_studio_image_generation` 默认值）
- 适用：封面草图、角色概念图、分镜概念图、带参考图的风格生成
- 限制：多轮一致性仍依赖提示词与参考图
- 项目备注：2026-10-08 图像线换代，万相旧 ID `wan2.6-t2i`、`wan2.7-image`、`qwen-image-2.0/-pro` 已注销；
  DreamWeaver 侧默认用 `qwen-image-3.0-pro`（`_DEFAULT_MODEL_IDS["dreamweaver_image"]`），
  4K 文生图与 9 张参考图、`bbox_list` 局部编辑走 `wan2.7-image-pro`
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

### wan3.0-video

- 定位：项目唯一现役视频生成 ID（all-in-one），资产工作台与 DreamWeaver 的视频/视频编辑/运动三档默认值都是它
- 适用：文生视频、首帧与首尾帧、参考生视频（图 ≤10 / 视频 ≤5 / 音频 ≤5 自由组合）、文件与网页参考生成、视频编辑、视频延长
- 限制：异步任务，端到端通常数分钟，`task_id` 与结果链接仅 24 小时有效；参考视频/音频总时长 ≤15 秒；1080P 档 1.2 元/秒是 720P（0.6 元/秒）的两倍
- 项目备注：官方 `audio` 默认 true，本项目默认置 false，避免与 DreamWeaver 自有对白/音效轨冲突
- 能力缺口（2026-10-08 对照官方 API 逐项核实，已按"接受缺口"记录在 `config/models.yaml` 的 `limitations`）：
  不提供 `driving_audio`（对白驱动）与 `first_clip`（首段续写）；无反向提示词、运镜控制、动作控制等专项入参。
  主体一致性由 All-in-One 参考图（≤10 张）部分覆盖，与旧专项线的等价性见 `docs/MODEL_LIFECYCLE_MANAGEMENT_GUIDE_20260731.md` 第 9 节能力等价矩阵
- 换代说明：2026-10-08 万相视频线收敛为单一现役 ID，`wan2.6-t2v`、`wan2.6-t2v-fast`、`wan2.7-t2v`、
  `wan2.7-i2v`、`wan2.7-r2v`、`wan2.7-videoedit` 已从注册中心物理删除，且不再出现在
  `core/model_resolution.py` 的 `MODEL_ALIASES` 里；传旧 ID 会直接失败，不会被改写。
  注意 `pipeline/media_presets.py` 的 `DREAMWEAVER_T2V_ENGINE` / `DREAMWEAVER_I2V_ENGINE` 是
  **引擎标识符**而非模型 ID，仍保留 `wan2.7-*` 字符串且有独立计费口径，不属退役范围
- 官方资料：
  - https://help.aliyun.com/zh/model-studio/use-video-generation
  - https://help.aliyun.com/zh/model-studio/video-synthesis
  - https://help.aliyun.com/zh/model-studio/image-to-video

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
- `qwen3-vl-plus`、`qwen-image-edit-plus`、`qwen-image-edit-max`、`qwen-image-3.0`、`qwen-image-3.0-pro`、`wan2.7-image-pro`、`wan3.0-video` 已具备 registry-backed adapter，可直接由统一运行时通过 registry 获取（2026-10-09 全量清点：媒体注册中心 46 个 spec 全部 `status: active`，无任何 `deprecated` 残留）
- runtime wrapper 现存入口 key 为 `qwen3_vl_plus`、`qwen3_tts`、`qwen_image_edit_plus`、`qwen_image_edit_max`、`wan_image_edit`、`qwen_multiperson_fusion`、`minimax-speech-2.8-turbo`、`minimax-speech-2.8-hd`；万相旧 T2I/T2V/I2V/R2V wrapper key 已随媒体线退役删除，不再默认回退到旧 media adapter 链路

仍然保留的工程边界：

- `ModelAdapterFactory`（`adapters/model_adapters.py:990`、`adapters/legacy_bridge.py:134` 两处同名类）保留但业务侧已无调用点：`agents/*` 现在只通过 `adapters/adapter_helpers.create_runtime_client(...)` 取客户端，`agents/asset_library.py` 是唯一仍直接创建 runtime wrapper 客户端的位置
- `legacy_bridge` 目前仅保留少量非统一媒体路径的旧式兜底，媒体模型侧的旧 fallback 已基本清空
- 后续推进方向是把 `ModelAdapterFactory` 这两处同名类一并收口，避免"哪个实现在跑"不可判断

