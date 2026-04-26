# User Asset Local Storage Metadata Contract

日期：`2026-04-25`
版本：`2026-04-25.7`

## 1. 目的

本文档定义 `UserAssetRecord.metadata_json` 中与 local-first 本地存储相关的共享契约字段，作为：

- 机器可读 contract：`frontend/src/contracts/userAssetLocalStorage.schema.json`
- 前端运行时 contract 封装：`frontend/src/contracts/userAssetLocalStorageContract.ts`
- 后端 schema / OpenAPI 暴露：`backend/app/schemas/user_asset.py`

本文档解决的问题不是“声明所有 `metadata_json` 业务字段”，而是明确：

- `local_storage_*` 已知字段的含义
- 前后端对这些字段的归一化规则
- 允许的兼容边界与演进约束

## 2. Contract Snapshot

- Contract ID：`novel-writing-agent://contracts/user-asset-local-storage-metadata/v1`
- Contract Version：`2026-04-25.7`
- Contract Owner：`user-assets/local-first`
- Schema Path：`frontend/src/contracts/userAssetLocalStorage.schema.json`
- Doc Path：`docs/contracts/USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md`
- Generator Script：`scripts/generate_user_asset_local_storage_contract.py`
- Frontend Generated Definitions：`frontend/src/contracts/userAssetLocalStorageContract.generated.ts`
- Backend Generated Definitions：`backend/app/schemas/user_asset_local_storage_contract_generated.py`

### 2.1 生成与校验规则

以下文件属于 **schema 派生产物**，不允许手改：

- `frontend/src/contracts/userAssetLocalStorageContract.generated.ts`
- `backend/app/schemas/user_asset_local_storage_contract_generated.py`

维护流程：

1. 修改 `frontend/src/contracts/userAssetLocalStorage.schema.json`
2. 运行 `python scripts/generate_user_asset_local_storage_contract.py` 重新生成
3. 运行对应前后端测试
4. 在 CI / 本地快速自检：`python scripts/generate_user_asset_local_storage_contract.py --check`
   - `--check` 仅校验派生产物是否与当前 schema 一致，不写文件；若不同步以非零退出码退出
5. CI 通过 `.github/workflows/contracts.yml` 对派生产物漂移、后端契约测试与前端契约测试做持续校验

## 3. 字段范围

当前纳入共享 contract 的已知字段只有以下四项：

| 字段 | 类型 | 约束 | 说明 |
| --- | --- | --- | --- |
| `local_storage_driver` | `string \| null` | 枚举：`legacy_indexeddb` / `opfs` / `external_directory`* | 本地副本当前使用的存储驱动 |
| `local_storage_path` | `string \| null` | `maxLength = 1000` | 本地副本的可迁移逻辑路径，例如 OPFS 路径 |
| `local_persist_level` | `string \| null` | 枚举：`best_effort` / `persistent_requested` / `user_directory`* | 本地副本当前申请到的持久化级别 |
| `external_relative_path` | `string \| null` | `maxLength = 1000` | 当使用用户目录等外部存储时，对应的相对路径 |

> *`external_directory` 驱动与 `user_directory` 持久化级别已启用最小运行时能力：当前 `localAssetVault` 支持在用户已授权目录句柄时执行保存 / 读取 / 删除；实现上 `local_storage_path` 与 `external_relative_path` 当前都会记录同一相对路径，其中 `external_relative_path` 是用户目录语义的显式字段。当前优先写入用户目录的显式入口仅包括 Asset Studio 工作台收录与 Audiobook 章节成品音频手动收录；DreamWeaver Library / Run 归档当前仍登记 `durable_cloud` 元数据，不走本地镜像写入。播放器自动缓存仍保留在浏览器管理的本地存储中；当目录权限失效时，用户中心顶部会给出目录健康提示，且会额外对登记为 `external_directory` 的资产做轻量健康校验：目录不可用时提示先恢复访问，目录可用但未读取到本地副本时提示“若这是主动清理可忽略，否则可重新收录”；当前这些健康校验结果还能导出为重建清单，按 `directory_inaccessible / missing_local_copy` 问题类型列出待处理资产。面板也会提供“恢复访问”入口、备份建议、“导出备份说明 / 本地资产清单 / 重建清单”入口，并支持对当前页缺失副本直接触发批量重新收录；跨页扫描则会先提供“扫描当前筛选（预览）”，并把缺失副本 / 目录异常明细直接展示在页内结果摘要下方，帮助用户先判断范围再决定是否执行重建；对 `missing_local_copy` 明细项可直接触发单项“重新收录到本地”，对两类明细项都可直接回到对应来源页。若显式收录发生回退，前端会明确提示已改存浏览器本地存储。*

## 4. 归一化规则

前端运行时与后端 schema 当前必须保持以下一致行为：

1. `metadata_json` 必须是对象；`null` 视为 `{}`。
2. 已知枚举字段在校验前要先做 `trim`，再转小写。
3. 已知枚举字段若为空字符串，归一化为 `null`。
4. 已知枚举字段若不在允许集合内，必须拒绝而不是静默透传。
5. `local_storage_path` 与 `external_relative_path` 需先 `trim`。
6. 上述两个路径字段若为空字符串，归一化为 `null`。
7. 上述两个路径字段超过 `1000` 字符时：
   - 前端归一化执行 `slice` 截断，保证调用方仍能构造出可序列化的 metadata（防御性行为），并同时通过 `console.warn` 记录被截断的 `fieldName` 与原始长度，避免"静默变短"难以定位
   - 后端 `UserAssetMetadata` 归一化拒绝（抛 `ValueError`），以贴合 JSON Schema `maxLength` 语义并阻止静默数据丢失；同样的"超长即拒绝"策略已扩展到 `source_uri / preview_uri / download_uri`（上限 `1000`），错误信息中会带上具体 `field_name`
8. 未纳入本 contract 的其它 `metadata_json` 字段当前允许保留，不在本 contract 中阻断。
9. `storage_mode` 取值中 `local_only` 当前属 **reserved**：JSON Schema 仍收录以避免派生产物漂移，但后端 `validate_storage_mode` 会显式拒写该值，防止写入链路提前进入尚未落地的仅本地语义。

### 4.1 前端构造约束

在前端调用 `createUserAsset(...)` 时，业务页面不要分散手写 `metadata_json: { ... }`，应通过共享 helper 收口：

- `buildUserAssetMetadataContract(...)`：合并多个 metadata 片段
- `normalizeUserAssetMetadataContract(...)`：对已知 `local_storage_*` 字段执行最终归一化
- `frontend/src/contracts/userAssetMetadataBuilders.ts` 中的场景化 builder

已收口的页面场景：Asset Studio 本地收录、Audiobook 章节成品音频手动收录、DreamWeaver 资料库素材归档、DreamWeaver 最终合成视频归档。

其中：

- Asset Studio 本地收录与 Audiobook 章节成品音频手动收录会落入 `localAssetVault` 本地镜像链路，并在可用时优先写入用户目录
- DreamWeaver 资料库素材归档与最终合成视频归档当前仍登记 `durable_cloud` 元数据，不走本地镜像写入

### 4.2 `source_payload_json` 的当前定位

`source_payload_json` **不是** 本文档所定义的正式共享 schema 契约对象，但项目已经围绕它沉淀了一套共享读写基础设施（builder / selector / reader / preview resolver / hook / presenter / view-model 等）。其详细演进历史不再追加进本契约文档，若需要查阅可参考 `docs/LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md` 的变更记录段落。

对 `source_payload_json` 的当前硬性要求：

- 不在业务页面里零散手写 `source_payload_json: { ... }`
- 写入侧统一通过 `frontend/src/contracts/userAssetSourcePayloadBuilders.ts`
- 读取侧统一通过 `frontend/src/contracts/userAssetSourcePayloadSelectors.ts`、`userAssetSourceReaders.ts`、`userAssetPreviewResolvers.ts`
- 不得与 `metadata_json.local_storage_*` 的正式 schema 契约混为一谈

补充边界说明：

- 自 `2026-04-24` 的收口后，新写入链路不再向 `source_payload_json` 复制 `local_asset_storage` 镜像
- Audiobook 场景的 source payload builder 现在也会显式剔除 `local_storage_driver / local_storage_path / local_persist_level / external_relative_path`，避免通过合并 `assetMetadata` 让本地驱动细节回流
- 历史记录里若仍残留该镜像，只能视为读侧兼容信息，不参与正式 schema 校验，也不替代 `metadata_json.local_storage_*` 的权威语义
- 若历史镜像与 `metadata_json.local_storage_*` 出现冲突，应以 `metadata_json.local_storage_*` 为准

是否为 `source_payload_json` 立一份同级最小契约，待 `project_id / run_id / library asset / audiobook chapter trace` 四类来源字段形状稳定后再评估。当前四类来源的事实形状已整理在 `docs/contracts/USER_ASSET_SOURCE_PAYLOAD_SHAPES.md`（**草稿 / 形状备忘录**，不参与 `--check` 派生产物校验）。

## 5. 职责边界

- `storage_mode`
  - 表达资产生命周期，例如 `local_mirror` / `local_only`
  - 不表达底层本地驱动实现细节
- `metadata_json.local_storage_*`
  - 表达本地副本落地方式、路径与持久化级别
  - 允许随本地资产层演进，但必须继续受共享 contract 约束

## 6. 兼容性规则

- `metadata_json` 允许额外字段存在，避免阻断现有业务扩展
- 新增 local-first 相关公共字段时，应优先先更新本 contract，再进入前后端代码
- 不允许把新的驱动类型直接塞进 `storage_mode`
- 不允许前后端各自手写一套不同的本地驱动枚举或路径长度约束

## 7. 演进要求

未来若修改以下任一内容，必须同步更新 schema、文档、测试与绑定实现：

- `local_storage_driver` 枚举（含新增 / 删除 / 语义升级）
- `local_persist_level` 枚举
- 已知路径字段的 `maxLength`
- 归一化语义
- contract version / owner / path / doc path

至少需要同步检查：

- `frontend/src/contracts/userAssetLocalStorage.schema.json`
- `frontend/src/contracts/userAssetLocalStorageContract.generated.ts`
- `frontend/src/contracts/userAssetLocalStorageContract.ts`
- `backend/app/schemas/user_asset_local_storage_contract_generated.py`
- `backend/app/schemas/user_asset.py`
- `frontend/src/contracts/__tests__/userAssetLocalStorageContract.test.ts`
- `backend/tests/test_user_asset_metadata_contract.py`

完成修改后必须执行 `python scripts/generate_user_asset_local_storage_contract.py --check` 自检。

## 8. 当前实现状态（Implementation Status）

| 项 | 状态 | 说明 |
| --- | --- | --- |
| 共享 JSON schema snapshot | ✅ 已落地 | `userAssetLocalStorage.schema.json` |
| 前端运行时归一化绑定 | ✅ 已落地 | `userAssetLocalStorageContract.ts` |
| 后端 schema / OpenAPI 注解绑定 | ✅ 已落地 | `backend/app/schemas/user_asset.py` |
| 派生产物生成脚本 | ✅ 已落地 | `scripts/generate_user_asset_local_storage_contract.py`（支持 `--check`） |
| 契约 CI 漂移校验 | ✅ 已落地 | `.github/workflows/contracts.yml` |
| `legacy_indexeddb` 驱动 | ✅ 已落地 | 历史写入与兼容回退 |
| `opfs` 驱动（写 / 读 / 持久化申请） | ✅ 已落地 | `frontend/src/utils/localAssetVault.ts` |
| `legacy → opfs` 懒迁移（读时触发） | ✅ 已落地 | `getLocalAsset → maybeMigrateLegacyBlobToOpfs` |
| `legacy → opfs` 主动批量迁移入口 | ✅ 已落地 | `migrateLegacyLocalAssetsToOpfs()` |
| `legacy → opfs` 启动空闲期批量迁移调度 | ✅ 已落地 | `frontend/src/main.tsx` 已在应用启动后空闲时触发，并落地 `legacyLocalAssetMigration:v2:status` 状态快照；仅当 `skipped = 0` 且 `failed = 0` 时记为 `completed` |
| `external_directory` 驱动（File System Access API） | ✅ 已落地最小运行时能力 | `localAssetVault` 已支持在用户目录句柄存在时写入、读取、删除与回退；用户中心已补上目录状态展示、恢复访问与选择/清除入口，并把目录异常提示提升到资产页顶部；当前还会对登记为 `external_directory` 的资产做轻量健康校验，在目录不可用或本地副本未读取到时给出恢复/重建提示，同时支持导出问题资产重建清单，并在面板中补上备份建议、“导出备份说明 / 本地资产清单 / 重建清单”入口，以及“扫描当前筛选（预览） / 重建当前页缺失副本 / 扫描当前筛选并重建”快捷动作；对于扫描/重建动作，面板还会展示执行中提示、最近一次结果摘要，以及可展开的缺失副本 / 目录异常明细，便于先预览范围再决定是否执行真正重建；其中 `missing_local_copy` 明细项已可直接触发单项重新收录，两类明细项都已支持直接回到来源页；当前已接入 Asset Studio 工作台收录与 Audiobook 手动收录两条显式本地镜像入口 |
| `user_directory` 持久化级别 | ✅ 已落地最小运行时能力 | 当资产实际写入用户授权目录时由运行时写入 |
| `requestLocalAssetPersistence()` 已接入 `navigator.storage.persist()` | ✅ 已落地 | 未授权 / best_effort 场景仍会受浏览器清理策略影响，属预期行为；`external_directory` 成功分支也会再触发一次 `persist()` 兜底 |
| 全局 `LocalAssetHealthBanner` | ✅ 已落地 | `frontend/src/components/user-assets/LocalAssetHealthBanner.tsx`，挂载于 `App.tsx` 顶部，分别覆盖"浏览器不支持"/"外部目录需要重新授权"/"外部目录授权被拒绝"三种场景，可 24h 内临时忽略 |
| Audiobook `chapter_audio_runs` checkpoint 清理诊断 | ✅ 已落地 | `temp_segment_janitor` 会把 `oss_delete_credentials_missing / oss_candidate_count / removed_temp_files_best_effort` 写入 checkpoint，供事后排查 best-effort 清理 |
| `storage_mode=local_only` reserved 拒写 | ✅ 已落地 | `backend/app/schemas/user_asset.py` `RESERVED_STORAGE_MODES` |
| schema `x-contract-compat-level` | ✅ 已落地 | `userAssetLocalStorage.schema.json` = `backward_compatible`，透传到 TS / Python 派生产物 |
| `source_payload_json` JSON Schema 草案 | ⏳ 草案 / 非绑定 | `frontend/src/contracts/userAssetSourcePayload.schema.json`（`x-contract-status: draft`、`x-runtime-enforced: false`），不参与 `--check` |
| `can_resume` blockers 回归 | ✅ 已落地 | `backend/tests/test_audiobook_can_resume_blockers.py` 覆盖 11 类 blockers + 去重 |

下一步优先方向：

- 减少剩余手写字面量定义，继续把 user-assets / local-first 调用点围绕本 contract 绑定
- 继续把 `external_directory` 从“底层可用”推进到“产品可用”：在已补齐异常提示、恢复引导、基础备份建议、“导出备份说明 / 本地资产清单 / 重建清单”入口的前提下，继续把重建清单推进到更顺手的回源补录执行流，并把“先预览、再决定是否执行重建”的问题明细保持为默认能力，对未来新增显式收录入口持续做 `preferredStorageDriver` 准入审查
- 用户中心已补上仅针对 `local_mirror` 资产的“清理本地副本”与“重新收录到本地”入口，并已扩展到批量动作；当前“清理本地副本”语义明确为“只清理当前浏览器中的本地镜像”，不联动改写服务端生命周期字段；“重新收录到本地”则会优先遵守 `metadata_json.local_storage_driver`，若登记为 `external_directory` 但目标目录当前不可用，会直接阻塞并提示恢复访问，而不是静默回退到其他驱动
- `legacyLocalAssetMigration:v2:status` 已接入用户中心轻量诊断提示，并通过同页事件同步刷新，便于排查启动迁移是否仍有 `partial / failed` 状态
- 继续把本地资产生命周期能力从 `save / get / delete` 推进到更完整的 GC / 重建 / 诊断工具链

> 备注：`LOCAL_FIRST_ASSET_ARCHITECTURE_PLAN_20260419.md` 中的实现状态表以本文件本节为准，避免两处状态漂移。

## 9. 变更历史（Changelog）

| 版本 | 日期 | 变更摘要 |
| --- | --- | --- |
| `2026-04-25.7` | 2026-04-25 | 用户中心用户目录面板把“回到来源页”进一步升级为精确上下文回跳：DreamWeaver Run 会带上 `runId`，素材库会带上 `assetId` 并自动定位/高亮，有声书会带上 `audiobookProjectId + chapterId + focus=script-editor` 并直接打开对应章节剧本编辑器。 |
| `2026-04-25.6` | 2026-04-25 | 用户中心用户目录面板继续把预览明细推进成可定位入口：缺失副本与目录异常明细项现在都可以直接回到对应来源页，减少从预览结果再回到资产卡片区寻找来源入口的跳转成本。 |
| `2026-04-25.5` | 2026-04-25 | 用户中心用户目录面板继续把预览明细推进成可执行入口：`missing_local_copy` 明细项现在可以直接触发单项“重新收录到本地”，减少从预览结果再回到资产卡片区定位目标资产的跳转成本。 |
| `2026-04-25.4` | 2026-04-25 | 用户中心用户目录面板把“扫描当前筛选（预览）”结果进一步产品化：最近一次扫描/重建摘要下方会展开缺失副本与目录异常明细，帮助用户在真正执行重建前先确认影响范围、路径与处理建议。 |
| `2026-04-25.3` | 2026-04-25 | 用户中心用户目录面板新增“扫描当前筛选（预览）”动作，并把跨页扫描结果与真正重建结果在页内摘要中区分开来：预览阶段只给出扫描命中与待重建数量，实际执行重建时再显示恢复结果。 |
| `2026-04-25.2` | 2026-04-25 | 用户中心用户目录面板为“重建当前页缺失副本 / 扫描当前筛选并重建”补上页内可观测性：执行时展示活动提示，完成后保留最近一次扫描/重建摘要，包含扫描范围、目录副本命中数、缺失副本数与恢复结果。 |
| `2026-04-25.1` | 2026-04-25 | 用户中心用户目录面板新增“扫描当前筛选并重建”动作：会跨页拉取当前筛选结果，复用同一套 `external_directory` 健康扫描逻辑识别 `missing_local_copy` 项，并对可恢复项直接复用现有批量“重新收录到本地”能力。 |
| `2026-04-24.10` | 2026-04-24 | 用户中心用户目录面板补上“重建当前页缺失副本”快捷动作：对当前页已检测到 `missing_local_copy` 的 `external_directory` 资产直接复用现有批量“重新收录到本地”能力，减少从导出清单回到页内逐项处理的跳转成本。 |
| `2026-04-24.9` | 2026-04-24 | 用户中心用户目录面板补上“导出重建清单”入口；`external_directory` 健康校验从纯数量提示扩展为可导出的问题资产明细，按 `directory_inaccessible / missing_local_copy` 区分待处理项，便于后续逐项补录。 |
| `2026-04-24.8` | 2026-04-24 | 12 项一致性改造落地：schema 引入 `x-contract-compat-level: backward_compatible` 并透传到 TS / Python 派生产物；后端 `storage_mode=local_only` 显式拒写；`source_uri / preview_uri / download_uri` 超长由截断改为拒绝；前端 metadata 路径截断新增 `console.warn` 诊断；新增 `LocalAssetHealthBanner` 全局顶部健康提示；`chapter_audio_runs` checkpoint 清理诊断落地；新增 `test_audiobook_can_resume_blockers.py` 覆盖全部 blockers；`source_payload_json` 形状落成 draft JSON Schema（非绑定、不入 `--check`）。 |
| `2026-04-24.7` | 2026-04-24 | 用户中心补上“重新收录到本地”单资产/批量入口：仅对 `local_mirror` 资产生效，恢复时优先遵守 `metadata_json.local_storage_driver`；若登记驱动为 `external_directory` 但目录不可用，则阻塞恢复并提示先恢复访问，避免静默换驱动造成 metadata 与真实本地状态失真。 |
| `2026-04-24.6` | 2026-04-24 | 激活 `external_directory / user_directory` contract 取值；`localAssetVault` 落地 File System Access API 用户目录的最小运行时能力（保存 / 读取 / 删除 / OPFS 回退）；用户中心“清理本地副本”扩展到批量动作，并补上用户目录状态展示与选择/清除入口；当前仅显式收录链路优先写入用户目录。 |
| `2026-04-24.5` | 2026-04-24 | 用户中心新增仅针对 `local_mirror` 资产的“清理本地副本”入口，动作语义明确为“只清理当前浏览器中的本地镜像”；同时把 `legacyLocalAssetMigration:v2:status` 接入前端轻量诊断提示，并通过同页事件同步刷新。 |
| `2026-04-24.4` | 2026-04-24 | Audiobook source payload builder 显式剔除 `local_storage_*` / `external_relative_path`，彻底阻止本地驱动细节回流到 `source_payload_json`；启动迁移状态仅在 `skipped = 0` 且 `failed = 0` 时记为 `completed`，否则保持可重试。 |
| `2026-04-24.3` | 2026-04-24 | 明确新写入链路不再向 `source_payload_json` 复制 `local_asset_storage` 镜像；历史镜像仅作为兼容读侧信息；补充启动空闲期迁移会写入 `legacyLocalAssetMigration:v2:status` 状态快照，并把本地资产生命周期能力现状更新为 `save / get / delete`。 |
| `2026-04-24.2` | 2026-04-24 | `local_storage_path` / `external_relative_path` 超长在后端侧由「截断」改为「拒绝」（抛 `ValueError`）；前端保留截断作为防御性归一化；CI 后端依赖锚定 `backend/requirements-contract.txt`；新增 pydantic ↔ JSON Schema 的 enum active 值跨检。 |
| `2026-04-24.1` | 2026-04-24 | 引入 `x-reserved-values`，`external_directory` / `user_directory` 明确为 reserved；生成器暴露 `USER_ASSET_ACTIVE_*` 与 `USER_ASSET_RESERVED_*` 两类集合；`UserAssetMetadata` 使用 Active Literal。 |
