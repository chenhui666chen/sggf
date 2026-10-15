# 立项：qwen-audio-3.1-tts-flash 正文情感标签装配

状态：**已立项，未开工**（2026-10-12 用户批准立项）。
立项依据：`docs/TTS_PROMPT_EVIDENCE_20261010.md` §20–§22（B3 批次：24 次合成 + 10 次 ASR + 本地能量剖面 + 12 次双模型盲评 + 人耳盲听裁定）。
本文自带全部关键约束，可单独粘给下一个窗口执行。

---

## 1. 要解决的问题

生产链路把 3.1 的情绪**只写进 `input.instruction`**，正文 `input.text` 原样透传、零预处理（`_aliyun_mixin.py:2079`）。实测结论是这条通道选错了：

| 写法 | 人耳（打乱盲听） | 时长 vs 基线 |
|---|---|---|
| 正文官方 `[sad]` 逐句（q7） | **最强** | 1.62× |
| 动机式 instruction（q2） | 次之 | 1.21× |
| 三段式【角色】【场景】【指导】instruction（q1） | **与念稿基线并列最弱** | 1.08× |
| 念稿基线（q4） | 同上 | 1.00× |

即：**3.1 上唯一被耳朵确认能改变表演的通道是正文标签，而生产代码没有用它。** 官方词表（控制类 23 个、富语言类 7 个）与作用域原文见证据表 §2。

## 2. 目标 / 非目标

目标：
1. 3.1 出站正文可按句装配**已实测放行的**官方控制类标签，逐句闭合、幂等、可整体关闭。
2. 标签长度进入成本口径（上游按 `characters` 实收，标签算正文），时长预估按净台词口径，两个口径分开且都有测试钉住。
3. 情绪值→官方标签走**白名单映射**，越界值丢弃并记 warning，不发未登记取值。

非目标（另案，勿混入本立项）：
- SSML `<break>` / `<phoneme>` 停顿通道（3.1 官方支持清单内，本轮未测，见证据表 §22.2 红线项）。
- 评分器改造（doubao 假阴性、qwen3.8 假阳性已登记在 §21.2/§22.1，属评测协议另案）。
- 其他引擎的正文标签形状（MiMo 圆括号、stepaudio 圆括号、豆包 `<cot>` 已各自收口，写法红利**不可跨模型移植**）。
- 任何音色复刻类测试（已裁定不开通）。

## 3. 设计

### 3.1 出站形状（已被实测证明的唯一形状）

```text
[sad]我没事。[sad]我真的没事，你们都不用管我。
```
- 半角方括号、标签后紧跟正文、**逐句下达**。**作用域已实测闭合（证据表 §23.2③，2026-10-13）**：同一句台词、只差标签数量，`[sad]` 段首一枚发声量 1.207×、逐句两枚 1.559×，**差 29%** ⇒ 官方那句「直到遇到下一个控制类标签或句子被自动切分」在短句上实际止于句界，"每个片段只写一枚标签"的省字符写法不成立，装配必须逐句下。**2026-10-13 耳裁补充（§23.6⑤）**：段首一枚与逐句两条在耳朵上**同为强档**，差异是表演量级而非"听不听得出来"，所以逐句是**默认档位而非硬红线**——渲染器保留一个"长句/预算紧张时段首一枚"的降级出口即可，不做开关。
- **取值层已实测并过人耳（证据表 §23、§23.5–§23.7，2026-10-13）**：官方 23 个控制类 + 7 个富语言类**逐个**验证均不发音（30/30 `leak=0`），含带空格的英文多词标签（`[like dracula]`、`[deep and loud shouting]`、`[very slowly]`、`[very fast]`）——这类取值"念出英文词"与"放慢表演"在总时长上无法区分，只有逐字转写能分开，所以必须逐取值实测、不能从 `[sad]` 外推。强度档已由耳朵定完（强 18／弱 10／无 1，客观无信号的 `[mischievously]`／`[empathetic]`／`[snorts]` 全部落弱档，已进暂缓），**剩最后一类未闭合问题是"近义取值名字能否被耳朵区分"**，见 §3.2 末尾。

### 3.2 白名单与映射

新增一张 3.1 专用映射，输入是我方现有情绪/演绎值（中文 `emotion_primary` / `emotion_mix` / `micro_tags` / `performance_notes`），输出是官方英文标签：

- **2026-10-13 人耳已签字，白名单按 §23.7 四档定档**（32 条 tag-blind 强度盲评，产物 `backend/data/tts_debug/b4_qwen31_tag_scan/listen_tag_scan.html`，强 18／弱 10／无 1）：
  - **第一档·情绪（13 值，进映射主表、逐句下标签）**：`sad`、`amazed`、`angry`、`crying`、`excited`、`panicked`、`sarcastic`、`scornful`、`trembling`、`tired`、`bored`、`shouting`、`deep and loud shouting`。`sad` 有两轮耳裁（§22 的 q7 与本轮的 q7/x01），其余 12 值一轮。
  - **第二档·富语言事件（6 值，只在句界/段首插一枚，不逐句）**：`gasp`、`sighing`、`clears throat`、`giggles`、`laughing`、`cough`。逐句会连发三次、无法判读落点（§23.2⑤）。
  - **第三档·物理效果（4 值，不进情绪表，只按节奏/音量显式调用）**：`very fast`、`very slowly`、`whispers`、`asmr`。这四条耳朵判弱/无、客观却有明确方向（0.79×／1.88×／Δ−9.5 dB／Δ−10.8 dB），**"变轻"和"变快"是独立需求，不能按情绪强度淘汰**；后两条会让成品人声低 9–10 dB，混音侧响度兜底尚未核实。
  - **暂缓（7 值，不放行）**：`curious`、`like dracula`、`mischievously`、`empathetic`、`reluctantly`、`serious`、`snorts`。
  - 仍**不能只靠"官方词表里有"放行**：新增取值必须补 B4 形状上的耳裁档位并把批次号写进映射表注释。依据：能力声明口径"这个 true 的证据在哪条实测里"答不出就降级（见记忆 [tts-capability-declaration-split]）。
- **一处待裁定会影响映射表结构**：第一档里七对近义取值（`bored`/`tired`、`sarcastic`/`scornful`、`trembling`/`crying`、`excited`/`amazed`、`shouting`/`deep and loud shouting`、`angry`/`panicked`、`giggles`/`laughing`）本轮只判了强度、没验名字。若耳朵分不出同一对的两条，映射层必须**把它们并进同一个语义桶、只放行一个取值**，否则中文情绪词到标签的映射名实不符。这一轮是页内点选的 forced-choice 对照，本地零成本，见 §23.7 末尾。
- 越界值（不在官方 23＋7 词表内的中文词、含 `<>[]` 的串）一律剔除，参照豆包 `_fit_doubao_cot_tag_text:571-587` 的禁字符处理。

### 3.3 装配函数与幂等

在 `tts_style_control.py` 内新增，形状完全照抄豆包 Cot 的既有模式（不发明新机制）：

| 新函数 | 参照实现 | 职责 |
|---|---|---|
| `_render_qwen31_control_tag` | `_render_doubao_voice_label_prefix:559-568` | 把白名单值渲染成 `[tag]` 前缀 |
| `_fit_qwen31_control_tags` | `_fit_doubao_cot_tag_text:571-587` | 取值过滤、禁字符剔除、长度装填 |
| `_wrap_qwen31_control_sentences` | `_wrap_doubao_cot_sentences:919-938` | 按 `_SENTENCE_BOUNDARY:59` 逐句下标签；正文已含 `[tag]` 时原样返回（幂等） |

接入点：`prepare_text_for_style_control:907-916` 增加 3.1 分支（当前 3.1 **完全不经此函数**，证据 `_aliyun_mixin.py:2071-2083` 无调用），并在 `_build_qwen_audio_31_http_payload:2071-2083` 内把 `input.text` 从"原样透传"改为"经装配后的正文"。WS 路径无 3.1 分支，只有 HTTP 一条出站路径需要改。

### 3.4 开关与默认值

- 开关沿用现有 `style_control_method` 取值体系（读取处 `tts_style_control.py:663-668`，别名归一 `tts_delivery_plan.py:29-49`），为 3.1 新增一个专用值（建议 `qwen31_control_tags`），不要复用 `audio_tags/tags/label/labels/voice_labels` —— 那五个是豆包 `[a，b]` 前缀的触发集，而该形状在 3.1 上会被朗读出口（证据表 §20.2 判定 1）。
- **默认关**。生产默认开启需要一次真实章节级别的验收（见 §6 切片 5），且必须过用户耳朵。
- 注意：`style_control_method` 目前**没有正式枚举定义**，生产链路也无赋值点（仅预览工具 `tts_test_unit.py:129,207` 会写），客户端快照里该键被黑名单剥离（`segment_synthesis_contract.py:87,118`）。要让运维能打开它，得先补枚举定义与快照放行——这是本立项最容易低估的一块，见 §5 风险 R3。

### 3.5 与 instruction 的分工（待 q8 裁定）

- 定序：标签为主、instruction 只保留动机式（q2 形状，耳裁次优有效）。
- 三段式（q1）在 3.1 上与念稿并列，属**无效投入**，装配时应避免把三段式模板塞进 3.1 的 instruction。
- 唯一未闭合的实测项：**q8（instruction＋标签叠加）没有耳裁定序**（本地已有音频，补听 1 条零成本）。叠加是否作为默认形态，等这条裁定；未裁定前按"标签下发、instruction 保持现状不动"实现，两者不互相抑制。

## 4. 落点清单（改造面，均已核实存在）

出站与装配：
- `backend/app/services/audiobook/tts_engine_pkg/_aliyun_mixin.py`：`_build_qwen_audio_31_instruction:2057-2069`、`_build_qwen_audio_31_http_payload:2071-2083`（`input.text` 直传在 2079）、HTTP 调用 `2085-2166`。
- `backend/app/services/audiobook/tts_style_control.py`：新增三函数（§3.3）、`prepare_text_for_style_control:907-916` 加分支、`_SENTENCE_BOUNDARY:59`、参照实现 `559-587 / 919-938`。
- 标签值来源：`_build_inline_tag_strategy:514-548`（← `voice_params.style_tags/inline_audio_tags`）、`delivery_plan_style_tags:246-253`、`delivery_plan_inline_tags:256-260`、`_infer_micro_tags:320-334`（关键词映射自 `performance_notes`）。

成本与时长口径（**两处口径相反，必须分开处理**）：
- 成本按**含标签**的正文长度：`_base.py:384,415,419,423` 的 `add_segment(len(effective_text))` → `_constants.py:156-171`（166 行成本 = chars/10000 × 单价）；`routes_tts.py:239-257`（242 行 `len(text)`）→ `:1070` fixed_fee；`billing_snapshot_builder.py:42,89,175-188,264-272`（unit=char）。
- 时长预估按**净台词**（剥标签）：`duration_estimator.py:14-15` 用 `len(text)/4.5` 估秒，标签会虚增时长。
- 上游 `usage.characters` **目前没有任何代码读取**（`_aliyun_mixin.py:2144-2166` 只解析 `output.audio`）→ 实收字符数与本地预估无法对账，这条缺口要一并收口（切片 4）。

档案与前端：
- `config/models.yaml` 3.1 卡片 447-536：能力 462-475、`constraints` 483-486、`cost_profile` 490-499（497 行已记 `usage.characters ≈ 1.93 × 正文`）、`integration_notes` 514-522（518 行写死 `instruction_budget=1200`）。
- `backend/app/services/audiobook/tts_model_ids.py:122-132`（128 行 budget 1200）、`:273-289`（277 行 `price_per_10k: 0.4`）。
- `frontend/src/pages/audiobook/ttsModels.ts:137-153`（152 行 `instructionBudget: 1200`）与兜底合并 `337,423-427,753`。

测试（改动会牵动的断言）：
- 必改：`backend/tests/test_audiobook_tts_provider_payloads.py:46`（70 行断言 `input.text == 原文`）、`:212`（227 行长正文原样）、`:231`（241-242）。
- 会自然失败，需按新语义重写而非放宽：`test_audiobook_voice_identity_stability.py:1163,1189`、`test_qwen_tts_voice_compat.py:30,40`。
- 一致性守卫（跨事实源，必须同步）：`test_audiobook_tts_model_ids.py:141-145`、`:1035-1051`、`:1054`、`:1085-1100`、`:1119`；`test_audiobook_prompt_contracts.py:53-128,346,353-375`。

## 5. 风险与未决

- **R1 标签污染是实测红线。** 全角圆括号舞台提示在 3.1 上**会被逐字朗读出口并且复读一遍**（证据表 §20.2）。任何"看起来像标签"的形状（圆括号、未登记取值、含禁字符）都必须在装配层拒绝，而不是交给上游。这条是本项目里唯二有 3/3 复现的失败形状，装配函数的负例测试优先级高于正例。
- **R2 计费长度上升是真实成本。** 标签进正文即进 `characters`，0.4 元/万字的派生价下每条多几十字符看着微不足道，但整章逐句下标签会累积；**逐句已由 §23.2③ 确认为必需**，所以增量是「标签字符数 × 句数」——`[sad]` 一枚 5 字符，`[deep and loud shouting]` 一枚 22 字符，长情绪词在多句片段里成倍放大。`pricing_basis: derived_from_token_price` 且带宽 0.285–0.42，换模型版本即作废。上线前要用真实章节量级重算一次，并把 `usage.characters` 读回来对账（当前无人读）。
- **R3 开关链路比函数本身更贵。** `style_control_method` 无正式枚举、生产无赋值点、快照黑名单剥离（§3.4）。若只做装配函数而不开这条链路，功能等于不存在。
- **R4 场景引擎提示词是第五层事实源。** 剧本 LLM 目前被明文禁止输出标签类字段（`_transform.py:512,516,554,570`）。要让演绎值流到标签映射，得决定是解禁该字段，还是继续由 `performance_notes` 经 `_infer_micro_tags` 关键词映射推断——后者改动面小、可解释性好，建议先走后者。**历史上"改代码没改提示词散文"造成过静默不一致，务必逐层扫。**
- **R5 既有档案不一致（本立项不修，但必须登记）**：`config/models.yaml:486` 写 `instruction_max_chars: 4000`，而代码与前端都是 1200（`tts_model_ids.py:128`、`ttsModels.ts:152`）。跨源一致性守卫测试未覆盖 3.1 这一对。修它属额度口径变更，需单独实测与批准，不与本立项混合。
- **R6 评分器不能验收本功能。** doubao 在本批把耳裁最强的那条评成"音高平稳、无哭腔"（假阴性），qwen3.8 把无指令基线说成"哭腔"（假阳性）。因此**任何"上线/默认开启"的决定必须由用户耳朵签**，模型一致不构成通过条件。

## 6. 实施切片（每片独立可测、可回滚）

1. **映射与白名单层**：新增 3.1 标签白名单（仅 `sad`）＋中文情绪→标签映射＋禁字符/越界过滤；纯函数，TDD 先写负例（R1 那批）。
2. **装配层**：三个渲染函数（§3.3）＋逐句闭合＋幂等；不动出站调用。测试覆盖：空标签集、正文已含标签、单句、跨句、含禁字符。
3. **接入层**：`prepare_text_for_style_control` 增 3.1 分支、`_build_qwen_audio_31_http_payload` 用装配后正文；默认关。改 §4 列出的必改断言（按新语义重写，禁止放宽为"包含即可"）。
4. **口径层**：成本按含标签长度、时长按净台词长度，两条各有测试钉住；顺手把 `usage.characters` 读进响应解析与账单对账（R2）。
5. **开关链路层**：补 `style_control_method` 枚举定义与快照放行（R3），前端设置项与档案卡同步（§4 档案/前端各点），跑跨源一致性守卫。
6. **验收**：真实章节级 1 章灰度，客观层（时长/ASR 逐字/无标签朗读）＋用户耳朵；两条通过才讨论默认开启。默认状态维持关闭直到该验收完成。

严格约束：全程 TDD（先红后绿）；后端从 `backend/` 跑 `python -m pytest tests/ -q`；**全量回归必须串行**（并发引入假失败）；每片完成后跑 `python scripts/cleanup_task_artifacts.py` 先 dry-run 再 `--apply`，但**不得删** §4 两个 probe 脚本与 B3 证据目录。

## 7. 完成定义

- 3.1 出站正文在开关打开时携带逐句官方标签，关闭时与现在逐字节一致（可用 `--batch qwen31_writing` 干跑 diff 验证）。
- 转写层零标签朗读（ASR 逐字 similarity=1.000，标签词不出现）。
- 成本与时长两个口径都有测试钉住，`usage.characters` 已被读回并出现在账单对账里。
- 真实章节灰度的音频经用户耳朵确认优于当前 instruction-only。
- `docs/TTS_PROMPT_EVIDENCE_20261010.md` §22 与 `docs/MODEL_INTEGRATION_REFERENCE.md` §11 回写落地状态（含放开的新标签取值与对应实测批次）。
