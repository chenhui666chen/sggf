# User Asset Local Storage Metadata Contract

日期：`2026-04-24`
版本：`2026-04-24.6`
权威源：`frontend/src/contracts/userAssetLocalStorage.schema.json` 的 `x-contract-version`

本文档只定义 `UserAssetRecord.metadata_json` 里与 local-first 本地存储相关的共享字段。平台架构、模块收录策略、用户中心面板行为见 [本地优先资产架构说明](../LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md)。

## 1. 目的

作为以下三处的人类可读说明：

- 机器可读 contract：`frontend/src/contracts/userAssetLocalStorage.schema.json`
- 前端运行时封装：`frontend/src/contracts/userAssetLocalStorageContract.ts`
- 后端 schema / OpenAPI：`backend/app/schemas/user_asset.py`

不声明全部 `metadata_json` 业务字段。只约束：

- 已知 `local_storage_*` 字段的含义
- 前后端归一化规则
- 兼容边界与演进流程

## 2. Snapshot

- Contract ID：`novel-writing-agent://contracts/user-asset-local-storage-metadata/v1`
- Contract Version：`2026-04-24.6`（必须与 schema `x-contract-version`、前后端 generated 文件一致）
- Compat Level：`backward_compatible`
- Owner：`user-assets/local-first`
- Schema：`frontend/src/contracts/userAssetLocalStorage.schema.json`
- Generator：`scripts/generate_user_asset_local_storage_contract.py`
- Frontend generated：`frontend/src/contracts/userAssetLocalStorageContract.generated.ts`
- Backend generated：`backend/app/schemas/user_asset_local_storage_contract_generated.py`

generated 文件禁止手改。改 schema 后执行：

1. `python scripts/generate_user_asset_local_storage_contract.py`
2. 跑对应前后端契约测试
3. `python scripts/generate_user_asset_local_storage_contract.py --check`

`--check` 只比对、不写文件。CI：`.github/workflows/contracts.yml`。

本文档版本号不得单独超前 schema。产品面板迭代若未改字段枚举、路径上限或归一化语义，写架构说明，不要 bump 本 contract。

## 3. 字段

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `local_storage_driver` | `string \| null` | `legacy_indexeddb` / `opfs` / `external_directory` | 本地副本当前驱动 |
| `local_storage_path` | `string \| null` | `maxLength = 1000` | 可迁移逻辑路径，常见为 OPFS 路径 |
| `local_persist_level` | `string \| null` | `best_effort` / `persistent_requested` / `user_directory` | 当前申请到的持久化级别 |
| `external_relative_path` | `string \| null` | `maxLength = 1000` | 用户目录相对路径；仅 `local_storage_driver = external_directory` 有意义 |

运行时约定（不是新字段）：

- `external_directory` 与 `user_directory` 已启用
- 写入用户目录成功时，`local_storage_path` 与 `external_relative_path` 当前记录同一相对路径；后者是用户目录语义的显式字段
- 新写入不得把这四项复制进 `source_payload_json`

## 4. 归一化

1. `metadata_json` 必须是对象；`null` 视为 `{}`。
2. 已知枚举先 `trim` 再转小写；空字符串变为 `null`。
3. 枚举不在允许集合内必须拒绝，禁止静默透传。
4. 两个路径字段先 `trim`；空字符串变为 `null`。
5. 路径超过 1000 字符：前端 `slice` 截断并 `console.warn(fieldName, originalLength)`；后端抛 `ValueError`。
6. `source_uri` / `preview_uri` / `download_uri` 超过 1000 字符时，后端同样拒绝（这三项不属于本 schema，但是同一条写入边界）。
7. 未纳入本 contract 的其它 `metadata_json` 字段允许保留。

`storage_mode` 不在本 schema 内。允许值是 `temp_cloud` / `durable_cloud` / `local_mirror` / `local_only`；其中 `local_only` 为 reserved，后端 `validate_storage_mode` 拒写。

前端构造 `createUserAsset(...)` 时不要手写 `metadata_json` 字面量，走：

- `buildUserAssetMetadataContract(...)`
- `normalizeUserAssetMetadataContract(...)`
- `frontend/src/contracts/userAssetMetadataBuilders.ts`

`source_payload_json` 不是本契约。写入用 `userAssetSourcePayloadBuilders.ts`，读取用 selectors / readers / preview resolvers。形状备忘录：`docs/contracts/USER_ASSET_SOURCE_PAYLOAD_SHAPES.md`（草稿，不进 `--check`）。历史记录若仍带 `local_asset_storage` 镜像，只作读侧兼容；冲突时以 `metadata_json.local_storage_*` 为准。

## 5. 职责边界

- `storage_mode`：资产生命周期，不编码 `indexeddb / opfs / external_directory`
- `metadata_json.local_storage_*`：本地副本怎么落地

新增本地驱动只能进本 schema，不能扩 `storage_mode`。前后端不得各写一套枚举或路径上限。

## 6. 演进

改枚举、`maxLength`、归一化、contract id/version/owner/path 时，必须同步 schema、本文档、generated 文件、`user_asset.py`、前后端契约测试，并跑 `--check`。

## 7. 契约落地状态

只记录本 schema 是否被代码绑定，不记录用户中心按钮。

| 项 | 状态 |
| --- | --- |
| JSON schema + generated TS/Python | 已绑定 |
| 前端归一化 / 后端校验 / OpenAPI 注解 | 已绑定 |
| `--check` 与 `contracts.yml` | 已绑定 |
| 三驱动枚举与三级 persist | 已写入 schema；运行时实现见架构说明 |
| `local_only` reserved 拒写 | 已绑定（在 `storage_mode` 校验，不在本 schema） |

## 8. Changelog

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| `2026-04-24.6` | 2026-04-24 | 当前 schema 快照。激活 `external_directory` / `user_directory`。文档版本收回与 schema 对齐；面板与模块现状改放到架构说明。 |
| `2026-04-24.2` | 2026-04-24 | 路径超长后端拒绝；`x-contract-compat-level` 透传。 |
| `2026-04-24.1` | 2026-04-24 | 引入 reserved / active 集合。 |