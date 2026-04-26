# User Asset `source_payload_json` 形状备忘录（非正式契约）

日期：`2026-04-24`
状态：**草稿 / 形状备忘录**（未升格为正式 JSON Schema 契约）

> 本文件不是共享 JSON Schema 契约，不进入 `--check` 派生产物校验链。
> 它的目的只有一个：把当前 `UserAssetRecord.source_payload_json` 在四类来源下的事实形状集中记录下来，作为后续决定是否升格为 `v1` 正式契约的前置资料。
>
> 对应的结构化草案见 `frontend/src/contracts/userAssetSourcePayload.schema.json`（`x-contract-status: draft`，`x-runtime-enforced: false`，不参与派生产物校验）。
>
> 正式 schema 契约见 `docs/contracts/USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md`（它只覆盖 `metadata_json.local_storage_*`，不涉及 `source_payload_json`）。

---

## 1. 写入侧权威入口

所有写入 `source_payload_json` 的业务调用必须通过以下 builder（不得在页面中零散手写 `source_payload_json: { ... }`）：

- `frontend/src/contracts/userAssetSourcePayloadBuilders.ts`
  - `buildAssetStudioCollectedSourcePayload`
  - `buildAudiobookChapterAudioSourcePayload`
  - `buildDreamWeaverLibrarySourcePayload`
  - `buildDreamWeaverMergedVideoSourcePayload`
  - 通用合并器：`buildUserAssetSourcePayload(...parts)`

## 2. 读取侧权威入口

- `frontend/src/contracts/userAssetSourcePayloadSelectors.ts`：字段级 selector
- `frontend/src/contracts/userAssetSourceReaders.ts`：读取行为封装
- `frontend/src/contracts/userAssetPreviewResolvers.ts`：预览解析

## 3. 四类来源的当前事实形状

### 3.1 Asset Studio 本地收录 — `AssetStudioCollectedSourcePayload`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `kind` | `string \| null` | 业务类型标识 |
| `mode` | `string \| null` | 采集模式 |
| `model_id` | `string \| null` | 使用的模型 id |
| `assets` | `AssetStudioMediaAsset[]` | 采集结果集合 |
| `primary_asset` | `AssetStudioMediaAsset \| null` | 主资产 |
| `metadata` | `Record<string, unknown>` | 业务自定义附加 |

### 3.2 Audiobook 章节成品音频 — `AudiobookChapterAudioSourcePayload`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `type` | `'chapter_audio'` | 固定判别字段 |

（额外字段：builder 允许把 `assetMetadata` 中的业务字段合入顶层，但会显式剔除 `local_storage_driver / local_storage_path / local_persist_level / external_relative_path`；本地副本驱动细节必须继续写入 `metadata_json.local_storage_*`，而不是在 `source_payload_json` 中复制一份镜像。）

### 3.3 DreamWeaver 资料库素材 — `DreamWeaverLibrarySourcePayload`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `project_id` | `number` | 项目 id |
| `asset_id` | `string \| number` | 素材 id |
| `role` | `string \| null` | 角色/用途 |
| `uri` | `string \| null` | 指向资源 URI |
| `entity_type` | `string \| null` | 所属实体类型 |
| `entity_id` | `string \| number \| null` | 所属实体 id |
| `view` | `string \| null` | 渲染/视图提示 |
| `approved` | `boolean` | 是否已审核 |

### 3.4 DreamWeaver 最终合成视频 — `DreamWeaverMergedVideoSourcePayload`

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `run_id` | `string` | 合成任务 id |
| `project_id` | `number \| null` | 项目 id |
| `type` | `'merged_video'` | 固定判别字段 |
| `path` | `string \| null` | 产出文件路径 |

## 4. 形状稳定性评估

在以下任一项发生时，应考虑把本文件升格为正式 JSON Schema 契约（并纳入 `scripts/generate_user_asset_local_storage_contract.py` 同级的 generator + `--check`）：

1. 需要后端直接消费 `source_payload_json` 的结构化字段（而不是 opaque dict）。
2. 第五类以上的来源形状加入（说明扩展点稳定）。
3. 出现跨端版本迁移需求（需要显式 `x-contract-version`）。

在此之前，本文件仅作为"事实形状备忘录"，**不绑定 runtime 校验**。所有 runtime 归一化仍由上述 builders / selectors 承担。

## 5. 不变式（当前硬性要求）

- 不得在业务页面里零散手写 `source_payload_json: { ... }`
- 写入侧必须经过 §1 列出的 builder
- 读取侧必须经过 §2 列出的 selector / reader
- 本地副本驱动细节属于 `metadata_json.local_storage_*`，不得在 `source_payload_json` 中再复制一份并行权威
- 不得把 `source_payload_json` 与 `metadata_json.local_storage_*` 混为同一契约
