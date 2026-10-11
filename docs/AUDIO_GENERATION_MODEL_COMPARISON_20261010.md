# 百炼音频生成模型对比：qwen3-tts / qwen-audio-3.1-tts-flash / qwen-audio-3.1-tts-next

生成日期：2026-10-10。数据来源：2026-10-10 对 `qwen-audio-3.1-tts-next` 的真实调用探测（含 5 秒音效档位实际返回 3.96 秒那一次端到端调用）、`qwen-audio-3.1-tts-flash` 的接入探测（见 `MODEL_INTEGRATION_REFERENCE.md` §11.7）、以及 `config/models.yaml` 档案卡。价格与限流是刊例/派生口径，换模型版本后必须重测，不能沿用。

## 1. 一句话结论

三个模型名字相近，实际是**两条完全不同的产品线**：

- `qwen3-tts-instruct-flash` 与 `qwen-audio-3.1-tts-flash` 是 **TTS（带音色朗读文本）**，走有声书 `TTSEngine` 直连；
- `qwen-audio-3.1-tts-next` 是 **Audiogen（按提示词生成音频，不朗读指定文本、不指定音色）**，走适配器注册表，落在资产工作台音效链路。

`next` 与两个 flash **不是换代关系**，不能拿来替换 `qwen3-tts-instruct-flash` 做有声书正文朗读；反过来也不要把 flash 系列的音色 ID 体系期待在 next 上生效。

## 2. 定位与链路归属

| | qwen3-tts-instruct-flash | qwen-audio-3.1-tts-flash | qwen-audio-3.1-tts-next |
| --- | --- | --- | --- |
| 档案定位 | 有声书默认朗读模型（`DEFAULT_AUDIOBOOK_TTS_MODEL` 未动） | 有声书第 2 位朗读模型，指令可控 | 提示词音频生成（音效/环境声/短播客） |
| `modality` | `text_to_speech` | `text_to_speech` | `text_to_audio` |
| 调用入口 | `TTSEngine` → `_aliyun_mixin` | `TTSEngine` → `_synthesize_qwen_audio_31` | `adapters/dashscope/audio_generation.py`（`QwenAudio31TtsNextAdapter`） |
| 项目内使用链路 | 有声书章节/片段 | 有声书章节/片段 | 资产工作台 `audio_sound_effect` 分组（与 `seed-audio-1.0` 并存） |
| 是否适配器注册表可见 | 否（NON_ADAPTER） | 否（NON_ADAPTER） | 是（`adapter=yes`） |

## 3. 端点与请求体形态

| | qwen3-tts-instruct-flash | qwen-audio-3.1-tts-flash | qwen-audio-3.1-tts-next |
| --- | --- | --- | --- |
| 端点 | `/api/v1/services/aigc/multimodal-generation/generation` | `/api/v1/services/audio/tts/SpeechSynthesizer` | `/api/v1/services/audio/tts/SpeechSynthesizer`（与 flash 同 URL） |
| 正文/提示词字段 | 顶层 `text` | `input.text` | `input.text_prompt` |
| 音色字段 | 顶层 `voice` / `language_type` | `input.voice` | **无**（传 `voice` 服务端忽略并返回 200） |
| 指令字段 | 顶层 `instructions` + `optimize_instructions` | `input.instruction` | 无独立指令字段，风格写在提示词里 |
| 参考音频 | 不支持 | 不支持 | `input.references[]`，≤3 条 |
| 输出参数 | — | — | `format` / `sample_rate` / `channels` / `volume` / `rate` / `seed` / `enable_cbr` / `bit_rate` / `quality` / `enable_aigc_tag` |
| 鉴权 | `DASHSCOPE_API_KEY` Bearer | 同 | 同，legacy 域名直接可用，**不需要 WorkspaceId** |

端点相同是最容易误判的地方：`next` 复用 flash 的 URL 与鉴权，但请求体语义完全不同，把 flash 的请求体发给 `next` 会得到一次"成功"但内容错误的生成。

## 4. 音色 / 参考音频机制

| | qwen3-tts-instruct-flash | qwen-audio-3.1-tts-flash | qwen-audio-3.1-tts-next |
| --- | --- | --- | --- |
| 机制 | 官方预置音色 + 音色复刻 | 官方预置音色（`_v3.1` 后缀） | 提示词描述 + 参考音频 |
| 音色表 | `voice_catalog.py`（qwen3 分支） | `shared/qwen_audio_3_1_tts_voices.json`，逐条实调得 **68** 个可用（官方页标称 69/73 不可信） | 无音色概念 |
| 跨模型兼容 | 与 3.1 音色集不相交 | 传 Qwen3 的 `Cherry` 等 → `400`（code 411） | — |
| 参考音频约束 | — | — | 每条**只能**给 `audio_url` 或 `audio_data` 二选一；≤30s、≤10MB；≤3 条；提示词用 `@voice1`..`@voice3` 按数组顺序引用 |

关键差异：`next` 的参考音频契约与有声书/场景链路的 `references=[{"speaker": ...}]` 音色 ID 形态**互斥**，这是 `next` 不并入 `audio_scene` 分组的直接原因——适配器对「有 speaker 且无 audio_url/audio_data」显式抛错。

## 5. 长度、时长与限流

| | qwen3-tts-instruct-flash | qwen-audio-3.1-tts-flash | qwen-audio-3.1-tts-next |
| --- | --- | --- | --- |
| 单次输入上限 | 档案 `max_prompt_length: 20000`；项目侧走 600 字校验 + `QWEN_RENDER_CHUNK_MAX_CHARS=360` 分块 | 实测正文 3000 / 6000 / 10000 字均 200（档案 `max_input_chars: 10000`）；指令写到 4000 字仍 200 且不计入 `input_tokens` | 提示词 **3000 字**（3001 字 → 400） |
| 分块策略 | Qwen 特化分块 | 走默认分块，**不进入** `_is_qwen_tts_model()` | 不适用（非 TTS 链路） |
| 产出时长 | 由文本长度决定 | 由文本长度决定 | **无 duration 入参**，时长由提示词决定：播客 ≤240s、其余 ≤120s |
| 实测延迟 | 档案 `avg_latency_seconds: 4.0` | 档案字段未填（`0.0`），本轮无实测延迟记录 | 实测 16.05s / 17.41s 两次，档案 `20.0` |
| 限流 | — | — | QPM 3（周期 1） |
| 交付方式 | `output.audio` 内联 | `output.audio.url`，约 24 小时有效 | `output.audio.url`，约 24 小时有效（`expires_at`），需下载落盘 |
| 输出格式 | — | — | wav / mp3 / pcm（**opus 不被接受**；参考音频可用 ogg_opus，输出不行） |
| 采样率 / 声道 | — | — | {8000,16000,24000,44100,48000}；channels ∈ {1,2} |
| 语速 / 音量 | — | `rate` 0.5–2.0、`volume` 0–100（越界报文文案错位） | `rate` 0.5–2.0、`volume` 0–100（越界报文**准确点名**，全部 400 InvalidParameter） |

## 6. 计费口径与实测成本

三个模型计价单位互不相同，横向比较必须先归一到同一口径。

| | qwen3-tts-instruct-flash | qwen-audio-3.1-tts-flash | qwen-audio-3.1-tts-next |
| --- | --- | --- | --- |
| 计价单位 | 每万字符 | 每万字符（派生） | 每秒音频（派生） |
| 档案价 | 0.8 元/万字（`public_list_price`） | 0.4 元/万字（`derived_from_token_price`） | 0.003 元/秒 = 0.18 元/分钟（`derived_from_token_price`） |
| token 刊例 | 按字符计费 | 输入 1.5 / 输出 12 元每百万 tokens | 输入 6 / 输出 12 元每百万 tokens |
| 实测换算关系 | `usage.characters` | `usage.characters ≈ 1.93 × len(text)` | `output_tokens = 200 × 音频秒数`；`input_tokens ≈ 152 + 2.1 × 提示词字符数` |
| 派生依据 | — | 长文本约 0.285 元/万字、带 instruction 约 0.42 元/万字 → 取保守 0.4 | 4 秒级音效实付约 0.011 元；本次端到端 3.96s 实付 **0.01093 元** |
| `usage.duration` 含义 | 字符 | 字符 + tokens | **向上取整的计费秒**，不等于真实音频时长 |

与音效链路现有落点 `seed-audio-1.0`（1.0 元/分钟，`public_list_price`）相比，`next` 的派生价约便宜 **5.6 倍**（0.18 vs 1.0 元/分钟）。但内部积分口径当前统一走 env 每秒价 `POINTS_ASSET_STUDIO_SOUND_EFFECT_PER_SECOND_YUAN`（默认 0.04 元/秒），不按模型分档：本次端到端实测冻结 5s = 0.20、按实际 3.96s 结算 = 0.16，供应商侧成本 0.011 元，毛利结构安全。

## 7. 适用链路建议

| 需求 | 该用 | 不该用 |
| --- | --- | --- |
| 有声书正文朗读（指定角色音色） | `qwen3-tts-instruct-flash`（默认）/ `qwen-audio-3.1-tts-flash`（需要长指令与更高输入上限时） | `next`：无音色、不朗读指定文本 |
| 短音效、环境声、无对白声音设计 | `qwen-audio-3.1-tts-next`（成本敏感、可接受时长由提示词决定）/ `seed-audio-1.0`（已验证的默认落点） | 两个 flash：需要指定文本与音色 |
| 需要精确时长档位 | 两者都不满足：`next` 无 duration 入参，`mureka-o1-instrumental` 会忽略 duration 返回整曲 | — |
| 多角色播客/对白音频 | `next`（`references` + `@voice1..3`，≤240s） | flash 系列单次单人 |
| 参考音频驱动的风格模仿 | `next` / `seed-audio-1.0` | flash 系列不支持 |

## 8. 已知坑（详见 `MODEL_INTEGRATION_REFERENCE.md` §11.7 / §11.8）

1. `next` 传 `voice` 返回 200 且静默忽略——**不能依赖上游报错**发现传参错误。
2. `next` 的参考音频必须 `audio_url` / `audio_data` 二选一，带 `speaker` 音色 ID 必须本地显式拒绝。
3. 资产工作台音效路由传来的 `audio_config` 是豆包口径，`pitch_rate` / `speech_rate` / `loudness_rate` / `enable_subtitle` 会被丢弃，适配器把它们写进 `result.metadata["dropped_params"]` 留痕。
4. 结算只认 `output.audio.duration`（真实秒数），不要用 `usage.duration`（计费整秒）。
5. `output_tokens = 200 × 秒数` 是本次实测推导，**模型换代后此比率必须重测**。
6. `adapters/dashscope/*` 与 `adapters/volcengine/*` 都通过 `import *` 汇入命名空间，`DEFAULT_AUDIO_CONFIG` 这类通用名会互相覆盖，新适配器常量必须带模型前缀；注册表 `module_names` 必须列叶子模块而非包名。
