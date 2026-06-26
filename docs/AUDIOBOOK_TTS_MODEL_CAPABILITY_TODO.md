# 有声小说 TTS 模型能力接入待办

更新时间：2026-06-25

本文档用于跟踪本轮对话中提出的模型中心、有声小说 TTS、声音描述与风格控制相关修改。后续实现进展必须同步更新本文档，避免模型配置、后端链路、前端展示和验证文档各自漂移。

## 状态说明

| 状态 | 含义 |
| --- | --- |
| 未开始 | 尚未修改代码或配置 |
| 进行中 | 已有部分实现，但不能视为端到端完成 |
| 阻塞 | 需要官方资料、真实接口结果或用户确认 |
| 已完成 | 代码、配置、测试和必要文档均已落地 |

## 合并后的实施主题

| 编号 | 主题 | 状态 | 优先级 | 当前结论 |
| --- | --- | --- | --- | --- |
| TTS-01 | Qwen3-TTS-Instruct-Flash 官方音色与模型卡片收敛 | 进行中 | P0 | `voice` 参数和 24 个 Instruct-Flash 官方音色已开始落地；仍需清理卡片能力来源、展示层和验证文档 |
| TTS-02 | 高质量声音描述规范接入有声小说生成链路 | 进行中 | P0 | 后端已新增统一声音描述策略，主渲染链路和旁白风格会携带多维声音描述；前端引导和更细粒度章节情绪仍待补齐 |
| TTS-03 | 已选音色与声音描述的融合和冲突检测 | 进行中 | P0 | 已实现 Qwen 官方音色的性别、年龄感、基础音调、核心音质和用途冲突修正；仍需扩展前端提示、机器可读画像和其他模型官方音色 |
| TTS-04 | 模型感知的风格控制策略 | 进行中 | P0 | 已将声音描述接入 Qwen/CosyVoice 自然语言和 MiMo 导演模式，并标准化模型风格控制能力字段；仍需继续完善上游朗读意图质量与前端展示 |
| TTS-05 | MiMo-V2.5-TTS 系列正式接入 | 进行中 | P1 | 已按官方资料接入 `mimo-v2.5-tts`、`mimo-v2.5-tts-voicedesign`、`mimo-v2.5-tts-voiceclone` 三模型、官方预置音色目录、运行时 payload、统一媒体运行时注册和前端兜底入口；仍缺真实接口验证 |
| TTS-06 | 模型中心 `/model-catalog` 展示适配 | 进行中 | P1 | 模型中心已展示 TTS 调用参数、音色数量、风格控制模式、消息位置与高级控制能力；仍需继续补官方来源校验和更多待接入模型资料 |
| TTS-07 | 前端有声小说声音设计面板适配 | 进行中 | P1 | 前端 TTS 模型能力对象已可读取不同模型可用控制方式；声音设计面板的可视化入口和冲突提示仍待落地 |
| TTS-08 | 领域知识配置与语义词汇表扩展 | 进行中 | P2 | 已加入独立 TTS domain 与 TTS 专用风格/场景词汇；仍需接入实际模型路由和更完整验证 |
| TTS-09 | 共享音色画像结构化 | 进行中 | P2 | 已为 Qwen3 Instruct-Flash 支持音色补充机器可读画像，并让后端优先读取；仍需扩展其他模型官方音色 |
| TTS-10 | 能力验证指南与接入参考文档同步 | 进行中 | P2 | 已补充豆包 Seed-TTS 2.0 Expressive 的接入参考与验证关注项；仍需补齐 Qwen3、MiMo、StepAudio 的完整验证矩阵和回写规则 |
| TTS-11 | 有声小说端到端测试补足 | 进行中 | P1 | 已补充片段模型解析、delivery plan、provider payload 与质量评审相关测试；仍缺前端选择模型到后端契约的端到端覆盖 |
| TTS-12 | StepAudio 2.5 TTS 正式接入 | 进行中 | P1 | 已完成模型注册、36 个官方音色目录、模型感知风格控制、StepFun 非流式 payload、模型中心卡片、本地 Zero-shot 参考样本资产、前端工作台和回归测试；真实 `STEP_API_KEY` 中文与英文基础试听均已通过，正式收费音色创建与文件上传 `file_id` 接口仍待官方合同确认 |
| TTS-13 | 豆包 seed-tts-2.0-expressive 正式接入 | 进行中 | P1 | 已完成官方资料核对、模型注册、99 个官方音色目录、模型感知风格控制、Volcengine V3 非流式 payload、语音标签前缀、模型中心卡片、本地回归测试和真实基础试听；仍需验证语音标签、复刻音色资产和双向流式链路 |

## TTS-01 Qwen3-TTS-Instruct-Flash 官方音色与模型卡片收敛

状态：进行中

### 已完成

- `config/models.yaml` 已将调用参数方向收敛为官方 `voice` 参数。
- `shared/qwen3_tts_voices.json` 已纳入支持 `qwen3-tts-instruct-flash` 的官方音色集合。
- 已排除仅支持 Flash 但不支持 Instruct-Flash 的音色。
- 已更新相关测试：
  - `tests/test_model_metadata_catalog.py`
  - `backend/tests/test_qwen_tts_voice_compat.py`

### 待办

- 清理 `qwen3-tts-instruct-flash` 能力条目中的 `TODO: verify from official docs` 来源占位。
- 确认 `documentation_url`、`source_urls` 与当前官方资料一致。
- 确认 `/model-catalog` 卡片展示 `voice` 参数、官方音色数量、语言支持和调用示例。
- 将该模型的能力验证步骤同步到 `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md`。
- 将接入说明同步到 `docs/MODEL_INTEGRATION_REFERENCE.md`。

### 验收标准

- 模型卡片不再使用未核验来源描述该模型的 TTS 核心能力。
- 模型中心能明确显示官方 `voice` 参数与 24 个 Instruct-Flash 支持音色。
- Qwen3 音色兼容性测试和模型元数据测试通过。

### 关联文件

- `config/models.yaml`
- `shared/qwen3_tts_voices.json`
- `tests/test_model_metadata_catalog.py`
- `backend/tests/test_qwen_tts_voice_compat.py`
- `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md`
- `docs/MODEL_INTEGRATION_REFERENCE.md`

## TTS-02 高质量声音描述规范接入有声小说生成链路

状态：进行中

### 合并说明

本项合并以下待办：声音描述最佳实践、旁白/角色声音生成规范、模型适配前的统一声音意图表达。先在后端形成统一声音描述，再交给不同模型策略转换，不在每个 provider 内重复拼提示词。

### 已完成

- 新增 `voice_description_policy.py`，统一构造包含性别、年龄感、音调、语速、情绪、特点、用途的声音描述。
- `VoiceDesigner` 已改用统一声音描述构造器，避免继续输出“好听”“普通”等不可执行描述。
- `VoiceManager.VoiceProfile.get_tts_params()` 已在主渲染链路 `voice_params` 中携带 `voice_description`。
- `tts_style_control.py` 已能把 `voice_description` 合并进 Qwen/CosyVoice 的自然语言 instructions 和 MiMo 导演模式指导字段。
- 已新增 `backend/tests/test_audiobook_voice_description_policy.py` 覆盖描述维度和主链路参数。
- `narration_styles.py` 已为 `professional`、`dramatic`、`relaxing`、`expressive`、`custom` 旁白风格生成旁白专用 `voice_description`，避免沿用角色对白画像。
- Qwen payload 测试已覆盖旁白风格描述进入 instructions，并在使用具体音色时保留旁白用途和节奏。

### 待办

- 继续完善 `voice_designer.py` 中不同角色类型的声音描述细分：
  - 性别
  - 年龄感
  - 音调
  - 语速
  - 情绪
  - 音色特点
  - 用途
- 继续补充独白、情绪爆发、低语、哭腔等章节内情绪片段的声音描述模板。
- 为角色对白、独白、章节内情绪片段分别输出更细粒度的描述。

### 验收标准

- 同一角色在不同场景下能生成稳定但有情绪变化的声音描述。
- 旁白与角色对白不会共用同一套泛化描述。
- 输出描述可被后续模型适配层转换成 Qwen、MiMo、MiniMax、CosyVoice 的不同控制格式。

### 关联文件

- `backend/app/services/audiobook/agents/voice_designer.py`
- `backend/app/services/audiobook/narration_styles.py`
- `backend/app/services/audiobook/tts_style_control.py`
- `backend/app/services/audiobook/voice_description_policy.py`
- `backend/app/services/audiobook/voice_manager.py`
- `backend/tests/test_audiobook_voice_description_policy.py`

## TTS-03 已选音色与声音描述的融合和冲突检测

状态：进行中

### 合并说明

本项合并“高质量声音描述是否与已选音色冲突”的处理规则和后续自动修正逻辑。原则是：已选音色为硬约束，声音描述为软约束。

### 已完成

- 新增 `reconcile_voice_description_with_selected_voice()`，在生成模型风格控制前按已选音色修正声音描述。
- Qwen 官方音色已支持基础画像推断，包括性别、年龄感、音调、语速和音质特点。
- 已实现性别与年龄感冲突检测，并返回可解释的 `warnings`。
- 已实现基础音调冲突检测，例如儿童/可爱音色会纠正“偏低”描述为匹配音色的偏高音调。
- 已实现核心音质冲突检测并返回 `warnings`，例如儿童/可爱音色会拒绝“沙哑烟嗓、苍老、浑厚”，沙哑磁性男声音色会拒绝“清脆童声、稚嫩、甜美”。
- 已实现用途冲突检测：角色对白场景会修正“纪录片解说/播报”等用途，旁白场景会保留“有声书旁白”用途。
- `tts_style_control.py` 已在 Qwen/CosyVoice/MiMo 风格控制构建前调用冲突修正，避免冲突描述直接进入最终 payload。
- 已新增冲突测试，覆盖选择 `Cherry` 时“低沉中年男性”被修正为女性青年音色，以及选择 `Bella` 时低沉纪录片用途被修正为角色对白。
- 已新增音质冲突测试，覆盖选择 `Bella` 时“沙哑烟嗓、苍老、浑厚”被修正为稚嫩甜美，以及选择 `Vincent` 时“清脆童声、稚嫩、甜美”被修正为沙哑有磁性。

### 待办

- 将当前 Qwen 基础画像迁移或扩展到 `shared/*voices.json` 的机器可读字段。
- 扩展更多核心音质冲突组合，例如“新闻播报型音色”与“撒娇萝莉感”的冲突。
- 将冲突警告透传到前端或更明确的日志/调试信息。
- 等 MiMo、StepAudio、豆包官方音色表落地后扩展同一套冲突规则。
- 增加无冲突、可软化冲突和其他模型音色冲突测试用例。

### 示例冲突

- 选择女性音色，却生成“低沉中年男性”。
- 选择儿童或少女音色，却生成“成熟御姐低音”。
- 选择新闻播报型音色，却要求“撒娇萝莉感”。
- 选择沙哑烟嗓音色，却要求“清脆童声”。

### 验收标准

- 冲突描述不会直接进入最终 TTS payload。
- 用户选择的官方音色不会被后端生成描述隐式覆盖。
- 测试覆盖冲突、无冲突、可软化冲突三类情况。

### 关联文件

- `shared/qwen3_tts_voices.json`
- 后续 MiMo 官方音色表
- `backend/app/services/audiobook/agents/voice_designer.py`
- `backend/app/services/audiobook/tts_style_control.py`
- `backend/app/services/audiobook/voice_description_policy.py`
- `backend/tests/test_audiobook_voice_description_policy.py`

## TTS-04 模型感知的风格控制策略

状态：进行中

### 已完成

- 已新增 `backend/app/services/audiobook/tts_style_control.py`。
- 已开始区分：
  - Qwen/CosyVoice：自然语言 `instructions`
  - MiMo 自然语言控制：`role: user`
  - MiMo 音频标签控制：`role: assistant`
- 已补充部分 provider payload 测试。
- 已将上游 `voice_description` 接入 Qwen/CosyVoice 自然语言控制和 MiMo 导演模式。
- 已新增 MiMo 导演模式测试，确认声音描述进入 `指导` 字段，音频标签模式不污染其它模型。
- MiMo 导演模式已合并显式 `instructions`、声音描述、情绪和演绎提示，避免显式指令绕过导演结构。
- `tts_model_ids.py` 已新增统一风格控制能力矩阵，暴露 `style_control_modes`、`preferred_style_control_mode`、`supports_voice_description`、`supports_audio_tags`、`supports_emotion_mixing`、`supports_micro_tags`、`supports_word_level_control`、`instruction_budget` 与 `control_message_roles`。
- `get_audiobook_tts_model_metadata()` 已合并风格控制能力，并返回深拷贝，避免调用方污染全局模型元数据。
- `tts_delivery_plan.py` 已改为从能力矩阵解析 `model_family` 与 `model_control_preference`，并在片段计划中写入 `model_style_control_modes` 和 `supports_audio_tags`。
- `tts_style_control.py` 已改为通过能力矩阵识别 MiMo 系列及其别名，并让 MiniMax 明确走 `basic` 控制模式，不再生成不会被消费的自然语言字段。
- `mimo-v2.5-tts-voicedesign` 已从普通 MiMo 导演/音频标签模型中单独分流，生成 `mimo_voice_design` 控制模式。
- `mimo-v2.5-tts-voicedesign` 的风格、情绪、角色、场景和演绎要求会合并进 `role=user` 的音色设计 prompt，不再把音频标签作为独立前缀拼入朗读正文。
- `mimo-v2.5-tts-voiceclone` 保留普通 MiMo 的导演模式、自然语言控制和音频标签控制，音色来源继续使用 `audio.voice` 样本。

### 待办

- 继续完善旁白风格、角色场景和章节情绪到 `voice_description` 的上游生成质量。
- 继续补齐模型能力的可读说明字段，例如：
  - `recommended_prompt_shape`
  - `voice_description_best_practices`
  - `unsupported_patterns`
- 为不同模型生成不同风格控制格式：
  - Qwen / CosyVoice：自然语言描述。
  - MiMo 自然语言：角色、场景、指导。
  - MiMo 标签模式：整体风格标签和文本内音频标签。
  - MiMo VoiceDesign：高质量声音描述优先，风格指令融合进 voice design prompt。
  - MiniMax：保持现有参数风格。

### 验收标准

- 同一个有声书片段选择不同 TTS 模型时，最终 payload 的风格控制字段不同且符合模型要求。
- MiMo 音频标签只出现在 MiMo 标签控制模式中。
- 现有 Qwen、MiniMax、CosyVoice 调用不被 MiMo 逻辑污染。

### 关联文件

- `backend/app/services/audiobook/tts_style_control.py`
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`
- `backend/tests/test_audiobook_tts_provider_payloads.py`

## TTS-05 MiMo-V2.5-TTS 系列正式接入

状态：进行中

### 已完成

- 后端已按官方资料注册：
  - `mimo-v2.5-tts`
- `mimo-v2.5-tts-voicedesign`
- `mimo-v2.5-tts-voiceclone`
- 已移除旧占位模型线 `mimo-v2.5-tts-hd`、`mimo-v2.5-tts-turbo`，并增加拒绝归一化测试，避免误导为官方模型。
- 已加入模型 ID 归一化、支持列表、runtime ID、能力矩阵和回归测试。
- 已实现 MiMo 官方 OpenAI 兼容 payload：
  - Base URL：`https://api.xiaomimimo.com/v1`
  - Endpoint：`/chat/completions`
  - 鉴权：`api-key: $MIMO_API_KEY`
  - 目标文本放在 `role=assistant` 的 message。
  - 自然语言/导演模式放在 `role=user` 的 message。
  - 音频标签嵌入 `role=assistant` 的 content。
- 已实现三类 payload 分流：
  - 预置音色：`audio.voice` 使用官方 voice ID，默认 `mimo_default`。
  - 音色设计：`role=user` 使用融合后的 voice design prompt，`audio` 不传预置 voice，可传 `optimize_text_preview`；显式 `audio_tags` 控制会被收敛为声音描述/风格描述，不污染朗读正文。
  - 音色复刻：`audio.voice` 使用 `data:{MIME_TYPE};base64,$BASE64_AUDIO`。
- 已新增 `shared/mimo_v2_5_tts_voices.json`，包含官方预置音色：
  - `mimo_default`
  - `冰糖`
  - `茉莉`
  - `苏打`
  - `白桦`
  - `Mia`
  - `Chloe`
  - `Milo`
  - `Dean`
- 已新增 `MiMoVoiceManager`，仅让 `mimo-v2.5-tts` 的官方预置音色进入自动分配；`voicedesign` 与 `voiceclone` 不参与系统音色自动兜底。
- `config/models.yaml` 已替换为官方三张模型中心卡片，并标注真实接口仍待 `MIMO_API_KEY` 端到端验证。
- 模型中心已能从统一 TTS 风格控制能力矩阵为 MiMo 卡片展示导演模式、音频标签、自然语言控制、消息位置和高级控制能力。
- 前端 TTS 模型兜底列表已加入三条 MiMo 官方模型线，并为预置/设计/复刻分别设置默认音色和能力字段。
- 统一媒体运行时已将三条 MiMo 模型加入 `synthesize_speech` 白名单，并注册轻量 TTS runtime spec，使 `/api/v1/audiobook/tts/models` 返回 `runtime_status=ready`。
- `mimo-v2.5-tts-voicedesign` 与 `mimo-v2.5-tts-voiceclone` 的 `/api/v1/audiobook/tts/voices` 已返回空音色目录，避免误回退到 Qwen 系统音色。
- `mimo-v2.5-tts-voicedesign` 的模型能力和卡片已收窄为 `voice_design` + `natural_language`，不再作为独立导演模式/音频标签模型展示；静态模型配置仍通过 `pending-runtime-validation` 标签标识真实接口待验证。

### 待办

- 增加真实接口最小验证。
- 验证模型中心页面 `/model-catalog` 中 MiMo 三张卡片展示与状态文案。
- 有 `MIMO_API_KEY` 后执行最小样例：
  - `mimo-v2.5-tts` + `Chloe` + wav 非流式。
  - `mimo-v2.5-tts` + audio tags。
  - `mimo-v2.5-tts-voicedesign` + `voice_description`。
  - `mimo-v2.5-tts-voiceclone` + 授权 mp3/wav 样本 data URL。
- 增加错误场景验证：不支持标签、非法音色、空文本、过长输入。
- 获取并回写官方价格与计费单位。

### 验收标准

- MiMo 三种模型的模型中心卡片来源清晰，不使用占位价格或占位 ID 作为最终结论。
- MiMo 有独立官方音色目录。
- MiMo 自然语言控制、标签控制、音色设计和音色复刻都有真实接口验证记录。

### 本轮验证

- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_qwen_tts_voice_compat.py" "tests/test_model_catalog_projection.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_metadata_catalog.py" -q`
- `python -m pytest "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_voice_description_policy.py" -q`
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_qwen_tts_voice_compat.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_voice_description_policy.py" "tests/test_model_catalog_projection.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_metadata_catalog.py" -q`（85 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"`
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/voiceCatalog.test.ts"`（12 passed）
- `npm run test -- "src/pages/audiobook/__tests__/loadingButtonSource.test.ts" "src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts"`
- `npm run type-check`
- `python -m pytest "tests/test_model_metadata_catalog.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_catalog_projection.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q`（60 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"`（8 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/setupStepSource.test.ts"`（9 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/voiceCatalog.test.ts" "src/pages/audiobook/__tests__/setupStepSource.test.ts" "src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts"`（14 passed）

### 关联文件

- `backend/app/services/audiobook/tts_model_ids.py`
- `backend/app/services/audiobook/voice_catalog.py`
- `backend/app/services/audiobook/voice_manager_factory.py`
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`
- `adapters/mimo/tts.py`
- `adapters/registry.py`
- `core/unified_media_runtime.py`
- `backend/tests/test_audiobook_tts_model_ids.py`
- `config/models.yaml`

## TTS-06 模型中心 `/model-catalog` 展示适配

状态：进行中

### 已完成

- `/api/v1/audiobook/tts/models` 返回的 `capabilities` 已包含模型风格控制能力字段。
- `frontend/src/pages/audiobook/ttsModels.ts` 已归一化并保留 `modelFamily`、`styleControlModes`、`preferredStyleControlMode`、`supportsVoiceDescription`、`supportsDirectorMode`、`supportsAudioTags`、`supportsEmotionMixing`、`supportsMicroTags`、`supportsWordLevelControl`、`instructionBudget` 和 `controlMessageRoles`。
- `frontend/src/pages/audiobook/__tests__/ttsModels.test.ts` 已覆盖后端风格能力字段与本地 fallback。
- 有声小说角色音色卡片已显示当前模型的风格控制方式标签，例如“自然语言指令”“导演模式”“音频标签”“基础参数”。
- `model_catalog_bootstrap.py` 已把 `config/models.yaml` 中的 `detailed_specs` 透传到模型中心投影，避免 Qwen3 语音合成明细在 `/model-catalog` 丢失。
- 模型中心投影已自动把有声小说 TTS 能力矩阵合并到 `detailed_specs.voice_synthesis.style_control`，包含模型家族、推荐控制模式、可用模式、消息位置、指令预算和高级控制能力。
- `frontend/src/pages/ModelCatalogPage.tsx` 已在“语音合成规格”中展示风格控制模式、推荐模式、消息位置、指令预算和高级控制标签。
- 已新增 `frontend/src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts` 和模型中心投影测试，防止后续页面或后端投影回退。
- 模型中心投影已将 `mimo-v2.5-tts-voicedesign` 的推荐模式显示为 `voice_design`，可用模式为 `voice_design` 与 `natural_language`，并明确 `supports_audio_tags=false`、`supports_director_mode=false`。

### 待办

- 继续清理 Qwen3、MiMo 相关来源链接与 `TODO: verify from official docs` 占位。
- 继续为 TTS 模型增加更明确的能力分组，区分“模型官方能力”“用户提供资料”“项目已接入能力”“真实接口已验证能力”。
- 后续 StepAudio 2.5 TTS 和 `seed-tts-2.0-expressive` 资料补齐后，按同一 `style_control` 结构接入模型中心卡片。

### 验收标准

- 访问 `http://localhost:5173/model-catalog` 时，Qwen3 和 MiMo 卡片能准确反映当前接入状态。
- 用户能从卡片判断该模型是否适合有声书、角色配音、批量预览或精细风格演绎。

### 关联文件

- `frontend/**/model-catalog*`
- `config/models.yaml`
- `tests/test_asset_studio_model_catalog.py`

## TTS-07 前端有声小说声音设计面板适配

状态：进行中

### 已完成

- 前端 TTS 模型能力类型已包含模型感知的风格控制字段，后续声音设计面板可以直接按所选模型判断自然语言控制、音频标签控制、导演模式和 basic 参数模式。
- `CharacterVoiceCard` 已在角色级模型/音色选择区展示所选模型的可用控制方式，避免用户把 MiMo 标签控制误认为所有模型都可用。
- 前端 fallback 已把 `mimo-v2.5-tts-voicedesign` 的控制方式显示为“音色设计”“自然语言指令”，不再显示“导演模式”“音频标签”。
- `VoiceCatalogStatusPanel` 已限制 CosyVoice 创建工作台仅在 `cosyvoice-v3.5-plus` 下展示；选择 MiMo Voice Clone/Voice Design 时改为显示 `audio.voice` 样本或 `role=user` voice design prompt 的只读接入提示，避免误导为 CosyVoice 自定义音色创建。
- MiMo Voice Clone 本地音色工作台已参考 CosyVoice 复刻交互补充“录音”和“上传音频”入口；上传或录音后前端会自动生成 MiMo 官方要求的 `data:audio/...;base64,...` 形式 `audio.voice`，再保存为可复用本地音色。
- MiMo Voice Clone / Voice Design 本地音色工作台已去除“备注”输入框，避免与“音色名称”和核心样本/描述参数混淆。
- CosyVoice v3.5-plus 声音设计创建成功后会保存接口返回的 `preview_audio`，原“开始设计”按钮切换为“试听”，可直接试听本次设计试听文本生成的预览音频。

### 待办

- 在声音描述输入区域加入高质量描述引导。
- 在角色声音配置中暴露或提示以下维度：
  - 性别
  - 年龄感
  - 音调
  - 语速
  - 情绪
  - 特点
  - 用途
- 根据所选模型显示可用控制方式：
  - 自然语言控制
  - 音频标签控制
  - 导演模式
- 避免 UI 暗示所有模型都支持同样的风格控制能力。
- 前端展示后端返回的音色/描述冲突提示。

### 验收标准

- 用户能按维度创建可执行的声音描述。
- 选择 MiMo 时能看到自然语言、标签、导演模式相关入口或说明。
- 选择 Qwen、MiniMax、CosyVoice 时不会出现不可用的 MiMo 标签控制入口。

### 关联文件

- `frontend/src/pages/audiobook/CosyVoiceDesignVoicePanel.tsx`
- `frontend/src/pages/audiobook/CharacterVoiceTraitControls.tsx`
- `frontend/src/pages/audiobook/CharacterVoiceConfigPanel.tsx`
- `frontend/src/pages/audiobook/ttsModels.ts`

## TTS-08 领域知识配置与语义词汇表扩展

状态：进行中

### 已完成

- `config/intent_domains.yaml` 已新增独立 `tts` domain，覆盖有声书、文本转语音、角色声音设计、旁白、对白等模态。
- 已新增 TTS 控制模式配置：自然语言控制、音频标签控制、导演模式、已选音色与声音描述融合。
- 已新增声音风格词汇：低语、哽咽、笑意、气声、破音、复合情绪等。
- 已新增场景规则：有声书旁白、角色对白、独白、情绪爆发、MiMo 音频标签。
- `core/semantic_matcher.py` 已新增 TTS 专用 `tts_*` 风格词汇和有声书场景词汇，避免与视觉风格、运镜词汇混用。
- 已新增 `tests/test_tts_semantic_vocabulary.py`，验证 TTS domain 和语义词汇存在。

### 待办

- 继续补充更多 MiMo 标签词汇和复杂情绪组合。
- 将新增 TTS 语义词汇接入实际模型路由或 prompt 生成链路，而不只是静态词表。
- 增加“声音风格不会被误判为视觉风格”的路由级测试。
- 后续 StepAudio、豆包模型官方能力明确后补充对应控制词。

### 验收标准

- 新增声音风格或场景类型后，模型路由和提示词生成能稳定识别。
- 语义词汇表不会把视觉风格、镜头语言和声音风格混为一类。

### 关联文件

- `config/intent_domains.yaml`
- `core/semantic_matcher.py`
- `tests/test_tts_semantic_vocabulary.py`

## TTS-09 共享音色画像结构化

状态：进行中

### 已完成

- 新增 `shared/qwen3_tts_voice_profiles.json`，为 24 个 `qwen3-tts-instruct-flash` 支持音色补充机器可读画像字段。
- 画像字段包含 `age_group`、`pitch`、`pace`、`emotion_baseline`、`timbre_traits`、`recommended_use_cases`、`avoid_use_cases`、`conflict_rules`。
- `voice_catalog.py` 已在加载 Qwen3 音色目录时合并 `voice_profile`，保留原始官方音色表与项目派生画像的边界。
- `voice_description_policy.py` 已优先使用 catalog 中的 `voice_profile`，缺失时继续使用 style/description 推断作为 fallback。
- 已新增测试确认 Qwen3 Instruct-Flash 支持音色均暴露 `voice_profile`，并确认声音描述策略优先读取 catalog 画像。

### 待办

- 继续校准 Qwen3 画像字段，后续可将 `gender` 也纳入统一画像或继续保留在官方音色表顶层。
- 后续为其他官方音色表补充同一套机器可读画像字段：
  - `gender`
  - `age_group`
  - `pitch`
  - `pace`
  - `emotion_baseline`
  - `timbre_traits`
  - `recommended_use_cases`
  - `avoid_use_cases`
  - `conflict_rules`
- 后续接入 MiMo 官方音色表后使用同一结构。

### 验收标准

- 音色画像可直接服务冲突检测和声音描述融合。
- 新增模型音色时能复用同一结构，不需要为每个 provider 写一套解析逻辑。

### 关联文件

- `shared/qwen3_tts_voices.json`
- `shared/qwen3_tts_voice_profiles.json`
- 后续 MiMo 官方音色表
- `backend/app/services/audiobook/voice_catalog.py`
- `backend/app/services/audiobook/voice_description_policy.py`
- `backend/tests/test_qwen_tts_voice_compat.py`
- `backend/tests/test_audiobook_voice_description_policy.py`

## TTS-10 能力验证指南与接入参考文档同步

状态：未开始

### 待办

- 在 `MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md` 增加 TTS 验证矩阵：
  - 基础合成。
  - 官方音色参数。
  - 自然语言风格控制。
  - MiMo 标签控制。
  - MiMo 导演模式。
  - 冲突描述处理。
- 在 `MODEL_INTEGRATION_REFERENCE.md` 增加 TTS 接入回写规则：
  - 模型配置。
  - 音色目录。
  - provider payload。
  - 前端卡片。
  - 有声小说端到端测试。

### 验收标准

- 后续新增 TTS 模型时，可以按文档完成验证和回写。
- 文档能区分“官方文档声称支持”“真实接口验证支持”“项目链路已接入可用”。

### 关联文件

- `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md`
- `docs/MODEL_INTEGRATION_REFERENCE.md`

## TTS-11 有声小说端到端测试补足

状态：进行中

### 已完成

- 已新增 `backend/tests/test_audiobook_delivery_plan.py`，覆盖片段级 TTS 模型解析、delivery plan 对自然语言控制和 MiMo 标签控制的消费。
- 已新增 `backend/tests/test_audiobook_delivery_quality.py`，覆盖强表现片段缺少可执行朗读意图时的质量评审提示，以及评审阶段临时生成 delivery plan。
- 已扩展 `backend/tests/test_audiobook_tts_provider_payloads.py`，覆盖 MiniMax `basic` 控制模式、MiMo 模型别名识别和 MiMo/Qwen 控制格式隔离。
- 已扩展 `backend/tests/test_audiobook_tts_model_ids.py`，覆盖统一风格控制能力元数据、深拷贝隔离、模型能力 fallback、MiMo 运行时注册和自定义音色模型空目录。

### 待办

- 增加角色声音描述生成测试。
- 增加旁白风格生成测试。
- 增加已选音色与声音描述融合测试。
- 增加冲突检测测试。
- 增加不同模型输出不同 payload 的端到端测试。
- 增加前端选择模型后后端收到正确配置的契约测试。

### 验收标准

- 从角色设定、章节场景、用户选择音色到最终 TTS payload 的链路有测试覆盖。
- 新增模型风格控制方式时，不会破坏已有 Qwen、MiniMax、CosyVoice 行为。

### 关联文件

- `backend/tests/test_audiobook_tts_provider_payloads.py`
- `backend/tests/test_audiobook_tts_model_ids.py`
- `backend/tests/test_audiobook_narration_style_routes.py`
- `frontend/src/pages/audiobook/__tests__/*`

## TTS-12 StepAudio 2.5 TTS 正式接入

状态：进行中

### 合并说明

本项作为独立模型接入主题跟踪，不并入 MiMo。StepAudio 2.5 TTS 的官方模型 ID、接口协议、音色目录和风格控制能力需要单独验证，避免把其他 provider 的假设套用到该模型。

### 已完成

- 已按官方资料确认并落地基础模型信息：
  - 官方模型 ID：`stepaudio-2.5-tts`。
  - provider 标识：`stepfun`。
  - 非流式合成端点：`POST https://api.stepfun.com/v1/audio/speech`。
  - 复刻试听端点：`POST /v1/audio/voices/preview`。
  - 鉴权方式：`Authorization: Bearer $STEP_API_KEY`，后端兼容 `STEPFUN_API_KEY`。
  - 单次 `input` 上限 1000 字符，`instruction` 上限 200 字符。
  - Global Context 写入 `instruction` 参数；Inline Context 保留在 `input` 文本圆括号中，不转成 MiMo 音频标签。
- `config/models.yaml` 已新增 StepAudio 2.5 TTS 模型中心卡片，记录官方来源、价格、能力边界、调用方式、36 个官方音色和真实接口验证状态。
- `shared/stepaudio_2_5_tts_voices.json` 已登记官方最佳实践音色表中的 36 个官方音色，并接入 `voice_catalog.py`。
- `backend/app/services/audiobook/tts_model_ids.py` 已接入模型常量、支持列表、runtime ID、别名归一化、价格、能力矩阵和 `/api/v1/audiobook/tts/models` 元数据。
- `backend/app/services/audiobook/tts_style_control.py` 已新增 StepAudio 模型识别和 `stepaudio_global_context` 风格控制，避免复用 Qwen/MiMo/CosyVoice 的字段假设。
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py` 已接入 StepFun HTTP 调用：
  - 构造 `model`、`voice`、`input`、可选 `instruction`、可选 `response_format`。
  - 支持官方可选参数：`speed`、`volume`、`sample_rate`、`pronunciation_map`、`markdown_filter`、`return_url`、`stream_format`。
  - 默认 voice 使用 `cixingnansheng`。
  - 对 `input` 与 `instruction` 做服务商限制内截断。
  - 兼容二进制 `audio/*` 响应和 JSON 中的 base64/URL 音频响应。
  - 不传 `voice_label`。
  - `response_format` 仅允许 `mp3`、`wav`、`flac`、`opus`、`pcm`，不再向 StepAudio 2.5 TTS 透传 `aac`。
  - 支持通过 `STEPAUDIO_TTS_BASE_URL` 覆盖默认 base URL，便于在 StepFun `.com` / `.ai` 或后续专属网关之间切换验证。
  - 已封装 `POST /v1/audio/voices/preview` 复刻试听接口；当运行时参数包含 `stepaudio_voice_file_id` 时，`stepaudio_clone:{asset_id}` 音色会走 preview，不再误传给 `/audio/speech`。
- 已新增 `backend/app/services/audiobook/voice_manager_stepaudio.py`，并在 `voice_manager_factory.py` 中路由到 StepAudio 专用 manager。
- 已新增 StepAudio 本地复刻参考样本资产链路：
  - `backend/app/services/audiobook/stepaudio_voice_assets.py` 将 mp3/wav 样本保存到 `backend/data/stepaudio_voice_assets`，`index.json` 仅保存元数据，不写入 base64。
  - 新增 `GET /api/v1/audiobook/tts/voices/stepaudio/assets`、`POST /api/v1/audiobook/tts/voices/stepaudio/clone-assets/upload`、`DELETE /api/v1/audiobook/tts/voices/stepaudio/assets/{asset_id}`。
  - `GET /api/v1/audiobook/tts/voices?model=stepaudio-2.5-tts` 会追加 `stepaudio_clone:{asset_id}` 自定义音色预设。
  - 有 `file_id` 的本地参考样本可按官方 `/audio/voices/preview` 合成；没有 `file_id` 的样本会保留在资产列表，但在角色音色下拉和工作台试听中标记为暂不可用，等待官方文件上传接口补齐。
- `core/unified_media_runtime.py` 已将 `stepaudio-2.5-tts` 注册到 `synthesize_speech` 可选模型。
- `frontend/src/pages/audiobook/ttsModels.ts` 已新增 StepAudio 前端兜底配置、别名、默认音色、能力字段和 `全局语境` / `文中语境` 标签。
- `frontend/src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx` 已新增 StepAudio 参考样本工作台，支持录音转 WAV、上传 mp3/wav、保存本地音色、折叠列表、播放与删除。
- 有声小说项目配置、角色音色映射、角色级试听和 preview 请求已支持 `stepaudio_voice_asset_id`。
- 已补充或更新回归测试：
  - `backend/tests/test_stepaudio_voice_assets.py`
  - `backend/tests/test_audiobook_tts_model_ids.py`
  - `backend/tests/test_audiobook_tts_provider_payloads.py`
  - `tests/test_model_metadata_catalog.py`
  - `tests/test_model_catalog_bootstrap.py`
  - `tests/test_model_catalog_projection.py`
  - `tests/test_unified_model_system.py`
  - `frontend/src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts`
  - `frontend/src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts`
  - `frontend/src/pages/audiobook/__tests__/ttsModels.test.ts`
  - `frontend/src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts`

### 真实接口验证记录

- 已将用户提供的 `STEP_API_KEY` 写入本地根目录 `.env`，该文件受 `.gitignore` 保护，不纳入版本提交。
- `GET https://api.stepfun.com/v1/models` 成功，模型列表包含 `stepaudio-2.5-tts`、`step-tts-mini`、`step-tts-2` 等 TTS/Audio 模型。
- `POST https://api.stepfun.com/v1/audio/speech` + `stepaudio-2.5-tts` + `cixingnansheng` + 英文文本已通过真实接口验证：
  - 项目封装层输出文件：`backend/data/tts_debug/stepaudio/stepaudio_engine_en_preview.mp3`。
  - 音频大小：57898 bytes。
  - metadata 记录 provider=`stepfun`、endpoint=`/audio/speech`、style_control=`global_context_inline_context`。
- `POST https://api.stepfun.com/v1/audio/speech` + `stepaudio-2.5-tts` + `cixingnansheng` + 中文文本已通过真实接口验证：
  - 输出文件：`backend/data/tts_debug/stepaudio/stepaudio_cn_unicode_escape.mp3`。
  - 音频大小：69802 bytes。
  - input：`智能阶跃，十倍每一个人的可能。`
  - instruction：`语气温柔，语速偏慢`
- 早前中文请求返回 `no available voice synthensis text` 的根因已确认为 PowerShell here-string 管道导致内联 Python 中文源码被替换成 `?`，不是 StepAudio 2.5 TTS 不支持中文。
- `https://api.stepfun.ai/v1/audio/speech` 使用当前 key 返回 `invalid_api_key`，说明当前 key 更像 `.com` 平台密钥，不适用于 `.ai` 公共端点。

### 待办

- 确认 StepFun 文件上传接口，补齐“上传本地音频后自动生成 `file_id`”的闭环。
- 继续确认 Zero-shot 自生成音色的正式创建接口、资产 ID 形态、语言支持和计费触发点，避免把 `/audio/voices/preview` 试听接口误当正式收费资产创建接口。
- 使用真实 `/audio/voices/preview` 对带 `file_id` 的本地参考样本资产做一次端到端验证。
- 若真实接口返回格式与当前兼容分支不同，回写 `_parse_stepaudio_audio_response()` 与对应测试。
- 将 StepAudio 的验证步骤同步到 `docs/MODEL_CAPABILITY_VALIDATION_GUIDE_20260422.md` 与 `docs/MODEL_INTEGRATION_REFERENCE.md`。

### 验收标准

- 模型中心能展示 StepAudio 2.5 TTS 的官方来源、能力边界、音色和调用方式。
- 有声小说链路能选择该模型并生成正确 payload。
- 不使用 Qwen、MiMo、MiniMax 或 CosyVoice 的音色和风格控制假设替代 StepAudio 官方能力。
- 模型卡片不再保留中文基础合成的 `pending-runtime-validation`；但在正式收费音色创建和文件上传接口确认前，继续标记或说明 `pending-official-voice-clone-assets`。

### 本轮验证

- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py::test_voice_manager_factory_routes_stepaudio_contextual_tts_model" -q`：1 passed。
- `python -m pytest "tests/test_model_metadata_catalog.py::test_stepaudio_25_tts_catalog_exposes_contextual_tts_contract" -q`：1 passed。
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "tests/test_model_metadata_catalog.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_catalog_projection.py" -q`：71 passed。
- `python -m pytest "tests/test_model_catalog_runtime.py" "tests/test_unified_model_system.py" -q`：40 passed。
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts"`：2 files / 10 tests passed。
- `npm run type-check`：通过。
- `python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py::test_stepaudio_http_call_allows_base_url_override" -q`：1 passed。
- `python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py::test_stepaudio_http_payload_passes_official_optional_parameters_only" "backend/tests/test_audiobook_tts_provider_payloads.py::test_stepaudio_http_payload_rejects_unsupported_response_format_and_ui_volume" -q`：先红后绿，2 passed。
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py::test_stepaudio_voice_catalog_contains_official_contextual_tts_voices" "tests/test_model_metadata_catalog.py::test_stepaudio_25_tts_catalog_exposes_contextual_tts_contract" -q`：先红后绿，2 passed。
- `python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_model_ids.py" -q`：62 passed。
- `python -m pytest "tests/test_model_metadata_catalog.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_catalog_projection.py" -q`：13 passed。
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts"`（在 `frontend/` 目录执行）：2 files / 10 tests passed。
- `npm run type-check`（在 `frontend/` 目录执行）：通过。
- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_project_audio_runtime.py" -q`：78 passed。
- `npm run test -- "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts"`（在 `frontend/` 目录执行）：25 passed。
- `npm run type-check`（在 `frontend/` 目录执行）：通过。
- 真实 StepFun API 英文试听：通过，生成 `backend/data/tts_debug/stepaudio/stepaudio_engine_en_preview.mp3`。
- 真实 StepFun API 中文试听：通过，生成 `backend/data/tts_debug/stepaudio/stepaudio_cn_unicode_escape.mp3`；早前失败为本地 PowerShell 脚本编码问题。

### 关联文件

- `config/models.yaml`
- `backend/app/services/audiobook/tts_model_ids.py`
- `backend/app/services/audiobook/voice_catalog.py`
- `backend/app/services/audiobook/voice_manager_factory.py`
- `backend/app/services/audiobook/voice_manager_stepaudio.py`
- `backend/app/services/audiobook/stepaudio_voice_assets.py`
- `backend/app/services/audiobook/tts_style_control.py`
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`
- `backend/app/api/v1/audiobook_api/routes_tts.py`
- `backend/app/schemas/audiobook.py`
- `backend/app/services/audiobook/project_audio_runtime.py`
- `core/unified_media_runtime.py`
- `shared/stepaudio_2_5_tts_voices.json`
- `frontend/src/pages/audiobook/ttsModels.ts`
- `frontend/src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx`
- `frontend/src/services/api.ts`
- `frontend/src/pages/audiobook/projectAudioConfigUtils.ts`
- `backend/tests/test_audiobook_tts_model_ids.py`
- `backend/tests/test_audiobook_tts_provider_payloads.py`
- `backend/tests/test_stepaudio_voice_assets.py`
- `frontend/src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts`
- `frontend/src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts`
- `tests/test_model_metadata_catalog.py`

## TTS-13 豆包 seed-tts-2.0-expressive 正式接入

状态：进行中

### 合并说明

本项用于跟踪“豆包语音合成大模型高表现力版 `seed-tts-2.0-expressive`”的正式接入。该模型涉及火山引擎/豆包独立鉴权、Volcengine V3 TTS endpoint、`context_texts` 对话式风格控制、官方音色目录和双向流式 WebSocket 能力，必须与百炼 TTS、MiMo、StepAudio 分开建模和验证。

### 已完成

- 已核对用户提供的火山/豆包产品资料和本地 PDF：
  - `D:/cuigu/Documents/豆包语音_双向流式语音合成WebSocket_1782219746.pdf`
  - `D:/cuigu/Documents/豆包语音_语音指令与标签_1780036074.pdf`
- 已确认基础协议要点：
  - 官方模型 ID：`seed-tts-2.0-expressive`。
  - provider 标识：`volcengine`。
  - 默认 resource id：`seed-tts-2.0`。
  - 非流式合成端点：`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`。
  - 双向流式端点：`wss://openspeech.bytedance.com/api/v3/tts/bidirection`。
  - 鉴权头：`X-Api-Key`、`X-Api-Resource-Id`，项目内兼容 `X-Api-App-Key`。
- 已确认高表现力能力边界：
  - `seed-tts-2.0-expressive` 支持 `context_texts` 语音指令。
  - `seed-tts-2.0-standard` 不支持 `context_texts` 和 `use_tag_parser`。
  - `use_tag_parser` 主要面向复刻音色和短文本精细控制。
  - 语音指令可控制整体情绪、方言、语气、语速和音调。
  - 引用上文能力用于让模型理解并承接语境情绪，引用内容不参与合成。
  - 语音标签支持在句子前用方括号描述表情、心理、肢体动作或局部演绎细节，属于官方抢鲜体验能力。
  - 语音标签官方示例推荐使用可爱女生、调皮公主、爽朗少年、天才同桌或声音复刻 2.0 模型复刻后的音色；当前系统音色目录已覆盖这些官方推荐音色。
  - 双向流式 WebSocket 支持 `StartConnection`、`StartSession`、`TaskRequest` 等事件，当前项目只建档能力，未接入实时播放链路。
- 已在 `config/models.yaml` 增加模型卡片，记录 endpoint、resource id、风格控制、音频格式、采样率、限制和待真实验证状态。
- 已在后端接入模型 ID、能力矩阵、别名归一化、voice catalog、voice manager 和 `UnifiedMediaRuntime` 注册。
- 已将用户提供的 99 个豆包 Seed-TTS 2.0 官方音色写入 `shared/seed_tts_2_0_voices.json`，保留音色名、推荐场景、语种和真实 `Voice_type`。
- 已在 `tts_style_control.py` 中将豆包模型映射为 `doubao_query_response`，把有声小说朗读意图写入 `req_params.additions.context_texts`。
- 已在 `tts_style_control.py` 和 `TTSEngine` 中接入显式标签模式：`inline_audio_tags` 会合成为 `[标签]正文`，并在 Seed-TTS payload 中设置 `use_tag_parser=true`。
- 已在 `TTSEngine` 的 Volcengine Seed-TTS 分支接入非流式 HTTP payload 构建、响应解析和合成元数据记录；真实接口已确认 `speaker` 与 `audio_params` 需要位于 `req_params` 内，`additions` 需要是 JSON 字符串。
- 已收紧 Seed-TTS 鉴权入口，只接受 `VOLCENGINE_TTS_API_KEY`、`DOUBAO_TTS_API_KEY`、`SEED_TTS_API_KEY`、`VOLCENGINE_SPEECH_API_KEY`、`DOUBAO_SPEECH_API_KEY` 作为 openspeech 专用 `X-Api-Key` 来源，避免误用火山方舟通用 `VOLCENGINE_API_KEY` / `DOUBAO_API_KEY`。
- 已配置真实 Seed Speech/openspeech 专用 `VOLCENGINE_TTS_API_KEY` 到 `.env.local`，并完成一次非流式基础试听验证。
- 已在前端 `ttsModels.ts` 增加模型选项、默认旁白、别名、风格控制标签和兜底能力。
- 已新增 `adapters/volcengine/tts.py`，让统一媒体注册中心能识别 `seed-tts-2.0-expressive`。

### 待办

- 使用真实接口分别验证：
  - 引用上文语境承接效果。
  - `[旁白，语调惊恐]正文` 这类方括号语音标签。
  - `use_tag_parser=true` 对系统音色和复刻音色的差异。
- 继续核对控制台后续新增/下线音色，并保持 `shared/seed_tts_2_0_voices.json` 与模型中心音色数量同步。
- 补充 `seed-icl-2.0` 复刻音色资产接入设计，尤其是付费确认、资产状态机和 `use_tag_parser` 触发条件。
- 评估是否将双向流式 WebSocket 接入有声小说实时预览或对话式试听链路。
- 在浏览器中人工核对 `http://localhost:5173/model-catalog` 的豆包模型卡片展示。
- 根据语音标签、复刻音色和双向流式验证结果继续回写 `config/models.yaml` 的待验证标签和能力置信度。

### 验收标准

- 模型中心能明确显示豆包高表现力版的官方 ID、能力边界、音色和调用方式。
- 有声小说链路能选择 `seed-tts-2.0-expressive` 并生成符合豆包接口要求的 payload。
- 高表现力能力必须区分“官方声明支持”“真实接口验证支持”“项目链路已接入可用”三类结论。
- 不调用真实接口时，测试只能标记为本地 payload/mock 通过，不能标记为远程可用。

### 关联文件

- `config/models.yaml`
- `shared/seed_tts_2_0_voices.json`
- `backend/app/services/audiobook/tts_model_ids.py`
- `backend/app/services/audiobook/voice_catalog.py`
- `backend/app/services/audiobook/voice_manager_seed_tts.py`
- `backend/app/services/audiobook/voice_manager_factory.py`
- `backend/app/services/audiobook/tts_style_control.py`
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`
- `adapters/volcengine/tts.py`
- `core/unified_media_runtime.py`
- `frontend/src/pages/audiobook/ttsModels.ts`
- `backend/tests/test_audiobook_tts_model_ids.py`
- `backend/tests/test_audiobook_tts_provider_payloads.py`
- `backend/tests/test_project_audio_runtime.py`
- `frontend/src/pages/audiobook/__tests__/ttsModels.test.ts`
- `tests/test_model_metadata_catalog.py`

## 当前测试记录

以下是本轮已知通过的测试集合，后续变更应继续保持通过：

- `python -m pytest "backend/tests/test_audiobook_voice_description_policy.py" -q`
- `python -m pytest "tests/test_model_metadata_catalog.py" -q`
- `python -m pytest "backend/tests/test_qwen_tts_voice_compat.py" "backend/tests/test_audiobook_tts_model_ids.py" "tests/test_asset_studio_model_catalog.py" -q`
- `python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py" -q`
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" -q`
- `python -m pytest "backend/tests/test_audiobook_narration_style_routes.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_qwen_tts_voice_compat.py" -q`
- `python -m pytest "tests/test_model_metadata_catalog.py" "tests/test_asset_studio_model_catalog.py" -q`
- `python -m pytest "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_qwen_tts_voice_compat.py" -q`
- `python -m pytest "backend/tests/test_qwen_tts_voice_compat.py" -q`
- `python -m pytest "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_qwen_tts_voice_compat.py" -q`（53 passed）
- `python -m pytest "tests/test_model_metadata_catalog.py" "tests/test_asset_studio_model_catalog.py" -q`（9 passed）
- `python -m pytest "tests/test_tts_semantic_vocabulary.py" -q`（2 passed）
- `python -m pytest "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_audio_quality_reviewer.py" "backend/tests/test_audiobook_quality_gate.py" "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_voice_description_policy.py" "backend/tests/test_audiobook_tts_model_ids.py" -q`（67 passed）
- `python -m compileall "backend/app/services/audiobook/tts_model_ids.py" "backend/app/services/audiobook/tts_delivery_plan.py" "backend/app/services/audiobook/tts_style_control.py"`
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"`（7 passed）
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q`（72 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"`（10 passed）
- `python -m pytest "backend/tests/test_project_audio_runtime.py" -q`（5 passed）
- `python -c "import yaml; data=yaml.safe_load(open('config/models.yaml', encoding='utf-8')); print(len(data.get('models', []))); print(any(m.get('id')=='seed-tts-2.0-expressive' for m in data.get('models', [])))"`（`41` / `True`）
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_project_audio_runtime.py" -q`（78 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts"`（10 passed）
- `python -c "import json, yaml; voices=json.load(open('shared/seed_tts_2_0_voices.json', encoding='utf-8')); models=yaml.safe_load(open('config/models.yaml', encoding='utf-8')); seed=next(m for m in models['models'] if m['id']=='seed-tts-2.0-expressive'); print(len(voices['voices'])); print(voices['default_voice']); print(seed['detailed_specs']['voice_synthesis']['default_voice'])"`（`99` / `zh_female_vv_uranus_bigtts` / `zh_female_vv_uranus_bigtts`）
- 真实接口最小请求已发送到 `POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`；使用火山方舟通用 `VOLCENGINE_API_KEY` / `DOUBAO_API_KEY` 时返回 `Invalid X-Api-Key`，随后配置 Seed Speech 专用 `VOLCENGINE_TTS_API_KEY` 后鉴权通过。
- 真实接口进一步暴露 V3 payload 契约：`req_params.additions` 必须是 JSON 字符串，`speaker` 和 `audio_params` 必须位于 `req_params` 内；修正后基础合成成功。
- `TTSEngine` 正式路径真实试听通过，生成文件：`backend/data/tts_debug/seed_tts_real_preview_20260625_093144.mp3`，返回 `41290` bytes，provider=`volcengine`，model=`seed-tts-2.0-expressive`，speaker=`zh_female_vv_uranus_bigtts`，resource_id=`seed-tts-2.0`，context_texts_count=`1`。
- `python -m pytest "backend/tests/test_audiobook_tts_provider_payloads.py::test_seed_tts_synthesis_requires_dedicated_speech_api_key" "backend/tests/test_audiobook_tts_provider_payloads.py::test_seed_tts_http_payload_uses_context_texts_and_audio_params" "backend/tests/test_audiobook_tts_provider_payloads.py::test_seed_tts_http_payload_supports_official_inline_voice_labels" "backend/tests/test_audiobook_tts_provider_payloads.py::test_seed_tts_http_call_uses_volcengine_v3_endpoint" -q`（4 passed）
- `npm run type-check`
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/loadingButtonSource.test.ts"`（11 passed）
- `python -m pytest "tests/test_model_catalog_projection.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_metadata_catalog.py" "backend/tests/test_audiobook_tts_model_ids.py" -q`（33 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/loadingButtonSource.test.ts" "src/pages/__tests__/modelCatalogTtsStyleControlSource.test.ts"`（12 passed）
- `npm run type-check`
- `python -m pytest "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_qwen_tts_voice_compat.py" "backend/tests/test_audiobook_tts_param_normalization.py" "backend/tests/test_audiobook_delivery_plan.py" "backend/tests/test_audiobook_delivery_quality.py" "backend/tests/test_audiobook_voice_description_policy.py" "tests/test_model_catalog_projection.py" "tests/test_model_catalog_bootstrap.py" "tests/test_model_metadata_catalog.py" -q`（85 passed）
- `npm run test -- "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/voiceCatalog.test.ts"`（12 passed）
- `npm run type-check`
- `npm run test -- "src/pages/audiobook/__tests__/cosyVoiceCloneUploadUtils.test.ts" "src/pages/audiobook/__tests__/voiceCloneAudioUtils.test.ts" "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/loadingButtonSource.test.ts" "src/pages/audiobook/__tests__/setupStepSource.test.ts"`（33 passed）
- `npm run type-check`

## 后续更新规则

- 每次实现本文件中的事项时，必须同步更新对应主题的状态、已完成内容和测试记录。
- 如果实现过程中发现两个待办实际属于同一职责边界，应先在本文档中合并，再修改代码。
- 如果官方资料与当前实现不一致，以真实接口验证和项目链路行为为准，并在对应主题中记录差异。
- 不把占位模型 ID、占位价格、临时复用音色目录作为最终完成条件。

## 本次落地记录：MiMo 本地音色资产库

更新时间：2026-06-24

### 状态更新

- TTS-05 MiMo-V2.5-TTS 系列正式接入：继续保持“进行中”，但新增的 Voice Clone / Voice Design 可复用音色资产能力已落地。
- TTS-07 前端有声小说声音设计面板适配：继续保持“进行中”，但 MiMo 本地资产管理入口、角色级资产选择和临时 inline 输入入口已落地。
- TTS-11 有声小说端到端测试补足：继续保持“进行中”，已新增 MiMo 本地资产库、项目配置 payload、manager 展开链路相关测试。

### 已完成

- 新增后端本地资产服务 `backend/app/services/audiobook/mimo_voice_assets.py`：
  - Voice Design 资产保存为 `voice_design_prompt`。
  - Voice Clone 资产保存为本地音频文件，`index.json` 仅保存元数据，不长期写入大段 base64。
  - 生成或试听时通过 `mimo_voice_asset_id` 展开为 `voice_design_prompt` / `voice_clone_data_url`。
  - 下拉音色 ID 使用 `mimo_design:{asset_id}` / `mimo_clone:{asset_id}`，便于像 CosyVoice 自定义音色一样选择。
- 新增后端 API：
  - `GET /api/v1/audiobook/tts/voices/mimo/assets`
  - `POST /api/v1/audiobook/tts/voices/mimo/clone-assets`
  - `POST /api/v1/audiobook/tts/voices/mimo/design-assets`
  - `DELETE /api/v1/audiobook/tts/voices/mimo/assets/{asset_id}`
- `GET /api/v1/audiobook/tts/voices?model=mimo-v2.5-tts-voiceclone|mimo-v2.5-tts-voicedesign` 已把本地 MiMo 资产作为 `VoicePreset` 返回，角色音色下拉可以直接使用。
- 有声小说项目配置、任务创建、项目运行时配置和试听请求已支持：
  - `voice_clone_data_url`
  - `voice_design_prompt`
  - `mimo_voice_asset_id`
- `MiMoVoiceManager` 已能在生成前解析 `mimo_voice_asset_id` 或 `mimo_clone:/mimo_design:` 形式的 `voice_id`，并展开为 MiMo 官方 payload 所需字段。
- 前端新增 `MimoVoiceAssetWorkbench.tsx`：
  - MiMo Voice Clone 模型下可保存 `audio.voice data URL` 为本地资产。
  - MiMo Voice Design 模型下可保存 `Voice Design Prompt` 为本地资产。
  - 已保存资产可删除，并会触发音色目录刷新。
- 角色音色卡在 MiMo Voice Clone / Voice Design 下支持：
  - 从本地资产下拉中选择可复用音色。
  - MiMo Voice Clone 可继续填写临时 `audio.voice`。
  - MiMo Voice Design 已取消角色级 `Voice Design Prompt` 入口，改为先保存音色、再直接选择音色。
  - 选择可复用资产时，保存 `mimo_voice_asset_id`，并避免把 stale inline base64/prompt 写入项目配置。
  - 前端相关文案已从“资产名称/保存资产”统一收敛为“音色名称/保存音色”。

### 验证记录

- `python -m pytest "backend/tests/test_mimo_voice_assets.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_project_audio_runtime.py" "backend/tests/test_audiobook_app_service_voice_config.py" -q`：60 passed。
- `python -m py_compile "backend/app/services/audiobook/mimo_voice_assets.py" "backend/app/services/audiobook/voice_manager_mimo.py" "backend/app/services/audiobook/project_audio_runtime.py" "backend/app/api/v1/audiobook_api/routes_tts.py" "backend/app/schemas/audiobook.py" "backend/app/api/v1/projects.py" "backend/app/services/audiobook/app_service.py"`：通过。
- `npm run test -- "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/voiceCatalog.test.ts" "src/pages/audiobook/__tests__/loadingButtonSource.test.ts"`：4 files / 28 tests passed。
- `npm run type-check`：通过。

### 后续待办

- 使用真实 MiMo API 做一次端到端试听验证，确认本地 clone 资产展开后的 `audio.voice` 和 design 资产展开后的 `voice_design_prompt` 与官方接口完全匹配。
- 如后续 StepAudio 2.5 TTS、`seed-tts-2.0-expressive` 也支持类似音色设计/克隆，应优先复用“本地资产 ID + 生成时展开”的模式，避免把大段 base64 写入项目配置。

## 本次落地记录：MiMo/CosyVoice 音色工作台交互收口

更新时间：2026-06-24

### 状态更新

- TTS-05 MiMo-V2.5-TTS 系列正式接入：继续保持“进行中”，本次完成 Voice Clone 本地音色入口的录音/上传辅助能力；真实 MiMo API 仍待验证。
- TTS-07 前端有声小说声音设计面板适配：继续保持“进行中”，本次完成 MiMo 工作台备注框移除、MiMo Clone data URL 自动生成、CosyVoice Design 试听按钮。
- TTS-11 有声小说端到端测试补足：继续保持“进行中”，本次补充前端工具函数和源码守卫测试。

### 已完成

- 新增 `frontend/src/pages/audiobook/voiceCloneAudioUtils.ts`：
  - `createRecordedCloneAudioFile()` 抽为通用录音 Blob 转 File 工具。
  - `readAudioFileAsDataUrl()` 将上传/录音得到的音频文件转换为 MiMo 所需 `data:audio/...;base64,...`。
  - `uploadCosyVoiceCloneSampleFile()` 保留 CosyVoice 复刻上传 OSS 临时 URL 链路。
- `cosyVoiceCloneUploadUtils.ts` 改为兼容转发层，避免旧导入路径断裂。
- `MimoVoiceAssetWorkbench.tsx`：
  - MiMo Voice Clone 下新增“录音”和“上传音频”按钮。
  - 上传或录音后自动回填 `audio.voice data URL`。
  - 移除备注输入框，保存时只提交音色名称和核心样本/描述。
- `CosyVoiceDesignVoicePanel.tsx`：
  - 设计成功后接收并保存 `preview_audio`。
  - 有预览音频时按钮从“开始设计”切换为“试听”。
  - 修改设计名称、声音描述或试听文本后清除旧试听音频，避免播放过期结果。

### 验证记录

- `npm run test -- "src/pages/audiobook/__tests__/cosyVoiceCloneUploadUtils.test.ts" "src/pages/audiobook/__tests__/voiceCloneAudioUtils.test.ts" "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/loadingButtonSource.test.ts" "src/pages/audiobook/__tests__/setupStepSource.test.ts"`：6 files / 33 tests passed。
- `npm run type-check`：通过。

### 后续待办

- 浏览器手动验证 MiMo Voice Clone 录音权限、上传文件转 data URL、保存本地音色、角色下拉选择和试听链路。
- 使用真实 MiMo API 验证保存后的本地 clone 音色展开为 `audio.voice` 后可被官方接口接受。
- CosyVoice Design 的 `preview_audio` 若官方接口返回格式发生变化，需要补充 URL/data URL/base64 归一化测试。

## 本次落地记录：MiMo/CosyVoice 音色工作台保存与试听修复

更新时间：2026-06-24

### 状态更新

- TTS-05 MiMo-V2.5-TTS 系列正式接入：继续保持“进行中”，本次将 MiMo Voice Clone 本地音色保存从前端长 `data:audio/...;base64,...` JSON 输入改为 multipart 音频文件上传保存；真实 MiMo API 仍待验证。
- TTS-07 前端有声小说声音设计面板适配：继续保持“进行中”，本次统一 MiMo Voice Clone / Voice Design 与 CosyVoice v3.5-plus 的复刻/设计面板文案和布局，并修复 CosyVoice Design 完成后试听按钮状态。
- TTS-11 有声小说端到端测试补足：继续保持“进行中”，本次补充前端工作台源码守卫、音频样本摘要、CosyVoice 试听音频归一化和 MiMo multipart 保存链路测试。

### 已完成

- `MiMoVoiceAssetStore` 新增 `create_clone_asset_from_bytes()`：
  - 可直接从上传文件 bytes 保存本地 Voice Clone 音色。
  - 继续只在磁盘保存音频文件，`index.json` 不写入大段 base64。
  - 原有 `audio_data_url` 保存入口保留，用于兼容既有调用。
- 新增后端 API：
  - `POST /api/v1/audiobook/tts/voices/mimo/clone-assets/upload`
  - 请求使用 multipart form，字段为 `name` 和 `file`。
  - 返回结构继续保持 `{ asset, voice }`，角色音色下拉刷新逻辑无需变更。
- 前端 `apiClient` 新增 `createMimoVoiceCloneAssetFromFile()`，MiMo Voice Clone 保存时直接上传文件，不再把大段 base64 放进页面输入框或 JSON 请求。
- `MimoVoiceAssetWorkbench.tsx`：
  - Voice Clone UI 改为“音色名称 + 音频样本摘要 + 保存音色”。
  - 上传/录音后展示“已选择音频样本”及文件名、MIME、大小摘要。
  - 新增“清除样本”按钮。
  - 不再展示 `audio.voice data URL` 输入框，避免长内容无法阅读和难以保存。
  - Voice Design UI 文案收敛为“声音设计 / 声音描述 / 保存音色”，与 CosyVoice 面板风格更接近。
- `CosyVoiceDesignVoicePanel` 相关状态修复：
  - 设计成功后不再清空 `designName`、`designPrompt` 和 `designPreviewText`，避免按钮回到初始灰色状态。
  - 有 `preview_audio` 时按钮保持切换为“试听”。
  - 新增 `normalizeCosyVoicePreviewAudioUrl()`，支持官方返回 URL、data URL 或裸 base64 时都能转成可播放地址。

### 验证记录

- `npm run test -- "src/pages/audiobook/__tests__/cosyVoiceCloneUploadUtils.test.ts" "src/pages/audiobook/__tests__/voiceCloneAudioUtils.test.ts" "src/pages/audiobook/__tests__/voiceActionsUtils.test.ts" "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts" "src/pages/audiobook/__tests__/loadingButtonSource.test.ts" "src/pages/audiobook/__tests__/setupStepSource.test.ts"`：7 files / 36 tests passed。
- `python -m pytest "backend/tests/test_mimo_voice_assets.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_project_audio_runtime.py" "backend/tests/test_audiobook_app_service_voice_config.py" -q`：62 passed。
- `npm run type-check`：通过。

### 后续待办

- 浏览器手动验证 MiMo Voice Clone 录音权限、上传文件、保存本地音色、角色下拉选择和试听链路。
- 使用真实 MiMo API 验证 multipart 保存后的本地 clone 音色展开为 `audio.voice` 后可被官方接口接受。
- 使用真实 CosyVoice Design 接口验证 `preview_audio` 返回格式，并确认“开始设计”完成后按钮稳定切换为“试听”。

## 本次落地记录：MiMo Voice Clone 录音试听失败修复

更新时间：2026-06-24

### 问题定位

- 录音保存本身成功，后端日志显示 `POST /api/v1/audiobook/tts/voices/mimo/clone-assets/upload` 返回 200。
- 失败发生在随后调用 MiMo Voice Clone 试听时，MiMo 返回：
  - `audio.voice must be a DataURL for voice clone model`
- 根因有两个：
  - 浏览器录音文件 MIME 为 `audio/webm;codecs=opus`，保存后展开为 `data:audio/webm;codecs=opus;base64,...`。MiMo 实测不接受带 codec 参数的 DataURL MIME。
  - Voice Clone payload 构建时优先使用了 `voice` 里的本地资产 ID（如 `mimo_clone:...`），而不是资产展开后的 `voice_clone_data_url`。

### 已完成

- `MiMoVoiceAssetStore` 在保存、解析和展开 clone 音频时将 MIME 归一为主类型：
  - `audio/webm;codecs=opus` -> `audio/webm`
  - 已保存的旧资产在展开时也会自动输出干净 DataURL，无需重新录音。
- MiMo Voice Clone payload 构建改为优先使用：
  - `voice_sample_data_url`
  - `voice_clone_data_url`
  - 只有当显式 `voice` 本身已经是 `data:audio/...` 时才使用 `voice`
- 新增 TTS 参数日志脱敏，避免 `voice_clone_data_url` 的大段 base64 完整写入服务端日志。

### 验证记录

- `python -m pytest "backend/tests/test_mimo_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q`：34 passed。
- `python -m py_compile "backend/app/services/audiobook/mimo_voice_assets.py" "backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py" "backend/app/services/audiobook/tts_engine_pkg/_base.py"`：通过。

### 后续待办

- 在浏览器中用已有录音资产直接重试试听，确认旧资产无需重新录音即可通过。
- 若 MiMo 仍拒绝 `audio/webm`，再按官方接受范围增加前端录音格式约束或后端转码策略。

## 本次落地记录：MiMo Voice Clone 样本格式收口

更新时间：2026-06-24

### 问题定位

- 真实 MiMo API 二次验证后确认，Voice Clone 的 `audio.voice` 源音频不仅要求 DataURL，还只接受 `mp3` / `wav`：
  - 上传 `audio/x-m4a` 返回：`Unsupported audio.voice source format: x-m4a. Supported formats: [mp3, wav]`
  - 浏览器录音 `audio/webm` 返回：`Unsupported audio.voice source format: webm. Supported formats: [mp3, wav]`
- 因此上一轮“去掉 codec 参数即可复用旧 webm 资产”的假设不成立；旧 `webm` / `m4a` 本地 clone 资产需要重新录音或重新上传支持格式。

### 已完成

- `frontend/src/pages/audiobook/voiceCloneAudioUtils.ts`：
  - 新增 MiMo Clone 样本格式判断，仅允许 `mp3` / `wav`。
  - 新增 PCM16 WAV 编码工具，将浏览器录音 Blob 解码后混合为单声道 WAV。
- `frontend/src/pages/audiobook/MimoVoiceAssetWorkbench.tsx`：
  - 上传入口从 `audio/*` 收窄为 `.mp3,.wav,audio/mpeg,audio/wav`。
  - 上传 `m4a` / `webm` 等不支持格式时在前端直接提示转换格式。
  - 录音完成后自动转换为 `audio/wav` 文件再保存为 MiMo 复刻音色。
- `backend/app/services/audiobook/mimo_voice_assets.py`：
  - 保存 clone 资产时仅接受 `audio/mpeg` / `audio/wav`，并兼容归一 `audio/mp3`、`audio/x-wav` 等别名。
  - 展开旧资产时同样校验 MIME，旧 `webm` / `m4a` 资产会在本地提前失败，不再继续调用 MiMo 外部接口。
- 测试已覆盖：
  - 前端 mp3/wav 白名单、webm/m4a 拒绝、WAV header 编码。
  - 后端 multipart 上传、DataURL 保存、旧资产展开三条路径的格式防线。

### 验证记录

- `npm run test -- "src/pages/audiobook/__tests__/voiceCloneAudioUtils.test.ts" "src/pages/audiobook/__tests__/setupStepSource.test.ts"`：2 files / 7 tests passed。
- `python -m pytest "backend/tests/test_mimo_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q`：36 passed。
- `npm run type-check`：通过。
- `python -m py_compile "backend/app/services/audiobook/mimo_voice_assets.py" "backend/app/api/v1/audiobook_api/routes_tts.py" "backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py" "backend/app/services/audiobook/tts_engine_pkg/_base.py"`：通过。

### 后续待办

- 浏览器手动复测：
  - 录音后样本摘要应显示 `audio/wav`，保存后试听不再触发 `webm` 格式错误。
  - 上传 `.wav` / `.mp3` 可保存并试听。
  - 上传 `.m4a` / `.webm` 应在前端直接提示不支持。
- 已存在的 `webm` / `m4a` MiMo Clone 音色需要删除后重新录音或上传 `mp3` / `wav`。

## 本次落地记录：StepAudio Voice Clone 自动生成 file_id

更新时间：2026-06-25

### 状态更新

- TTS-12 StepAudio 2.5 TTS 正式接入：继续保持“进行中”，本次完成 Zero-shot 参考样本上传后自动生成官方 `file_id` 的闭环。
- StepFun 文件上传合同已按官方资料接入：
  - `POST https://api.stepfun.com/v1/files`
  - multipart/form-data：`file` + `purpose=storage`
  - 鉴权：`Authorization: Bearer $STEP_API_KEY`
  - 返回 `id` 作为后续 `/audio/voices/preview` 的 `file_id`

### 已完成

- `backend/app/services/audiobook/stepaudio_voice_assets.py`：
  - 新增 `upload_stepaudio_voice_reference_file()`，负责将 mp3/wav 样本上传到 StepFun 文件接口并返回 `file_id`。
  - 复用 StepAudio 样本格式白名单，仅允许 `audio/mpeg` / `audio/wav` 及其常见别名，避免先发外部接口再失败。
  - 新增 `get_stepaudio_api_key()`，统一读取 `STEP_API_KEY` / `STEPFUN_API_KEY`。
- `backend/app/api/v1/audiobook_api/routes_tts.py`：
  - `POST /api/v1/audiobook/tts/voices/stepaudio/clone-assets/upload` 在未手填 `file_id` 且已配置 Step API Key 时，自动上传样本生成 `file_id` 后再保存资产。
  - 如果用户显式传入 `file_id`，保持原行为，不重复调用 StepFun 文件接口。
  - 当前保存路径需要可用的 `file_id`，也就是手填 `file_id` 或已配置 Step API Key 自动上传生成，避免保存不可试听/不可生成的参考样本。
- `frontend/src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx`：
  - `file_id` 输入框文案改为“可选，留空自动上传生成”。
  - 增加说明：留空时后端使用 `STEP_API_KEY` / `STEPFUN_API_KEY` 调用 StepFun 文件接口；确认保存复用已经生成的 `file_id`。

### 验证记录

- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" -q`：9 passed。
- `npm run test -- "src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts"`：1 file / 5 tests passed。

### 后续待办

- 浏览器手动复测 StepAudio Voice Clone：
  - 录音后自动转换为 wav。
  - 留空 `file_id` 预试听时应自动生成 `file_id`，确认保存后列表中试听按钮可用。
  - 未配置 Step API Key 且未手填 `file_id` 时，应在预试听/确认保存前直接提示缺少密钥或 `file_id`。
- 在用户明确确认后，再使用真实 StepFun `/v1/files` + `/audio/voices/preview` 做一次端到端验证；当前测试使用 mock，未主动调用真实外部接口。
- 继续确认 StepFun 正式收费音色创建接口；当前实现仍是“参考样本资产 + preview file_id”，不伪造正式 voice id。

## 本次落地记录：StepAudio Voice Clone 样本文本校验修复

更新时间：2026-06-25

### 问题定位

- 真实接口日志显示 `/v1/files` 已成功返回 `file_id`，失败发生在后续 `POST /v1/audio/voices/preview`。
- StepFun 返回 `CER_NOT_PASS`，并在错误详情中同时给出 `asr_result` 和 `user_text`：
  - `asr_result` 是官方 ASR 从参考音频中识别出的真实内容。
  - `user_text` 是 StepFun 用于校验参考音频的 HTTP `text` 字段。
- 因此根因不是文件上传失败，而是 StepAudio Voice Clone 的参考音频逐字内容必须放到官方 preview payload 的 `text` 字段；项目内部仍保留 `sample_text` 表示“参考音频逐字内容”，但 provider 适配层会把它映射到 HTTP `text`。

### 已完成

- `frontend/src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx`：
  - StepAudio Clone 的 `sampleText` 默认值改为空。
  - 保存前必须填写“参考音频逐字内容”。
  - 输入框文案明确说明官方会校验样本文本与音频 ASR，不能填写试听文本。
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`：
  - 解析 StepAudio voice preview 错误响应。
  - 遇到 `CER_NOT_PASS` 时转换为 `TTSUserInputError(code="stepaudio_clone_sample_text_mismatch")`。
  - 修正 StepAudio `/audio/voices/preview` 字段映射：内部 `sample_text` 写入官方 HTTP `text` 用于参考音频 ASR 校验，内部试听文本写入 HTTP `sample_text`，避免默认试听句被官方当成参考音频逐字内容。
- `backend/app/services/audiobook/tts_engine_pkg/_api_call_mixin.py` 与 `backend/app/api/v1/audiobook_api/routes_tts.py`：
  - 用户输入错误不再走 provider fallback 或泛化为 503。
  - `/api/v1/audiobook/tts/preview` 返回 400，并携带可读 `message`、`code`、`retryable=false`。
- `backend/app/services/audiobook/tts_engine.py`：
  - 兼容导出 `TTSUserInputError`，保持旧导入路径可用。

### 手动修复方式

- 对已经保存但 `sample_text` 不匹配的 StepAudio Clone 音色，删除后重新录音或上传。
- 保存时“参考音频逐字内容”必须与录音/上传音频中的实际口播逐字一致。
- 例如参考音频实际说的是“费尽心血，费尽金钱，费尽我们的时间……”，就不能填写“当你真的喜欢一个人的时候就容易说傻话办蠢事。”。
- 重新保存后再试听；若仍失败，优先对照错误中的 `asr_result` 和本地填写内容。
- 若日志中的 `user_text` 仍显示默认试听句，说明 provider payload 字段映射回归，需要检查 `_build_stepaudio_voice_preview_payload()`。

### 验证记录

- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" -q`：10 passed。
- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_project_audio_runtime.py" -q`：83 passed。
- `npm run test -- "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts"`：3 files / 27 tests passed。
- `npm run type-check`：通过。

## 本次落地记录：StepAudio Voice Clone 预试听后确认保存

更新时间：2026-06-25

### 问题定位

- StepAudio 官方资料标注语音复刻/生成按音色计费，正式复刻成功可能产生 9.9 元/音色费用。
- 原工作台是单步“保存音色”，容易在用户尚未听过复刻效果前就保存可复用音色资产，不适合带付费风险的声音克隆流程。

### 已完成

- `backend/app/api/v1/audiobook_api/routes_tts.py`：
  - 新增 `POST /api/v1/audiobook/tts/voices/stepaudio/clone-assets/preview`。
  - 预试听接口上传参考音频生成或复用 `file_id`，调用 StepAudio `/audio/voices/preview` 返回试听音频。
  - 预试听接口只返回 `audio_data_base64`、`audio_mime_type`、`file_id`、`sample_text` 等信息，不写入本地音色资产。
  - 保存接口继续写入本地 StepAudio 参考音色资产，但当前前端只会在预试听成功后调用，并复用预试听返回的 `file_id`。
  - 读取上传文件后先校验 mp3/wav MIME，再校验 `sample_text`，让用户优先看到最直接的格式错误。
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`：
  - 真实 StepAudio `/audio/voices/preview` 成功响应会返回 JSON 字段 `sample_audio`，已将其纳入音频解析候选，兼容裸 base64、data URL 和 URL。
  - 保留对 `audio`、`data`、`output` 等既有响应字段的兼容。
- `frontend/src/services/api.ts`：
  - 新增 `previewStepAudioVoiceCloneAssetFromFile()`，对接 `/clone-assets/preview`，返回试听音频 base64 与 `file_id`。
- `frontend/src/pages/audiobook/StepAudioVoiceCloneWorkbench.tsx`：
  - 单步“保存音色”改为“预试听”与“确认保存”两步。
  - 预试听成功后展示内置 audio 播放器，并回填 `file_id`。
  - 修改参考音频、逐字内容或 `file_id` 时会清除旧预试听结果，避免用过期试听结果确认保存。
  - “确认保存”默认禁用，只有预试听成功且填写音色名称后才可点击。
  - 增加 9.9 元/音色付费风险提示，明确“先预试听，再确认保存”。

### 验证记录

- `npm run test -- "src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts"`：1 file / 7 tests passed。
- `npm run test -- "src/pages/audiobook/__tests__/projectAudioConfigUtils.test.ts" "src/pages/audiobook/__tests__/stepAudioVoiceAssetSource.test.ts" "src/pages/audiobook/__tests__/ttsModels.test.ts"`：3 files / 28 tests passed。
- `npm run type-check`：通过。
- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q`：49 passed。
- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" -q`：50 passed。
- `python -m pytest "backend/tests/test_stepaudio_voice_assets.py" "backend/tests/test_audiobook_tts_provider_payloads.py" "backend/tests/test_audiobook_tts_model_ids.py" "backend/tests/test_project_audio_runtime.py" -q`：84 passed。

### 后续待办

- 浏览器手动验证 StepAudio Voice Clone 两阶段流程：
  - 上传/录音参考音频。
  - 填写与参考音频完全一致的逐字内容。
  - 点击“预试听”后能播放试听音频并回填 `file_id`。
  - 点击“确认保存”后音色进入列表，列表试听按钮可用。
- 若 StepFun 返回 `CER_NOT_PASS`，以错误中的 `asr_result` 为准修正输入框里的参考音频逐字内容；例如日志中 `asr_result` 为“当你真的喜欢一个人的时候，就喜欢说傻话办蠢事。”时，输入框不能填写“时间会缓和所有的悲伤……感到满足”。
- 继续确认 StepFun 是否存在“正式创建持久音色资产”的单独接口；若官方接口明确会收费，需要把“确认保存”改成更明确的二次付费确认弹窗。
