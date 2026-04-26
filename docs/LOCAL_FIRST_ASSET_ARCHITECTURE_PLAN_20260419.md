# 本地优先资产架构方案

日期：`2026-04-19`
更新：`2026-04-25`

## 1. 背景

当前项目并不是单一的媒体生成小工具，而是一个完整的小说创作平台，包含：

- 用户、项目、章节、角色、知识图谱、记忆系统等核心创作数据
- Asset Studio 图片 / 视频 / 音频生成
- DreamWeaver 短剧生成与素材资产沉淀
- Audiobook 有声书生成
- 积分、订单、权限、审核、诊断等平台能力

因此，项目不适合整体改造成“纯前端本地存储 + 后端只做代理”的极端模式。

更合理的方向是：

- 核心业务数据继续以服务端数据库为权威
- 大体积媒体结果尽量不做长期服务端持久化
- 用户侧优先持有生成资产本地副本
- 后端继续持有 API Key、鉴权、限流、风控、业务编排能力

这是一套**混合架构**，而不是纯粹的“全本地”或“全云端”。

## 2. 最终结论

本项目的最优方案不是“完全改成纯云端代理模式”，也不是“继续把所有本地文件长期直接堆进 IndexedDB”，而是：

**核心业务服务端权威 + 媒体资产 local-first + 浏览器本地资产层分级演进 + 后端代理与临时资产层**

具体原则如下：

1. 用户、项目、章节、积分、订单、审核、RAG、Agent 编排保留服务端权威。
2. 图片、视频、音频这类大文件结果不再作为长期服务端资产保存，服务端主要承担临时中转与轻量元数据登记。
3. 后端仍然负责：
   - API Key 管理
   - 第三方模型调用
   - 鉴权、限流、风控
   - 临时结果物化与对外受控暴露
4. 前端负责：
   - 通过统一 `localAssetVault` 管理本地资产
   - 当前默认层：`OPFS + IndexedDB 索引`
   - 当前兼容回退层：`legacy IndexedDB blob`
   - 用户可选增强层：`File System Access API` 本地资料库目录
   - 优先展示本地副本
   - 仅将轻量元数据登记到服务端
5. “刷新浏览器后是否丢失”需要区分两类目标：
   - **同一站点内刷新 / 重开页面后尽量不丢缓存**：默认依赖 `OPFS + IndexedDB 索引`，并配合 `navigator.storage.persist()`
   - **用户可见真实本地文件，清理站点数据后也尽量不受影响**：依赖用户授权的 `File System Access API` 目录

这套方案兼顾了：

- Key 安全
- 成本控制
- 用户本地掌控资产
- 现有平台能力可持续演进

### 2.1 代码锚点（截至 `2026-04-25`）

为避免本方案继续脱离实际代码，后续讨论应优先对照以下入口：

- `backend/app/main.py`：后端应用入口、路由挂载、Socket.IO 挂载位置
- `frontend/src/App.tsx`：当前前端主路由树
- `frontend/src/utils/localAssetVault.ts`：本地资产存储抽象与 `external_directory -> opfs -> legacy IndexedDB blob` 写入优先级
- `backend/app/api/v1/user_assets.py`：用户资产记录的收录、列表、批量更新接口
- `backend/app/schemas/user_asset.py`：用户资产 metadata contract 与 `storage_mode` 运行时约束
- `backend/app/api/v1/asset_studio_api/`：Asset Studio API 聚合入口
- `backend/app/api/v1/dreamweaver_api/`：DreamWeaver API 聚合入口
- `backend/app/api/v1/audiobook_api/`：Audiobook API 聚合入口
- `scripts/generate_user_asset_local_storage_contract.py`：前后端共享 contract 的生成与校验脚本
- `backend/tests/test_user_asset_metadata_contract.py`：后端 contract 回归校验
- `frontend/src/contracts/__tests__/userAssetLocalStorageContract.test.ts`：前端 contract 回归校验

## 3. 架构定位

本方案本质上属于：

- `BFF (Backend For Frontend)`
- `受控代理网关`
- `本地优先资产存储`
- `服务端权威业务模型`

### 3.1 浏览器侧职责

- 展示和交互
- 本地资产库（当前 `OPFS + IndexedDB 索引`，兼容回退 `legacy IndexedDB blob`）
- 用户可选长期资料库目录（`File System Access API`）
- 本地优先预览
- 临时草稿与缓存

### 3.2 服务端职责

- 登录态与用户鉴权
- 项目、章节、角色、积分、订单等业务模型
- 第三方媒体模型调用
- 将第三方结果物化为平台内部临时资产
- 资产元数据登记
- 限流、风控、审核、日志、诊断

### 3.3 第三方 AI 服务职责

- 实际的图片 / 视频 / 音频生成能力
- 外部模型推理成本承担方

## 4. 为什么不是纯“云端代理模式”

纯“云端代理模式”对本项目只有一部分适用。

适合纯代理化的部分：

- Asset Studio 的图片 / 视频 / 音频结果
- DreamWeaver 的部分成片和素材收录
- 后续可扩展到 Audiobook 的音频成品

不适合纯本地化的部分：

- 用户账号和权限
- 小说项目、章节正文、角色设定
- 知识图谱和向量检索
- 多智能体任务状态和运行上下文
- 积分、订单、结算
- 审核记录和风控记录

原因很明确：

1. 这些数据需要多设备同步。
2. 这些数据需要服务端可信。
3. 这些数据本身体积很小，节省不了多少存储成本。
4. 这些数据是平台能力的核心，不适合下放到浏览器作为唯一真相源。

## 5. 目标架构

### 5.1 总体结构

```text
┌─────────────────────────────────────────────────────┐
│                   用户浏览器                         │
│                                                     │
│  Local Asset Vault 抽象                             │
│  - 默认文件存储：OPFS                               │
│  - 本地索引：IndexedDB                              │
│  - 兼容回读：legacy IndexedDB blob                  │
│  - 可选增强：File System Access API 用户目录         │
│  - 本地 object URL / File 预览                      │
│                                                     │
│  前端应用状态                                       │
│  - 编辑器 / 用户中心 / Asset Studio / Audiobook     │
│  - 统一按 asset_uuid 读写本地资产                   │
└─────────────────────────┬───────────────────────────┘
                          │ HTTPS
                          ▼
┌─────────────────────────────────────────────────────┐
│                平台服务端（FastAPI）                 │
│                                                     │
│  核心业务层                                         │
│  - 用户 / 项目 / 章节 / 角色 / 积分 / 订单          │
│  - DreamWeaver / Audiobook / RAG / Agents           │
│                                                     │
│  媒体代理层                                         │
│  - Asset Studio 生成调用                            │
│  - 第三方结果物化为内部临时资产                     │
│  - /api/v1/asset-studio/files/...                   │
│                                                     │
│  资产元数据层                                       │
│  - user_asset_records 仅存轻量元数据                │
│  - 不长期保存大文件                                 │
└─────────────────────────┬───────────────────────────┘
                          │
                          ▼
┌─────────────────────────────────────────────────────┐
│                第三方 AI 服务提供商                  │
│  - 百炼 / 豆包 / Vidu / Mureka / 其他媒体模型       │
└─────────────────────────────────────────────────────┘
```

### 5.2 关键数据原则

- **核心业务数据**：服务端权威
- **媒体大文件**：浏览器 local-first
- **浏览器默认本地文件层**：`OPFS`
- **浏览器本地索引层**：`IndexedDB`，记录 `asset_uuid -> driver/path/metadata`
- **用户可选长期资料库**：`File System Access API` 目录
- **临时生成结果**：服务端短期存在，作为受控中转层
- **长期可见资产目录**：服务端只保留元数据，不保留大文件本体
- **storage_mode 的职责**：表达资产生命周期，不直接编码 `indexeddb / opfs / external_directory` 这类本地驱动细节

## 6. 数据模型设计

本轮将 `user_asset_records` 从旧结构：

- `file_url`
- `preview_url`

升级为统一资产元数据结构。

### 6.1 新字段

`user_asset_records` 关键字段：

- `asset_uuid`
- `storage_mode`
- `source_uri`
- `preview_uri`
- `download_uri`
- `mime_type`
- `file_size`
- `checksum`
- `expires_at`

保留并继续使用的字段：

- `source_module`
- `asset_kind`
- `asset_class`
- `title`
- `description`
- `model_id`
- `generation_mode`
- `tags`
- `metadata_json`
- `source_payload_json`
- `is_favorite`
- `archived_at`

### 6.2 storage_mode 语义

- `temp_cloud`
  - 资产当前只在平台临时资产层存在，适合刚生成未本地镜像的结果。
- `durable_cloud`
  - 资产来源于平台其他长期可访问链路，例如 DreamWeaver 受控下载端点。
- `local_mirror`
  - 资产已在用户浏览器完成本地镜像，同时仍保留服务端或临时端点兜底。
- `local_only`
  - 资产仅存在于本地，服务端只保留登记元数据。

补充说明：

- `local_only` 当前仍是模型可表达但尚未产品化的生命周期语义；截至 `2026-04-24`，主收录链路仍以 `local_mirror / durable_cloud` 为主。
- 当前不建议为了区分 `IndexedDB / OPFS / File System Access API` 而扩展 `storage_mode` 枚举。
- 用户中心当前已把“清理本地副本”定义为浏览器侧 `local_mirror` 动作：只删除当前浏览器中的本地镜像，不在这一轮联动改写服务端 `storage_mode` 生命周期。
- 本地驱动细节建议先写入 `metadata_json`，例如：
  - `local_storage_driver`: `legacy_indexeddb` | `opfs` | `external_directory`
  - `local_storage_path`
  - `external_relative_path`
  - `local_persist_level`: `best_effort` | `persistent_requested` | `user_directory`

### 6.3 当前采用策略

本轮优先采用：

- Asset Studio 收录结果：`local_mirror`
- Audiobook 章节成品音频手动收录：`local_mirror`
- DreamWeaver 合成视频 / 素材库收录：`durable_cloud`

## 7. API Contract 设计

### 7.1 Asset Studio 生成返回结构

旧结构的问题：

- 只返回 `outputs[]`
- 前端没有稳定资产主键
- 前端无法区分来源、介质类型、生命周期

新结构：

```ts
interface AssetStudioMediaAsset {
  asset_uuid: string
  media_kind: 'image' | 'video' | 'audio' | string
  storage_mode: 'temp_cloud' | 'durable_cloud' | 'local_mirror' | 'local_only'
  source_uri: string
  preview_uri: string
  download_uri: string
  file_name: string
  mime_type?: string | null
  file_size?: number | null
  expires_at?: string | null
}

interface AssetStudioGenerateResponse {
  kind: string
  mode: string
  model_id: string
  assets: AssetStudioMediaAsset[]
  primary_asset?: AssetStudioMediaAsset | null
  metadata?: Record<string, any>
}
```

收益：

- 前端可以直接按 `asset_uuid` 写入本地资产库
- 用户中心与收录逻辑不再依赖脆弱 URL
- 可以明确区分“临时云端结果”和“本地镜像结果”

### 7.2 User Asset 收录结构

收录接口现在不再接受旧的 `file_url / preview_url`，而是统一接受：

- `asset_uuid`
- `storage_mode`
- `source_uri`
- `preview_uri`
- `download_uri`
- `mime_type`
- `file_size`
- `expires_at`

这样服务端保存的就是**资产描述**，而不是“某个历史链接”。

## 8. 生成与收录链路

### 8.1 Asset Studio 生成链路

1. 前端提交生成请求。
2. 后端调用第三方模型。
3. 如果第三方返回远端 URL，后端先拉取并物化到内部临时目录。
4. 后端向前端返回内部资产描述对象 `assets / primary_asset`。
5. 前端在用户点击“收录”时下载该资产 blob。
6. 前端将 blob 写入统一本地资产层。
7. 当前显式收录链路的写入优先级为：`用户目录（已授权时） -> OPFS -> IndexedDB blob`；自动缓存链路仍保持 `OPFS` 优先写入、`IndexedDB` 承担索引与 legacy blob 回退。
8. 前端调用 `/api/v1/user-assets` 仅登记元数据。

### 8.2 用户中心预览链路

1. 用户中心拉取 `user_asset_records`。
2. 前端尝试按 `asset_uuid` 通过 `localAssetVault` 读取本地资产。
3. 当前实际读取逻辑会先按资产记录中的本地驱动读取对应副本：`external_directory -> opfs -> legacy IndexedDB blob`；若本地副本不可用，再退回受保护资源接口 / 远端 URL。
4. 若本地存在，则生成 object URL 或 File 预览。
5. 若本地不存在，则退回：
   - 受保护 DreamWeaver 文件接口
   - `preview_uri`
   - `source_uri`
   - `download_uri`

这保证了：

- 有本地副本时，优先本地展示
- 没有本地副本时，仍能从服务端链路兜底

## 9. 当前已落地内容

以下为**截至 `2026-04-24`** 已与代码对齐的实际落地状态。

### 9.1 后端

- `user_asset_records` 模型已升级为新资产字段结构
- `user-assets` schema 与 API 已升级为新 contract
- 已新增开发期迁移：
  - 直接重建 `user_asset_records` 表
  - 不兼容旧结构
- `Asset Studio` 返回结构已升级为 `assets / primary_asset`
- `Asset Studio` 已对第三方远端结果先做内部物化，再向前端暴露平台内地址
- Audiobook 侧已新增 `chapter_audio_runs` 模型、仓储与 Alembic migration，说明“运行态与最终结果拆分”已经开始落地
- Audiobook 后台任务已开始向 `chapter_audio_runs` 写入**部分**运行态 / checkpoint 信息
- 已提供 `/checkpoint` 查询接口，作为后续恢复能力的基础
- `/resume-generation` 已升级为真实排队恢复：会创建新的任务与 `chapter_audio_run`，并返回新的 `job_id`；当前在 checkpoint 持有可用 temp 片段时，已经能跳过已缓存 segment、只补缺失 segment，并且 TTS 过程中已开始按单个成功 segment 持续写 checkpoint
- Audiobook 后端已新增正式的临时分段音频存储 helper，并按 `backend/data/tmp/audiobook_runs/{engine_task_id}/chapter_{chapter_id}/segment_XXX.mp3` 物化片段
- `full` 与 `audio_from_scripts` 两条 TTS 主链路已在 `_synthesize_segments(...)` 后写入临时片段，并把 `temp_asset_prefix / cached_audio_paths / segments.*.temp_object_key` 回写到 `checkpoint_json`
- `resume-generation` 对应的新 run 现已会消费这些 checkpoint temp 片段：优先复用当前 run checkpoint，其次回退到 `source_checkpoint`，仅对缺失 segment 重新发起 TTS，并把合成后的完整片段集重新写入新的 temp cache
- `full` 与 `audio_from_scripts` 在 TTS 处理中已开始在每个成功 segment 完成后，把当前累计成功 segment 写入**新 run 自己的 temp prefix**，并同步回写 `checkpoint_json / completed_segment_count / completed_segment_indices`；当前恢复边界已推进到“单 segment 成功级安全点”
- `full` 与 `audio_from_scripts` 的项目级统计已改为按 `chapter_audios` 真实现况回算，不再在单章补跑/增量生成时把 `completed_chapters / total_duration / total_cost` 当成整批新任务重置
- 后端已新增过期临时片段 janitor：会定时清理 `expires_at` 已过期且仍可恢复的 run，把 `temp_asset_prefix / cached_audio_paths / segments` 从 checkpoint 中失效化，并把 run 标记为 `expired`
- `full` 与 `audio_from_scripts` 成功分支现已在 run 标记 `completed` 后主动清理临时片段，并把 checkpoint 中的 `temp_asset_prefix / cached_audio_paths / segments` 收口为非 resumable 的完成态
- temp segment store 已收口为 provider-aware 实现：`save` 按活动 driver 落盘，`load / exists / delete` 按路径自动分发；当前已支持 `local_fs` 与 `dashscope_oss` 两种后端，旧本地 checkpoint 与新对象存储 checkpoint 可并存恢复

### 9.2 前端

- API 类型定义已切到新 contract
- 已新增 `localAssetVault`，并已经形成稳定的 `save / get / delete` 抽象
  - 显式收录链路当前按 `用户目录（已授权时） -> OPFS -> legacy IndexedDB blob` 优先级写入
  - 自动缓存链路仍保持 `OPFS` 优先写入、`IndexedDB` 索引/兼容回退
  - `external_directory` 最小运行时底座已补齐：在已有用户目录句柄时可保存 / 读取 / 删除，并在不可用时回退到 OPFS / legacy IndexedDB blob
- 用户中心资产页已补上用户目录状态展示与“选择目录 / 恢复访问 / 清除配置 / 导出本地资产清单 / 重建当前页缺失副本 / 扫描当前筛选（预览） / 扫描当前筛选并重建 / 导出重建清单 / 导出备份说明 / 刷新状态”入口；当前已接入 Asset Studio 工作台显式收录与 Audiobook 页面手动收录，播放器自动缓存仍留在浏览器管理存储中
  - 当显式收录因用户目录不可用而回退到 OPFS / legacy 本地存储时，页面会明确提示不是写入用户目录成功
  - 资产页顶部当前也会并列展示迁移诊断与用户目录异常提示；对于登记为 `external_directory` 的资产，还会额外做轻量健康校验，在目录不可用或未读取到本地副本时提示恢复访问或重新收录；当前健康校验结果也可整理为“重建清单”导出，便于后续逐项补录
  - 目录面板中已补上基础备份建议，并可导出当前目录状态、恢复建议与备份边界说明，同时支持导出浏览器侧本地资产索引清单、按问题类型整理的本地副本重建清单，以及对“当前页缺失副本”直接触发批量重新收录
  - 对“扫描当前筛选（预览） / 重建当前页缺失副本 / 扫描当前筛选并重建”这几条动作，目录面板当前也会在页内展示执行中提示与最近一次扫描/重建结果摘要，便于回看扫描范围、目录副本命中数量、缺失副本数量与恢复结果
  - 最近一次扫描/重建摘要下方还会展开缺失副本与目录异常明细，直接给出来源模块、登记路径与处理建议，帮助用户先预览命中范围，再决定是否执行真正重建；其中缺失副本项已支持直接单项“重新收录到本地”，两类明细项也都可直接回到来源页；当前来源跳转还会尽量带上 `runId / assetId / audiobookProjectId + chapterId` 等上下文参数，在目标页自动定位、高亮或直接打开章节剧本编辑器
- `legacy → opfs` 主动批量迁移已接入应用启动后的空闲时机调度，并把最近一次执行结果写入 `legacyLocalAssetMigration:v2:status`，用于加速存量 legacy blob 清理与启动观测
  - 仅当 `skipped = 0` 且 `failed = 0` 时才记为 `completed`；只要仍有未完成迁移项，后续启动仍允许继续补跑
- 用户中心资产卡片已新增“清理本地副本”与“重新收录到本地”单资产动作，并已扩展到批量工具栏；当前都只对 `local_mirror` 资产生效，其中“清理本地副本”成功后预览会自动回退到远端 / 受保护资源兜底链路，“重新收录到本地”则会优先遵守 `metadata_json.local_storage_driver` 所登记的目标驱动，避免静默换驱动导致服务端 metadata 与真实本地状态失真
- `legacyLocalAssetMigration:v2:status` 已接入用户中心轻量诊断提示，并通过同页事件同步刷新迁移状态
- `metadata_json.local_storage_*` 已进一步收口到共享 JSON schema snapshot、schema 派生产物与独立 contract 文档：
  - `frontend/src/contracts/userAssetLocalStorage.schema.json`
  - `frontend/src/contracts/userAssetLocalStorageContract.generated.ts`
  - `backend/app/schemas/user_asset_local_storage_contract_generated.py`
  - `docs/contracts/USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md`
- `Asset Studio` 收录流程已改为：
  - 下载 blob
  - 写本地资产库
  - 再写服务端资产元数据
- 用户中心预览已改为：
  - 本地副本优先
  - 云端受控地址兜底
- DreamWeaver 资产收录 payload 已同步新字段
- 业务页中零散的 `metadata_json: { ... }` 构造已开始收口到共享场景化 builder：
  - `frontend/src/contracts/userAssetMetadataBuilders.ts`
  - 当前已覆盖 Asset Studio / Audiobook / DreamWeaver Library / DreamWeaver Run 等主要收录入口
- `source_payload_json` 页面层构造已开始收口到共享场景化 builder：
  - `frontend/src/contracts/userAssetSourcePayloadBuilders.ts`
  - 当前仍定位为“共享 builder 约束”，而不是正式 schema 契约
  - 新写入链路已不再复制 `local_asset_storage` 镜像，本地驱动细节统一回到 `metadata_json.local_storage_*`
  - Audiobook builder 合并 `assetMetadata` 时也会显式剔除 `local_storage_* / external_relative_path`，避免 contract 字段从另一条路径回流
- 读取侧 fallback 已开始从页面逻辑抽离到共享 selector：
  - `frontend/src/contracts/userAssetSourcePayloadSelectors.ts`
  - `UserCenterPage` 已开始通过 selector 读取 `project_id / run_id / library asset / audiobook trace` 等来源信息
- 读取侧来源展示语义已开始继续收口到共享 reader / view-model helper：
  - `frontend/src/contracts/userAssetSourceReaders.ts`
  - `UserCenterPage` 已开始通过共享 reader 生成来源标签、traceLabel、回跳路径与受保护资源判定
- 读取侧预览回退顺序已开始继续收口到共享 preview resolver：
  - `frontend/src/contracts/userAssetPreviewResolvers.ts`
  - `UserCenterPage` 已开始通过共享 resolver 统一本地 object URL、受保护资源 object URL 与普通远端 URL 的预览回退顺序
- 读取侧受保护资源下载分发与 object URL 生命周期管理已开始继续收口到共享 preview loading hook：
  - `frontend/src/hooks/useUserAssetPreviewObjectUrls.ts`
  - `UserCenterPage` 已开始通过共享 hook 统一本地预览与受保护预览的 object URL 加载/释放
- 读取侧资产卡片预览渲染已开始继续收口到共享 presenter / preview component：
  - `frontend/src/components/user-assets/userAssetPreviewPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetPreviewMedia.tsx`
  - `UserCenterPage` 已开始通过共享 preview component 渲染 placeholder / image / audio / video 四种预览分支
- 读取侧资产卡片的来源 chips、说明文案、标签摘要与操作按钮拼装已开始继续收口到共享 card-level presenter / component：
  - `frontend/src/components/user-assets/userAssetCardPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetCard.tsx`
  - `UserCenterPage` 已开始通过共享 card component 渲染资产卡片主内容，而不是继续在页面中展开整段卡片模板
- 读取侧资产列表级的筛选 option、过滤 view-model 与单卡片 / 批量 action command 已继续收口到共享 asset list helper：
  - `frontend/src/components/user-assets/userAssetListPresentation.ts`
  - `frontend/src/components/__tests__/userAssetListPresentation.test.ts`
  - `UserCenterPage` 已开始通过共享 helper 生成 kind/tag/source options、过滤结果、单卡片 action key 与单个 / 批量更新命令
- 读取侧资产列表的选择态统计、可见结果选择同步与 batch toolbar presenter / component 已继续收口到共享层：
  - `frontend/src/components/user-assets/userAssetBatchToolbarPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetBatchToolbar.tsx`
  - `UserCenterPage` 已开始通过共享 helper / component 生成选择摘要 chips、全选 / 清空动作与批量操作按钮可用性，而不是继续在页面中手写工具条模板
- 读取侧资产列表的过滤工具条 presenter / component 与 list section container 已继续收口到共享层：
  - `frontend/src/components/user-assets/userAssetFilterToolbarPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetFilterToolbar.tsx`
  - `frontend/src/components/user-assets/UserAssetListSection.tsx`
  - `UserCenterPage` 已开始通过共享 presenter / component 生成筛选字段、结果摘要、刷新动作与 loading / empty / grid 分支骨架，而不是继续在页面中手写整段资产列表 section 模板
- 读取侧资产概览 metrics、列表 warning/empty state delivery 与资产编辑器 dialog presenter / component 已继续收口到共享层：
  - `frontend/src/components/user-assets/userAssetOverviewPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetOverviewMetrics.tsx`
  - `frontend/src/components/user-assets/userAssetEditorPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetEditorDialog.tsx`
  - `UserCenterPage` 已开始通过共享 presenter / component 生成资产概览指标、列表 warning / empty copy 与编辑器表单 view-model，而不是继续在页面中手写这些壳层模板与表单归一化逻辑
- 读取侧单资产 / 批量资产 action feedback 与资产页 workspace section container 已继续收口到共享层：
  - `frontend/src/components/user-assets/userAssetActionFeedbackPresentation.ts`
  - `frontend/src/components/user-assets/UserAssetWorkspaceSection.tsx`
  - `UserCenterPage` 已开始通过共享 helper 生成更新 / 批量操作 / 编辑保存 feedback 文案，并通过共享 workspace section container 组合 overview、list section 与 editor dialog，而不是继续在页面中手写资产区块壳层
- 读取侧资产页 controller / hook、编辑器提交状态切换与 user-assets 提交副作用分发 已继续收口到共享层：
  - `frontend/src/hooks/useUserAssetWorkspaceController.ts`
  - `UserCenterPage` 已开始通过共享 hook 承接资产加载、筛选状态、选择态、编辑器开关、单资产 / 批量提交与 feedback 分发，而不是继续在页面中维护整段 asset controller 逻辑
- 读取侧资产卡片 action controller、preview bridge 与 cards grid container 已继续收口到共享层：
  - `frontend/src/components/user-assets/userAssetCardController.ts`
  - `frontend/src/components/user-assets/userAssetPreviewBridge.ts`
  - `frontend/src/components/user-assets/UserAssetCardsGrid.tsx`
  - `UserCenterPage` 已开始通过共享 cards grid container 组合单卡 action command、选择态、preview object URL bridge 与导航 / 编辑接线，而不是继续在页面中手写 `filteredUserAssets.map(...)` 卡片桥接段
- 读取侧 preview object URL hook 接线、cards grid props 组装与页面级导航 fallback 已继续收口到共享 asset workspace view-model / adapter hook：
  - `frontend/src/hooks/useUserAssetWorkspaceViewModel.ts`
  - `UserCenterPage` 已开始通过共享 view-model hook 组合 workspace controller、preview loading hook、cards grid props、刷新资产动作与导航 fallback，而不是继续在页面中手写这层 route integration / adapter 逻辑
- 读取侧 asset workspace content container 已继续收口到共享层：
  - `frontend/src/components/user-assets/UserAssetWorkspaceContent.tsx`
  - `frontend/src/hooks/useUserAssetWorkspaceViewModel.ts`
  - `UserCenterPage` 已开始通过共享 content container 与 `workspaceContentProps` 渲染资产 tab 内容，而不是继续在页面中同时拼装 `UserAssetWorkspaceSection + UserAssetCardsGrid`
- 读取侧 user-center asset summary / refresh helper 已继续收口到共享层：
  - `frontend/src/components/user-assets/userCenterAssetSummaryHelper.ts`
  - `frontend/src/hooks/useUserAssetWorkspaceViewModel.ts`
  - `UserCenterPage` 已开始通过共享 helper / view-model 承接页面顶部刷新按钮中的 `loadUserCenterData(true) + loadUserAssets(true)` 双调度，以及 `pointsConnectedOverview?.user_asset_count ?? userAssets.length` 的资产数量 fallback，而不是继续在页面中手写这些资产侧桥接逻辑
- 读取侧 user-center asset workspace input helper 已继续收口到共享层：
  - `frontend/src/components/user-assets/userCenterAssetWorkspaceInputHelper.ts`
  - `frontend/src/hooks/useUserAssetWorkspaceViewModel.ts`
  - `UserCenterPage` 已开始直接把 `projects / pointsOverview` 交给共享 view-model，由共享 helper 承接 `projects -> projectTitleMap` 构造与 `pointsOverview -> connectedUserAssetCount` 提取，而不是继续在页面中手写这层资产输入归一化逻辑
- Audiobook 页面已支持**手动收录章节成品音频**：
  - 下载受控音频 blob
  - 写入本地资产库
  - 再登记 `user_asset_records`
- Audiobook 页面已接入**有限但已扩展到多任务**的 `localStorage` 会话恢复：
  - `projectId`
  - `audiobookProjectId`
  - `taskId`
  - `activeTasks`
  - `selectedChapterIds`
  - `activeStep`
  - `generating`
  - `ttsModel`
- 上述 `localStorage` 会话现已额外带上 `updatedAt / writerTabId` 轻量元数据，用于同项目多标签页同步时的基础判定与去抖
- Audiobook 剧本编辑器已补上**同标签页刷新恢复**的 `sessionStorage` 草稿态：
  - `chapterId`
  - `reviewMode`
  - `openSegmentDetailIndices`
  - `segmentReviews`
  - 当前未保存的 `scriptSegments` 草稿
  - 并额外补上基于 `localStorage` 广播的**跨标签页同章草稿冲突提示**：当其它标签页更新同一章节未保存草稿时，当前标签页会提示“载入对方草稿”或“保留本页草稿”
  - 上述冲突提示已继续推进到**字段级自动合并前的差异预览**：在用户决策前可先看到顶层状态差异，以及片段级 `text / performance_notes / pause / instruct / voice_params / sound_effects / music_cue` 等字段变更摘要
  - 当前草稿广播还已接入 `updatedAt` 心跳与 TTL/GC，减少异常关闭标签页后遗留的伪占位
- Audiobook 主页面已新增独立的 `sessionStorage` page session：
  - `BrowserPlayer` 打开态
  - 历史记录弹窗打开态
  - 生成前关键配置（`scriptOnlyMode / narrationStyle`）
  - 剧本评审弹窗与其已加载数据
  - 阶段指标弹窗与其已加载数据
  - 章节删除确认弹窗、目标章节与当前删除表单态
  - CosyVoice 声音复刻 / 声音设计草稿与录音提示弹窗
  - “从文本创建项目”弹窗及其当前输入草稿
- `BrowserPlayer` 已接入：
  - 章节音频本地优先回读
  - 首次远端拉取后的本地缓存
  - 字幕下载时的本地缓存
  - `currentChapterIndex / currentTime / volume / subtitleFormat / showSubtitles / wasPlaying` 的 `localStorage` 持久化
- Audiobook 页面行内播放也已支持优先回读本地音频
- 但当前本地资产层仍是 `IndexedDB blob`，尚未升级到 `OPFS + IndexedDB 索引`
- 也还没有用户可选的真实本地资料库目录

> **一致性复核批次（`2026-04-24`）：** 以 `USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md` 为权威，本轮对齐了 12 项前后端与文档不一致：schema `x-contract-compat-level` 透传、`storage_mode=local_only` reserved 拒写、`*_uri` 超长拒绝、前端 metadata 截断 `console.warn`、`legacy_indexeddb` 不再允许显式请求（窄化为 `ExplicitPreferredLocalAssetStorageDriver`）、全局 `LocalAssetHealthBanner`、`chapter_audio_runs` checkpoint 清理诊断、`source_payload_json` 形状落成 draft schema（非绑定）、`can_resume` blockers 回归测试固化。详表见 `USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md` §8。

## 10. 当前未落地内容

以下内容尚未纳入本轮，或仅处于**部分落地 / 过渡态**：

### 10.1 Audiobook 主链路

Audiobook 不适合直接照搬 Asset Studio 的“生成完成 -> 前端下载 -> 本地收录”最简链路。

原因不是音频成品本身，而是 Audiobook 除了“最终音频文件”，还天然包含：

- 异步任务调度
- 阶段进度追踪
- 章节级脚本与评审
- 断点续传
- 运行期中间片段缓存
- 计费与风控

这意味着 Audiobook 需要单独定义一套 **运行态数据分层**，不能把“断点数据”“缓存数据”“最终资产”混在一起。

#### 10.1.1 数据分层原则

Audiobook 相关数据应拆成四层：

1. **浏览器本地层**
   - 只负责页面恢复态、最近一次任务入口、最终成品的本地镜像
   - 不负责保存断点真相
2. **服务端数据库层**
   - 负责任务状态、章节脚本、章节评审、断点元数据、恢复校验信息
   - 这是断点续传的权威来源
3. **服务端临时对象层**
   - 负责存放已生成但尚未合并/尚未交付的片段音频
   - 必须带 TTL 与清理策略
4. **用户本地资产层**
   - 负责保存用户最终收录的章节音频、试听音频或导出成品
   - 这部分进入 local-first 资产体系

结论很明确：

- **页面恢复态可以本地化**
- **断点续传真相必须服务端化**
- **中间片段缓存必须服务端临时化**
- **最终成品可以 local-first 化**

#### 10.1.2 当前实现的真实问题

当前代码已经有一套“断点续传 / 缓存系统”的雏形，但还没有形成真正闭环。

当前已存在的基础包括：

- 前端已有 `localStorage` 会话恢复，并已扩展到 `projectId / audiobookProjectId / taskId / activeTasks / selectedChapterIds / activeStep / generating / ttsModel`，同时补上 `updatedAt / writerTabId` 轻量元数据
- 后端已有 `AudiobookTask` 持久化任务状态
- `ChapterAudio.generation_progress_json` 已从运行时模型中移除，并已补上 Alembic 物理删列迁移
- 后端已新增 `chapter_audio_runs`
- 后端已有 `/checkpoint` 与 `/resume-generation` 接口
- 用户中心已经能优先读取已收录的本地资产副本

但目前仍存在以下问题：

1. `chapter_audio_runs` 已经成为 `/checkpoint` 与 `/resume-generation` 的唯一恢复依据；`ChapterAudio.generation_progress_json` 与 `ChapterAudio.task_id` 也已从运行时模型移除，并补上 Alembic 物理删列迁移，运行态真相已经在代码与表结构两侧收口到 `chapter_audio_runs + checkpoint_json`。
2. `resume-generation` 已能真正启动续跑任务，并在 checkpoint 含有可用 temp 片段时跳过已缓存 segment、只补缺失 segment；同时 TTS 处理中已开始在每个成功 segment 后持续写 checkpoint。当前恢复边界已经从“批次级”推进到“单 segment 成功级”，但仍不是 segment 内部任意时刻都无损续跑。
3. `checkpoint_json` 已升级为版本化文档，并开始写入 `schema_version / script_hash / voice_config_hash / audio_fx_hash / checkpoint_updated_at / temp_asset_prefix / segments.*.temp_object_key / completed_segment_indices` 等字段；当前已经具备本地文件版 TTL janitor、completed run 主动清理、基于 temp cache 的 segment 级复用，以及 TTS 单 segment 成功后 checkpoint 持续落盘；对象存储版 temp segment 生命周期也已接入同一套 store 抽象，并支持在配置直连 OSS 删除凭证时按 checkpoint 逐对象物理删除与删除计数回写；仅依赖 DashScope `getPolicy` 直传且没有 delete 凭证的环境仍保持 best-effort 回退，完整 prefix 枚举清理仍待后续补齐。
4. `can_resume` 已接入 `script_hash / voice_config_hash / audio_fx_hash / tts_model / output_format / expires_at / 临时对象是否存在` 的恢复校验与 blocker 解释，`missing_temp_assets` 也已基于真实临时片段存在性校验；当前 run checkpoint 缺少可恢复材料时也不会再因为“只有 run 行存在”而被误判为可恢复，但整体仍未达到严格的 segment 级恢复标准。
5. `ChapterAudio.task_id` 已停止作为运行态字段继续写入章节结果表，`routes_projects` 的章节结果返回里也不再暴露该字段；旧 `script_review` 路由也已改为直接读取 `script_json / script_review_json`，不再依赖 `task_id`。`ChapterAudio.task_id` 与 `ChapterAudio.generation_progress_json` 已完成物理删列迁移并在真实 PostgreSQL 环境执行验证。
6. 已补上 `align_chapter_audios_with_runtime_model` Alembic 迁移，并在真实 PostgreSQL 上补齐 `narration_style / narration_style_prompt / subtitle_path / subtitle_format / segment_reviews_json`，避免 `ChapterAudio` ORM 查询与物理表结构继续漂移。
7. 前端页面级会话恢复仍以轻量字段为主；当前已补到章节勾选、多任务焦点、同项目多标签页间的轻量同步，以及剧本编辑器在**同标签页刷新**时的 `chapterId / reviewMode / 详情展开 / 当前 scriptSegments 草稿` 恢复；同时主页面也已补上 `BrowserPlayer / 历史记录 / 生成前关键配置 / 剧本评审 / 阶段指标 / 删除确认 / CosyVoice 草稿态 / 从文本创建项目` 这类 page session 的同标签页刷新恢复；`narration_style` 也已真正透传到创建任务与“从剧本生成音频”接口。剧本编辑器还新增了基于 `localStorage` 的跨标签页同章草稿冲突提示与“载入对方草稿 / 保留本页草稿”二选一保护层，并进一步补上用户决策前可见的字段级差异预览，同时接入 `updatedAt` 心跳与 TTL/GC 以减少草稿占位残留。但章节菜单锚点、更细粒度 UI 临时态仍未持久化，未保存编辑内容也还没有跨标签页自动合并。
8. `AudiobookPage` 首屏恢复链路中的主要状态清空竞争已经修复，并已补上“同一小说项目下多个活跃 Audiobook 任务”的自动发现、轮询恢复与焦点切换，以及基于 `storage` 事件的跨标签页轻量同步；当前同步 payload 也已补上 `updatedAt / writerTabId` 元数据以降低回写抖动与自覆盖风险，但更复杂的多标签页冲突解决、更细颗粒度的恢复场景与自动合并语义仍未覆盖。
9. 最终章节音频目前除了用户手动点击“收录”外，也可能在播放器播放或页面内试听时被写入本地缓存；但这仍不是统一的“自动收录”策略，未被缓存过的音频刷新后仍主要依赖服务端下载链路。
10. `BrowserPlayer` 已形成单独的 local-first 播放闭环，并持久化了 `currentChapterIndex / currentTime / volume / subtitleFormat / showSubtitles / wasPlaying`；但这套恢复仍依赖浏览器本地存储，且自动续播仍受浏览器自动播放策略影响。
11. TTS 的 `enable_cache` 不能等价视为“断点续传已经完成”。

也就是说：

- **当前已有字段、表和接口可以作为过渡基础**
- **但当前实现仍是“部分恢复、非闭环”状态**

#### 10.1.3 推荐数据库结构（开发阶段可直接重构）

`chapter_audio_runs` 这条路线已经被代码验证为正确方向，但当前仍处于“表已存在、语义未收口”的过渡态。

建议继续拆分职责：

1. **`chapter_audios` 仅保留章节最终结果与章节级内容**
   - 最终章节音频元信息
   - 剧本 `script_json`
   - 剧本评审 `script_review_json`
   - 片段评审 `segment_reviews_json`
   - 最终音频评审 `final_audio_review_json`
   - 最终时长、大小、成本、字幕等
2. **`chapter_audio_runs`（已建模，待收口）**
   - 用于记录每一次生成尝试的运行态与断点状态

推荐字段如下：

```text
chapter_audio_runs
- id
- audiobook_project_id
- chapter_id
- run_type                  # full | script_only | audio_from_scripts
- celery_task_id
- status                    # pending | running | paused | completed | failed | expired
- current_stage
- progress
- completed_segment_count
- total_segment_count
- tts_model
- output_format
- narration_style
- narration_style_prompt
- voice_config_hash
- audio_fx_hash
- script_hash
- resumable                 # bool
- checkpoint_json           # 断点元数据
- temp_asset_prefix         # 临时对象目录/前缀
- expires_at
- error_message
- started_at
- updated_at
- finished_at
```

如果采用该方案，建议：

- 短期：以 `chapter_audio_runs + checkpoint_json` 作为唯一恢复接口；`generation_progress_json` 不再参与恢复判定
- 中期：确保所有环境都完成 `remove_legacy_chapter_audio_runtime_fields + align_chapter_audios_with_runtime_model`，让 `ChapterAudio` 真表结构与当前 ORM 结果字段持续对齐
- 最终：运行态全部迁移到 `chapter_audio_runs`

这是因为：

- `ChapterAudio` 是“章节结果”
- `chapter_audio_runs` 是“某一轮生成过程”

两者职责不同，混在一个表里后续会越来越难维护。

#### 10.1.4 checkpoint_json 推荐结构

当前现状校准：

- `checkpoint_json` 已有写入
- 当前已开始收口为版本化文档，并补入 `schema_version / status / current_stage / script_hash / voice_config_hash / audio_fx_hash / checkpoint_updated_at`
- 当前已开始写入 `temp_asset_prefix / cached_audio_paths / segments.*.temp_object_key`
- 当前已经具备生命周期清理、基于 temp cache 的 segment 级复用执行，以及 TTS 过程中单 segment 成功后的 checkpoint 持续落盘；但仍不足以支撑“单个 segment 处理中任意时刻都无损”的更细粒度安全续跑

不建议再只保存：

- `completed_segment_indices`
- `cached_audio_paths`

建议至少升级为版本化 checkpoint 文档：

```json
{
  "schema_version": 1,
  "run_id": "uuid",
  "status": "running",
  "current_stage": "tts_synthesis",
  "tts_model": "qwen3-tts-instruct-flash",
  "output_format": "mp3",
  "script_hash": "sha256",
  "voice_config_hash": "sha256",
  "audio_fx_hash": "sha256",
  "total_segments": 48,
  "completed_segment_indices": [0, 1, 2, 3],
  "failed_segment_indices": [],
  "segments": {
    "0": {
      "status": "completed",
      "temp_object_key": "tmp/audiobook/run_xxx/segment_000.mp3",
      "duration": 2.31,
      "file_size": 18234,
      "checksum": "sha256",
      "updated_at": "2026-04-19T12:00:00Z"
    }
  },
  "last_error": null,
  "checkpoint_updated_at": "2026-04-19T12:03:00Z",
  "expires_at": "2026-04-22T12:03:00Z"
}
```

这些字段的作用如下：

- `script_hash`
  - 用于判断用户是否修改了剧本，避免错误复用旧断点
- `voice_config_hash / audio_fx_hash`
  - 用于判断音色和音频配置是否发生变化
- `segments.*.temp_object_key`
  - 指向服务端临时片段，不进入用户资产系统
- `expires_at`
  - 用于后续清理过期中间缓存

另外，当前 `completed_segment_indices / cached_audio_paths` 仍只适合作为**过渡兼容字段**，不应继续作为唯一恢复依据。

#### 10.1.5 本地数据与服务端数据的边界

Audiobook 相关数据推荐按下表处理：

| 数据类型 | 存储位置 | 说明 |
| --- | --- | --- |
| 页面恢复态 | 浏览器 `localStorage` / IndexedDB | 仅用于 UI 恢复，当前只部分实现 |
| 播放器状态 | 浏览器本地 | `BrowserPlayer` 已实现章节、进度、音量、字幕与上次播放态持久化，但页面级状态仍未统一 |
| 任务状态 | 服务端数据库 | 以 `AudiobookTask` 或 `chapter_audio_runs` 为权威 |
| 章节剧本/评审 | 服务端数据库 | 业务真相，不下放浏览器 |
| 断点元数据 | 服务端数据库 | 必须跨设备、跨刷新、跨 worker 恢复 |
| 中间片段音频 | 服务端临时对象层 | 仅用于恢复，不属于正式资产 |
| 最终章节音频 | 用户本地资产库 + 服务端短时兜底 | 进入 local-first 资产链路；当前可由手动收录或播放缓存进入本地资产库，但仍缺统一自动收录策略 |

不建议做的事情：

- 不要把中间片段 base64 塞进数据库
- 不要把断点真相只放在浏览器
- 不要把中间片段收录为 `user_asset_records`
- 不要把 `detail_json` 演化成超大 JSON 垃圾桶

#### 10.1.6 服务端临时对象层建议

为了让断点续传真正可用，服务端必须持有可恢复的中间片段。

开发阶段建议先采用最简单但边界清晰的方式：

```text
backend/data/tmp/audiobook_runs/{run_id}/segment_000.mp3
backend/data/tmp/audiobook_runs/{run_id}/segment_001.mp3
backend/data/tmp/audiobook_runs/{run_id}/segment_002.mp3
```

当前代码已按这个方向落地了本地文件版实现，但实际目录进一步细化为：

```text
backend/data/tmp/audiobook_runs/{engine_task_id}/chapter_{chapter_id}/segment_000.mp3
```

数据库保存的应是可迁移的相对 key。

当前代码里实际写入的是仓库相对路径，例如：

- `backend/data/tmp/audiobook_runs/{engine_task_id}/chapter_{chapter_id}/segment_000.mp3`

后续如果切换为对象存储，也只需要替换底层实现，不需要改业务模型。

推荐清理策略：

- `running`：保留
- `failed` / `paused`：保留 24-72 小时
- `completed`：在最终章节音频合成并确认落地后尽快清理
- `expired`：由后台清理任务定时删除

当前真实状态补充：

- 临时片段已经会被正式写盘
- `checkpoint_json` 已能记录并校验这些路径
- 已新增后台 TTL janitor，用于清理 `expires_at` 已过期的 resumable run 临时片段，并同步把对应 checkpoint 失效化
- `completed` run 现已在成功分支主动清理临时片段
- 已具备基于 temp cache 的 segment 级复用，以及 TTS 过程中单 segment 成功后的 checkpoint 持续落盘；对象存储版 temp segment 也已纳入同一套 provider-aware 生命周期，并支持在配置直连 OSS 删除凭证时按 checkpoint 逐对象清理；无删除凭证时仍是 best-effort 回退，更细粒度的 segment 内安全恢复仍未落地

#### 10.1.7 恢复判定规则

当前代码已**部分实现**下面这套校验，但仍未全部达成，以下为修正文档后的**目标规则**：

以下情况应判定为 **不可恢复，必须重新生成**：

- `script_hash` 不一致
- `voice_config_hash` 不一致
- `audio_fx_hash` 不一致
- `tts_model` 不一致
- `output_format` 不一致
- 任意已记录的临时片段文件不存在
- checkpoint 已过期
- checkpoint schema 版本不匹配

恢复逻辑不应只看“有没有 `completed_segment_indices`”，而应同时校验：

- 输入是否一致
- 临时片段是否仍然存在
- 该 run 是否仍处于可恢复窗口内

#### 10.1.8 前端推荐交互

前端只保留轻量会话恢复，不保留断点真相。

当前实现校准：

- 现在已有轻量会话恢复、章节勾选恢复、项目内多任务发现与任务轮询
- 还没有完整的“发现可恢复 run -> 用户确认 -> 真正续跑 -> 回到统一任务状态流”的交互闭环

推荐交互如下：

1. 页面恢复时，根据本地保存的 `taskId / audiobookProjectId / activeTasks / selectedChapterIds`，并结合服务端任务列表，恢复当前小说项目下的活跃任务集合与章节勾选
2. 加载项目与章节数据时，不得覆盖已恢复的活跃任务焦点；当存在多个活跃任务时，需要允许用户切换查看不同任务，并在同项目多标签页之间保持轻量一致性
3. 若发现存在失败或暂停且可恢复的 `chapter_audio_run`，显示“继续生成”提示
4. 用户确认后调用**真正执行恢复**的接口，返回新的 `task_id / run_id`
5. 恢复任务启动后，继续沿用统一的任务状态轮询
6. 任务完成后，前端再按 local-first 资产链路收录最终章节音频

也就是说：

- **前端负责发现与触发恢复**
- **服务端负责判断是否真的能恢复**

#### 10.1.9 与 local-first 资产体系的衔接

当前状态校准：

- Audiobook 已完成“手动收录章节成品音频”的入口
- 本地资产回读当前已经发生在用户中心、Audiobook 页面行内播放与 `BrowserPlayer`
- 但这些调用当前仍共同落在 `IndexedDB blob` 兼容层上，尚未升级到 `OPFS` 驱动

Audiobook 真正接入本地优先资产抽象时，建议只把 **最终章节音频** 纳入资产收录。

推荐链路：

1. 后端完成章节音频生成
2. 前端通过受控下载接口获取最终音频 blob
3. 前端写入统一本地资产层（当前 IndexedDB，后续演进到 OPFS）
4. 前端调用 `/api/v1/user-assets` 登记轻量元数据
5. 用户中心优先显示本地副本

这条链路与当前真实代码是对齐的，而且 [AudiobookPage](../frontend/src/pages/AudiobookPage.tsx) 与 [BrowserPlayer](../frontend/src/components/audiobook/BrowserPlayer.tsx) 已经是最适合第一批切换到 `OPFS` 的调用方，因为它们都围绕 `assetUuid + getLocalAssetBlob()/saveLocalAsset()` 工作。

补充建议：

- 对于章节成品音频，优先提供“显式收录”或“可配置自动收录”，不建议在没有容量提示的情况下静默全量写入 IndexedDB
- 如果后续引入自动收录，需要同时补齐：
  - 存储空间提示
  - 收录失败回退
  - 本地资产缺失重建策略

而以下内容 **不要进入用户资产系统**：

- 中间 segment 片段
- 恢复用 checkpoint
- 临时调试音频
- 运行态任务 detail

#### 10.1.10 推荐落地顺序

Audiobook 建议按以下顺序改造，而不是一次性大拆：

1. 先明确运行态与最终资产的边界
   - `ChapterAudio` 只保最终结果
   - 继续把 `chapter_audio_runs` 收口为唯一运行态模型
2. 再补 checkpoint 实际写入
   - 每完成一个成功 segment 就写 checkpoint
3. 再补 resume 真正续跑
   - 恢复时跳过已完成片段，只补剩余片段
4. 再修前端刷新恢复链路
  - 避免 `handleSelectProject` 覆盖已恢复的 `taskId / audiobookProjectId`
  - 补齐多标签页竞争与更多 UI 临时态的持久化边界
5. 最后接前端恢复交互与 local-first 收录 / 回读
   - 保证用户完成后能把最终音频拿回本地
   - 让 Audiobook 页面与播放器也能优先读本地副本

如果只做一件 **Audiobook 专项改造**，优先级最高的是：

**先让“断点真相”真正收口到 `chapter_audio_runs`，并让 `resume-generation` 具备真实续跑能力。**

#### 10.1.11 刷新浏览器后的数据保真判断

这个问题需要区分“目标架构”与“当前实现”。

**按目标架构完整实现后：**

- 服务端权威数据不应因浏览器刷新丢失：
  - 项目
  - 章节
  - 任务状态
  - 断点元数据
  - 章节剧本与评审
- 已收录到本地资产库的最终章节音频，在**同一浏览器、同一站点存储未被清理**的前提下，刷新后不应丢失
- 纯 UI 临时态是否保留，取决于是否显式持久化；这不是 local-first 资产架构自动解决的问题

**按当前实现为准：**

- 刷新后通常能恢复一部分会话入口：
  - `projectId`
  - `audiobookProjectId`
  - `taskId`
  - `activeTasks`
  - `selectedChapterIds`
  - `activeStep`
  - `generating`
  - `ttsModel`
- 以及用于多标签页轻量同步判定的 `updatedAt / writerTabId`
- 刷新后如果同一小说项目下存在多个活跃 Audiobook 任务，当前前端已经能自动重新发现这些任务、恢复轮询，并允许用户切换焦点任务
- 同一小说项目在多个标签页中打开时，当前前端已经能通过 `storage` 事件同步轻量会话状态，包括焦点任务与章节勾选；当前同步已带 `updatedAt / writerTabId` 作为基础保护
- 若仍停留在同一标签页、且当前 `audiobookProjectId` 一致，剧本编辑器的当前章节、`reviewMode`、片段详情展开状态与当前未保存草稿，刷新后通常也能恢复
- 若多个标签页同时编辑同一章节，当前剧本编辑器已经能基于 `localStorage` 草稿广播提示跨标签页冲突，并支持手动选择“载入对方草稿”或“保留本页草稿”；当前草稿广播还带有心跳与 TTL/GC，异常关闭后旧占位通常会在过期后自动失效
- 同标签页刷新后，主页面的 `BrowserPlayer` 打开态、历史记录弹窗、生成前关键配置、剧本评审弹窗、阶段指标弹窗、章节删除确认弹窗、CosyVoice 声音复刻 / 设计草稿与录音提示弹窗，以及“从文本创建项目”弹窗与其当前草稿，当前通常也能恢复
- `BrowserPlayer` 当前已能恢复：
  - 当前章节
  - 播放进度
  - 音量
  - 字幕格式 / 显示状态
  - 上次是否处于播放态
- 但“自动续播”仍可能受浏览器自动播放策略影响，不能承诺绝对无感恢复
- 已进入 `localAssetVault` 的章节成品音频，在同一浏览器、同一站点存储未被清理的前提下，刷新后通常不会丢
- 但当前底层仍属于浏览器站点存储：虽然已升级为 `OPFS` 优先 + `IndexedDB` 索引/兼容回退，但如果浏览器清理站点数据、配额被回收、切换浏览器或重装环境，仍可能丢失本地副本
- 未手动收录、也未被播放器或页面缓存过的章节成品音频，刷新后仍依赖服务端下载链路
- 以下状态当前刷新后会丢，或至少不会被稳定恢复：
  - 章节菜单锚点等仍依赖真实 DOM 的瞬时 UI 状态
  - 未保存编辑内容的跨标签页自动合并与统一同步
  - 页面级任务恢复过程中的更细粒度临时 UI 上下文
  - 多标签页同时操作时更复杂的冲突解决语义

因此，修正文档后的准确表述应是：

- **方案方向本身可以做到“刷新后核心数据不丢，已缓存资产尽量不丢”**
- **但以当前代码状态看，还做不到“清站点数据后仍稳定保有本地副本”，也还做不到“刷新后任务恢复与播放恢复完全无感”**

### 10.2 本地资产存储演进（IndexedDB -> OPFS -> 用户目录）

先给结论：

- 当前工程已经落地的是：**`IndexedDB 直接存 Blob`**
- 下一阶段默认方案应当是：**`OPFS 存文件 + IndexedDB 存索引`**
- 用户如果希望拿到更接近“真实本地文件夹”的体验，应增加：**`File System Access API` 用户授权目录**
- “下载到本地 + IndexedDB 索引”不适合作为主架构，只适合作为导出 / 备份能力

#### 10.2.1 当前 IndexedDB 方案能解决什么、解决不了什么

当前 `localAssetVault` 的优点是：

- 已经接入现有业务代码，迁移成本最低
- 同一浏览器内刷新、重开标签页后，通常还能命中本地副本
- 非常适合做 local-first 第一阶段验证

但它的边界也很明确：

- 仍属于站点存储，受浏览器 quota 和清理策略影响
- 用户清理站点数据后，本地副本会一起消失
- 对大体积 blob 的长期读写、迁移、诊断都不够友好
- 没有真正“用户可见文件”的概念

因此，准确表述不应是“实现后刷新就绝对不会丢”，而应是：

- **在同一浏览器、同一站点存储未被清理的前提下，刷新后通常不会丢**
- **一旦站点数据被清理、浏览器换环境、或配额被回收，本地副本仍可能丢**

#### 10.2.2 方案对比与推荐角色

| 方案 | 角色定位 | 优点 | 限制 | 推荐级别 |
| --- | --- | --- | --- | --- |
| `IndexedDB blob` | 当前兼容层 / 迁移来源 | 已落地、接入成本低 | 大文件体验一般，仍易受站点清理影响 | 保留兼容，不作为长期目标 |
| `OPFS + IndexedDB 索引` | 浏览器默认本地资产层 | 更适合文件式读写，适合大文件缓存主存储，可继续走 `asset_uuid` 抽象 | 仍受站点配额与清理策略影响，需要兼容性 fallback | **主方案** |
| `File System Access API` 用户目录 | 用户可选长期资料库 | 真正落到用户可见目录，对“站点数据清理”更不敏感，适合长期保有 | 需要用户授权，浏览器支持不一致，需要处理重新授权与句柄失效 | **增强方案** |
| 导出下载 + 本地索引 | 导出 / 备份 | 简单直观 | 依赖用户手动管理，不能自动作为统一资产主存储 | 辅助能力 |

这里要特别避免两个误判：

- 不要把 `OPFS` 描述成“几乎无限、不会被清理”的本地磁盘替代
- 不要把“下载到本地”误当成统一资产系统，它更适合作为导出而不是运行态主存储

#### 10.2.3 推荐数据结构方向

为了不破坏当前后端 schema 与前端 contract，推荐：

- 继续保留现有 `storage_mode` 四种语义：
  - `temp_cloud`
  - `durable_cloud`
  - `local_mirror`
  - `local_only`
- 暂不把 `indexeddb / opfs / external_directory` 这种驱动类型塞进 `storage_mode`
- 驱动细节先写入本地索引或服务端 `metadata_json`

推荐字段方向：

- `local_storage_driver`: `legacy_indexeddb` | `opfs` | `external_directory`
- `local_storage_path`
- `external_relative_path`
- `local_persist_level`: `best_effort` | `persistent_requested` | `user_directory`

这样可以在不改后端枚举的情况下，让本地资产层独立演进。

#### 10.2.4 推荐迁移策略

本项目最适合的演进方式不是“一次性切掉 IndexedDB”，而是渐进迁移：

1. 提升 `localAssetVault` 的 `DB_VERSION`
2. 保留 legacy `blob` 字段的兼容读取能力
3. 新资产默认直接写入 `OPFS`
4. 旧资产在读取命中时，按需迁移到 `OPFS`
5. IndexedDB 只保留索引与少量兼容字段
6. 同步接入 `navigator.storage.persist()` 申请更稳的站点存储策略
7. 为存储失败、空间不足、句柄失效提供可见提示与回退逻辑

对当前工程来说，最佳切入点就是先改 [localAssetVault](../frontend/src/utils/localAssetVault.ts)，而不是先改业务页面，因为 `Asset Studio`、用户中心、`AudiobookPage`、`BrowserPlayer` 已经都通过同一套抽象访问本地资产。

### 10.3 PWA 与持久化增强

当前本地资产层尚未做以下增强：

- PWA 安装态
- Service Worker
- `navigator.storage.persist()`
- 存储空间 / quota 可视化
- 离线包策略

### 10.4 真正的纯流式代理

本轮 `Asset Studio` 对第三方远端 URL 的处理仍然是：

- 先由后端下载到临时内部资产目录
- 再返回内部链接

这比“直接暴露第三方 URL”更安全、更稳，也更适合作为第一阶段。

但它还不是最终形态的“全程内存流式 pipe”。

### 10.5 真实环境迁移执行与联调

当前已完成的是：

- 代码
- schema
- contract
- 迁移文件
- 关键迁移在真实 PostgreSQL 环境中的执行验证：
  - `remove_legacy_chapter_audio_runtime_fields`
  - `align_chapter_audios_with_runtime_model`

当前仍未完全收口的是：

- 其它环境的迁移补齐与回放验证
- 端到端手工联调回归
- 不同存储后端组合下的恢复 / 清理边界验证
- 测试面与新 contract 的进一步收口；截至 `2026-04-23`，`user_assets` 路由回归测试、主要测试辅助代码，以及用户中心 / 积分相关回归已经同步到 `asset_uuid / source_uri / preview_uri / download_uri` 新 contract；Audiobook / DreamWeaver 预检路由测试也已完成装配修正，DreamWeaver 聚合入口对 `get_db / get_current_user` 的兼容导出与 `_helpers` 星号导入下划线 helper 的 `__all__` 问题也已收口，当前本轮涉及的后端测试文件中已不再保留旧 `file_url / preview_url` 命名语义

### 10.6 现状校准与关键风险点

以下风险判断以当前代码与文档现状为准，避免继续沿用已经过时的描述。

1. Audiobook 运行态模型**已基本收口**，风险已从“模型混杂”转向“迁移残留与联调不足”
   - `ChapterAudio.task_id` 与 `ChapterAudio.generation_progress_json` 已从当前 ORM 与真实迁移中移除
   - 运行态真相已收口到 `chapter_audio_runs + checkpoint_json`
   - 当前真正的风险不再是“字段还混在一起”，而是旧环境未迁干净、真实部署链路验证不充分
2. 本地资产层已经从“纯 IndexedDB blob”推进到“OPFS 优先 + IndexedDB 索引/兼容回退”，但仍属于**浏览器站点存储优先**
   - 当前 `localAssetVault` 会优先写入 `OPFS`
   - OPFS 不可用或写入失败时，仍会回退到 legacy `IndexedDB blob`
   - 这意味着 quota、站点数据清理、浏览器清理策略仍会影响本地副本持久性
3. 断点续传已经不是单纯的“章节级重新入队”，而是**基于 checkpoint + temp segment cache 的 segment 缺口补齐**
   - `resume-generation` 已能创建新 run，并跳过已有 temp segment，只补缺失 segment
   - TTS 过程中已经按成功 segment 持续回写 checkpoint
   - 但当前仍未达到“segment 内任意时刻都能无损恢复”的严格标准
4. TTL 清理调度已经存在，但对象存储版本的 GC 仍有边界待补
   - 本地文件版 temp segment janitor 已落地
   - completed run 的 temp segment 主动清理已落地
   - 对象存储在无直连删除凭证的场景下仍主要依赖 best-effort 回退，完整 prefix 枚举清理仍待补齐
5. 前端刷新恢复主链路已补齐，多任务恢复与跨标签页轻量同步已落地，但**更细粒度冲突语义尚未完成**
   - 当前已覆盖 `activeTasks / selectedChapterIds / page session / editor session`
   - 多任务焦点恢复、`storage` 事件同步、同章草稿冲突提醒与字段级差异预览均已落地
   - 但未保存编辑内容仍未支持跨标签页自动合并，更细粒度 UI 临时态也未完全持久化
6. 本地资产层演进路径仍然偏长，兼容负担需要持续控制
   - 当前已经同时涉及 `OPFS / IndexedDB / metadata_json` 兼容语义
   - 后续若再接入 `File System Access API` 用户目录，需要谨慎控制迁移与回退路径，避免抽象层失控
7. `storage_mode + metadata_json` 的职责边界需要持续约束，但当前不宜把它定义为“已经失控”的设计问题
   - `storage_mode` 目前表达的是资产生命周期
   - `metadata_json` 目前承载的是本地驱动细节
   - 真正风险在于后续演进中若缺少 schema 约束，`metadata_json` 容易退化成任意兜底字段
   - 截至 `2026-04-24`，`local_storage_driver / local_storage_path / local_persist_level / external_relative_path` 已统一由共享 JSON schema（`frontend/src/contracts/userAssetLocalStorage.schema.json`）定义，前端运行时归一化、后端 `UserAssetRecordCreate` 校验、OpenAPI 注解与人类可读契约文档（`docs/contracts/USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md`）都围绕这份 snapshot 对齐，派生产物由 `scripts/generate_user_asset_local_storage_contract.py` 生成并支持 `--check` 模式自检
  - `external_directory` 驱动与 `user_directory` 持久化级别已从 reserved 切换为已激活 contract 取值；当前已具备最小运行时能力，用户中心也已补上基础目录配置 UI、顶部异常提示、针对 `external_directory` 资产的轻量健康校验、权限恢复入口、备份建议、“导出备份说明 / 本地资产清单 / 重建清单”入口，以及“扫描当前筛选（预览） / 重建当前页缺失副本 / 扫描当前筛选并重建”快捷动作；对应扫描/重建流程还会在面板内留下最近一次结果摘要与可展开的问题明细，Asset Studio 工作台显式收录与 Audiobook 手动收录也已接入，但更完整的长期持有策略仍待继续产品化
   - 后续收口重点：把剩余手写的枚举 / 长度常量继续替换为 schema 派生产物，避免 `metadata_json` 回退成任意兜底字段
8. `navigator.storage.persist()` 申请已经通过 `requestLocalAssetPersistence()` 接入
   - OPFS 成功时会尝试申请 `persistent` 级别；未授权或 best_effort 回退时仍受浏览器清理策略影响，属预期行为
   - legacy → OPFS 懒迁移已落地（读时触发），主动批量迁移入口 `migrateLegacyLocalAssetsToOpfs()` 也已具备，可在应用空闲期调用以加速存量清理；最近一次启动迁移结果会写入 `legacyLocalAssetMigration:v2:status`
9. 当前 local-first 更接近“单机优先”，多设备资产可用性尚未定义
   - 这不是现阶段必须马上修掉的 bug
   - 但如果产品目标要扩展到跨设备无感继续工作，就需要补一层“元数据同步 + 资产重拉 / 导出导入 / 云端镜像”的明确策略

### 10.7 当前收口判断

| 维度 | 评估 | 现状说明 |
| --- | --- | --- |
| 架构方向 | ✅ 正确且已验证 | local-first + 服务端权威业务模型的方向没有问题 |
| 核心基础设施 | ✅ 基本完成 | 模型、API、checkpoint、temp segment store、前端抽象层都已成型 |
| Audiobook 运行态闭环 | ⏳ 基本收口 | 运行态真相已收口，但仍需继续做真实迁移、恢复边界与联调验证 |
| 本地资产层演进（浏览器存储 → 更强持久化） | ⏳ 已开始 | OPFS 优先与用户目录最小闭环已落地，但更完整的长期持有策略、导出/备份与更多产品化引导仍待推进 |
| 前端刷新恢复闭环 | ⏳ 主链路已补齐 | 多任务恢复与 page/editor session 已落地，但细粒度 UI 态与自动合并仍未完成 |
| PWA / 离线 / 持久化增强 | ❌ 未开始 | 当前仍以普通 Web 站点存储能力为主 |
| 真实迁移与联调 | ⏳ 待继续推进 | 关键迁移已验证，但仍需继续覆盖更多环境与完整回归路径 |

## 11. 为什么这版方案是当前最优解

### 11.1 相比纯服务端存储

优势：

- 降低媒体长期存储成本
- 降低大文件长期治理成本
- 用户更容易形成“资产在自己手里”的心理预期

### 11.2 相比纯浏览器本地化

优势：

- 保留多设备同步与平台权威业务能力
- 保留积分、订单、审核、风控可信性
- 不破坏现有项目型产品架构

### 11.3 相比一步到位的大重构

优势：

- 改造边界清晰
- 风险可控
- 已有平台模块不必一起重写
- 可以先从媒体资产层拿到最大收益

## 12. 推荐推进顺序

### 阶段 1：当前已完成

- Asset Studio local-first 收录闭环
- 用户资产新模型
- 用户中心本地优先预览
- DreamWeaver 收录字段切换
- `localAssetVault` 已形成统一前端抽象，并已实现 `OPFS` 优先写入、`IndexedDB` 索引/兼容回退与 legacy blob 渐进迁移
- Audiobook 运行态已基本收口：
  - `chapter_audio_runs` 已建表并承接运行态真相
  - `checkpoint_json` 已形成版本化恢复文档
  - temp segment store 与 TTL janitor 已落地
  - `resume-generation` 已支持基于 temp cache 的 segment 缺口补齐
  - 章节成品音频已支持手动收录，播放器播放/试听也可触发本地缓存
- 前端恢复链路已从“轻量会话恢复”推进到：
  - 多任务 `localStorage` 会话恢复
  - `BrowserPlayer / 历史记录 / 剧本评审 / 阶段指标 / 删除确认 / CosyVoice 草稿态 / 从文本创建项目` 的 page session 恢复
  - 剧本编辑器 `sessionStorage` 草稿恢复
  - 跨标签页轻量同步、同章草稿冲突提醒与字段级差异预览
- `BrowserPlayer` 已接入章节音频本地优先回读、字幕缓存与播放器状态持久化

### 阶段 2：建议下一步

1. 继续在其它环境执行数据库迁移并完成联调，确保 `remove_legacy_chapter_audio_runtime_fields + align_chapter_audios_with_runtime_model` 全量落地
2. 在已有真实续跑入队能力、单 segment 级 checkpoint 写入与对象存储版 temp segment store 的基础上，继续补齐恢复校验边界，以及无直连删除凭证场景下的对象存储 prefix 枚举清理 / GC 策略
3. 继续补齐 Audiobook 页面刷新恢复链路中的边界场景、多标签页更细粒度冲突处理，以及字段级差异预览之后的半自动 merge 语义
4. 视验证结果决定是否把最终章节音频的自动收录策略从“播放/试听触发缓存”继续收口为更显式、更可观测的统一入口
5. 保持 `storage_mode` 不扩枚举，并继续围绕已落地的 `metadata_json.local_storage_*` 共享 schema 契约治理新增调用点与边界
   - 截至 `2026-04-24`，机器可读 schema、前后端生成定义、后端校验、共享文档、回归测试与 CI 漂移校验已经落地
  - 当前阶段优先把 `external_directory` 从“基础可配置”推进到“默认体验更完整”，在已补上顶部异常提示、基础备份建议、“导出备份说明 / 本地资产清单 / 重建清单”入口的前提下，对未来新增的显式收录入口持续做 `preferredStorageDriver` 准入审查，同时补齐 `source_payload_json` 的边界说明，并继续把“导出清单”推进到更顺手的回源补录执行流，把“先预览问题明细、再决定是否重建”作为默认产品体验，并逐步减少从预览结果回跳资产卡片区的额外定位成本；当前已补上从明细直接回到来源页的快捷入口，并进一步升级为可携带 `runId / assetId / audiobookProjectId + chapterId` 的精确上下文回跳
   - `source_payload_json` 当前仍宜按“共享 builder 约束”治理，而不宜直接升级宣称为与 `metadata_json.local_storage_*` 同级别的正式 schema 契约
   - 在读取侧，`source_payload_json?.x / metadata_json?.y` fallback 逻辑已开始抽到共享 selector，形成“场景化 builder + selector”基础；当前 `UserCenterPage` 已开始围绕 `frontend/src/contracts/userAssetSourcePayloadSelectors.ts` 收口
   - `UserCenterPage` 内的来源展示语义、受保护资源判定与跳转信息拼装已开始抽到共享 reader / view-model helper，读取侧已从“builder + selector”推进到“builder + selector + reader/view-model”
   - “本地 object URL / 受保护资源 object URL / 普通远端 URL”这条预览回退顺序也已开始收口到共享 preview resolver，进一步减少了页面内的预览决策逻辑
   - 受保护资源下载分发与 object URL 生命周期管理也已开始收口到共享 preview loading hook，页面内剩余的异步加载编排已明显缩小
   - 资产卡片中的预览渲染也已开始收口到共享 presenter / preview component，页面内剩余的展示分支逻辑进一步缩小
   - 资产卡片的来源 chips、说明文案、标签摘要与操作按钮拼装也已开始收口到共享 card-level presenter / component，页面内剩余的卡片展示逻辑进一步缩小
   - 资产列表级的筛选 option 生成、过滤 view-model 与卡片 / 批量 action command 也已继续收口到共享 helper，页面内剩余的列表编排逻辑进一步缩小
   - 列表选择态统计、可见结果选择同步、批量操作可用性摘要与 batch toolbar presenter / component 也已继续收口到共享层，页面内剩余的选择态编排与工具条模板逻辑进一步缩小
   - 过滤工具条的 select 字段文案、结果摘要与刷新动作，以及 loading / empty / grid 分支骨架，也已继续收口到共享 asset filter toolbar presenter / component 与 asset list section container，页面内剩余的资产列表骨架模板进一步缩小
   - 资产概览 metrics、列表告警 / 空态文案与 warning/empty state delivery，以及资产编辑器表单 view-model 与 dialog 模板，也已继续收口到共享 presenter / component，页面内剩余的资产中心壳层模板与编辑表单拼装逻辑进一步缩小
   - 单资产 / 批量资产 action feedback 与资产页 workspace section container 也已继续收口到共享层，页面内剩余的交互编排与壳层模板进一步缩小
   - 资产页 controller / hook、编辑器提交状态切换与 user-assets 提交副作用分发也已继续收口到共享层，页面内剩余的 API 编排、反馈派发与状态切换逻辑进一步缩小
  - 资产卡片 action controller、preview bridge 与 cards grid container 也已继续收口到共享层，页面内 `filteredUserAssets.map(...)` 卡片桥接段已被搬离
  - preview object URL hook 接线、cards grid props 组装与页面级导航 fallback 也已继续收口到共享 `asset workspace view-model / adapter hook`，`UserCenterPage` 中剩余的资产区块接线已继续缩小
  - asset workspace content container 与 `workspaceContentProps` bundling 也已继续收口到共享层，`UserCenterPage` 中剩余的资产 tab 壳层已继续缩到单个内容组件节点
  - 页面顶部刷新按钮中的 `loadUserCenterData(true) + loadUserAssets(true)` 双调度，以及 `pointsConnectedOverview?.user_asset_count ?? userAssets.length` 这类资产数量 fallback，也已继续收口到共享 `user-center asset summary / refresh helper`
  - `projects -> projectTitleMap` 构造与 `pointsOverview -> connectedUserAssetCount` 提取，也已继续收口到共享 `user-center asset workspace input helper`
  - `userAssetCount / refreshUserCenterAssets / workspaceContentProps` 这组三元输出，以及页面里两处“已接入概览”中的资产相关 rows，也已继续收口到共享 `user-center asset facade / overview helper`
  - 两处“已接入概览”的重复 Card 壳层与 item 渲染模板，也已继续收口到共享 `user-center asset connected overview card`
  - `assetConnectedOverviewItems` 这组页面侧概览数据拼装，以及 overview / points tab 中的资产概览接线，也已继续收口到共享 `user-center asset connected overview presentation / section`
  - `assetConnectedOverviewSectionProps` 这段页面级 `useMemo`，以及 `pointsConnectedOverview / projects.length / overviewMetrics / totalAudiobookCost / totalDreamweaverRuns` 这组概览来源输入，也已继续收口到共享 `user-center asset connected overview input helper / adapter`
  - `pointsOverview?.connected_overview` 中 `project_count / audiobook_project_count / audiobook_total_cost / dreamweaver_run_count` 这组来源读取与默认值 fallback，也已继续收口到共享 `user-center asset connected overview source helper`
  - `assetConnectedOverviewSource + assetConnectedOverviewSectionProps` 这两段页面级 `useMemo`，以及 `formatCurrency(assetConnectedOverviewSource.audiobookTotalCost)` 这层串联，也已继续收口到共享 `user-center asset connected overview view-model helper`，并已落为单一 `buildUserCenterAssetConnectedOverviewViewModel(...)` 组合 helper
  - `assetConnectedOverviewViewModel` 这段页面级 `useMemo` 与两处 section props 接线，也已继续收口到共享 `user-center asset connected overview adapter hook / facade bridge`，并已落为 `useUserCenterAssetConnectedOverviewBridge(...)`
  - 两处 `<UserCenterAssetConnectedOverviewSection {...assetConnectedOverviewBridge.sectionProps} />` 节点接线，也已继续收口到共享 `user-center asset connected overview section bridge component / slot helper`，并已落为 `UserCenterAssetConnectedOverviewSectionBridge.tsx` 与 `buildUserCenterAssetConnectedOverviewSectionSlot(...)`
  - overview / points 两处包含资产概览 slot 的 `Grid container` 行布局，与右侧 companion card 壳层，也已继续收口到共享 `user-center asset connected overview row layout / slot component`，并已落为 `UserCenterAssetConnectedOverviewRow.tsx` 与 `buildUserCenterAssetConnectedOverviewRowSlot(...)`，`UserCenterPage` 已切换为只消费这层共享 row slot
  - 右侧 `资产接入策略 / 当前积分规则` companion card body 内的 `Stack / Typography / Chip / summary grid` 结构，也已继续收口到共享 `user-center asset connected overview companion presenter / slot helper`，并已落为 `UserCenterAssetConnectedOverviewCompanion.tsx` 与 companion content builder，`UserCenterPage` 已切换为只消费这层共享 companion content
  - 页面内残留的 strategy 文案数组、`pointsRuleSummaryItems`、`sourceLabel / updatedAtLabel / updatedByLabel` 这类 companion 输入装配，也已继续收口到共享 `user-center asset connected overview companion input / view-model helper`，并已落为 `userCenterAssetConnectedOverviewCompanionInputHelper.ts` 与 `userCenterAssetConnectedOverviewCompanionViewModelHelper.ts`，`UserCenterPage` 已切换为只消费这层 companion view-model
  - 页面内残留的 `assetConnectedOverviewStrategyRowSlot / assetConnectedOverviewPointsRulesRowSlot` 组装、`companionTitle` 常量与 row slot builder 接线，也已继续收口到共享 `user-center asset connected overview rows helper / slots view-model helper`，并已落为 `userCenterAssetConnectedOverviewRowsHelper.ts` 与 `userCenterAssetConnectedOverviewRowsViewModelHelper.ts`，`UserCenterPage` 已切换为只消费这层共享 rows 结果
  - 页面内残留的 `assetConnectedOverviewBridge + assetConnectedOverviewCompanionViewModel + assetConnectedOverviewRows` 这组串联，也已继续收口到共享 `user-center asset connected overview rows adapter hook / facade helper`，并已落为 `useUserCenterAssetConnectedOverviewRows.ts`，`UserCenterPage` 已切换为只消费这层单一 rows hook
  - 页面内残留的 `projects.length / assetFacade.userAssetCount / getPointsRuleSourceLabel / formatCurrency / formatAccountMetric / formatDateTime` 这组 rows hook 输入装配，也已继续收口到共享 `user-center asset connected overview rows input helper / page-facing facade hook options builder`，并已落为 `userCenterAssetConnectedOverviewRowsInputHelper.ts` 与 `buildUserCenterAssetConnectedOverviewRowsOptionsFromInput(...)`，`UserCenterPage` 已切换为只消费这层共享 rows options builder
  - `useUserCenterAssetConnectedOverviewRows(buildUserCenterAssetConnectedOverviewRowsOptionsFromInput(...))` 这段页面级串联，也已继续收口到共享 `user-center asset connected overview rows page-facing facade hook`，并已落为 `useUserCenterAssetConnectedOverviewRowsFromInput.ts`，`UserCenterPage` 已切换为只消费这层 page-facing rows hook
  - overview 页签中围绕 connected overview 的 `pointsOverview / overviewMetrics / pricingPolicySummaryItems / pointsAccountStatusMeta` 这组相邻页面级派生装配，也已继续收口到共享 `user-center overview tab facade / metrics helper`，并已落为 `userCenterOverviewTabMetricsHelper.ts`，`UserCenterPage` 已切换为只消费这层共享 overview-tab metrics helper
  - overview 页签中围绕 `pricing policy / points status` 的 `pointsAccountStatus / connectedLedgerSourceCount / pendingLedgerSourceCount / pointsAccountBalance / pointsAccountFrozen / pointsAccountExpiringSoon / pricingPolicy` 这组相邻输入装配，也已继续收口到共享 `user-center overview tab metrics input helper / page-facing metrics hook`，并已落为 `userCenterOverviewTabMetricsInputHelper.ts` 与 `useUserCenterOverviewTabMetrics.ts`，`UserCenterPage` 已切换为只消费这层共享 overview-tab metrics hook
  - 下一步应继续把 overview / points 区块中紧邻这层 facade 的 `MetricCard` 入参与 `pricingPolicyPresentation` 展示输入，收口到共享 `user-center overview tab metric cards / pricing policy presentation helper`，优先从 points account 概览四个指标卡输入开始，进一步减少 `UserCenterPage` overview 区块中的局部展示装配

### 阶段 3：中期增强

1. 把现有 `File System Access API` 用户目录模式从基础版推进到更完整体验，在已落地轻量目录健康检查与“备份说明 / 本地资产清单 / 重建清单”导出能力的基础上，继续补齐更顺手的缺失副本回源补录流程，并维持“先预览问题明细、再决定是否执行重建”的交互闭环；当前已支持从预览明细直接触发单项补录与来源页跳转，且来源页跳转已能带上 `runId / assetId / audiobookProjectId + chapterId` 做精确定位，后续仍可继续补批量决策效率
2. 继续扩大显式收录入口覆盖范围，并保持 `preferredStorageDriver` 准入审查
3. 继续增强本地资产导出 / 备份 / 重建链路的一致性与可观测性
4. 引入 PWA 与离线增强能力

### 阶段 4：长期优化

1. 将临时资产层从“下载落临时目录”演进为真正的流式代理
2. 完善媒体清理策略与 TTL
3. 为 local-first 资产补充跨设备可用性的产品策略
4. 将更多长期媒体产物纳入统一本地资产生命周期管理

## 13. 一句话结论

本项目当前最优方案不是“全量改成纯云端代理模式”，而是：

**让核心业务继续服务端权威，让媒体资产转向 local-first，并把浏览器本地资产层从“IndexedDB 存 Blob”演进到“OPFS + IndexedDB 索引”，再用用户可选目录模式承接真正长期本地持有。**

修正文档后需要明确两点：

- 这套方案的**方向**仍然正确
- 但以当前实现为准，只能保证“浏览器站点存储仍可用时，核心业务数据与已缓存本地资产尽量不丢”，还不能保证“清站点数据后本地文件仍稳定保留”，也还不能保证“跨设备资产天然同步”与“任务恢复 / 播放恢复 / 跨标签页协作完全无感”

也就是说，目标架构没有问题，当前优先要补的是：

- **更强的本地资产持久层**（从站点存储进一步走向用户可控长期目录）
- **Audiobook 恢复边界与对象存储 GC 策略**
- **前端更细粒度的刷新恢复与跨标签页半自动 merge 语义**
