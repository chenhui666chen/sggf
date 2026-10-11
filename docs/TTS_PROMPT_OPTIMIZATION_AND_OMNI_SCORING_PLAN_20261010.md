# TTS / Audiogen 提示词差异化优化 + 四模型自动化音频评分方案

> 平台：耳畔星河（novel_writing_agent）
> 状态：**部分已执行，其余仍为待批准方案**。2026-10-10 已就 `qwen-audio-3.1-tts-next` 与四模型评分器做过真实调用实验（生成 29 段、约 105 次评分调用），结论与提示词写法见 `docs/QWEN_AUDIO_TTS_NEXT_PROMPT_GUIDE_20261010.md`，该模型线已收口；本文剩余部分（朗读 TTS 增量优化、全量 A/B、评分层接入）仍是方案，未改动生产配置，实施与真实调用需逐阶段单独批准。
> 关联：`docs/AUDIOBOOK_TTS_PROMPT_OPTIMIZATION_GUIDE.md`（朗读 TTS 现有优化系统 G1–G7）、`docs/QWEN_AUDIO_TTS_NEXT_PROMPT_GUIDE_20261010.md`（**qwen-audio-3.1-tts-next 实测提示词写法与人工裁定结论，该模型已收口不再实验**）、`docs/AUDIO_GENERATION_MODEL_COMPARISON_20261010.md`（qwen-next vs flash vs seed 对比）、`MULTI_MODEL_REVIEW_GUIDE.md`（多模型评审范式）
> 遵循：`.agent/skills/backend-dev-guidelines`、`.agent/skills/test-driven-development`、`.agent/skills/doc-coauthoring`

---

## 0. 已确认的决策边界

| 决策点 | 用户裁定 |
|---|---|
| 评分模型 | **4 个全要，含接入 qwen3.8-omni-flash**：qwen3.5-omni-flash、qwen3.5-omni-plus、qwen3.8-omni-flash（需先接入）、doubao-seed-2-1-lite |
| 被测生成模型范围 | **全部 10 个朗读 TTS + qwen-audio-3.1-tts-next** 都真实测；seed-audio-1.0 **只调研优化、不真实测** |
| 评分目的 | **优化前 vs 优化后对照**（同文本/同音色，只有提示词不同），验证提示词优化是否真的提升 |
| 付费授权 | **先出方案与成本估算再定**——本轮不跑真实 API |

---

## 1. 现状取证结论（代码 + 配置实证）

### 1.1 三类"音频模型"不能混为一谈

| 类别 | 模型 | 提示词形态 | 现有优化程度 |
|---|---|---|---|
| 朗读 TTS（有声书正文） | qwen3-tts-instruct-flash、qwen-audio-3.1-tts-flash、cosyvoice-v3.5-plus、minimax-speech-2.8-hd/turbo、mimo-v2.5-tts(×3)、stepaudio-3-tts、seed-tts-2.0-expressive | instructions / instruction / messages / context_texts / inline 标签 | **已有成熟系统**：`tts_delivery_plan → tts_style_control → tts_prompt_strategy → build_provider_prompt_snapshot`，G1–G7 差距清单大部分已落地 |
| Audiogen（整段音频生成） | qwen-audio-3.1-tts-next | `input.text_prompt`（含人声/音效/环境/配乐一体） | **裸透传，无模板层** |
| Audiogen（音效/场景） | seed-audio-1.0 | `text_prompt` + `references[speaker]` | 场景引擎有确定性编译器 `scene_engine/prompt_compiler.py`；资产工作台音效分支裸透传 |

### 1.2 提示词注入点已定位

- **朗读 TTS**：改 `tts_prompt_strategy.py` / `tts_style_control.py` / `tts_model_ids.py`（能力矩阵）即可全链路生效，最终 payload 在 `tts_engine_pkg/_aliyun_mixin.py`、`_minimax_mixin.py` 的各 `_build_*_payload`。
- **音效（qwen-next / seed-audio 共用）**：`backend/app/api/v1/asset_studio_api/routes_audio.py:438-444` 裸透传 `adapter.generate(prompt=cleaned_prompt)`，两模型走同一段代码——这是加"分模型提示词模板"的最干净注入点，但两模型语义不同必须分开处理（qwen-next 无时长入参、无 speaker 音色、有 rate/volume/seed 白名单；seed 只能靠文本"时长约 N 秒"控时长）。

### 1.3 "之前的人工评分"已定位

- `backend/app/services/audiobook/seed_scene_blind_review.py`（`SeedSceneBlindReviewService`）：盲测，人工 1–5 分 + flags，含 answer_key/reveal 机制。
- G7 质量回写：`prompt_audio_review` 的 `manual_review_fields`（score / tag_parse_success / text_contamination）目前由人工填。
- `backend/app/scripts/generate_prompt_strategy_acceptance_samples.py`：现成"真实合成落盘 + ASR 标签残留自动检测 + review_sheet.md 人工分 + index.html 试听"三件套 harness——**可直接平移复用**。

### 1.4 四模型评分的两个硬缺口（本方案最大工作量）

1. **qwen3.8-omni-flash 未接入**：`config/` 全量检索无此 ID；只有 qwen3.5-omni-flash（音频理解已验证）、qwen3.5-omni-plus（音频理解标注 `pending-runtime-validation`）。上游真实存在（阿里 2026-09-18 发布，全模态、1M 上下文、输入 0.8 元/百万 tokens、免费 100 万 tokens）。
2. **omni 音频评分只有"合同"没有"真实调用实现"**：`scene_quality/qwen_omni_reviewer.py` 定义了十维度 JSON 评审合同，但 `omni_client.review_audio(prompt, audio_path, model)` 全仓只有测试里的 `FakeOmniClient`，生产实现缺失且门控默认关。`adapters/dashscope/chat.py` 的 omni adapter 是纯文本（无 analyze_audio）；`adapters/volcengine/chat.py` 的 doubao-seed-2-1-lite 是纯文本字符串 content（`DISABLE_THINKING=True`、只申请 200 tokens），**不支持音频输入**，尽管档案卡声明 audio_understanding native。
   - 可复用真实范式：`prompt_audio_asr_provider.py` 的 `FunAsrFlashPromptAudioAsrProvider`——base64 → `input_audio` → dashscope `multimodal-generation/generation` 端点。

---

## 2. 目标与范围

1. **调研**：优先从各模型官方文档取证，产出"每个模型吃什么提示词、擅长什么、有什么坑"的证据表（含 URL + verified 日期）。
2. **优化**：按模型特性差异化改造提示词生成，使系统充分发挥各模型优势（朗读 TTS 补 G1–G7 残留 + 官方新特性；qwen-next 新建模板层；seed-audio 只出优化建议不测）。
3. **真实测试**：10 个朗读 TTS + qwen-next 跑"优化前 vs 优化后"对照生成。
4. **四模型评分**：新建统一音频评分层，4 个模型对每段音频盲评打分。
5. **元评估**：检验 4 个模型的评分能力（相互一致性、与人工锚点相关性、自洽性、缺陷检出力）。

**不在本轮范围**：seed-audio-1.0 真实调用；改前端 UI（除非评分结果需要展示）；把评分层默认接进生产章节链路（保持影子/离线，避免阻断与账单影响）。

---

## 3. 分模型提示词优化策略

### 3.1 官方文档取证清单（执行第一步，read-only）

按 `model-version-sources` 记忆的权威入口逐个取证（阿里/火山部分页面是 SPA，须用 browser-use 抓 `document.body.innerText`，不能只靠 WebFetch）：

| 模型 | 官方取证入口 | 取证重点 |
|---|---|---|
| qwen3-tts-instruct-flash / qwen-audio-3.1-tts-flash | help.aliyun.com/zh/model-studio/tts-model、qwen-tts API 参考 | instructions 写法、optimize_instructions、语言/方言、音色集 |
| cosyvoice-v3.5-plus | help.aliyun.com/zh/model-studio/cosyvoice（instruct 指令） | 7 类 emotion 枚举、instruction 短 cue、pause 参数上限 |
| minimax-speech-2.8-hd/turbo | platform.minimaxi.com/docs/guides/speech-t2a-websocket | basic 参数边界、是否支持 pronunciation/多音字、情绪字段 |
| mimo-v2.5-tts(×3) | mimo.mi.com/docs/zh-CN | director/audio-tags/voice-design 三模式标签语法、复合情绪 |
| stepaudio-3-tts | platform.stepfun.com/docs/zh/api-reference/audio/create-audio | 全局 instruction + 圆括号 inline 语法、字上限（已核实：instruction ≤500、单次输入 ≤1000；旧档 200 是 2.5 代限制） |
| seed-tts-2.0-expressive | docs.volcengine.com/docs/DoubaoVoice/model-list | context_texts Query-Response、use_tag_parser 标签集 |
| qwen-audio-3.1-tts-next | help.aliyun.com/zh/model-studio（Audiogen/qwen-audio） | text_prompt 写法、@voiceN 引用、时长/播客语义、rate/volume/seed |
| seed-audio-1.0 | docs.volcengine.com/docs/DoubaoVoice（Seed Audio） | text_prompt 结构、speaker 参考、时长只能写文本 |
| 评分侧 omni | help.aliyun.com/zh/model-studio/qwen-omni、qwen3-8-omni-flash-realtime | 音频输入格式/时长/采样率、思考开关、结构化输出能力 |

产出：`docs/TTS_PROMPT_EVIDENCE_<date>.md` 证据表（每条带 source URL + verified_at + confidence），作为优化改动的取证依据（遵循"踩坑经验回写模型接入指导文档"偏好）。

### 3.2 朗读 TTS 优化（基于现有系统增量，不重写）

以官方证据补齐 G1–G7 残留与新增能力，重点：

- **G2 情绪归一**：核对各模型官方 emotion 枚举，更新 `tts_model_ids.py` 的 `supported_emotions`/`emotion_aliases`。
- **G3 停顿**：cosyvoice pause 参数、stepaudio 圆括号已落地；核对官方上限与语义，补齐 seed-tts/qwen 的停顿表达。
- **G1 预算压缩**：按官方 instruction 上限（cosyvoice 100 / stepaudio 200 / qwen 600）复核压缩优先级。
- **模型专属新特性**：如 qwen 的 optimize_instructions、minimax 多音字、mimo 复合情绪等，按证据决定是否启用。
- 每个改动配 `tts_prompt_strategy` / `tts_style_control` 单测（TDD 先写测试），并跑现有 TTS 回归套件保证非目标模型不受影响。

### 3.3 qwen-audio-3.1-tts-next 优化（新建模板层）

> **2026-10-10 更新：本模型的提示词实验已收口**，写法与人工裁定结论落在 `docs/QWEN_AUDIO_TTS_NEXT_PROMPT_GUIDE_20261010.md`，不再为该模型安排新实验。下列"模板层"仍属**未实施的生产改动**，需要时另行批准。

- 在 `routes_audio.py` sound-effect 分支（或下沉到 `asset_studio_model_catalog` / 新 helper）为 qwen-next 增加**专属 text_prompt 模板**：把用户的 mood/tempo/duration 表单字段与音效描述，按官方 text_prompt 写法结构化拼装（声源/材质/动作/强弱/空间感 + 时长语义写进文本），并程序化利用 rate/volume/seed 白名单参数。
- 与 seed-audio 分支解耦（当前共用裸透传），避免"一套提示词喂两个语义不同的模型"。
- 因是 Audiogen 非朗读，评分维度不同（见 4.2）。

### 3.4 seed-audio-1.0（只调研优化，不真实测）

- 产出提示词优化**建议**（基于官方文档 + 现有 `prompt_compiler.py`/`doubao_sfx_generator.build_text_prompt` 的"时长约 N 秒"模式），落到证据表与优化指南，不跑真实 API、不改会触发真实调用的路径。
- 若发现现有场景引擎编译器有可改进处，只提改动建议，待后续单独批准。

---

## 4. 四模型自动化音频评分框架

### 4.1 评分模型接入补齐（前置工作）

| 模型 | 缺口 | 补齐动作 |
|---|---|---|
| qwen3.5-omni-flash | 无生产 review_audio 实现 | 复用 dashscope multimodal-generation + base64 input_audio，建 `OmniAudioScorer` |
| qwen3.5-omni-plus | 音频理解 pending-runtime-validation | 真实探测确认音频输入可用 + 上限 |
| qwen3.8-omni-flash | **完全未接入** | 建 config 档案卡（0.8/2.7 元、免费 100 万 tokens、1M 上下文）+ adapter 音频输入路径 + 真实探测（按"换代后档案上限与思考开关必须重测"跑 `probe_llm_output_limits.py`）+ 注册 model_hub/catalog |
| doubao-seed-2-1-lite | adapter 纯文本、不支持音频输入、思考默认开 | 新开 Ark 多模态音频 content 路径 + 评分时给足 max_tokens（勿沿用 200）+ 思考开关处理 |

统一抽象：新增 `backend/app/services/audiobook/scene_quality/omni_audio_scorer.py`（或独立评测模块），实现鸭子合同 `async score_audio(*, prompt, audio_path, model) -> ScorerVerdict`，四模型各自 provider 适配；离线/影子运行，**不接进生产章节账单链路**。

### 4.2 评分维度（rubric）

**朗读 TTS**（每维 1–5 分 + 证据 + 置信度）：
- emotion_match 情绪贴合、prosody_pause 节奏停顿自然度、fidelity 台词保真（结合 ASR WER）、contamination 正文污染/标签泄漏（结合 ASR）、voice_identity 音色一致性、overall_naturalness 整体自然度（类 MOS）。

**qwen-audio-3.1-tts-next（Audiogen）**：
- prompt_adherence 提示词遵循、sound_event 声音事件贴合、speaker_separation 多说话人区分、mix_balance 混音平衡、duration_fit 时长符合、overall_quality 整体质量。

评分器输出严格 JSON（复用 `qwen_omni_reviewer.py` 的 schema 校验思路），非法输出 recorded_error 不计入统计。

### 4.3 优化前 vs 优化后对照实验设计

- **测试语料**：固定 6–8 段脚本，覆盖各模型擅长维度（narration/dialogue/monologue × 情绪 × 停顿 × 语势变化）。
- **对照**：同一 `voice_id`、同一正文，A=优化前提示词产物（今天的 `build_provider_prompt_snapshot`），B=优化后产物。**只有提示词不同**，隔离音色/文本变量。
- **盲评**：4 模型对 A/B 音频匿名打分（复用 blind_review 的匿名/乱序/answer_key 机制），互不可见。
- **样本量**：11 模型 × 7 段 × 2 变体 ≈ **154 段生成音频**；每段 4 模型评分 ≈ **616 次评分调用**。
- **判定**：B 相对 A 的分数提升是否显著（配对比较），分模型给出"优化有效/无效/回退"结论。

### 4.4 评分能力元评估（"测试这四个模型的评分能力"）

1. **一致性**：4 模型两两相关 / 排名一致性 / Krippendorff alpha。
2. **与人工锚点相关性**：复用历史人工盲测分，或请你提供 ~15–20 段人工锚点分，算 Spearman 相关。
3. **自洽性**：同一段音频重复评分 2–3 次，看方差。
4. **缺陷检出力（spike-in 对照）**：故意构造已知缺陷样本（标签泄漏进正文、情绪明显错配、台词漏读），看 4 模型能否稳定识别——这是"评分能力"最硬的检验。
5. 产出：4 模型评分能力对比报告 + 推荐"主评/复核"分工（参考 MULTI_MODEL_REVIEW 的主审范式）。

---

## 5. 实施阶段（每阶段独立验证，逐步放量）

- **阶段 0 取证（read-only，零成本）**：官方文档证据表；预检 voice 资产是否已存在（决定一次性费用）。
- **阶段 1 提示词优化**：朗读 TTS 增量改造 + qwen-next 模板层 + seed-audio 建议；全部配单测 + 回归。
- **阶段 2 评分层接入**：qwen3.8-omni-flash 接入 + 4 模型 OmniAudioScorer + 真实探测（用免费额度/极小样本）。
- **阶段 3 小样本联调**：每模型 1–2 段跑通"生成→ASR→4 模型评分"全链路，校准 schema 与成本。
- **阶段 4 全量对照实验**：154 段生成 + 616 次评分 + 元评估（含 spike-in 与人工锚点）。
- **阶段 5 结论回写**：优化效果报告 + 4 模型评分能力报告 + 证据/踩坑回写文档；按"任务完成后自动清理"清临时产物。

阶段 2–4 涉及真实付费调用，**每阶段开跑前单独报预计花费并等确认**。

---

## 6. 成本估算（按文件实证单价 + 官方价，标注假设）

### 6.1  recurring（每次全量对照实验）

| 项 | 估算 | 依据 |
|---|---|---|
| 朗读 TTS 生成（~140 段，每段~150 字） | **≈ 2–3 元** | qwen3-tts 0.8/万字、cosyvoice 1.5、minimax 2.0/3.5、stepaudio 2.5、seed-tts 3.0 元/万字；**mimo 三档限免 0 元** |
| qwen-audio-3.1-tts-next 生成（~14 段，~15s/段） | **≈ 0.6 元** | 0.18 元/分钟 |
| ASR 保真/污染比对（~154 段） | **≈ 0.7 元** | fun-asr-flash 0.00022 元/秒 |
| 4 模型评分（~616 次，音频+文本输入） | **≈ 3–10 元** | qwen3.8-omni-flash 0.8 元/百万 tokens（且免费 100 万 tokens 可覆盖大部分）；doubao 音频输入 12 元/百万 tokens 为主要项；qwen3.5-omni 两档档案标 verification_required 需实时核价 |
| **recurring 合计** | **≈ 6–15 元 / 轮** | 若 qwen3.8 走免费额度则更低 |

### 6.2 一次性费用（**最大不确定项，需预检**）

| 项 | 费用 | 说明 |
|---|---|---|
| seed-tts-2.0-expressive 后付费槽位**首次**正式使用 | **138 元** | 若项目已激活该槽位则为 0 |
| stepaudio-3-tts 正式复刻 | 9.9 元 | 若已有复刻音色则为 0 |
| minimax 克隆首次正式使用 | 9.9 元 | 若已有克隆音色则为 0 |
| qwen3.8-omni-flash 接入探测 | ≈ 0 元 | 100 万 tokens 免费额度覆盖 |

> **关键预检**：阶段 0 需查项目 voice 资产库/账单，确认 cosyvoice/minimax/stepaudio/seed-tts 的音色与槽位是否已存在。若都已存在，一次性费用 ≈ 0，全量一轮 **总成本 ≈ 6–15 元**；若 seed-tts 槽位需首次激活，则 **+138 元**。

### 6.3 建议放量策略

先跑"阶段 3 小样本联调"（每模型 1–2 段，成本 < 2 元）验证链路与真实单价，再据实调整全量预算。

---

## 7. 风险与护栏

- **成本控制**：所有真实调用走显式付费门控 env（沿用 `AUDIOBOOK_TTS_PROVIDER_SMOKE=1` / `RUN_DOUBAO_SEED_SCENE_REAL_API=1` 范式）、`max_retries=0`、小样本先行、ASR 预算上限（0.2 元/场景）。
- **key 依赖**：根 `.env` 缺 `DOUBAO_API_KEY` 与 seed-tts 专用 key，跑豆包/Seed-TTS 需依赖 `backend/.env`（预检确认）。
- **qwen3.5-omni-plus 音频能力未验证**：先真实探测，不可用则记 accepted-gap 并从评分组降级说明。
- **doubao 思考默认开**：评分请求须显式关思考或给足 max_tokens，避免 content 被思维链吃空（已知坑）。
- **不污染生产**：评分层离线/影子运行，不接进章节账单与阻断链路；不改固定音色身份策略（`VOICE_IDENTITY_POLICY_VERSION`）。
- **档案上限重测**：接入 qwen3.8-omni-flash 后必须跑 `probe_llm_output_limits.py` + `test_llm_output_limit_fact_table.py`（第四/五道门禁）。
- **模型限流**：qwen-next 供应商限流 3 次/秒，批量生成需排队处理 429。

---

## 8. 交付物

1. `docs/TTS_PROMPT_EVIDENCE_<date>.md`——官方文档证据表。
2. 提示词优化改动（朗读 TTS 增量 + qwen-next 模板层 + seed-audio 建议）+ 配套单测/回归。
3. `OmniAudioScorer` 四模型评分层 + qwen3.8-omni-flash 接入（档案卡/adapter/探测）。
4. 对照实验产物：音频样本包 + 评分数据 + `index.html` 试听页。
5. 结论报告：优化效果（A/B）+ 4 模型评分能力元评估。

---

## 9. 待确认 / 预检项（开跑前）

1. 一次性费用预检：voice 资产/槽位是否已存在（决定 +0 还是 +138 元）。
2. 人工锚点：元评估是否复用历史盲测分，还是你提供 ~15–20 段人工分？
3. 测试语料：用现有章节片段，还是我拟一组覆盖各维度的标准语料？
4. 评分层归属：作为离线评测脚本（`backend/app/scripts/`）还是接入现有影子评审框架（`scene_quality/`）？
5. qwen3.5-omni 两档实时核价（档案标 verification_required）。

---

_创建：2026-10-10。本文档为待批准方案，实施须遵循 backend-dev-guidelines 与 TDD 规范，真实付费调用前逐阶段确认。_
