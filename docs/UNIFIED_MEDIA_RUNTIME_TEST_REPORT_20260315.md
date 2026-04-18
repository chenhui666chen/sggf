# 多模态统一运行时测试报告

日期：`2026-03-15`

## 1. 目标

本次测试聚焦以下改造范围：

- 新增统一多模态运行时 `core/unified_media_runtime.py`
- 将图像生成、视频生成、图像编辑、视觉分析、TTS 收口到统一入口
- 将 `audiobook` 关键 TTS 业务路径切换到统一运行时 / TTS 工厂
- 将 `qwen3_tts` 的历史 helper / wrapper / bridge / adapter 调用路径收口到统一 TTS 机制
- 验证 `adapters/adapter_helpers.py` 不再忽略显式 `model_id`

## 2. 涉及文件

- `core/unified_media_runtime.py`
- `adapters/adapter_helpers.py`
- `adapters/model_adapters.py`
- `adapters/legacy_bridge.py`
- `adapters/legacy_runtime_wrappers.py`
- `adapters/__init__.py`
- `backend/app/api/v1/audiobook.py`
- `backend/app/services/audiobook/engine.py`
- `backend/app/services/audiobook/engine_clean.py`
- `backend/app/services/audiobook/tts_engine.py`
- `agents/audio_sync_manager.py`
- `agents/simple_audio_sync_manager.py`
- `agents/optimized_audio_sync_manager.py`
- `agents/performance_audio_sync_manager.py`
- `tests/test_unified_media_runtime.py`
- `tests/test_adapter_helpers_tts_compat.py`
- `tests/test_adapter_helpers_media_runtime.py`
- `tests/test_painter_model_id_runtime.py`
- `tests/test_legacy_runtime_wrappers.py`
- `tests/test_model_adapters_legacy_delegate.py`
- `tests/test_vlm_model_id_compat.py`

## 3. 测试项

### 3.1 单元测试

新增/更新测试文件：

- `tests/test_unified_media_runtime.py`
- `tests/test_adapter_helpers_tts_compat.py`
- `tests/test_adapter_helpers_media_runtime.py`
- `tests/test_painter_model_id_runtime.py`
- `tests/test_legacy_runtime_wrappers.py`
- `tests/test_model_adapters_legacy_delegate.py`
- `tests/test_vlm_model_id_compat.py`

覆盖点：

- 平衡策略下 TTS 默认选型是否命中 `qwen3-tts-flash`
- 质量优先策略下图像编辑是否优先命中 `qwen-image-edit-max`
- 显式 `model_id` 是否真正参与图像生成路由
- 视觉分析是否通过 registry adapter 执行
- `qwen3-vl-plus`、`qwen-image-edit-*`、`wan2.6-i2v/r2v` 是否能由 registry 自动加载
- `create_tts_engine` 是否兼容旧调用参数 `model=...`
- `create_tts_engine` 是否兼容历史别名 `qwen3_tts`
- `UnifiedMediaRuntime.synthesize_speech_result` 是否保留统一 TTS 引擎返回的时间戳元数据
- `adapter_helpers.synthesize_speech` / `synthesize_speech_sync` 是否正确返回统一运行时的音频 payload
- `SimpleAdapterFactory().get_adapter("qwen3_tts")` 是否正确完成旧参数到新 TTS helper 的映射
- 旧 `Qwen3TTSAdapter` 是否已退化为新 helper 的薄包装
- `legacy_bridge.ModelAdapterFactory.create("qwen3_tts")` 是否优先路由到 runtime wrapper
- `adapter_helpers.generate_video` / `create_runtime_client` / `chat_messages` 是否直接委托统一运行时 / runtime wrapper
- `vlm_utils.vlm_chat_json`、`best_image_selector.select_best_candidate(..., selector="vlm")` 是否支持直接传入 `model_id` 字符串
- `Qwen3TTSRuntimeWrapper` 是否与 `SimpleAdapter` / `Qwen3TTSAdapter` 共用一致的旧 TTS 参数归一化规则
- `agents.painter._generate_t2i_with_candidates(...)` 与 `_generate_edit_with_candidates(...)` 是否支持直接传入字符串 `model_id`，并在 keyframe / midframe 业务链路上不再强依赖预实例化 runtime wrapper

### 3.2 回归测试

回归范围：

- `tests/test_model_metadata_catalog.py`
- `tests/test_model_dispatch_refactor.py`
- `tests/test_unified_model_system.py`
- `tests/test_legacy_runtime_wrappers.py`
- `backend/tests/test_auth_routes.py`

验证目标：

- 模型档案读取与结构化元数据未回退
- 文本统一调度中心未受多模态改造影响
- 认证接口等后端基础功能未受影响

### 3.3 导入冒烟测试

额外执行导入与初始化检查：

- `core.unified_media_runtime`
- `app.services.audiobook.engine`
- `app.services.audiobook.engine_clean`
- `app.api.v1.audiobook`

验证统一运行时、多模态业务入口与有声书 API 可以正常导入。

## 4. 执行命令

```powershell
$env:PYTHONPATH='c:\Users\cuigu\novel_writing_agent;c:\Users\cuigu\novel_writing_agent\backend'
.\.venv\Scripts\python -m pytest tests/test_adapter_helpers_tts_compat.py -q
.\\.venv\Scripts\python -m pytest tests/test_adapter_helpers_media_runtime.py tests/test_vlm_model_id_compat.py -q
.\.venv\Scripts\python -m pytest tests/test_unified_media_runtime.py -q
.\.venv\Scripts\python -m pytest tests/test_model_metadata_catalog.py tests/test_model_dispatch_refactor.py tests/test_unified_model_system.py -q
.\.venv\Scripts\python -m pytest tests backend/tests/test_auth_routes.py -q
```

### 2026-03-16 跟进更新

- 新增 `.venv\Scripts\python -m pytest tests/test_painter_model_id_runtime.py tests/test_adapter_helpers_tts_compat.py tests/test_legacy_runtime_wrappers.py tests/test_adapter_helpers_media_runtime.py tests/test_vlm_model_id_compat.py tests/test_model_adapters_legacy_delegate.py -q`，用于覆盖兼容壳、统一 helper、Painter model-id 直传与 VLM model-id 直传链路的定向回归。
- 新增 `.venv\Scripts\python -m pytest tests/test_model_adapters_legacy_delegate.py -q`，用于验证直接实例化历史媒体 adapter 时也会转发到 runtime wrapper。
- 最新全量回归命令仍为 `.venv\Scripts\python -m pytest tests backend/tests/test_auth_routes.py -q`。
- 新增 `adapters.adapter_helpers.build_legacy_tts_request(...)`，把 `SimpleAdapter`、`Qwen3TTSRuntimeWrapper`、`Qwen3TTSAdapter` 的旧 TTS 参数映射统一到一套逻辑，修复 wrapper 路径先前对 `volume/speed/pitch` 处理不一致的问题。
- 新增 `adapters.adapter_helpers.match_scene(...)`，并将 `qwen_multiperson_fusion` 接入统一模型别名归一化；`agents/painter.py` 已继续收口到 keyframe / midframe 的 T2I / image-edit / VLM / multiperson-fusion 主链路全部支持直接传递字符串 `model_id`，并行候选生成也不再依赖 `create_runtime_client(...)`。
- `legacy_runtime_wrappers.py` 已继续向 `adapter_helpers` 收口：`qwen3_vl_plus`、`wan_t2i`、`wan_t2v`、`wan_i2v`、`wan_r2v`、`qwen_image_edit_*`、`wan_image_edit`、`qwen_multiperson_fusion` 等 wrapper 的内部执行现在优先复用统一 helper；同时统一 helper 也补齐了 `generate_video` 的 `negative_prompt` 与 `edit_image` 的 `seed` 标准字段传递，避免 wrapper 复用 helper 后出现字段语义回退。
- 定向回归结果：`38 passed`。
- 最新全量回归结果：`91 passed, 2 warnings`。
- 本次跟进也补充验证了 `Qwen3TTSAdapter` 的 speaker 归一化在隔离测试环境中依然可用，不依赖完整的有声书包初始化链路。
- `adapters/model_adapters.py` 中已被 runtime wrapper 接管的旧媒体类，其历史 HTTP / DashScope 主链路实现已完成物理清理，文件内不再保留重复的公开方法定义。
- 历史业务面中直接媒体生成的几条主干链路已继续收口：
  - `agents/dreamweaver.py` 的 Wan I2V / T2V 已改为直接走 `adapter_helpers.generate_video(...)`
  - `backend/app/api/v1/dreamweaver.py` 的库素材再生成 T2I / image-edit 已改为直接走 `adapter_helpers.generate_image(...)` / `edit_image(...)`
  - image-edit 多参考图能力判断已改为读取统一注册中心元数据 `model_supports_capability(...)`
- `pipeline/autoqc.py` 的 VLM `chat` 质检调用已进一步切换为统一 `adapter_helpers.chat_messages(...)`，不再需要先通过 `SimpleAdapterFactory` 构造兼容 adapter。
- `agents/painter.py` 与 `agents/asset_library.py` 的业务层已继续收口：其中 `agents/asset_library.py` 仍通过 `create_runtime_client(...)` 直接创建 runtime wrapper 客户端，而 `agents/painter.py` 的 keyframe / midframe 主链路已经进一步下沉为字符串 `model_id` 驱动，连并行候选 clone 兼容路径也不再要求预实例化 runtime wrapper；`SimpleAdapterFactory` 已不再出现在业务调用面，当前兼容壳仅保留在 `adapters/adapter_helpers.py` 及兼容测试中，用于兜住历史外部接口。

导入冒烟测试：

```powershell
$env:PYTHONPATH='c:\Users\cuigu\novel_writing_agent;c:\Users\cuigu\novel_writing_agent\backend'
@'
from core.unified_media_runtime import media_runtime
from app.services.audiobook.engine import AudiobookEngine
from app.services.audiobook.engine_clean import AudiobookEngine as CleanAudiobookEngine
from app.api.v1 import audiobook
print("runtime_ok", media_runtime.select_model(operation="synthesize_speech", modality="text_to_speech").id)
print("engine_import_ok", AudiobookEngine.__name__)
print("clean_engine_import_ok", CleanAudiobookEngine.__name__)
print("api_import_ok", audiobook.router.prefix)
'@ | .\.venv\Scripts\python -
```

## 5. 结果

- `tests/test_unified_media_runtime.py`：`10 passed`
- `tests/test_adapter_helpers_tts_compat.py`：`6 passed`
- `tests/test_adapter_helpers_media_runtime.py`：`5 passed`
- `tests/test_painter_model_id_runtime.py`：`4 passed`
- `tests/test_vlm_model_id_compat.py`：`2 passed`
- `tests/test_legacy_runtime_wrappers.py`：`11 passed`
- `tests/test_model_adapters_legacy_delegate.py`：`10 passed`
- 兼容壳 / helper / Painter / VLM 定向回归：`38 passed`
- `tests/test_model_metadata_catalog.py` + `tests/test_model_dispatch_refactor.py` + `tests/test_unified_model_system.py`：`31 passed`
- `tests` + `backend/tests/test_auth_routes.py`：`91 passed`
- 导入冒烟测试：通过
- registry 适配器实测：
  - `qwen3-vl-plus -> Qwen3VLPlusRegistryAdapter`
  - `qwen-image-edit-plus -> QwenImageEditPlusRegistryAdapter`
  - `qwen-image-edit-max -> QwenImageEditMaxRegistryAdapter`
  - `wan2.6-t2i -> WanxAdapter`
  - `wan2.6-t2v -> Wan26VideoAdapter`
  - `wan2.6-i2v -> Wan26ImageToVideoAdapter`
  - `wan2.6-r2v -> Wan26ReferenceVideoAdapter`

## 6. 结论

- 统一多模态运行时已可稳定承接图像生成、视频生成、图像编辑、视觉分析与 TTS 的上层调用
- `audiobook` 相关 TTS 试听与引擎初始化已改走统一运行时，不再由业务代码直接分散实例化旧路径
- `qwen3_tts` 历史别名、`legacy_bridge`、`Qwen3TTSAdapter` 与 4 个历史音频同步管理器现已统一收口到 `adapters.adapter_helpers.synthesize_speech_sync(...)` 与 `TTSEngine.synthesize_with_metadata(...)`
- 同步与异步 TTS 返回现已统一兼容 `audio_bytes`、`audio_data`、`tts_timestamps`、`phoneme_timestamps`
- `SimpleAdapter`、`Qwen3TTSRuntimeWrapper`、`Qwen3TTSAdapter` 现已共用同一套历史 TTS 参数归一化 helper，旧入口传入的 `voice_style/speed/pitch/volume` 会被一致转换后再进入统一 TTS 运行时
- `adapters/adapter_helpers.py` 已接入统一多模态运行时，显式 `model_id` 现在会真正影响路由
- `qwen_multiperson_fusion` 已接入统一模型别名归一化与 `adapter_helpers.match_scene(...)` helper，`agents/painter.py` 的候选生成与多人物融合底层 helper 已支持直接传入字符串 `model_id`，并行路径也不再需要为字符串模型额外构造 runtime wrapper，业务层对 runtime wrapper 对象的依赖进一步缩小
- `legacy_runtime_wrappers.py` 当前更多承担的是“旧签名兼容壳”而不是“独立执行实现”，与 `adapter_helpers` 的职责重叠已进一步减少
- `SimpleAdapterFactory` 现已支持 runtime wrapper 懒代理，历史调用 `qwen3_vl_plus.chat(...)`、`analyze_image(...)`、`qwen_multiperson_fusion.match_scene(...)` 等旧方法时，也会转发到新 registry / TaskSpec 路径
- `wan_t2i/wan26_t2i` 与 `wan_t2v/wan26_t2v` 也已迁入 runtime wrapper，历史旧工厂调用现在会直接转发到 `wan2.6-t2i` / `wan2.6-t2v` 的 registry / TaskSpec 路径
- `qwen3-vl-plus`、`qwen-image-edit-*`、`wan2.6-t2i`、`wan2.6-t2v`、`wan2.6-i2v/r2v` 已迁入 registry-backed adapter，统一运行时内部不再保留这些链路的 legacy bridge fallback 分支
- `adapters/model_adapters.py` 已新增 runtime wrapper 兼容层，历史 Agent 对 `wan_t2i/wan_t2v`、`qwen3_vl_plus`、`qwen3_tts`、`qwen_image_edit_*`、`wan_image_edit`、`wan_i2v/wan_r2v`、`qwen_multiperson_fusion` 的旧签名调用已转发到新 registry / TaskSpec 机制
- `adapters/model_adapters.py` 中历史媒体 adapter 类被直接实例化时，公开的 `generate/chat/analyze_image/analyze_video/match_scene` 入口也会优先薄代理到 runtime wrapper，不再重新走旧 HTTP / DashScope 主链路
- `legacy_bridge` 对已 wrapper 化的媒体模型旧 fallback 已基本移除，当前仅保留 `jianying` 旧式适配路径
- 文本统一调度中心和认证接口回归通过，未发现本次改造引入的功能回退

## 7. 剩余边界

- 仍有部分历史 Agent 代码直接依赖 `adapters/model_adapters.py` 的 `ModelAdapterFactory`，但高频多模态旧 key 已由 runtime wrapper 接管
- `python-jose` 的 `datetime.utcnow()` 弃用告警依旧存在，但不是本次改造引入
