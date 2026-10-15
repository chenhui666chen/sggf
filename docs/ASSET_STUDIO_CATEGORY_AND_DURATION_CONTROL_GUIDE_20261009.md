# 资产工作台「分类 + 时长参数控件」改造指导文档

- 文档日期：2026-10-09
- 关联任务：#14 资产工作台参数控件按可灵交互模式改造
- 文档性质：**历史调研 + 实施台账 + 待实施设计**。§2–§9 保留 2026-10-09 原始方案，不能直接作为当前接口契约或验收清单；§10 为落地台账，台账与代码冲突时以代码及测试为准。§11 为按当前候选、官方资料可核对范围与实际调用链重订的能力/组件方案。历史行号仅对应写作时快照，实施前应重新定位；标注「待实测」的能力不能直接上线。
- 参考基准：可灵（Kling）滑杆式时长、百炼/Bailian「智能时长」模式位、即梦（Dreamina）生成页工具栏与浮层（2026-10-09 浏览器实测，见附录 A）。

---

## 1. 已拍板决策与落点一览

| # | 决策（用户原话要点） | 落地位置 | 本文小节 |
|---|---|---|---|
| 1 | 连续时长用**纯 slider（可灵式）**；5/10/15 三档视为 3 个离散档位，2–30 秒视为约 29 个离散档位 | `DurationControl.tsx`（新）+ 各工作台时长 `Select` 替换 | §5、§7.1 |
| 2 | **智能时长做成「模式 chip」（百炼式）**，不是 slider 上的额外刻度 | `DurationControl.tsx` 的 chip 组 + `duration=-1` 提交 | §5、§7.2 |
| 3 | 区间真值**写进 `config/models.yaml` + 契约测试对齐**，不做适配器反射 | `models.yaml constraints.duration` 新结构 + `ConstraintSpec` + 新契约测试 | §4、§6 |
| 4 | 信息架构改为**大类 → 小分类 → 模型**：图片生成 / 视频生成（动作控制并入）/ 音乐生成 / 音效生成 / 视觉识别；小分类按模型真实能力划分，一个模型可重复出现在多个小分类；选参传参照各模型实际支持 | `modelEntryData.ts` + `_GROUP_MODEL_IDS` + `subcategory` | §3 |
| 5 | 2.5 的 draft 做成**独立选项「Seedance 2.5 样片模式」**（不是开关） | 小分类级条目 + 后端两步编排 | §7.4 |
| 6 | 本轮**先写好指导文档，不动手修改** | 本文 | §9 分期计划 |
| 7 | 放开时长后计费口径：**改 basis 分档**（不是加 `ui_max` 临时上限）**已落地 2026-10-09** | 按「模型 × 短边分辨率档 × 输出秒」取价：`asset_studio_model_catalog.py:349`、`points_usage_pricing.py:437`、缺价 400 `_helpers.py:1154` | §5.4、§8 R1 |
| 8 | **TTS 放「音效生成」下的小分类**，不新开第 6 个大类 | `modelEntryData.ts` 大类常量 + `_GROUP_MODEL_IDS` 的 `text_to_speech` | §3.4 |
| 9 | **已裁定（2026-10-09）：复活，不删净** —— 通道 B（`GET /api/v1/model-catalog/entries`）改造为资产工作台运行时视图 | `model_catalog_projection.py:119-164` 显式发三个 `runtime_*` 键 | §5.5、§8 R4 |
| 10 | **已裁定（2026-10-09）：不需要重定向层，直接改名** —— 大类拆分后旧 `audio` tab id | `modelEntryData.ts:9` 类型收窄，编译期枚举引用点 | §3.2、§8 R5 |

---

## 2. 现状事实（先纠偏，再谈改造）

### 2.1 时长元数据在 `config/models.yaml` 里有四种写法

42 个媒体模型条目（`config/models.yaml`，`models:` 列表）中，`constraints.duration` 实测分布：

| 形态 | 模型 | 值 |
|---|---|---|
| 区间字典 | `wan3.0-video` | `{min: 2, max: 30, default: 5, supports_auto: true}` |
| 离散列表 | `doubao-seedance-2-5` | `[4, 5, 10, 15, 20, 30]` |
| 离散列表 | `doubao-seedance-2-0` / `-2-0-fast` | `[4, 5, 10, 15]` |
| 区间字典 | `vidu-q3-pro-text2video` / `-img2video` / `-start-end2video` | `{min: 1, max: 16, default: 5}` |
| 区间字典 | `kling/kling-v3-video-generation` / `kling/kling-v3-omni-video-generation` | `{min: 3, max: 15, default: 5}` |
| 区间字典 | `pixverse-v6-t2v` | `{min: 1, max: 15, default: 5}` |
| 空列表 | `pixverse-c1-r2v` | `[]`（= 无信息，该档不在资产工作台视频宇宙内，未随批订正） |
| 缺字段 | 全部图片/音频/TTS/视觉模型 | `None` |

视频档的区间已按 2026-10-09 官方文档口径订正：kling v3/v3-omni `[3,15]` 默认 5，vidu q3-pro 三档 `[1,16]` 默认 5，pixverse-v6-t2v `[1,15]`（官方标 duration 必选，`default: 5` 取官方示例值，仅作 UI 默认）。证据：`bailian-docs-llm-wiki` 的 `raw/model-api-reference/video-generation-api/kling-api-reference/kling-video-generation-api-reference.md:398-402`、`.../vidu-api-reference/vidu-{text-to-video,image-to-video,keyframe-to-video}-api-reference.md`、`.../pixverse-api-reference/pixverse-text-to-video-api-reference.md:352-354`。

**离散列表仍是档位而非连续区间**：`doubao-seedance-2-5` 接受 4–30 任意整数与 `-1`（`adapters/volcengine/video.py:24, 60-61`），`2-0`/`2-0-fast` 接受 4–15 与 `-1`（同文件 `:73-74, :83-84`），YAML 只列了几个档位；这三家仍按「档位下拉」渲染，是刻意的（用户裁定：官方档位表未给连续区间的模型保持 chip 语义，不硬凑 slider）。`wan3.0-video` 已由离散列表改为区间（Slice 2）。

### 2.2 谁在真正校验时长：三层，各有各的口径

| 层 | 位置 | 行为 |
|---|---|---|
| API 入口 | `backend/app/api/v1/asset_studio_api/routes_video.py:83`、`:218`、`routes_video_edit.py:91` | `max(1.0, min(float(duration), 15.0))` —— **无条件钳到 1–15 秒**，`-1` 会被抬成 `1.0` |
| API 校验 | `_helpers.py:1110-1145 _validate_video_duration` | 已支持 range：`duration_values` 为空时才用 `duration_min/max`；`duration_values` 非空则**必须精确命中档位**（±0.1） |
| 路由候选过滤 | `core/unified_media_runtime.py:1060-1072` | 同上口径：有 `duration_values` 就只认档位 |
| 适配器 | `adapters/dashscope/video_wan3.py:174-177`、`adapters/volcengine/video.py:195-202` | 真实区间硬校验（2–30 / 4–30 / 4–15 + `-1`） |
| 其余视频适配器 | `adapters/dashscope/video_kling.py:54`、`video_i2v.py:54`、`video_t2v.py:41`、`adapters/vidu_platform/video.py:63` | **不校验**，`parameters` 整包透传给百炼 |

结论：**kling / vidu / pixverse / mureka 的区间目前只是 YAML 里的文档值，没有任何代码强制**；wan3.0 与 seedance 三家有代码级真值。这决定了 §6 契约测试的强度分层：能对拍的真值才写断言，其余标注为「上游文档值」。

### 2.3 `ConstraintSpec` 已经把区间塌成单档位（活缺陷）

`schemas/model_spec.py:36-47`：`duration` 为字典时取 `min/max` 存字段，同时把 `self.duration` 覆写为 `[default]`。实测（`ModelSpec.from_dict`）：

```
vidu-q3-pro-text2video  | duration=[5.0]  min/max=5.0/10.0  has_duration_range=True  supports_duration(7.0)=True
kling/kling-v3-video-generation | duration=[5.0] min/max=5.0/10.0  has_duration_range=True  supports_duration(7.0)=True
```

`supports_duration()` 本身正确（优先 range）。但下游两处都只读 `duration` 列表、不看同级的 `duration_min/duration_max`：

- `core/unified_media_runtime.py:1029`（`_extract_duration_constraints(spec.constraints.duration)` 收到的是塌好的 `[5.0]`，`min/max` 变 `None`）→ 路由候选里 vidu/kling 只接受 **恰好 5 秒**；
- `backend/app/api/v1/asset_studio_api/_helpers.py:999, 1018-1023`（`static_constraints` 走的是 `spec.to_dict()`，`duration=[5.0]`，而 `to_dict` 里独立的 `duration_min/duration_max` 键没有被读取）→ Asset Studio 提交 7 秒 vidu 会被判非法。

### 2.4 前端有两条 manifest 通道，其中一条**字段名对不上，等于不存在**

| 通道 | 后端 | 前端类型 | 实际状态 |
|---|---|---|---|
| A：`GET /api/v1/asset-studio/model-catalog` | `backend/app/services/asset_studio_model_catalog.py:209-239`（`_build_option` → `duration_options`） | `AssetStudioModelCatalogOption.duration_options: number[]`（`frontend/src/services/api.ts:1018-1029`） | 活着；但只发档位数字数组，无 range/step/auto |
| B：`GET /api/v1/model-catalog/entries` | `backend/app/api/v1/model_catalog.py:123-150` + `model_catalog_projection.py:119-164`（发 `constraints`、`constraints_json`、`constraints_summary`） | `AssetStudioWorkbench.tsx:223-247` 读 `runtime_task_constraints` / `runtime_capability_hints` / `runtime_routing_signal` | **端点本身是活的**（模型中心 `/n` 正常消费 `constraints_summary`，见 `frontend/src/pages/ModelCatalogPage.tsx:197, 1243-1247, 2106-2129`）；但资产工作台读的**这三个键后端一个都不发**（全仓 `rg runtime_task_constraints` 在 `*.py` 零命中），前端 `:2038-2052` 恒置 `null` → 资产工作台这条读取路径等于不存在 |

通道 B 失效的连锁后果（都在 `AssetStudioWorkbench.tsx`）：

- `getRuntimeDurationOptions:876-898` → `duration_values` 恒空 → 永远走前端硬编码表；
- `filterSizeOptions:900-926` → `ratio_values/min_width…` 恒空 → **不按模型裁剪尺寸**，全模型共用一份 `VIDEO_SIZE_OPTIONS`；
- `getSupportsCameraControl:928-933` → 恒 `false`；
- `getMaxReferenceImages:935-944` → 恒回退 `4`（即梦 2.5 实为 50 参考、wan3.0 为 10 图 + 5 视频）；
- `getRoutingStatusLabel:946+` → 路由徽标恒空。

另：`config/model_catalog_runtime.json` 在本仓不存在（仅测试用 tmp 路径写入），所以 `get_task_constraints()` 恒 `{}`（`core/model_catalog_runtime.py:189-199`）。

### 2.5 快照生成侧的潜在缺陷（一旦启用通道 B 就暴露）

`backend/app/services/model_catalog_bootstrap.py:613-625`：

```python
duration_values = [float(value) for value in (constraints.get("duration") or [])
                   if isinstance(value, (int, float))]
```

遍历字典得到的是字符串键（`"min"`/`"max"`/`"default"`），`isinstance(..., (int, float))` 全假 → vidu/kling 的 `constraints_summary` **完全没有 duration 段**。现在因为通道 B 死着，这 bug 未显形；改造若复用 DB 投影必须先修它。

同理：2.5 的 `constraints.resolutions: [480p, 720p, 1080p]`、`max_reference_images: 30` / `max_reference_videos: 10` / `max_reference_audios: 10` / `max_reference_total: 50` 这些**已经在 YAML 里的真值**，既不被 `ModelSpec.from_dict`（`schemas/model_spec.py:435-445`，只映射 duration/ratios/宽高/batch/prompt 长度）映射，也不被 `_build_constraints_summary` 输出，前端拿不到。

### 2.6 前端硬编码档位与 YAML/适配器三方不一致

`AssetStudioWorkbench.tsx` 的档位常量已收口到 `frontend/src/utils/assetStudioDurationControls.ts`（Slice 4）：`VIDEO_DURATION_OPTIONS_BY_MODEL`（档位表）与 `VIDEO_DURATION_RANGES_BY_MODEL`（区间表）两张**离线兜底镜像**，目录可用时一律以 catalog 下发值为准。当前两表与 `config/models.yaml`、适配器真值对拍：

| 模型 | 前端镜像 | `models.yaml` | 适配器真值 | 判定 |
|---|---|---|---|---|
| `wan3.0-video` | range 2–30 + 智能时长 | 同 | 2–30 + `-1` | 一致 |
| `doubao-seedance-2-5` | chip 4/5/10/15/20/30 | 同 | 4–30 + `-1` | 档位正确但非连续 |
| `doubao-seedance-2-0` | chip 4/5/10/15 | 同 | 4–15 | 一致（原镜像里的 30 已删） |
| `doubao-seedance-2-0-fast` | chip 4/5/10/15 | 同 | 4–15 | 一致 |
| `kling/kling-v3-*` | range 3–15 | 同 | 无本地校验，透传 | 按官方区间放开，越界由 `_validate_video_duration` 拒绝 |
| `vidu-q3-pro-*` | range 1–16 | 同 | 无本地校验，透传 | 同上（原镜像把连续区间压成 5/10 两档） |
| `pixverse-v6-t2v` | range 1–15 | 同 | 无本地校验，透传 | 原 `[]` 已补官方区间 |

镜像表由 `frontend/src/utils/__tests__/assetStudioDurationControls.test.ts` 与 `frontend/src/components/home/__tests__/assetStudioDurationControlSource.test.ts` 锁定：后者禁止 `AssetStudioWorkbench.tsx` 再声明同名常量，保证镜像只有 utils 一处。改 `models.yaml` 区间时必须同步这三处，否则离线态（目录拉不到）会给出上游拒绝的时长。

音频侧同样分裂：`AUDIO_DURATION_OPTIONS_BY_TYPE:800+`（music 15/30/45/60、sound-effect 3/5/8/10）与后端 `asset_studio_model_catalog.py:124-127 _AUDIO_DURATION_OPTIONS` 各写一份，`_validate_audio_duration`（`_helpers.py:1146-1158`）按后者拒绝请求。

### 2.7 端点输入面：小分类目前能不能落地，取决于这里

| 端点 | 现有字段（`Form`/`File`） | 缺口 |
|---|---|---|
| `POST /asset-studio/video`（`routes_video.py:52-64`） | `prompt, negative_prompt, model_id, width, height, duration, seed, camera_control, reference_image(单个)` | 无 `ratio`、无数量、无水印开关、无首尾帧双图、**最多 1 张参考图**、无参考视频/音频 |
| `POST /asset-studio/motion`（`routes_video.py:188-197`） | 同上 + `motion_control`，`reference_image` 单个 | 同上 |
| `POST /asset-studio/video-edit`（`routes_video_edit.py:50-57`） | `edit_feature, reference_video(单个), reference_images(列表)` | 有 `ratio`/`duration` 但 `duration` 同样被钳 15；无参考音频 |
| `POST /asset-studio/audio`（`routes_audio.py:54-68`） | `generation_type, duration(int), style, mood, tempo, voice_id, instruction, rate, pitch, volume, emotion, speaker_ids` | `scene-audio`（`:92-123`）与 `speech`（`:289+`）**不校验时长**（speech 按字符计费） |

所以：**「全能参考 / 首尾帧 / 参考视频驱动」这三类小分类当前后端做不到**，需要新增多文件字段；而「文生视频 / 图生视频 / 动作控制 / 视频编辑 / 样片模式」只改参数就能落地。这是 §9 分期的主要依据。

### 2.8 成本敞口（slider 放开到 30 秒会立刻踩到）

`backend/app/services/points_usage_pricing.py:423-433`（改造前位置）：视频/动作/编辑的冻结与结算基准一律是 `duration × 0.2~0.3 元/秒`，**与模型、分辨率无关**；`_settle_asset_studio_billing`（`_helpers.py:140-158`）沿用同一 `basis_yuan`。而 2026-10-08 实测的火山方舟官方价（`docs/MODEL_INTEGRATION_REFERENCE.md` 第 7 节）：

| 组合 | 官方成本（刊例价） | 平台冻结 basis |
|---|---|---|
| `wan3.0-video` 720P / 5s | 3.00 元 | 1.00 元 |
| `seedance-2-5` 720p / 5s | 7.56 元 | 1.00 元 |
| `seedance-2-5` 1080p / 30s | ≈112.3 元 | **6.00 元** |

即：把 slider 上限从 15 放到 30、并暴露 1080p 之后，**单条上游成本相对现状默认档（720P / 5s）最多放大约 37 倍（3.00 → 112.26 元），而平台冻结与结算额只有 6.00 元，欠收 18.7 倍**。改造必须与 §8 R1 的成本闸门一起做，否则属于已知亏损。

**本段是改造前事实**：§8 R1 闸门已于 2026-10-09 落地（§5.4），同一条「30 秒 × 1080P」现在按 `18.71 ÷ 5 × 30 ≈ 112.26` 元冻结，与官方 5 秒示例价的线性外推逐档相等（`backend/tests/test_asset_studio_video_tiered_pricing.py::TestFreezeCoversUpstreamCost::test_30s_1080p_freeze_matches_official_example_extrapolation`）。残余欠口见 §10.3 第 10 项（带参考视频）与 §5.4 末注（两步编排只算一次 basis）。

补充两个更极端的口径，供后续分期时核对：

- 含输入视频时官方单价降到 42.00（720p）/ 46.00（1080p）元每百万 token，但 token 用量要把输入秒一起算，官方给出的 2.5 1080p 含视频区间是 **20.12~78.25 元/条（5 秒）**；若「全能参考」小分类落地（P3），30 秒 + 参考视频的单条上游成本可达 **数百元**，而 basis 公式里根本没有参考输入这一项。
- 时长对成本是**线性**的，分辨率是**平方级**的（480p→1080p 单价 3.36→18.71，5.6 倍），所以真正危险的是「长 × 高分辨率」的组合，而不是单独的 slider 上限。

---

## 3. 目标信息架构：大类 → 小分类 → 模型

### 3.1 分类原则

1. **大类 = 产物类型**，对应用户定的五个：图片生成、视频生成（动作控制并入）、音乐生成、音效生成、视觉识别。
2. **小分类 = 输入形态 × 任务语义**，判据只取模型**已验证的能力**（`models.yaml` 的 `modality` 与 `capabilities[].name`，`verified_at`/`confidence` 字段为准），不取厂商营销卖点。
3. **一个模型可重复出现在多个小分类**：小分类是过滤器，不是模型的从属关系（即梦同款做法：2.5 在「全能参考/首尾帧/智能编辑/超长视频」里都出现）。
4. 小分类选定后，模型下拉只列**支持该小分类的模型**；模型选定后，参数控件按该模型的 `duration_mode / resolution_options / ratio_options / max_reference_*` 裁剪。
5. 前端不得再自持档位表；模型可见性与参数范围一律来自 manifest（§4）。

### 3.2 大类归属调整（现状 → 目标）

| 现状（`modelEntryData.ts:24-85`） | 目标 |
|---|---|
| 图片生成 `image` | 保留，下增设小分类 |
| 视频生成 `video` | 保留，吸收动作控制 |
| 动作控制 `motion` | **取消大类**，降为视频生成下的小分类（后端仍复用 `/motion` 端点，见 §5.4） |
| 音乐音效 `audio`（内含 music/sound-effect/scene-audio/speech 四型 `Select`，`AssetStudioWorkbench.tsx:3062-3075`） | **拆成两个大类**：音乐生成、音效生成；原四型转为各自小分类 |
| 视觉识别 `vision-review` | 保留，下增设小分类 |

`AssetStudioTabId` 因此从 5 值变 5 值但语义不同：`image | video | music | sfx | vision-review`（语音合成按决策 8 作为 `sfx` 下的小分类，不单独开 tab）。现存的 `audio` tab id 只在 `AssetStudioPage.tsx:23`、`modelEntryData.ts`、工作台内 `activeTabId === 'audio'` 分支被引用，**已裁定（2026-10-09）：直接改名，不做旧 id 重定向层**（理由与取证见 §8 R5）；把 `AssetStudioTabId` 联合类型收窄即可让编译器枚举出全部引用点，改漏的地方编不过。

### 3.3 视频生成大类的小分类与成员矩阵

成员判据来自 `config/models.yaml`（`modality` / `capabilities`）。**视频大类中 `motion` / `video_edit` / `dreamweaver_video_edit` 三组已不再手写名单**，改由 `asset_studio_model_catalog.py` 的 `_derive_video_group()` 在「视频宇宙」（`_VIDEO_UNIVERSE_MODEL_IDS`，= `video_generation` / `dreamweaver_video` 两组）上按 `modality` 派生；宇宙本身仍是手工准入清单，决定哪些档位进资产工作台。

| 小分类 | 准入判据 | 成员（= 派生结果，2026-10-09） | 需要的输入槽位 | 落哪个端点 |
|---|---|---|---|---|
| 文生视频 | `modality ∋ text_to_video` | wan3.0-video、seedance-2-5、2-0、2-0-fast、kling/kling-v3-video-generation、kling/kling-v3-omni、pixverse-v6-t2v、vidu-q3-pro-text2video | 提示词 | `/video`（现成） |
| 图生视频（首帧） | `modality ∋ image_to_video` | wan3.0-video、2-5、2-0、2-0-fast、kling-v3、kling/kling-v3-omni、vidu-q3-pro-img2video、vidu-q3-pro-start-end2video（`pixverse-c1-r2v` 在视频宇宙外） | 1 张图 | `/video`（现成，`reference_image`） |
| 首尾帧 | `capabilities ∋ {first_frame, last_frame}` 或 `modality ∋ start_end_to_video` | wan3.0-video、2-5、vidu-q3-pro-start-end2video | 2 张图（有序） | **需新槽位** |
| 全能参考 | `capabilities ∋ reference_images` 且上限 > 1，或 `modality ∋ reference_to_video` | wan3.0-video（10 图 / 5 视频）、2-5（30 图 / 10 视频 / 10 音频，总 50） | 多文件（图+视频+音频） | **需新槽位** |
| 视频编辑 | `modality ∋ video_edit` | wan3.0-video、2-5、2-0、2-0-fast | 参考视频 + 提示词 | `/video-edit`（现成） |
| 视频延长 | `capabilities ∋ video_extend` | wan3.0-video、2-5、2-0、2-0-fast | 1 段视频 | `/video-edit`（需新增 `edit_feature=extend`） |
| 音频驱动 | `modality ∋ audio_to_video` | 2-5、2-0 | 音频 | **需新槽位** |
| 动作控制 | `modality ∋ image_to_video`（派生，与图生视频同判据） | 同「图生视频（首帧）」8 档 | 1 图 + 动作描述 | `/motion`（现成） |
| 样片模式（Draft） | `capabilities ∋ draft_mode` | **仅 2-5** | 同所选任务 | 两步编排（§7.4） |

档案声明冲突的处置（实施时先改档案，不要迁就 UI）：

- `doubao-seedance-2-0` / `2-0-fast` 的 `modality` 已补 `video_edit`，与官方能力矩阵「编辑视频」「延长视频」均为 ✓ 对齐（2026-10-09 核对教程），并进入 `video_edit` / `dreamweaver_video_edit` 分组与 `_OPERATION_MODEL_IDS["edit_video"]` 白名单（Slice 6）。**2.0 不接收 2.5 独有的 `omni_reference_task_type`**，编辑时长仍按 4–15 整数校验；两档编辑链路尚未付费冒烟。
- `kling/kling-v3-video-generation` 曾同时挂着「档案只声明 `text_to_video`」和「被放进 `motion` 组」两个矛盾事实。裁定依据是官方文档：该档支持图生视频-基于首帧与首尾帧，`adapters/dashscope/video_kling.py:19-107` 也在 `image_path` 存在时下发 `media type=first_frame` → **档案 `modality` 补 `image_to_video`（含 `capabilities` 条目与官方来源、`verified_at: 2026-10-09`、`confidence: high`）**，UI 侧由派生自然获得入口。它没有编辑能力，`video_edit` 判据不成立，**已从 `video_edit` 组移除**。同期补上了此前完全缺失的 `_OPERATION_MODEL_IDS["edit_video"]` 键——缺这个键时 `/video-edit` 的候选集恒空，任何模型都只能在路由期报 does not support。**同一入口还有第二层缺口**：`edit_video()` 传入的 modality 字符串 `video_edit` 当时并不是 `schemas/common.py` 里 `Modality` 枚举的成员，`TaskSpecBuilder.with_modality()` 在路由之前就抛 `ValueError: 'video_edit' is not a valid Modality`，即白名单补齐后 `/video-edit` 仍然全挂；现已补 `Modality.VIDEO_EDIT` 枚举成员，并由 `tests/test_media_runtime_executability_guard.py::TestEditVideoOperationIsConfigured` 端到端锁定「路由可达 + 源视频落到 adapter 调用参数」。
- 视觉识别两档（`qwen3-vl-plus`、`qwen3.5-omni-plus`）曾只有档案与 `_OPERATION_MODEL_IDS["analyze_*"]` 白名单，adapter 上没有 `analyze_image` / `analyze_video` 方法，而运行时这两个 operation 走 `_execute_custom_registry_method`（要求方法存在）→ `/vision-review` 必然 `adapter_missing`。**已修复**：`adapters/dashscope/chat.py` 以 `_DashScopeVisionReviewMixin` 实现真正的百炼 compatible-mode 多模态评审并混入这两档（纯文本档位 `qwen3.6-plus` 不混入，由反向断言钉住），`config/models.yaml` 里 `qwen3.5-omni-plus` 补声明 `image_understanding` / `video_understanding`，入口 gate 的 400 文案原先硬写「仅支持 qwen3-vl-plus」与实际集合 `VISION_REVIEW_MODELS` 不符，已改为按集合动态生成。
- 视觉识别档位换代（2026-10-12）：上面那套实现把「评审结构」和「百炼客户端」绑死在一个 mixin 里，档案里早已声明视觉理解能力的 `qwen-plus`（Qwen3.7 Plus）与豆包 Seed 2.1 两档因此一直停在档案层——页面自持两档名单，白名单也只有两档，能力面比上游实际可交付的窄。现已把执行层抽到 `adapters/_shared_vision_review.py::VisionReviewMixin`（素材编码、评审提示词、JSON 解析、`analyze_image`/`analyze_video` 全部供应商中立），各家子类只出两个钩子：`_vision_client()` 决定 base_url 与密钥，`_vision_disable_thinking_kwargs()` 决定关思考的载荷写法（百炼顶层 `enable_thinking: False`、方舟 `extra_body={"thinking": {"type": "disabled"}}`）。新增档位 = 混入 + 白名单 + catalog 分组 + 档案 `modality` 四处同步，实现在同一处，不再有可能漂移的第二份评审逻辑。真实调用验收（同一 3.4KB 图 / 2s 视频 / 生产评审提示词，思考关闭，走 `media_runtime` 全链路）：qwen3-vl-plus 图 8.9s 视频 6.2s、qwen3.5-omni-plus 5.5s/3.8s、qwen-plus 8.0s/7.4s、doubao-seed-2-1-lite 7.1s/6.0s、doubao-seed-2-1-pro 15.9s/12.5s，十次调用全部 success 且响应可解析为评审 JSON。**关思考是新接入档位的硬前提**：豆包两档开思考实测 39.8s/40.8s、输出 1900+ tokens，关闭后 9.4s/15.7s、输出 363/398 tokens，延迟与成本都差 4~5 倍。三层一致性由 `tests/test_vision_review_multi_provider.py` 钉住（含 `vision_review` 分组 ≡ `analyze_image`/`analyze_video` 白名单 的逐字对齐判据），执行层由 `tests/test_media_runtime_executability_guard.py::TestVisionAnalysisIsExecutable` 钉住。`qwen3-vl-plus` 的物理退役（节点 2）与 `qwen3.5-omni-plus` 是否继续留在视觉下拉，仍待单独裁定，本轮只增不删（该裁定已于同一天做出并执行，见下方"产品入口退役收口"条）。计价不受影响：`vision_review` 是统一定价（图 0.04 元/条、视频 0.12 元/条），加档位只改我方成本。
- 视觉评审三档效果测评（2026-10-12，`qwen3-vl-plus` / `qwen3.5-omni-plus` / `qwen3.8-omni-flash`）：素材用视频路由审计线留下的 11 条真实产物 + 本地 ffmpeg 造的 5 条可控退化锚点（`boxblur` 模糊、`eq` 偏暗、后 4 秒 `tpad` clone 冻结、纯黑、320p 放大回 720p）+ 6 条抽帧图片，每条先用 ffprobe + OpenCV 算客观真值（拉普拉斯方差、平均亮度、帧间运动量、冻结帧比例），21 素材 × 3 档 = 63 次真实调用全部 success。**检出率三档打平（6/8），但判词质量差一个档次**：只有 3.8 的扣分理由逐条抽帧复核为真（广告牌画面突变成艺伎脸谱、蝴蝶从窗外跳到猫头顶、出租车行驶中变形），另两档对同一素材给 8.5~9.8 的无差别好评；3.8 打分均值 7.46 / 区分度 std 3.21 三档最高（更严但不乱扣分：11 条真实素材无一条维度掉到 5 分以下），中位延迟 8.7s、P95 10.2s（vl-plus 11.4s / 13.1s），单条成本 0.0031 元 ≈ vl-plus 的 44%、omni-plus 的 9%。测评总花费 0.98 元。**证据层级**：本轮的一次性脚本（素材拼装、评审调用、统计）与逐条原始响应放在 `%TEMP%\vision_eval`，2026-10-12 收口时已删除，仓库内不落文件。上面的数字是一次性观测快照，不可逐条复核；复现方式是按同一方法论重跑（11 条真实素材取自视频路由审计线留在 `%TEMP%\router_*\videos\` 的产物，属临时目录、随系统清理会消失；5 条锚点用 ffmpeg `boxblur` / `eq` / `trim+tpad` / `lavfi` 现场重建），21×3 真实调用刊例成本约 1 元。
- 同轮暴露并修掉的判据缺陷（与选模无关）：三档都把整段偏暗素材（实测平均亮度 33.5）的 `lighting` 评到 9.8，把后 4 秒完全冻结素材的 `smoothness` 评到 8.5——只给维度名时模型按"看着顺眼"打分。修法是 `adapters/_shared_vision_review.py::VISION_CRITERION_RUBRICS` 把逐维度扣分下限写进 `build_vision_review_prompt`，并要求 comment 必须写画面里看到的具体证据。复测：偏暗锚点 lighting 9.8→6.0（vl-plus）/ 6.5~7.8（omni-plus），冻结锚点 smoothness 8.5→6.0（vl-plus）/ 4.0~4.5（另两档）。**口径顺序敏感，别照字面改**：把"冻结必须扣分"写在前面会把慢镜头误判成冻结（omni-plus 4.0），把"低运动量不扣分"写在前面真冻结又漏检（两档 9.0~10.0）；现口径两条并列，只有 3.8 在这一版下同时判对（慢镜头 9.0 / 真冻结 2.0）。维度名、执行层默认维度、扣分约束三源一致由 `tests/test_vision_review_multi_provider.py` 钉住。
- 视觉评审的两个负结果（省成本，别重复试）：① 提高抽帧率救不了冻结漏检——`video_url` part 的 `fps` 兄弟字段（官方默认 2.0、范围 0.1~10，五档都接受不报错）实测 vl-plus 在 2/4/8fps 下 smoothness 恒为 8.5，视频 token 却从 3062 涨到 12248，4 倍成本换 0 改善，因此**没有**接入 `fps` 参数；② `response_format={"type":"json_object"}` 能保证 JSON 合法，但 3.8 延迟从 6~9s 涨到 22~33s（3~4 倍），未采纳。3.8 遗留缺陷：约 7%（3/42）调用输出不可解析（`finish_reason=stop`、正文看起来完整，疑为字符串内裸换行），另两档 0 次，命中时页面降级为纯文本展示；是否给 `parse_vision_review_content` 加容错重试待裁定。
- `qwen3.8-omni-flash` 接线（2026-10-12）：进入 `core/unified_media_runtime.py` 的 `analyze_image` / `analyze_video` 白名单与 `vision_review` catalog 分组（视觉识别现为六档），关思考写法是第三家——OpenAI 标准顶层 `reasoning_effort="none"`（百炼 `enable_thinking` 不适用于本档，混用会静默保留 xhigh 思考：实测开思考 22.3s/12.4s、多吃 1655/651 reasoning tokens，关闭后 6.4s/4.3s）。入口默认档仍是 `qwen3-vl-plus`，`DEFAULT_VISION_REVIEW_MODEL_ID` 本轮未动。
- 视觉识别产品入口退役收口（2026-10-12，紧接上两条裁定执行）：三档测评的结论是"检出率打平、判词质量差一个档次"，`qwen3.5-omni-plus` 没有任何维度胜出、单条成本却是 3.8 的约 11 倍，`qwen3-vl-plus` 只剩"能用"。经用户裁定按两片执行，**本片（Slice A）只摘产品入口**：`vision_review` 与 `dreamweaver_vision` 两个分组收敛为四档（`qwen-plus`、`qwen3.8-omni-flash`、`doubao-seed-2-1-lite`、`doubao-seed-2-1-pro`），默认档改为 `asset_studio_vision_review=qwen3.8-omni-flash`、`dreamweaver_vision=qwen-plus`，`_constants.DEFAULT_VISION_REVIEW_MODEL_ID` 兜底、前端 `VISION_MODEL_OPTIONS` 与 i18n label、短剧配置的两处兜底同步跟进。`qwen3.5-omni-plus` 走完整物理退役：档案卡 + `@register_model` 装饰器 + `analyze_*` 白名单三处删净，登记进 `RETIRED_MEDIA_MODELS`（承接 `qwen3.8-omni-flash`），库内旧 ID 用 `scripts/rewrite_legacy_model_ids.py` 预览复核为零命中。
  **Slice B 已完成（2026-10-12 同日）**：短剧 QC 线后继档按裁定取 `qwen3.8-omni-flash`，`pipeline/autoqc_pkg/` 六个模块各自的 `DEFAULT_SEMANTIC_VLM_ADAPTER` / `DEFAULT_STATE_QC_VLM_ADAPTER` / `DEFAULT_VIDEO_CLIP_QC_VLM_ADAPTER` 常量副本与 `.env`、`.env.example` 的 `DREAMWEAVER_SEMANTIC_VLM_ADAPTER`、`DREAMWEAVER_STATE_QC_VLM_ADAPTER` 同批改（只改一边必漂移；解析顺序是 项目配置 → ENV → 代码默认，见 `_qc_config.py:156/206`）。旧档随后逐层删净：`adapters/dashscope/multimodal.py` 整文件 + 注册表自动导入项 + `adapters/dashscope/__init__.py` 星号导入、legacy 适配器类与其 runtime wrapper 及表键、`core/model_resolution.py` 别名、`config/models.yaml` 档案卡、`config/model_catalog_profiles.yaml` 画像段（含指向该档的 `router_rules`）、`_OPERATION_MODEL_IDS["analyze_*"]` 过渡项、`QWEN_VL_PLUS_*` 三行 env。消费侧同时从"传适配器对象"改为"传模型 ID 字符串"（`agents/asset_library.py`），兼容层才能整块删除而不留残骸。库内存量用 `scripts/rewrite_legacy_model_ids.py` 复核零命中；上条降级为 ⊆ 的判据**已恢复为分组 ≡ 白名单逐字相等**（`tests/test_vision_review_multi_provider.py::test_vision_catalog_group_equals_allowlist`）。退役门禁 `scripts/audit_model_references.py --all-retired --expect-zero` 归零。
  本片新增两层教训：④ **兼容层是退役的第五层事实源，且漏改零报错**——旧 ID 还活在 `legacy_runtime_wrappers._RUNTIME_WRAPPER_CLASSES`（表键下划线形态）、`model_adapters.ModelAdapterFactory._ENV_PREFIX_MAP/_DEFAULT_MODEL_NAME_BY_ENV`、`MODEL_ALIASES` 里，这些表全是"查不到返回 None"的软失败，`_run_helpers.py:26-56` 会把 QC 开关静默置 False，症状是 QC 永久关闭且无报错，比拒单难发现得多；⑤ **env 扫描有口径盲区**——`audit_model_references.py` 的 `ENV_MODEL_KEY_RE` 只认含 `MODEL` 的键，`*_VLM_ADAPTER` 不在内，门禁归零证明不了 env 已收口，本批靠手工盘点。
  摘档位前必须逐条确认的三条隐藏事实源（本轮实测得出，任一条漏掉都是静默故障）：① `_OPERATION_MODEL_IDS["analyze_*"]` 被短剧 QC 与工作台视觉评审**共用**（`pipeline/autoqc_pkg/_utils.py` 经 `adapters.adapter_helpers` 直连 media_runtime）；② 短剧的 `vision_model` 还会被喂给 `chat_messages`（`pipeline/autoqc_pkg/_semantic_match.py:76`，非流式 + `json_object`）——Slice B 已核实这条**对任何模型 ID 都是死路**：注册表里的对话适配器只有 `generate`、没有 `chat`，退役前的 vl-plus 同样（它继承 `_DashScopeChatAdapter`），所以该路径从来没通过，`dreamweaver_vision` 分组默认档因此仍是标准 chat 档 `qwen-plus`；③ 引用审计工具在 Windows 下按 git 默认 `core.quotepath=true` 取清单，中文命名文件"在清单里却读不出"，本轮修了解析并补了常驻判据（详见 `docs/MODEL_INTEGRATION_REFERENCE.md` §10.28）。
- `pixverse-v6-t2v` `capabilities` 有 `motion_control/camera_control`（批量模板挂的，来源 `TODO: verify`），`modality` 只有 `text_to_video`，官方 t2v 端点也不接收参考图 → **派生后自动离开 `motion` 组**，capability 声明保留但未参与成员判定。这条是「靠 capability 标签判成员」的典型反例：判据必须用 `modality`。
- `kling/kling-v3-omni-video-generation` 官方另有视频编辑能力（`media type=base`），但档案未声明 `video_edit`、adapter 未下发参考视频 → 派生结果把它挡在编辑组外。要放它进编辑组，需先补 adapter 与付费冒烟，再改档案声明，顺序不可颠倒。

### 3.4 其余大类的小分类与成员

| 大类 | 小分类 | 判据 | 成员 |
|---|---|---|---|
| 图片生成 | 文生图 | `text_to_image` | qwen-image-3.0、3.0-pro、wan2.7-image-pro、seedream-5-0、5-0-pro、kling/kling-v3-image-generation、kling/kling-v3-omni-image-generation |
| 图片生成 | 图生图 / 参考图 | `image_to_image` | qwen-image-3.0、3.0-pro、wan2.7-image-pro、seedream-5-0、5-0-pro、kling/kling-v3-omni-image-generation |
| 图片生成 | 指令编辑 | `image_edit` | qwen-image-edit-plus、qwen-image-edit-max、seedream-5-0（`image_editing`） |
| 图片生成 | 局部重绘 | `local_edit` / `region_edit` | qwen-image-edit-plus、wan2.7-image-pro |
| 音乐生成 | 纯音乐/配乐 | `music_generation` | mureka-o1-instrumental |
| 音效生成 | 短音效 | `sound_effect_generation` | seed-audio-1.0（默认，首位）、qwen-audio-3.1-tts-next（2026-10-10 已并入） |
| 音效生成 | 场景音频 | `multi_speaker_dialogue` | seed-audio-1.0（next **不并入**：场景链路提交 `references=[{"speaker":…}]` 音色 ID，next 只认 `audio_url`/`audio_data`，必 400） |
| 音效生成 | 语音合成 | `text_to_speech` | qwen3-tts-instruct-flash、cosyvoice-v3.5-plus、minimax-speech-2.8-hd、-turbo |
| 视觉识别 | 图片理解 | `image_understanding` | qwen-plus（Qwen3.7 Plus）、qwen3.8-omni-flash、doubao-seed-2-1-lite、doubao-seed-2-1-pro（2026-10-12 换代与三档测评后收敛为四档，真实调用实测见 §3.3；`qwen3-vl-plus` 仅剩短剧 QC 存量档、不在产品入口，`qwen3.5-omni-plus` 已物理退役） |
| 视觉识别 | 视频理解 | `video_understanding` | 同上，六档图片/视频两条入口均已真实调用验收 |

说明：**已裁定（2026-10-09）—— TTS 放「音效生成」下的小分类**，不新开第 6 个大类。理由与音效同属音频产物、`generation_type` 语义已按此运作一致；大类数量保持用户清单的五个。

---

## 4. 数据契约：把区间真值写进 `config/models.yaml`

### 4.1 新结构（统一到一个 `duration` 键下，保持向后兼容）

```yaml
# 连续区间（可灵式 slider）
constraints:
  duration:
    mode: range            # range | discrete | model_decided | not_applicable
    min: 2
    max: 30
    step: 1                # 前端 slider 粒度；2–30 + step 1 = 29 个可选值
    default: 5
    supports_auto: true    # 允许 -1「智能时长」
    auto_value: -1

# 离散档位（保持 chip，不硬凑 slider）
    mode: discrete
    values: [5, 10]

# 时长由模型决定（mureka / seed-audio）
    mode: model_decided    # 前端只读文案「实际时长由模型决定」，不发 duration

# 不适用（TTS 按文本长度）
    mode: not_applicable
```

兼容规则：`duration` 仍允许旧的「数字列表」与「`{min,max,default}` 字典」两种写法，读取方按 `mode` 缺省推断（列表 → `discrete`，字典含 `min/max` → `range`，空 → 未知）。**新代码一律写 `mode`。**

### 4.2 每个模型应写入的取值（含来源与置信度）

| 模型 | `mode` | min | max | step | default | `supports_auto` | 依据 |
|---|---|---|---|---|---|---|---|
| `wan3.0-video` | range | 2 | 30 | 1 | 5 | true（`-1`） | `adapters/dashscope/video_wan3.py:50-53`，2026-10 实测可用 |
| `doubao-seedance-2-5` | range | 4 | 30 | 1 | 5 | true | `adapters/volcengine/video.py:24, 60-61`；契约测试 `backend/tests/test_seedance_25_contract.py`（`[4, 30]`） |
| `doubao-seedance-2-0` | range | 4 | 15 | 1 | 5 | true | `adapters/volcengine/video.py:73-74` |
| `doubao-seedance-2-0-fast` | range | 4 | 15 | 1 | 5 | true | `adapters/volcengine/video.py:83-84` |
| `kling/kling-v3-video-generation` / `-omni-` | range | 3 | 15 | 1 | 5 | false | **已落地（2026-10-09）**：官方区间 `[3,15]` 默认 5（`kling-video-generation-api-reference.md:398-402`）；适配器仍透传不校验（`adapters/dashscope/video_kling.py:54`），越界由 `_validate_video_duration` 按档案拒绝，3/15 秒尚未付费冒烟 |
| `vidu-q3-pro-{text2video,img2video,start-end2video}` | range | 1 | 16 | 1 | 5 | false | **已落地（2026-10-09）**：官方区间 `[1,16]` 默认 5（`vidu-{text-to-video,image-to-video,keyframe-to-video}-api-reference.md`）；适配器仍透传（`adapters/vidu_platform/video.py:63`） |
| `pixverse-v6-t2v` | range | 1 | 15 | 1 | 5 | false | **已落地（2026-10-09）**：官方 `[1,15]` 整数且 duration 必选（`pixverse-text-to-video-api-reference.md:352-354`），`default: 5` 取官方示例值；YAML 原为 `duration: []` |
| `pixverse-c1-r2v` | 未订正 | – | – | – | – | – | YAML 仍 `duration: []`：该档不在资产工作台视频宇宙内，无 UI 入口，留待进入宇宙时一并补 |
| `mureka-o1-instrumental` | model_decided | – | – | – | – | – | **上游根本没有 duration 入参**（2026-10-11 官方文档 + 真实调用确证：载荷只接受 `model`/`n`/`prompt`/`instrumental_id`/`stream`）。两处调用点（`adapters/mureka/instrumental.py`、`backend/app/services/audiobook/ai_music.py`）已删除 `duration` 并固定 `model=mureka-9.5`、`n=1`；实测产物 188.5s / 189.7s 且不裁剪，15/30/45/60 档只做校验与积分冻结，属于本表要收敛的 `model_decided` 情形 |
| `seed-audio-1.0` / `-multilingual` | model_decided | – | – | – | – | – | `adapters/volcengine/audio_generation.py:192` 只从响应读 `duration` 做上报 |

Seedance 三档（`2-5` / `2-0` / `2-0-fast`）**没有**按本表早期建议改成 range：档案仍是离散档位列表（UI 走 chip），因为官方给的是档位表而非连续区间；`2-5` 的 `[4,30]` 与 `-1` 只出现在 `backend/tests/test_seedance_25_contract.py` 的契约断言里（编辑任务的 `-1` 规则见 Slice 1）。
| 全部 TTS（`qwen3-tts-instruct-flash`、`cosyvoice-v3.5-plus`、`minimax/speech-2.8-*`、`seed-tts-2.0-expressive`、`mimo-v2.5-tts*`、`stepaudio-3-tts`） | not_applicable | – | – | – | – | – | 计费与产物按文本长度（`points_usage_pricing.py:436-443`） |

补充：**编辑 / 延长任务的时长是「强制自动」而不是「可选自动」**。`adapters/volcengine/video.py` 的 `_apply_task_type_rules` 对 `edit`/`extend` 把 `duration` 改写为 `DURATION_SMART`；即梦在同一场景把按钮变成不可点的「自动」（附录 A）。契约里用 `duration_lock: auto` 表达（见 §5.3），不要让用户能拖动。

### 4.3 需要同批归一的其它参数（今天已在 YAML、但没人读）

| YAML 键 | 现状 | 目标 manifest 字段 |
|---|---|---|
| `constraints.resolutions`（2.5：`[480p,720p,1080p]`） | `ModelSpec.from_dict` 不映射，前端拿不到 → 尺寸全模型共用一份 | `resolution_options: string[]`（按模型裁剪，即梦 mini 只显示 720P 的做法） |
| `constraints.ratios` | 已被 `_get_effective_task_constraints` 读，但因通道 B 死着前端用不到 | `ratio_options: string[]`，含 `adaptive` |
| `constraints.max_reference_images / _videos / _audios / _total` | 只在适配器内部用 | `max_references: {images, videos, audios, total}` |
| `capabilities[].name`（`first_frame`/`draft_mode`/`video_extend`…） | 有，但没有小分类语义 | `subcategories: string[]`（或由 §3.3 判据在服务端算出，避免 YAML 双写） |
| `output_formats`（2.5 支持 mp4/mov） | 只在文档里 | `output_formats: string[]` |

**推荐由服务端按判据派生 `subcategories`，不把小分类名单再抄一遍进 YAML**，否则「模型能力」和「UI 分类」两处真值会长期漂移（这正是 §2.6 三方不一致的成因）。

### 4.4 为什么不从适配器反射（决策依据，避免二次讨论）

1. kling / vidu / pixverse / mureka **没有适配器常量**，反射得到的是空，反而更危险；
2. `models.yaml` 是 `ModelRegistry` 的权威源，YAML spec 在适配器被删除后仍存活，反射会把「代码实现细节」升级成「契约」；
3. 反射需要每个适配器暴露统一接口（3 家手写 + 1 家 profile 驱动），改造面比「写进 YAML + 契约测试对拍」大得多；
4. 反射对前端 manifest 无益：`/asset-studio/model-catalog` 是纯 YAML 读取链（`asset_studio_model_catalog.py:135-140`），引入 registry 会破坏它的 lru_cache 语义。

因此：**YAML 是唯一真值源，适配器只做二次校验，契约测试负责证明两边没分家。**

---

## 5. 后端改造清单（按文件，含函数与行号）

### 5.1 `schemas/model_spec.py`

- `ConstraintSpec`（`:21-31`）增字段：`mode: str = "auto"`、`step: Optional[int] = None`、`supports_auto: bool = False`、`auto_value: int = -1`、`duration_lock: Optional[str] = None`、`resolutions: List[str]`、`max_reference_images/videos/audios/total`。
- `__post_init__`（`:36-47`）**停止把 range 塌成 `[default]`**：保留 `duration = []`（或 `values`），并让 `duration_values` 为空时才走 min/max；这是 §2.3 的根因修复。
- `from_dict`（`:435-445`）补传上述新键；同时兼容 YAML 顶层 `duration_min/duration_max` 平铺写法（当前写了也不会被读）。
- `supports_duration`（`:52-59`）：`supports_auto` 且 `duration == auto_value` 时直接放行；`mode == "model_decided"/"not_applicable"` 时忽略时长。
- `to_dict`（`:80-92`）输出全部新字段，保证 `spec.to_dict()` 消费方（`_helpers`、catalog）能读到 range 而不是塌后的档位。

### 5.2 `core/unified_media_runtime.py`

- `_extract_duration_constraints`（`:1134-1167`）识别 `mode/step/supports_auto`，并在 `spec.constraints` 已归一的情况下优先读 `duration_min/max` 字段而非仅读 `duration` 字典。
- `_spec_matches_task`（`:1060-1072`）改为：`auto_value` 直放 → `values` 命中 → 否则 range 判定；修掉「有 `values` 就永不看 range」。

### 5.3 Asset Studio API

- **去掉 15 秒硬钳制**（`routes_video.py:83, :218`、`routes_video_edit.py:91`）：改为原样透传给 `_validate_video_duration`，越界直接 400（当前静默改写用户意图的行为必须消失，与既有反馈「尊重用户时长」一致）。
- `_validate_video_duration`（`_helpers.py:1110-1145`）：`-1` 直通（当模型 `supports_auto`）；`duration_values` 与 range 的优先级修正；错误文案带上 `min/max/step`。
- `_get_effective_task_constraints`（`:987-1024`）补读 `static_constraints["duration_min"/"duration_max"]`（当前只读 `duration` 列表），并新增 `duration_mode`、`duration_step`、`supports_auto`、`resolutions`、`max_references`。
- 新增/扩展 manifest：`asset_studio_model_catalog.py:209-239 _build_option` 输出
  `duration_mode`、`duration_range{min,max,step,default,supports_auto,locked}`、`duration_options`（离散档）、`resolution_options`、`ratio_options`、`max_references`、`subcategories`、`output_formats`；`_extract_duration_values:176-206` 不再把字典压成 `[min,default,max]`。
- 小分类白名单：`_GROUP_MODEL_IDS`（`:14-105`）按 §3.3/§3.4 判据由函数派生（`_build_subcategory` 目前抄的是 `version`，`model_catalog_bootstrap.py:255-260`，语义要重定义），DB 列 `subcategory` 已存在（`backend/app/models/model_catalog.py:35`），无需迁移。
- **新增输入槽位**（P1 期，做「首尾帧 / 全能参考 / 音频驱动」）：`/video` 增 `first_frame`、`last_frame`、`reference_images: list[UploadFile]`、`reference_videos`、`reference_audios`、`ratio`、`resolution`、`count`；上限按 manifest 校验后再进适配器。
- 样片模式：新增两步编排（§7.4）复用 `adapters/volcengine/video.py` 已实现的 `draft_task` 分支。

### 5.4 计费闸门（R1 已裁定并落地 2026-10-09：basis 分档取价）

- `points_usage_pricing.py:423-433`（**改造前位置**，现为 `:437`）：视频 / 动作 / 编辑三档的 basis 一律改为**按「模型 × 分辨率档 × 输出秒」取价**，取代单一 `POINTS_ASSET_STUDIO_VIDEO_PER_SECOND_YUAN`（0.2，已物理删除）。取价数据源用 `models.yaml` 的 `pricing_info`：
  - token 计价模型（Seedance 三家）**没有搬 token 公式**（裁定结果）：直接取官方 5 秒示例价 ÷5 反推每秒价，写进新键 `pricing_info.per_second_estimate.tiers`，反推系数与口径来源写在 `derived_from` / `note`；读哪个键由 `unit` 决定（`每秒` → `tiers`，`每百万 token` → `per_second_estimate.tiers`）。既有 `tiers` 与 `unit: 每百万 token` 不能改——被 `backend/tests/test_seedance_25_contract.py:102` 锁死。取价链四层与七条不变量见 `MODEL_INTEGRATION_REFERENCE.md` §10.25。
  - 秒计价模型（`wan3.0-video`、kling/vidu/pixverse）按**短边**选档，判据函数与运行时下发上游的 `parameters["resolution"]` 是同一个 `core/model_resolution.pick_resolution_label:165`；分辨率档名只认 `480P/720P/1080P`，档案里的 `360P/540P/4K` 因此不可达（540P 会被归到 720P，多冻不欠收）。
  - 取不到价时**拒绝生成并报错**（`AssetStudioVideoPriceMissing` → 入口 400），不静默回落到 0.2 元/秒（否则 §2.8 的欠收会伪装成「配置缺失」继续发生）。
- 落地后仍需注意：冻结额即实扣额（`_settle_asset_studio_billing` 不复算，只有音频按实际时长重算），basis 估低没有二次校正机会；带参考视频的编辑/延长任务仍欠闸门化（§10.3 第 10 项）。
- `_validate_audio_duration`（`_helpers.py:1146-1158`）与 `_AUDIO_DURATION_OPTIONS`（`asset_studio_model_catalog.py:124-127`）改为读 YAML，消灭双写；`music` 的 mureka 属 `model_decided`，应显示只读文案而不是 15/30/45/60 档位。

### 5.5 快照生成侧（ latent bug）

- `model_catalog_bootstrap.py:613-625 _build_constraints_summary` 增字典/`mode` 分支，输出 `duration.mode/min/max/step/supports_auto`；顺带输出 `resolutions` 与 `max_reference_*`。
- **通道 B 复活（已裁定 2026-10-09，方案与理由见 §8 R4）**：`model_catalog_projection.py:119-164` 增一个显式的资产工作台运行时视图，键名沿用前端既有类型 `runtime_task_constraints` / `runtime_capability_hints` / `runtime_routing_signal`（`AssetStudioWorkbench.tsx:223-247`），数据源＝经 `ConstraintSpec` 归一的 YAML spec（含 §4 新字段）+ DB 验证态；前端 `:2038-2052` 的恒置 `null` 映射改为真读，并与通道 A 在**一处合并函数**收口（A 管分组/默认值/文案，B 管运行时约束 + 信号）。
- `config/model_catalog_runtime.json` 保持**不存在**：快照优先于 YAML，残留旧快照会静默覆盖新契约（§2.4 末注）。

---

## 6. 契约测试清单（真值防漂移）

新增 `tests/test_asset_studio_duration_contract.py`（根 `tests/`，与 `test_constraint_duration_range.py`、`test_wan30_video.py` 同目录）：

1. **YAML ↔ 适配器对拍**：对 `wan3.0-video`、`doubao-seedance-2-5`、`2-0`、`2-0-fast`，断言 YAML `duration.min/max/supports_auto` == 适配器常量（`DURATION_MIN/MAX/SMART`、`SeedanceProfile.duration_min/max`）；边界各取 `min-1 / min / max / max+1 / auto_value`。
2. **mode 与前端可见档位一致**：`mode: range` 的模型，manifest `duration_options` 必须为空且 `duration_range` 非空；`mode: discrete` 反之。禁止同时给出（否则前端又回退到硬编码表）。
3. **API 不再静默钳制**：`/asset-studio/video` 传 `duration=30`（wan3.0）→ 通过；传 `duration=31` → 400；传 `duration=30`（2-0，max 15）→ 400 且文案含 `[4, 15]`；传 `duration=-1`（`supports_auto` 模型）→ 通过，非 auto 模型 → 400。
4. **塌档位回归守卫**：`ConstraintSpec.from_dict({duration: {min:5,max:10,default:5}})` 后 `constraints.duration == []` 且 `duration_min/max` 保留；`_spec_matches_task` 对 7 秒放行（钉死 §2.3）。
5. **`_build_constraints_summary` 字典形态**：vidu/kling 条目的 `constraints_summary.duration` 必须含 `min_seconds/max_seconds`（钉死 §2.5）。
6. **小分类成员表快照**：断言每个 subcategory 的模型集合与 §3.3/§3.4 一致（新增/退役模型时必须显式更新，防止白名单与能力声明脱节）。
7. **前端 fallback 表只减不增**：对 `VIDEO_DURATION_OPTIONS_BY_MODEL` 与 manifest 做等值断言，并在测试注释里声明「manifest 全量就绪后本表应删除」，防止它继续充当事实源。

适配器既有测试（`backend/tests/test_seedance_25_contract.py`，35 条）与 `test_wan30_video.py` 保持；§5.1 的 `__post_init__` 改动会牵动 `tests/test_constraint_duration_range.py`，实施时需一并核对该文件对 `duration == [default]` 的既有断言。

---

## 7. 交互规格

### 7.1 时长 slider（可灵式，决策 1）

- 呈现：工具栏汇总按钮（如 `16:9 · 720P · 5s`）+ 浮层内 **slider + 数字输入框**（即梦同款：`role=slider` 轨道 `aria-valuemin/valuemax`，旁边一个可键入的数值框）。
- 取值：`min..max`，`step` 来自 manifest；`2–30 step 1` = 29 档，`4–30` = 27 档，`5–10` = 6 档，`4–15` = 12 档。
- 刻度标签：每 5 秒一个文字刻度（轨道上小点按档位数渲染，即梦在 max 15 时 11 个点、max 30 时 20 个点）。
- 提交值仍是**整数秒字符串**（`formData.append('duration', videoDuration)`，`AssetStudioWorkbench.tsx:2461 / 2497 / 2569`），状态键 `videoDuration/motionDuration/audioDuration`（`:1595/1605/1617`）**保持不变**，请求体字段不变 → 后端除钳制外无需改签名。
- 越界处理：`useEffect` 里原先「不在档位表就重置为推荐值」（`:2277-2281`、`:2291-2295`）改为「按 `min/max` 夹取并提示一次」，不要静默跳到别的档位。

### 7.2 智能时长 chip（百炼式，决策 2）

- 与 slider **同级但互斥**的一组 chip：`手动 (N 秒)` / `智能时长`。选中「智能时长」时 slider 区置灰、提交 `duration=-1`。
- 仅当 `duration_range.supports_auto == true` 出现；`false` 时连 chip 都不渲染（不留禁用态）。
- 历史目标文案：「由模型自行决定时长，实际计费按产出秒数结算」。**当前实现并不满足**：`_helpers.py:_resolve_video_billing_seconds` 对 `-1` 按档案默认秒数冻结和结算，既不按真实产出秒数补扣，也不按区间上限冻结；启用该文案前须先解决 §11 的自动时长成本闸门。

### 7.3 强制自动（编辑 / 延长 / 样片第二步）

- 该场景 chip 组固定为 `自动`，且 `aria-disabled=true`（即梦「智能编辑」模式下时长按钮变成不可点的「自动」，汇总行同步显示「自动 720P 1」）；slider 不渲染。
- 前端不做假设：由 manifest 的 `duration_range.locked == "auto"` 决定，后端 `_apply_task_type_rules` 才是真值。

### 7.4 「Seedance 2.5 样片模式」独立选项（决策 5）

- 落为**小分类/模式位**，不是开关：`全能参考 → 样片模式`，与即梦把「即梦 Seedance 2.5 (样片模式)」列为独立模型条目同款（附录 A）。
- 后端两步编排：Step1 固定 480p 出多条样片 → UI 列表选择 → Step2 仅带 `model` + `draft_task` + `resolution=1080p`（`adapters/volcengine/video.py` 已实现；`draft_task` ID 仅 7 天有效）。
- 计费必须**两步分别冻结/结算**，并在 UI 明示「两步都收费」。basis 已在 2026-10-09 改为按「模型 × 分辨率档 × 秒」取价（R1，见 §5.4），旧的单一 0.2 元/秒低估问题已消失；但一次请求只算一次 basis，两步编排落地时**必须分别按 Step1 的 480P 档与 Step2 的目标分辨率档各冻各结算**（官方口径：Step2 token 单价由 Step1 是否含输入视频决定，Draft 成片不计入输入时长），沿用单档会漏收 Step1。

### 7.5 参数 bar 结构（对齐即梦，服务五分类）

```
[汇总按钮: 比例 · 分辨率 · 数量 · 时长]  [时长 chip: 手动 | 智能时长]  [样片模式入口]  [成本预览]
  └ 浮层：选择比例(chip 组，来自 ratio_options)
          选择分辨率(chip 组，来自 resolution_options，按模型裁剪)
          选择生成数量(chip 1..max_batch_size)
          时长（slider 或 chip，按 duration_mode）
```

- 现有控件映射：视频尺寸 `Select:2897`、时长 `Select:2907`；动作尺寸 `:3020`、时长 `:3030`；音频生成类型 `:3062`、模型 `:3084`、时长 `:3277`；图片模型 `:2657`、尺寸 `:2778`。**全部由 `AssetStudioParamBar` 接管**，`Select` 组件在时长/尺寸/数量三处退出历史舞台。
- 比例与分辨率拆开：现在 `getAspectRatio` 把比例折进尺寸选项（`:867-870` + `IMAGE_SIZE_OPTIONS/VIDEO_SIZE_OPTIONS`），无法表达即梦式「比例 × 分辨率」二维选择；`filterSizeOptions:900-926` 保留为「分辨率→宽高」的映射工具，不再充当裁剪入口。
- 参考槽位上限与提示文案来自 `max_references`（即梦把上限写进 placeholder：mini 12、2.5 50），不再固定 4。
- 成本预览：随 时长 × 分辨率 × 数量 实时刷新，复用 §5.4 改造后的 basis 函数（前端只展示，不自行估价）。

### 7.6 音频大类特例（不做 slider）

- `mureka-o1-instrumental`：`duration_mode: model_decided` → 控件位显示只读说明「实际时长由模型决定」，提交不带 `duration`；`style/mood/tempo` 维持 chip 组。
- `seed-audio-1.0`（音效 / 场景音频）：同上；音效结算继续走「按实际时长」既有口径（`_resolve_billed_audio_duration_seconds:871-876`）。
- `qwen-audio-3.1-tts-next`（2026-10-10 并入音效分组，默认仍是 `seed-audio-1.0`）：上游**没有 duration 入参**，时长由提示词决定（实测 5 秒档位请求返回 3.96 秒）。当前链路行为是：档位值 3/5/8/10 仍由 `_validate_audio_duration` 校验并用于**冻结**，但不会下发给模型，真实秒数写在响应 `output.audio.duration` → 适配器 `metadata["duration"]`，结算按它复算。因此档位对该模型语义是「预期长度上限」而非硬约束，改造时应归入 `model_decided`，不要为它编造 duration 映射。
- 语音合成：不显示时长，显示文本字数与音色选择（`instruction` 长度限制按模型显示，如 qwen-audio 系 100 字）。

---

## 8. 风险与待决策项

| 编号 | 风险/问题 | 建议 |
|---|---|---|
| R1 | 放开 30 秒 + 1080p 后，basis 仍是 0.2 元/秒 → 上游成本放大 37 倍而冻结额只有 6 元，欠收 18.7 倍（§2.8） | **已裁定（2026-10-09）：改 basis 分档**。**已落地（2026-10-09，取数与代码位置见 §10.1 的 R1 A1/A2 两行，反制测试 `backend/tests/test_asset_studio_video_tiered_pricing.py`）**：视频/动作/编辑三档按「模型 × 短边分辨率档 × 输出秒」从 `models.yaml` 的 `pricing_info` 取价（token 计费条目读 `per_second_estimate`，由官方 5 秒示例价 ÷5 反推），取不到价一律 400 拒单，`POINTS_ASSET_STUDIO_{VIDEO,MOTION,VIDEO_EDIT}_PER_SECOND_YUAN` 已物理删除；slider 上限一次放开到模型真实 `max`，不设 `ui_max` 过渡值 |
| R2 | 「首尾帧 / 全能参考 / 音频驱动」需要新的多文件 API 面（§2.7） | 分期：第一期只做「小分类 UI + 已支持小分类」，把三类灰显为「待接入」并在 manifest 里标 `status: planned`，**不要**先造空壳分类 |
| R3 | kling/vidu/pixverse 区间只是 YAML 文档值，无适配器级校验 | **已按官方区间放开（2026-10-09，见 §10）**：档案区间成为 `_validate_video_duration` 的拒绝依据，用户侧提交越界时长一律 400；适配器仍整包透传，所以上限之上的真实上游行为未实测——3/15（kling）、1/16（vidu）、1/15（pixverse）的边界值属用户付费冒烟清单，冒烟失败时应收紧档案而不是加代码兜底 |
| R4 | 通道 B 的字段名不匹配，资产工作台整块运行时约束逻辑失效（端点对模型中心仍正常） | **已裁定（2026-10-09）：复活，但不是补三个魔法键**。在 `model_catalog_projection.py` 增一个显式的资产工作台运行时视图（沿用 `runtime_task_constraints` / `runtime_capability_hints` / `runtime_routing_signal` 三个键名以对齐前端既有类型），数据源＝经 `ConstraintSpec` 归一的 YAML spec（含 §4 新字段）+ DB 验证态；同时修 §2.5 的 `_build_constraints_summary` 字典分支。不选「删净」的原因：删掉后资产工作台彻底失去「近期失败/校验过期」信号，而 `sortModelOptionsByRoutingSignal` 靠它把坏模型排后，这是用户选模的实际依据；而通道 A 是纯 YAML + `lru_cache(maxsize=1)`（`asset_studio_model_catalog.py:143-150, 229-239`），硬塞 DB 依赖会破坏它的缓存语义。复活后两条通道分工写死：**A 只管分组/默认值/文案，B 只管运行时约束 + 信号**，前端一处合并函数收口，不留第三条 |
| R5 | `tab id: audio` 拆成 `music`/`sfx`/`speech` 是否算破坏性变更 | **已裁定（2026-10-09）：不需要重定向层，直接改名。** 已核实 tab id 没有任何对外契约：tab 状态是 `AssetStudioPage.tsx:23` 的内存 `useState`（默认取 `modelUseEntries[0].id`），URL 无 `?tab=`/query 参数，无 localStorage/sessionStorage 持久化，`AssetStudioTabId` 只被 3 个文件引用（`modelEntryData.ts`、`ModelUseEntryStrip.tsx`、`AssetStudioWorkbench.tsx`），`userAssetSourceReaders.ts:129` 的 `/asset-studio` 返回路径不带 tab，测试里也没有断言 tab id。因此把 `AssetStudioTabId` 联合类型收窄即可让编译器枚举出全部 `activeTabId === …` 分支，改一处漏一处都编不过。若将来做深链（`?tab=music`），届时再引入旧 id → 新 id 的映射表；现在加映射属于为不存在的外部调用方写兼容层（YAGNI）。原建议中的「一条 hook 测试」降级为可选，`#1` 的类型收窄本身就是守卫 |
| R6 | 资产工作台目前只有源码文本断言测试（`components/home/__tests__/assetStudioSeedAudioSource.test.ts`），无交互测试 | slider/chip 改造前补 `@testing-library` 交互测试（拖动、越界夹取、chip 互斥、模式锁定），否则回归无网 |
| R7 | i18n 需新增键：`label.subcategory`、`durationMode.manual/auto`、`durationAuto.lockedAuto`、`modelDecidedHint`、`costPreview`、各小分类名，`zh-CN`（`frontend/src/i18n/resources/zh-CN/common.json`，`workbench.*` 在 4922+ 行区）与 `en-US` 同步 | 按既有 `label.*` 命名风格成对添加；注意历史上出现过高频注入错位问题（顶层 walk 导致命名空间 miss） |

---

## 9. 分期实施建议

> 本节是最初的排期。**P0 与 Slice 1–8 的实际落地范围、与计划的差异、仍欠差集统一见 §10**，本节保留原貌以便对照。

**P0｜数据契约与时长真值（可独立发布，无 UI 风险）**
1. `models.yaml` 写入 §4.2 取值 + `mode/step/supports_auto`；
2. `ConstraintSpec`/`unified_media_runtime`/`_helpers` 三层 range 语义修正（§5.1、§5.2、§5.3 前半）；
3. 去掉 15 秒硬钳制；
4. 契约测试 1/3/4/5；
5. 成本闸门 R1（**已裁定：改 basis 分档**，按「模型 × 分辨率档 × 输出秒」取价，取不到价即拒单；不设 `ui_max` 过渡上限）。
验收：`tests/test_constraint_duration_range.py`、`test_wan30_video.py`、`backend/tests/test_seedance_25_contract.py` 全绿；后端全量与既有基线（9 failed / 4784 passed）无新增失败。

**P1｜slider + 智能时长 chip + 参数 bar**
6. 新建 `AssetStudioParamBar.tsx`、`DurationControl.tsx`；替换三处时长 `Select`（2907 / 3030 / 3277）与尺寸 `Select`（2778 / 2897 / 3020）；
7. manifest 扩展（§5.3）+ 复活通道 B（§5.5，三个 `runtime_*` 键）+ 前端类型改造与 A/B 单点合并；删除 `VIDEO_DURATION_OPTIONS_BY_MODEL`、`AUDIO_DURATION_OPTIONS_BY_TYPE` 两份硬编码；
8. 交互测试 + i18n 成对补齐。
验收：视频时长可任意落在 2–30（wan3.0）/4–30（2.5）；智能时长 chip 只对 `supports_auto` 模型出现；编辑/延长为锁定「自动」。

**P2｜五分类 + 小分类 IA**
9. `modelEntryData.ts` 大类重排（动作控制并入视频、音频拆音乐/音效/语音合成）；旧 `audio` tab id **直接改名，不加重定向层**（§8 R5，已核实无 URL/存储/测试契约），靠 `AssetStudioTabId` 类型收窄让编译器枚举引用点；
10. `_GROUP_MODEL_IDS` → 判据派生 `subcategories`，DB `subcategory` 落真值；
11. 小分类选择器（chip 组，模型下拉随之过滤）；
12. 「Seedance 2.5 样片模式」独立选项 + 两步编排 + 两步计费。

**P3｜需要新 API 面的小分类**
13. 首尾帧双图、全能参考多文件（图/视频/音频）、音频驱动；
14. `count`（批量，受 `max_batch_size` 约束，当前所有视频模型 = 1 → 实际上线前该 chip 只能显示 1）。

---

## 10. 落地状态（2026-10-09 收口）

本节是唯一落地台账：§2 的现状缺陷、§3 的成员矩阵、§4.2 的取值、§6 的测试清单凡与本节冲突处，**以本节为准**。

### 10.1 已落地

| 切片 | 落地内容 | 事实源位置 | 锁定测试 |
|---|---|---|---|
| 1 | Seedance 编辑任务强制 `duration=-1`（上游只接受「自动」），仅 2.5 生效 | `adapters/volcengine/video.py:215`（`_apply_task_type_rules`） | `backend/tests/test_seedance_25_contract.py` |
| 2 | wan3.0 档案区间 `[2,30]` + `step 1` + `supports_auto: true` | `config/models.yaml:93-97` | `tests/test_dreamweaver_duration_bounds.py:65`、`tests/test_asset_studio_model_catalog.py:158` |
| 3 | 三个入口删除 `max(1.0, min(d, 15.0))` 硬钳制，改为按档案区间校验并 400 拒绝 | `backend/app/api/v1/asset_studio_api/_helpers.py:1152`（`_validate_video_duration`） | `backend/tests/test_asset_studio_video_duration_validation.py`（`TestEntriesNoLongerClampTo15Seconds`） |
| 4 | catalog 透出区间元数据（min/max/step/default/supports_auto）；前端区间模型渲染滑块 + 数字输入 + 智能时长 chip，档位模型保留下拉 | `backend/app/services/asset_studio_model_catalog.py:218`（`_extract_duration_spec`）、`frontend/src/utils/assetStudioDurationControls.ts` | `tests/test_asset_studio_model_catalog.py:158`、`frontend/src/utils/__tests__/assetStudioDurationControls.test.ts`、`frontend/src/components/home/__tests__/assetStudioDurationControlSource.test.ts` |
| 5 | DreamWeaver 分镜时长吸附放开到 2–30，提示词里的区间由常量动态拼接（消灭第二事实源） | `pipeline/media_presets.py:220-221`（`DREAMWEAVER_STORYBOARD_MIN_SHOT_S` / `MAX_SHOT_S`，可被 `.env` 覆盖） | `tests/test_dreamweaver_duration_bounds.py` |
| 6 | `doubao-seedance-2-0`、`2-0-fast` 进入视频编辑三层（档案 `modality` / 运行时白名单 / 目录分组） | `config/models.yaml`、`core/unified_media_runtime.py`（`_OPERATION_MODEL_IDS`）、`asset_studio_model_catalog._GROUP_MODEL_IDS` | `backend/tests/test_asset_studio_model_catalog_image_line.py`、`tests/test_media_runtime_executability_guard.py` |
| 7 | 档案 `modality` 与适配器 `get_model_spec()` 对齐：kling-v3 补 `image_to_video`（YAML 在 `adapters/registry.py:357-383` 覆盖适配器 spec，但适配器内仍存第四处硬编码 modality，必须同步订正） | `config/models.yaml` kling-v3 块 + `adapters/dashscope/video_kling.py:94` | 同 Slice 6 的 image_line 测试 |
| 8 | motion / video_edit / dreamweaver_video_edit 三组改为**按档案判据派生**，手写白名单从字面量物理删除 | `asset_studio_model_catalog.py:16`（`_VIDEO_UNIVERSE_MODEL_IDS`）、`:138`（`_derive_video_group`） | `tests/test_asset_studio_model_catalog.py`（`TestVideoGroupsDerivedFromArchive`，5 例含反向断言） |
| #26 C1 | 六档区间放开到官方值：kling `[3,15]`×2、vidu `[1,16]`×3、pixverse-v6-t2v 由 `duration: []` 补成 `[1,15]`；每个块带一行来源注释；前端离线镜像同步 | `config/models.yaml`（pixverse-v6-t2v `:2127`、vidu img/text/start-end `:2250/:2364/:2479`、kling-v3/kling-v3-omni `:2608/:2732`）、`frontend/src/utils/assetStudioDurationControls.ts`（`VIDEO_DURATION_RANGES_BY_MODEL`） | `tests/test_asset_studio_model_catalog.py:144`（逐秒阶梯）、`tests/test_constraint_duration_range.py`（vidu 1/16 放通、30 拒绝）、`frontend/src/utils/__tests__/assetStudioDurationControls.test.ts`（兜底表） |
| R1 A1 | kling-v3 / kling-v3-omni / vidu 三档 / pixverse-v6-t2v 六档 `pricing_info` 换成百炼公开目录真价目（逐秒刊例 + 无声档 + 上游计费尺寸清单），并把取价判据写进 note | `config/models.yaml`（`pricing_info` 起始：pixverse `:2169`、vidu img/text/start-end `:2290/:2404/:2520`、kling-v3/omni `:2648/:2772`），取数命令 `bl model list --model <id> --output json` | `backend/tests/test_asset_studio_video_tiered_pricing.py`（`TestTierPriceLookup` 逐档取价 + `test_tier_names_are_ladder_labels_and_unique` 档名合法唯一） |
| R1 A2 | basis 分档取价：视频/动作/编辑三档改为「模型 × 短边分辨率档 × 输出秒」，取不到价抛 `AssetStudioVideoPriceMissing` 由入口映射 400；三条单一均价 env（`POINTS_ASSET_STUDIO_{VIDEO,MOTION,VIDEO_EDIT}_PER_SECOND_YUAN`）与对应分支物理删除；seedance 三档用官方 5 秒示例价 ÷5 反推每秒价放进新键 `pricing_info.per_second_estimate`（`tiers` 与 `unit: 每百万 token` 不动）；短边档位判定从 `UnifiedMediaRuntime` 私有方法提升为 `core.model_resolution.pick_resolution_label`，运行时下发 `parameters["resolution"]` 与取价共用同一函数 | `core/model_resolution.py:165`、`backend/app/services/asset_studio_model_catalog.py:349`（`resolve_video_price_per_second`）、`backend/app/services/points_usage_pricing.py:411`、`backend/app/api/v1/asset_studio_api/_helpers.py:1154`（`_estimate_video_basis_yuan`）+ 三个入口调用点 | `backend/tests/test_asset_studio_video_tiered_pricing.py`（61 例：`TestTierPriceLookup` / `TestBasisUsesTieredPrice` / `TestFreezeCoversUpstreamCost` / `TestFlatPriceIsGoneFromSource`） |

上述 R1 A2 的「已落地」只指确定秒数的取价代码，不意味着智能时长或参考视频的冻结额已覆盖实际成本；未闭环项见 §10.3 第 8/10 项及 §11.3。

派生结果与旧手写白名单的差异（必须显式记录，否则下次会当成回归）：

- **motion = 视频宇宙 ∩ `modality ∋ image_to_video` = 8 档**：wan3.0-video、seedance-2-5、2-0、2-0-fast、kling-v3、kling-v3-omni、vidu-img2video、vidu-start-end2video。相对旧表**移出** `pixverse-v6-t2v`（档案只有 `text_to_video`，旧白名单是手工塞入的），**移入** `2-0-fast` 与 vidu 两档。
- **video_edit / dreamweaver_video_edit = 视频宇宙 ∩ `modality ∋ video_edit` = 4 档**（与旧表一致）。
- 判据必须用 `modality`，**不能用 capability 标签**：`pixverse-v6-t2v` 挂在批量模板能力上写了 `motion_control`，但它没有图生视频能力——用它做判据会把纯文生档放进动作组。
- `pixverse-c1-r2v` **不在视频宇宙内**（`_GROUP_MODEL_IDS["video_generation"]` 无它），因此不会因为派生自动进入资产工作台视频页。这是刻意设计：它的档案 `duration` 仍是 `[]`（`config/models.yaml:2019`），进 UI 前必须先补官方区间。
- 前端镜像同步：`AssetStudioWorkbench.tsx` 的 `MOTION_MODEL_OPTIONS`（catalog 不可用时的兜底动作组）改为派生后的 8 档并删掉 pixverse 条目；`VIDEO_DURATION_OPTIONS_BY_MODEL` 移除 pixverse（它已转为区间模型）；`SAFE_FALLBACK_DURATION_OPTIONS`（5/10）不变，因为放开后全体合法交集仍是 {5, 10}。
- `.env` 的 `DREAMWEAVER_STORYBOARD_*_SHOT_S` 首次真正生效：切片 5 之前提示词写死 2–15，改后由 env → 常量 → 提示词拼接，运行时上限与档案区间同源。

A2 落地后暴露的三条口径事实（不是缺陷，但下次改动画会被当成回归）：

- **480P 档只有 wan3.0 与 seedance 有价**：kling（最低 720P）、vidu（最低 540P）、pixverse（最低 360P）上游没公布 480P，短边落到 `480P` 时按裁定「取不到价即拒单」返回 400。前端四个预设（1920x1080 / 1280x720 / 1080x1920 / 1080x1080）只会产生 720P/1080P，所以这条只影响直接调 API 的调用方；要放 480P 必须先补档案价。
- **`2-0-fast` + 1080P 一律 400**：该档档案 `resolutions: [480p, 720p]`、官方只给 480p/720p 示例价，反推后没有 1080P 单价。该档运行时 `max_width/max_height` 是 4096 且声明 16:9，所以 `1920x1080` 过得了入口尺寸闸门（2026-10-11 起闸门按目标模型自己判，见参考文档 §10.27），拒单发生在取价层。前端仍会把 1920x1080 摆在 fast 的下拉里——拒单是正确结果，错的是入口还给它（见 §10.3 第 9 项）。
- **无声档分支当前休眠**：`/video`、`/motion`、`/video-edit` 三个端点都没有 audio 入参，`resolve_video_price_per_second` 的 `audio_output` 默认 `True`；kling/pixverse 的 `no_audio_price_per_second` 已入档，只有显式传 `False` 才生效。上游未单独公布无声价的条目回落含声档（档案里含声价恒 ≥ 无声价，宁可多冻不欠收）。

### 10.2 §6 契约测试清单逐条对账

| §6 项 | 状态 | 说明 |
|---|---|---|
| 1 YAML ↔ 适配器对拍 | **部分** | wan3.0 已由 `test_duration_range_matches_wan3_adapter` 钉住；seedance 三档 YAML `[4,15]`/`[4,30]` 与 `SeedanceProfile.duration_min/max` **刻意不对拍**（上游官方区间与可下单档位口径不同，见 §4.2 表后说明），不要补成等值断言 |
| 2 `mode` 与前端可见档位一致 | **未按原方案落地** | YAML 仍以 dict/list 区分区间/档位、step 由 catalog 默认 1；区间 manifest **同时**发 `duration_min/max` 与逐秒展开的非空 `duration_options`，供旧消费者使用（`asset_studio_model_catalog.py:219-245`）。§6 原「二者互斥」断言与现状相反，不能照抄 |
| 3 API 不再静默钳制 | **已落地** | `TestRangeModelFollowsOfficialBounds`（区间模型逐秒放通 + 越界 400 + 文案含区间）、`TestTierModelKeepsExactMatch`（档位模型精确匹配、拒绝智能时长） |
| 4 塌档位回归守卫 | **部分，不满足原 §6 断言** | `schemas/model_spec.py:43-51` 仍将 dict 默认值写为 `duration==[default]`；`tests/test_constraint_duration_range.py:54-65` 明确锁定此行为。`supports_duration()` 能看区间，但只读 `duration` 列表的消费方仍有退化风险；若要实现 §6 原断言，须改代码和既有测试，不能标为已完成 |
| 5 `_build_constraints_summary` 字典形态 | **未落地** | 属通道 B 复活范围（R4），见 §10.3 第 3 项 |
| 6 小分类成员表快照 | **仅视频部分派生，目标未完成** | `_derive_video_group` 只覆盖 motion / video_edit / dreamweaver_video_edit 的候选成员并有正反向断言；图片、音频、视觉仍是静态组，任务级 `subcategories` 尚未进入 manifest。现有测试不能证明「每个小分类」正确，更不能证明候选均可执行（Vidu 双帧仍缺双图入口） |
| 7 前端 fallback 表只减不增 | **未落地** | `VIDEO_DURATION_OPTIONS_BY_MODEL`、`VIDEO_DURATION_RANGES_BY_MODEL` 仍在充当 catalog 不可用时的离线镜像，本轮还给 pixverse 新增了区间条目。已用 `assetStudioDurationControlSource.test.ts`（「不再在工作台内维护会过期的时长兜底表」）禁止出现**第三份**，但删除这两张表要等通道 B 与 manifest 全量就绪 |

### 10.3 仍欠差集（每项都应是独立切片，需再裁定后动手）

1. **#26 C2｜自动调用侧按目标引擎区间判兼容**：DreamWeaver 分镜给出 16–30 秒时，kling/vidu 侧没有「该引擎跑不了，换一个或拒绝」的可读 reason。挂点候选：`core/selector.py`、`pipeline/dreamweaver_smart_dispatch_trace.py`。（`agents/storyboarder_pkg/_run.py` 的 `uses_video_containers` 分支已于 2026-10-11 接回 `dreamweaver_beat_duration_bounds_s()`，容器窗口不再自造 5~15，这一处挂点候选已消除；剩余问题是跨引擎的 reason。）
2. ~~`routes_video.py:213` 的静默换模型改为 400~~ **已落地（2026-10-11，范围扩到三链路）**：`_helpers.py:_resolve_requested_video_model` 让 video / motion / video_edit 三个入口对越集合模型名一律 400 并回吐可选清单；尺寸改为按目标模型自己的档案判；运行时仍换档时改为 400 且释放冻结、不交付换档产物。`routing_message` 与前端那条 info 提示已物理删除。契约与结构性事实见参考文档 §10.27，锁定测试 `backend/tests/test_asset_studio_video_model_routing.py`。
3. **R4 通道 B 复活**（三个 `runtime_*` 键 + A/B 单点合并）与 §2.5 的 `_build_constraints_summary` 字典分支修复，随之落地 §6 第 5 项。
4. **`pixverse-c1-r2v` 补官方区间**，再讨论是否纳入视频宇宙。
5. **kling-v3-omni 官方视频编辑能力**（`media type=base`）在档案、适配器、运行时三层均未接通；接通后 `video_edit` 派生组会自动多一档，无需改代码。
6. **§9 P1 余下**：`AssetStudioParamBar.tsx`、三处时长 `Select` 与尺寸 `Select` 替换、i18n 成对补齐（R7）、`@testing-library` 交互测试（R6）。
7. **§9 P2/P3 全部未动**：五分类 IA、小分类选择器、Seedance 2.5 样片模式、首尾帧/全能参考/音频驱动 API 面、`count`。
8. ~~R1 成本闸门未落地~~ **确定输出秒数的分档取价已落地，成本闭环未完成**（取数与代码位置见 §10.1 R1 A1/A2）：视频三档按「模型 × 短边分辨率档 × 传入输出秒」冻结并结算，缺价 400；但 `duration=-1` 用档案默认秒数计费（`_helpers.py:1161-1177`），参考视频的输入秒数未纳入 `/video-edit` 估算（`routes_video_edit.py:98-115`）。这两类不能声称由 R1 保证成本覆盖。
9. **分辨率按模型裁剪（展示层，承接第 1、2 项）**：入口侧 2026-10-11 已改为按目标模型判（`_validate_dimensions_for_models({resolved_model_id}, …)`，见参考文档 §10.27），「该档档案认不下的画幅比/尺寸」（现例：Vidu 系只认 16:9 / 9:16 / 1:1，传 `1440x1080`）已在入口 400 并点名模型；仍要等到取价层才 400 的是「档案认得下尺寸、但该档没有单价」（`2-0-fast` + 1920x1080）。前端 `filterSizeOptions` 依赖尚未复活的通道 B `runtime_task_constraints`，所以这两类非法组合在下拉里仍可选。通道 B 复活后应把档案 `constraints.resolutions` 变成前端可见的裁剪依据，拒单理由也才说得清是「该模型不出这个档」。
10. **带参考视频的任务仍有欠收口**：`/video-edit` 传参考视频，而 seedance 的每秒估算价取的是官方「不含输入视频」示例——token 公式会把输入秒计入用量，实扣可高于冻结额。另 §2.8 引用的「2.5 1080p 含视频 20.12~78.25 元/5 秒」在 `docs/MODEL_INTEGRATION_REFERENCE.md:731-737` 的官方表里查不到对应读数，落地这条闸门（按输入秒加计）前必须先复核该数字。

### 10.4 待用户付费冒烟（本文所有「上游文档值」都在等这一步变成实测值）

- kling-v3 / kling-v3-omni：图生视频（首帧、首尾帧）、3 秒、15 秒。
- vidu-q3-pro：img2video 与 start-end2video 走 motion 端点、1 秒、16 秒。
- pixverse-v6-t2v：1 秒、15 秒（旧档位表 3/5/10 已删，区间是新的未实测值）。
- seedance-2-0 / 2-0-fast：`/video-edit` 全链路（切片 6 只保证代码层放通，未在 motion/编辑端点冒烟过）。
- wan3.0：20–30 秒长视频、智能时长 `duration=-1`。

冒烟失败时的处置口径见 §8 R3：**收紧 `config/models.yaml` 档案值，不加代码兜底**。

---

## 11. 当前候选模型的能力复核与组件设计（本次代码快照）

本节只设计实现，不表示已修改业务代码或完成付费冒烟。候选范围取 `backend/app/services/asset_studio_model_catalog.py:16-96` 的资产工作台组，不把 DreamWeaver 专用组、别名或官方尚未接入的变体自动加入。证据级别：**A**＝百炼官方 API 原文在本地知识库的镜像（目录 `C:/Users/cuigu/.qoder-cn/skills/bailian-docs-llm-wiki/raw/`）；**B**＝官方模型市场结构化记录或仓库保存的官方链接/历史实测，未实时在线验证；**C**＝仅本地 YAML 或适配器声明。A/B 仍需按部署地域、开通状态和实际响应验证；火山与 Mureka 官网本轮未取得可核验正文，不能把 C 升格为官方真值。以下引用的 `raw/...` 和 `models/groups/...` 相对于该知识库根目录。

### 11.1 视频：按任务签名分组，不按营销能力词开放

| 当前候选 | 官方可核对能力与边界 | 工作台现状 / 拟开放任务 | 证据 |
|---|---|---|---|
| `wan3.0-video` | 文生、首帧、首尾帧、参考生、编辑/延长；无输入视频时输出 2–30 秒，含视频时输入总秒数＋输出秒数≤30；参考图≤10、视频≤5 段且合计≤15 秒、音频≤5 段且合计≤15 秒；首尾帧不能混参考素材 | `/video` 只收一张 `reference_image`；文生/首帧可继续使用，双帧/多参考/编辑/延长须逐任务接线和实测 | A：`raw/model-api-reference/video-generation-api/wan-api-reference/wan3-video-generation-api-reference.md`；`routes_video.py:53-64` |
| `doubao-seedance-2-5` | 仓库记录 4–30 秒、480p/720p/1080p、图/视频/音频多参考、编辑/延长及 Draft 两步；官方正文本轮未读到，具体任务互斥与输入限额仍待复核 | 当前 catalog 为 4/5/10/15/20/30 离散档，不按适配器范围强改 slider；2.5 编辑在 adapter 内强制自动，不代表入口允许显式 `-1`；Draft 不开放空壳 | B/C：`config/models.yaml`、`adapters/volcengine/video.py:244-260`；官方链接见档案 |
| `doubao-seedance-2-0` / `-2-0-fast` | 仓库记录 4–15 秒，Fast 只到 720p；编辑完整 API 及自动时长未独立获官方确认 | 保留离散档；编辑虽已接入候选，但未付费冒烟；2.0 编辑 adapter 拒绝 `-1`，不能显示全局「锁定自动」 | B/C：`config/models.yaml`、`adapters/volcengine/video.py:244-260`、§10.4 |
| `kling/kling-v3-video-generation` / `-omni-video-generation` | 两者文生/首帧/首尾帧，3–15 秒；仅 Omni 另有参考生与编辑；720p/1080p/4K，比例 16:9/9:16/1:1。Omni 纯图参考图＋主体≤7，混视频时≤4 且视频仅一段 | 普通版不得因「Kling」品牌共性进入编辑/多参考；Omni 的多参考和编辑须适配器、运行时、端点全部贯通后才显示 | A：`raw/model-api-reference/video-generation-api/kling-api-reference/kling-video-generation-api-reference.md` |
| `pixverse-v6-t2v` | 当前候选仅是文生视频型号，1–15 秒；PixVerse 另有 it2v/kf2v/r2v 等不同型号，不能把它们的能力并到 `t2v` | 只进文生；不得因档案批量模板中的 motion_control 标签进图生/动作；其他型号未加入候选 | A：`raw/model-api-reference/video-generation-api/pixverse-api-reference/`；`asset_studio_model_catalog.py:139-158` |
| `vidu-q3-pro-text2video` / `-img2video` / `-start-end2video` | 依次是文生、恰好一张首帧、恰好两张有序首尾帧；均 1–16 秒；双帧图像像素比须 0.8–1.25 | 前两型按任务接线；双帧型当前单图入口无法完整执行，不能因它在 motion 候选组就显示可生成 | A：`raw/model-api-reference/video-generation-api/vidu-api-reference/vidu-{text-to-video,image-to-video,keyframe-to-video}-api-reference.md`；`routes_video.py:53-64` |

**「动作控制」不是图生视频的同义词。** 当前 `motion` 组是视频候选中 `modality ∋ image_to_video` 的派生集合（`asset_studio_model_catalog.py:139-157`），`/motion` 只收单图与通用 `motion_control`；小分类必须拆成「首帧图生」与「厂商动作控制」，后者仅在对应适配器确实解释动作参数、且完成模型级调用验证后显示。Vidu 首尾帧型号不得通过单图 motion 入口假装可执行。`/video-edit` 的 UI `style-transfer/video-extend/video-remix` 与适配器读取的 `video_edit/video_extend` 尚需逐项映射，不能直接把三个按钮当成已接通编辑能力（`routes_video_edit.py:50-75`、`adapters/volcengine/video.py:236-260`）。

### 11.2 图片、音频与视觉：以实际输入槽位为边界

| 当前候选 | 官方可核对能力 / 待核实项 | 当前链路与目标组件 | 证据 |
|---|---|---|---|
| `qwen-image-3.0` / `-pro` | 文生、图生/编辑；官方输入 1–3 张，输出 1–6 张 | `/image` 有图即切换到**已退役** `image_edit` 模型组，**不能**把生成组选中的 Qwen 3.0 解释为已执行其图生/编辑能力；迁移替代路线见 §11.4 | A：`raw/model-api-reference/image-generation/qwen-image-api-reference/qwen-image-generation-and-editing-api-reference.md`；`routes_image.py:67-118` |
| `wan2.7-image-pro` | 文生、多参考、组图、编辑；输入最多 9 张；仅无图普通文生支持 4K，编辑/组图至 2K | UI 按文生/参考/组图区分尺寸及 `n`，不可共用 4K 选项；先修图片入口有图即换组及多图传递 | A：`raw/model-api-reference/image-generation/wan-image-api-reference/wan-image-generation-and-editing-api-reference.md` |
| `doubao-seedream-5-0` / `-pro` | 本轮官网仅返回脚本外壳；档案图生/编辑能力及尺寸、参考数仍待逐型号官方 API 正文确认 | 先保留可执行的文生与既有尺寸实测；多图/局部编辑不得仅凭 YAML `capabilities` 开放 | B/C：`config/models.yaml`、`adapters/volcengine/image.py`、`docs/MODEL_INTEGRATION_REFERENCE.md` |
| `kling/kling-v3-image-generation` / `-omni-image-generation` | 普通版参考输入仅 1 张，Omni 参考图＋主体合计≤10，可输出组图；两者控件不能共享「10 图」提示 | 当前有图请求会转入 Qwen 编辑组；接线前仅展示工作台实际可执行的文生，组图/多参考待接 | A：`raw/model-api-reference/image-generation/kling-image-api-reference/kling-image-generation-api-reference.md`；`routes_image.py:108-118` |
| `qwen-image-edit-plus` / `-max` | **用户已确认完全下线退役，禁止继续作为可售模型及默认值。** 百炼市场记录均标推理下线时间 2026-10-10 00:00:00；旧 API 文档只用于历史迁移对照 | 现有 `image_edit` 组及默认仍引用 plus/max，`routes_image.py` 有图即静默回退 plus，是必须尽快阻断的故障链；确认替代链路可用前不可仅换默认 ID 放行 | A/B：`models/groups/qwen-image-edit.json`、`qwen-image-edit-max.json` 的 `offlineInfo`；`asset_studio_model_catalog.py:39-42,81-84`、`routes_image.py:74-117` |
| `mureka-o1-instrumental` | 历史调用显示上游固定 `mureka-9.5`、无 duration 请求字段；产物可长于本地 15/30/45/60 档，本轮官方正文未复核 | 音乐控件取消「保证生成 N 秒」的表达，显示模型决定时长；冻结/结算依据真实扣费契约明确之前不能只删时长入参 | B：`adapters/mureka/instrumental.py`、`docs/MODEL_INTEGRATION_REFERENCE.md` |
| `seed-audio-1.0` | 仓库记载文本生成音效/场景音频、最多 3 条音频参考；未从官方正文确认限额，adapter 不接收时长 | 音效与场景展示模型决定时长，场景 `speaker_ids` 不等同上传参考音频；补实际时长计费验收 | B/C：`adapters/volcengine/audio_generation.py`、`routes_audio.py:92-134,403-469` |
| `qwen-audio-3.1-tts-next` | 官方独立统一音频生成端点，可输入文本及最多 3 条参考音频（各≤30 秒/10MB），生成音效、对话等；不是 Flash 的换音色开关 | 仅在「短音效」保留当前已接路径；播客/参考音频槽位需新增端点参数、adapter 映射和校验；不套用 Flash `voice_id` | A：`raw/model-api-reference/audio-api-references/audio-generation-api.md`；`asset_studio_model_catalog.py:47-50` |
| `qwen-audio-3.1-tts-flash` / `cosyvoice-v3.5-plus` / `minimax-speech-2.8-hd` / `-turbo` | TTS 按文本与音色 ID 合成，不是按目标秒数；CosyVoice 的参考音频克隆属于先建音色的资产流程；MiniMax 两档文本 <10000 字符，最多 4 音色混合且不支持 `whisper` 情绪 | 语音合成小分类显示文本、合法音色、当前确实透传的语速/情绪等参数；多音色混合、实时上传参考音频与流式播放均需独立链路，不以官方支持直接出控件 | A：`raw/_short/qwen-audio-tts-http-api-6a5232db21a53ba2.md`、`raw/_short/minimax-synchronous-speech-synthesis-api-bbe4c9f0093c0534.md`；B：`models/groups/cosyvoice.json`；`routes_audio.py:289-340` |
| `qwen3-vl-plus` / `qwen3.5-omni-plus`（**2026-10-12 已退出产品入口**：前者仅剩短剧 QC 存量档、待 Slice B 迁移，后者物理退役，承接 `qwen3.8-omni-flash`；现役四档见 §3.3） | 输入单图/视频可做理解与评审，输出文本；VL 不理解视频里的音频；Omni 的模型市场与指南视频时长口径不同，不能用统一上限 | 当前 `/vision-review` 接单文件并使用质量评审提示词，展示「图片评审/视频评审」而非未实现的通用问答、音轨评审或超长视频；Omni 上限待按具体接口验证 | A：`raw/model-user-guide/model-experience/vision-model/vision.md`、`raw/model-user-guide/model-experience/omni-modal/qwen-omni.md`；`routes_vision.py:47-107` |

### 11.3 前后端组件契约与落地门槛

1. **小分类使用任务签名，不直接复用 `capabilities[].name`。** 服务端由「明确型号 × 任务」白名单派生 `subcategories`：`text_to_video`（提示词）、`first_frame_video`（一图）、`first_last_frame_video`（有序两图）、`reference_video`（按模型限定图/视频/音频）、`video_edit`（源视频）、`motion_control`（专用动作输入）、`text_to_image`、`reference_image_edit`、`image_series`、`music`、`sound_effect`、`scene_audio`、`text_to_speech`、`image_review`、`video_review`。一个模型可入多个已贯通任务；**可见列表只发已贯通任务**，官方支持但缺 route/adapter 的任务仅在文档记录，不做可点击空壳。
2. **统一 manifest 是可用性与控件源，先保证 A 可独立支撑页面。** 后端 `asset_studio_model_catalog._build_option` 输出每个任务的 `status`（`available`/`needs_upstream_verification`/`integration_pending`）、输入 schema（必填/可选、素材类型、有序性、每类数量/总数/总秒数/体积、互斥条件）、输出 schema（比例、尺寸/分辨率、数量、时长 `discrete|range|model_decided|not_applicable`、auto 限定）、计费预览能力。前端以 manifest 渲染 `TaskInputSlots`、`DurationControl`、`ResolutionControl`、`ReferenceLimits`、`CostPreview`；对区间当前 `duration_options` 为逐秒兼容镜像、`duration_min/max` 才是 slider 真值，禁止以「options 非空」覆盖 range。离线 fallback 不应暴露未经实时校验的多素材、超长或高价任务。
3. **通道职责须先收敛，本文推荐 A 管参数、B 管运行态信号。** §5.5/§8 R4 原案要求 B 管运行时约束＋信号，与本节建议冲突；实施前须由用户重新裁定该职责变更，不能同时照两版做。推荐在 A 的 YAML manifest 补齐时长、尺寸、参考上限和任务可执行白名单；B 的 `model_catalog_projection.py` 仅提供 DB 验证状态、近期失败、路由可用性，不复制时长与尺寸真值。前端单点合并：A 有效且 B 缺失时仍按 A 渲染；B 只降级可用性/排序并说明原因，不用旧快照覆盖 A。若继续保留 B 的 `constraints_summary`，则同步修 `_build_constraints_summary` 的 dict 分支并测试刷新；不得将它回写为工作台参数源。
4. **多素材要做完整传递而非只加上传按钮。** `/video` 增有序 `first_frame/last_frame` 及按任务区分的 `reference_images/videos/audios`；`/image` 保留用户选中的模型与任务，避免「有图即切 Qwen 编辑组」。请求边界校验 MIME、体积、图像几何、视频秒数、素材互斥和任务专属上限；runtime 传保序结构至 adapter，不让 `image_path` 与 `image_paths` 重复编码首图；对外错误说明型号和具体限制。`/motion` 不用作首尾帧通用入口，`/video-edit` 逐一映射任务字段，Draft 必须两次冻结结算并处理任务 ID 有效期。
5. **成本与自动时长先设硬门槛。** 确定时长且不含输入视频的价格分档已在 `points_usage_pricing.py:437-449`；`-1` 当前按档案默认秒数结算（`_helpers.py:1161-1177`），参考视频未计输入秒（`routes_video_edit.py:98-115`）。在拿到实际输出秒数、上游计量及可执行的补结算/封顶口径前，不承诺「按真实秒数收费」，也不扩展自动时长/含视频任务的可售范围；请求前的估价、冻结、失败释放及实际结算必须由同一任务 schema 驱动。不能用「缺价 400」代替对输入 token、模型决策时长和分辨率的成本测试。
6. **分期验收按可执行能力，而非 UI 截图。** 第一阶段修 §10.2 两处错误台账、建立「型号 × 任务 × 官方证据 × route × runtime × adapter × 计费」矩阵及测试，并将已确认退役的旧 Qwen 编辑档从可售路径移出（细节见 §11.4）；第二阶段只为完整贯通的单素材任务出五类/小分类与差异化控件；第三阶段逐模型接双帧/多参考/编辑/组图/Draft、逐个付费冒烟。每个任务覆盖正常参数、边界、互斥、缺价拒单、付费失败释放与「用户所选型号不被静默改写」；官方资料不能取得正文或实测失败的任务保留 `integration_pending`，不得因档案标签自动放行。

### 11.4 旧 Qwen 图片编辑退役后的替代路线（本轮用户确认）

**阻断现状：** `qwen-image-edit-plus`、`qwen-image-edit-max` 已完全退役，不再视作「待确认是否停服」。`config/models.yaml` 仍标 `active`；`asset_studio_model_catalog.py:39-42,81-84` 把两档作为图片编辑全集并默认 plus；`routes_image.py:74-117` 上传图片后只允许旧编辑组，其他已选模型会静默切成 plus；`core/unified_media_runtime.py:34` 的 `edit_image` 白名单也只有两档。此状态下参考图提交不能保证成功，也不保证执行用户所选型号。**不能仅修改前端下拉或替换默认 ID**；迁移获批准前不要把未贯通的新编辑模型伪装成可用。

| 现役图片型号 | 官方可用编辑形态 | 迁移定位和接通条件 |
|---|---|---|
| `qwen-image-3.0` | 1–3 张图的图生/指令编辑；输出 1–6 张 | 推荐普通编辑默认候选；复用其现有 `generate_image` adapter，但须核实编辑任务的 API 载荷、接 `edit_image` 或明确统一操作语义、正确传全部图，不能只凭 `image_to_image` 标签入白名单 |
| `qwen-image-3.0-pro` | 同系列图生/编辑能力 | 推荐用户可选高质量档；输入/输出与计价单独按该档验证，不能用普通档报价 |
| `wan2.7-image-pro` | 0–9 张图、编辑/多参考/组图、区域框选 `bbox_list`；编辑与组图最高 2K | 推荐多图/区域编辑档；需独立校验素材顺序、区域坐标与 `n`，且按任务裁剪 4K，否则无图文生能力会误传给编辑态 |
| `kling/kling-v3-image-generation` | 单张参考图任务；不等于 Omni 的多图编辑 | 条件备选：先补档案任务声明，核对异步 adapter 的素材 URL 与回调，再做单图冒烟 |
| `kling/kling-v3-omni-image-generation` | 多图参考、组图，参考图＋主体合计≤10 | 条件备选：当前 adapter 只读首图，上传图片编码为 data URL 而官方要求 HTTP(S) URL；需先接素材托管及异步组包，再按官方任务语义确认是否称「编辑」 |
| `doubao-seedream-5-0` / `-pro` | 档案写有图生/编辑，官网规格正文本轮无法核实 | 暂列待核实，不仅凭 YAML 标签承诺多图、局部编辑或具体上限；先取得官方 API 原文与模型级调用证据 |

证据：百炼原文 `raw/model-api-reference/image-generation/qwen-image-api-reference/qwen-image-generation-and-editing-api-reference.md`、`raw/model-api-reference/image-generation/wan-image-api-reference/wan-image-generation-and-editing-api-reference.md`、`raw/model-api-reference/image-generation/kling-image-api-reference/kling-image-generation-api-reference.md`；本地编辑选择 `backend/app/api/v1/asset_studio_api/routes_image.py:74-117`，适配器 `adapters/dashscope/image_sync.py:35-55,77-114`、`adapters/dashscope/image_async.py:31-53,106-127`、`adapters/volcengine/image.py:54-73`。视频的 `reference_images`、视觉理解的图片输入均不产出静态编辑图，不能拿来充当图片编辑替代。

**前后端组件与验收顺序：**先让 manifest 不再发退役档作为可售项，并移除失效默认与静默切模；在新操作尚未贯通前，参考图入口应明确拒绝而不是回退旧型号。接着逐档接 `ImageTaskSelector`（文生/单图编辑/多图参考/区域编辑/组图）、`ImageReferenceSlots`（1–3、0–9 或 Omni 专属上限）、模型专属尺寸/数量控件与可见报价；后端把用户所选任务与型号从 route 原样传至 runtime/adapter，完成 MIME、大小、数量、URL/异步素材要求及输出尺寸校验。`core/unified_media_runtime.py:19-35` 的生成/编辑白名单和 `image_to_image_edit` 路由语义需与新档对齐；`adapters/dashscope/image_sync.py` 等不能只取首张图。当前 `points_usage_pricing.py:429-435` 的参考编辑按固定环境价、不分型号和输出数量，迁移前须有模型级价档、缺价拒单、冻结/结算对拍，并测试「上传图不会静默切型号」「退役档不可选不可路由」「多图全数进载荷」及失败释放。官方能力确认不代表此时已可售。

---

## 附录 A：即梦（Dreamina）生成页实测证据（2026-10-09，浏览器实取）

- 顶层三个下拉：**类型**（Agent 模式 / 图片生成 / 视频生成 / 音乐生成 / 音频生成 / 数字人 / 动作模仿）、**模型**、**模式**。
- 模型下拉每项带一行定位副标题：`即梦 Seedance 2.5`＝「最强模型，支持 50 个参考，新增视频编辑、超长生成」；**`即梦 Seedance 2.5 (样片模式)` 是独立条目**＝「节省预算，先生成 480P 样片，选择满意版本后直出高分辨率版本」；列表还含 2.0 mini / 2.0 Fast VIP / 2.0 VIP / 2.0 Fast / 2.0 / 1.0 / 1.0 Fast / HappyHorse 1.1 / **Wan 3.0**。
- **模式**（即小分类）：全能参考 / 首尾帧 / 智能多帧 / 智能编辑 / 超长视频。
- 工具栏：汇总按钮 `16:9 720P 1` + 独立时长按钮 `5s`；浮层分三组——选择比例（6 chip）/ 选择分辨率（chip **按模型裁剪**：mini 只有 720P，2.5 有 480P/720P/1080P）/ 选择生成数量（1–4）。
- 时长浮层：标题「选择视频生成时长」，**真 slider**（`role=slider`，轨道 `aria-valuemin=0`、`valuemax=15`；2.5 变 0→30；每 5 秒一个文字刻度；15 秒档 11 个点、30 秒档 20 个点）**+ 独立数字输入框**（`aria-valuemin=4`、`valuemax=15`→`30`，当前值 5）。
- 即梦**没有「智能时长」选项**（该位为可灵式纯 slider）；「智能编辑」模式下时长按钮变为字符串 **「自动」且 `aria-disabled=true`**，汇总变「自动 720P 1」，并多出一个「高级编辑」入口，提示词 placeholder 被改写为编辑指引。
- 参考上限通过 placeholder 文案外露（mini 12、2.5 50）；工具栏实时显示积分消耗（mini 30/45，2.5 100/130）。

三平台取舍（决策来源）：可灵＝纯 slider（本方案时长形态）；百炼＝模式 chip（本方案智能时长形态）；即梦＝汇总按钮 + 分组浮层 + 分辨率按模型裁剪 + 样片模式独立条目（本方案工具栏与信息架构形态）。

## 附录 B：涉及的上游计费事实（写进 YAML 注释与文案用）

- 火山方舟视频按 token：`token 用量 =（输入视频秒 + 输出视频秒）× 宽 × 高 × 帧率 / 1024`，实际以 `usage.completion_tokens` 为准；**仅成功生成计费**；含输入视频时有最低 token 用量下限。
- 刊例价（元/百万 token）：2.5 = 70.00（480p/720p 无视频）/ 42.00（含视频）/ 77.00（1080p 无视频）/ 46.00；2.0 = 46/28、51/31、4k 26/16；2.0-fast 原价 37/22。
- 官方示例价（16:9、输出 5 秒、不含输入视频，元/个）：2.5 = 3.36 / 7.56 / 18.71（480p/720p/1080p）；2.0 = 2.31 / 4.97 / 12.39 / 25.27（…/4k）；fast = 1.86 / 4.00。
- Draft 两步计费：Step1 按 480p 计费，Step2 按目标分辨率计费，Step2 单价取决于 Step1 是否含输入视频，**Draft 成片不计入输入时长**；两步都收费。
- 已实测：2.5 480p/4s 一条 94 秒、38,830 tokens ≈ 2.7 元（`cgt-20261008153554-cao75`）。
- 付费档位探测纪律：参数非法在提交阶段即被拒、不计费；任务进入 running 后无法删除（`409 InvalidAction.RunningTaskDeletion`），故新分辨率/新时长务必先用 **480p + 最短时长**验证。
- 本项目冻结口径（2026-10-09 落地）：按秒计费的条目（wan3.0 / kling / vidu / pixverse）直接取 `pricing_info.tiers[].price_per_second`；按 token 计费的 seedance 三档取 `pricing_info.per_second_estimate.tiers[].price_per_second`，其值等于官方示例价 ÷ 5 秒的线性外推（`18.71 → 3.742` 等）。分辨率档一律按 `pick_resolution_label` 的**短边**判定，不按精确尺寸匹配上游 `size_values`。

## 附录 C：本文引用的关键代码位置速查

| 主题 | 位置 |
|---|---|
| 时长区间真值（代码级） | `adapters/dashscope/video_wan3.py:50-53, 174-177`；`adapters/volcengine/video.py:24, 60-61, 73-74, 83-84, 195-202` |
| 时长塌档位 | `schemas/model_spec.py:36-47` |
| range 语义被 `values` 遮蔽 | `core/unified_media_runtime.py:1029, 1060-1072, 1134-1167` |
| 15 秒硬钳制 | `backend/app/api/v1/asset_studio_api/routes_video.py:83, 218`；`routes_video_edit.py:91` |
| 时长校验 | `backend/app/api/v1/asset_studio_api/_helpers.py:987-1024, 1110-1145, 1146-1158` |
| manifest（活通道） | `backend/app/services/asset_studio_model_catalog.py:14-105, 124-127, 176-239, 256-273` |
| 快照生成（潜在缺陷） | `backend/app/services/model_catalog_bootstrap.py:613-625`；`model_catalog_projection.py:14-31, 119-164` |
| 前端时长/尺寸控件 | `frontend/src/components/home/AssetStudioWorkbench.tsx:2657, 2778, 2897, 2907, 3020, 3030, 3062, 3084, 3277` |
| 前端选项解析链 | 同文件 `148`（`buildCatalogDurationOptionsByModel`）、`610-661`（硬编码档位）、`800+`（音频档位）、`876-898`（`getRuntimeDurationOptions`）、`900-926`（`filterSizeOptions`）、`935-944`（参考上限）、`2277-2295`（越界重置）、`2461/2497/2569`（提交体） |
| 前端类型 | `AssetStudioWorkbench.tsx:223-247`；`frontend/src/services/api.ts:1018-1035, 2162` |
| 大类入口定义 | `frontend/src/components/home/modelEntryData.ts:9, 24-85`；`frontend/src/pages/AssetStudioPage.tsx:23` |
| 计费 basis | 取价 `backend/app/services/asset_studio_model_catalog.py:349`（`resolve_video_price_per_second`）、分档口径 `backend/app/services/points_usage_pricing.py:411`（`estimate_asset_studio_basis_yuan`）、入口拒单映射 `backend/app/api/v1/asset_studio_api/_helpers.py:1154`；改造前的单一均价在 `points_usage_pricing.py:423-433` |
