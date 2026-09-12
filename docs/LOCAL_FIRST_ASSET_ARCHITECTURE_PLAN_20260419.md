# 本地优先资产架构说明

日期：`2026-04-25`
状态：当前实现说明（不是待办清单）
字段契约：[User Asset Local Storage Metadata Contract](contracts/USER_ASSET_LOCAL_STORAGE_METADATA_CONTRACT.md)

本文说明媒体资产为什么采用混合架构、当前代码怎么走，以及哪些东西**故意不**放进用户资产合同。Audiobook 运行时 checkpoint、音频库 `local_cache`、用户中心面板按钮细节不属于合同版本。

## 1. 目标

服务端长期目录不堆用户可见大文件。浏览器刷新后，已收录资产尽量仍能从本地打开。

不是全盘本地、也不是全盘云端。边界：

- 账号、项目、章节、积分、RAG、Agent 记忆：服务端权威
- 图片 / 视频 / 音频成品：local-first，服务端主要存元数据，必要时做临时中转或受控下载
- API Key、模型调用、鉴权、临时中转：服务端

## 2. 混合模型

`user_asset_records.storage_mode` 表达生命周期：

| 值 | 含义 | 运行时 |
| --- | --- | --- |
| `temp_cloud` | 平台临时中转，适合刚生成、尚未收录 | 已用。Asset Studio 生成默认如此 |
| `durable_cloud` | 权威在平台受控路径 | 已用。DreamWeaver 资料库 / 合成成片当前如此 |
| `local_mirror` | 用户可见副本在本地，服务端保留元数据与可能的回源 URI | 已用。Asset Studio 收录、Audiobook 章节成品手动收录 |
| `local_only` | 仅本地，服务端只留元数据 | reserved，后端拒写 |

本地驱动细节只进 `metadata_json`，见合同文档。不要把 `opfs` 做成新的 `storage_mode`。

另一套同名字段：`audio_library_assets.storage_mode`（默认 `local_cache`，云端 `durable_cloud`）属于有声书音频库，**不是** `user_asset_records` 生命周期。两边不要混读。

## 3. 本地存储层

统一入口：`frontend/src/utils/localAssetVault.ts`。

写入优先级：

1. 显式收录且用户已授权目录：`external_directory`（File System Access API），`persist_level = user_directory`
2. 否则 OPFS，并申请 `navigator.storage.persist()`
3. OPFS 失败：legacy IndexedDB blob

显式首选驱动类型收窄为 `external_directory | opfs`。`legacy_indexeddb` 只作运行时回退，业务页不能点名选择。

读取现状（代码事实）：按记录上的当前 driver 读；`opfs` miss 后才看 legacy blob。`external_directory` 读失败**不会**自动改读 OPFS，而是回落到远端 URI。用户中心恢复收录会遵守登记驱动；目录不可用时阻塞，不静默换驱动。

启动后空闲时：legacy blob → OPFS 批量迁移（`frontend/src/main.tsx`）。

清理本地副本：只删当前浏览器里的镜像，不改服务端 `storage_mode`。

## 4. 主链路

Asset Studio / 同类生成：

1. 后端调模型，必要时把远程结果落到内部临时目录
2. 返回 `assets / primary_asset`（含 `asset_uuid`、URI、`storage_mode=temp_cloud`）
3. 用户收录时前端下载 blob，写入 vault
4. `POST /api/v1/user-assets` 只登记元数据，`storage_mode=local_mirror`，并把合同字段写入 `metadata_json`

预览：

1. 用 `asset_uuid` 读 vault
2. 有本地 blob 就本地展示
3. 没有则回源 DreamWeaver 文件接口 / `preview_uri` / `source_uri` / `download_uri`

## 5. 模块现状

| 模块 | 当前策略 | 说明 |
| --- | --- | --- |
| Asset Studio 生成 | `temp_cloud` | 内部中转，不把平台临时地址当长期资产 |
| Asset Studio 收录 | `local_mirror` | 显式收录优先用户目录 |
| Audiobook 章节成品手动收录 | `local_mirror` | 走同一 vault |
| Audiobook 播放器自动缓存 | 浏览器管理存储 | 不登记为用户目录权威副本 |
| DreamWeaver Library / 合成成片 | `durable_cloud` | 受控下载；尚未切成本地镜像 |
| 有声书音频库 | `local_cache` / `durable_cloud` | 独立模型，勿与用户资产枚举对齐硬改 |

用户中心已有：目录授权/恢复、健康提示、清理/重新收录（含批量）、扫描预览与重建清单。这些是产品层，不 bump 字段合同版本。

## 6. 已知缺口

- vault 读取未实现“external miss → OPFS → legacy blob”的完整回退
- `local_only` 只有拒写，没有产品状态机
- DreamWeaver 成片仍走 `durable_cloud`
- 合同文档曾标到 `2026-04-25.7`，schema 实际是 `2026-04-24.6`；现已改回以 schema 为准

## 7. 不要做的

- 不要为本地驱动扩 `storage_mode`
- 不要把小说正文、积分、Agent 状态放进 vault
- 不要把 `chapter_audio_runs.checkpoint_json` 写进用户资产合同
- 不要在清理本地副本时改服务端生命周期字段