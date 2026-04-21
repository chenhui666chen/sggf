# 本地优先资产架构方案

日期：`2026-04-19`
更新：`2026-04-21`

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
   - 当前兼容层：`IndexedDB blob`
   - 下一阶段默认层：`OPFS + IndexedDB 索引`
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

## 3. 架构定位

本方案本质上属于：

- `BFF (Backend For Frontend)`
- `受控代理网关`
- `本地优先资产存储`
- `服务端权威业务模型`

### 3.1 浏览器侧职责

- 展示和交互
- 本地资产库（当前 `IndexedDB blob`，目标 `OPFS + IndexedDB 索引`）
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

- 当前不建议为了区分 `IndexedDB / OPFS / File System Access API` 而扩展 `storage_mode` 枚举。
- 本地驱动细节建议先写入 `metadata_json`，例如：
  - `local_storage_driver`: `legacy_indexeddb` | `opfs` | `external_directory`
  - `local_storage_path`
  - `external_relative_path`
  - `local_persist_level`: `best_effort` | `persistent_requested` | `user_directory`

### 6.3 当前采用策略

本轮优先采用：

- Asset Studio 收录结果：`local_mirror`
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
7. 当前实现仍为 `IndexedDB blob`，目标演进为 `OPFS + IndexedDB 索引`。
8. 前端调用 `/api/v1/user-assets` 仅登记元数据。

### 8.2 用户中心预览链路

1. 用户中心拉取 `user_asset_records`。
2. 前端尝试按 `asset_uuid` 通过 `localAssetVault` 读取本地资产。
3. 目标读取顺序应为：`OPFS -> 用户目录 -> legacy IndexedDB blob`。
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

以下为**截至 `2026-04-20`** 已与代码对齐的实际落地状态。

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
- 但 `/resume-generation` 目前还不是“真正恢复执行”，当前更接近“返回 checkpoint 摘要”

### 9.2 前端

- API 类型定义已切到新 contract
- 已新增 `localAssetVault`，当前基于 IndexedDB 保存本地资产 blob，并已经形成稳定的 `save / get` 抽象
- `Asset Studio` 收录流程已改为：
  - 下载 blob
  - 写本地资产库
  - 再写服务端资产元数据
- 用户中心预览已改为：
  - 本地副本优先
  - 云端受控地址兜底
- DreamWeaver 资产收录 payload 已同步新字段
- Audiobook 页面已支持**手动收录章节成品音频**：
  - 下载受控音频 blob
  - 写入本地资产库
  - 再登记 `user_asset_records`
- Audiobook 页面已接入**有限的** `localStorage` 会话恢复：
  - `projectId`
  - `audiobookProjectId`
  - `taskId`
  - `activeStep`
  - `generating`
  - `ttsModel`
- `BrowserPlayer` 已接入：
  - 章节音频本地优先回读
  - 首次远端拉取后的本地缓存
  - 字幕下载时的本地缓存
  - `currentChapterIndex / currentTime / volume / subtitleFormat / showSubtitles / wasPlaying` 的 `localStorage` 持久化
- Audiobook 页面行内播放也已支持优先回读本地音频
- 但当前本地资产层仍是 `IndexedDB blob`，尚未升级到 `OPFS + IndexedDB 索引`
- 也还没有用户可选的真实本地资料库目录

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

- 前端已有 `localStorage` 会话恢复，但只覆盖 `projectId / audiobookProjectId / taskId / activeStep / generating / ttsModel`
- 后端已有 `AudiobookTask` 持久化任务状态
- 后端保留了 `ChapterAudio.generation_progress_json`
- 后端已新增 `chapter_audio_runs`
- 后端已有 `/checkpoint` 与 `/resume-generation` 接口
- 用户中心已经能优先读取已收录的本地资产副本

但目前仍存在以下问题：

1. `chapter_audio_runs` 虽然已经建模，但恢复逻辑仍同时依赖 `ChapterAudio.generation_progress_json`，运行态真相尚未完全收口。
2. `resume-generation` 当前只返回 checkpoint 摘要，并不会真正启动续跑任务。
3. `checkpoint_json` 已开始写入，但当前主要是 `engine_task_id`、`output_path`、`tracker_detail` 等轻量信息，尚未达到 segment 级可恢复数据标准。
4. `can_resume` 当前主要依赖 `completed_segment_indices / cached_audio_paths`，且把 `failed` run 排除在外，也没有按 `script_hash / voice_config_hash / audio_fx_hash / expires_at / 临时对象是否存在` 做完整校验。
5. `ChapterAudio.task_id` 与 `ChapterAudio.generation_progress_json` 仍在使用，容易和最终章节结果耦合。
6. 前端页面级会话恢复仅覆盖极少数字段，不包含章节勾选、弹窗状态、未保存编辑态等大部分 UI 临时态；播放器进度与音量当前只在 `BrowserPlayer` 内部单独持久化。
7. 当前 `AudiobookPage` 的恢复顺序存在竞争窗口：先恢复 `taskId / audiobookProjectId`，后续 `handleSelectProject` 又会清空它们，因此刷新恢复现在并不完全可靠。
8. 最终章节音频目前除了用户手动点击“收录”外，也可能在播放器播放或页面内试听时被写入本地缓存；但这仍不是统一的“自动收录”策略，未被缓存过的音频刷新后仍主要依赖服务端下载链路。
9. `BrowserPlayer` 已形成单独的 local-first 播放闭环，并持久化了 `currentChapterIndex / currentTime / volume / subtitleFormat / showSubtitles / wasPlaying`；但这套恢复仍依赖浏览器本地存储，且自动续播仍受浏览器自动播放策略影响。
10. TTS 的 `enable_cache` 不能等价视为“断点续传已经完成”。

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

- 短期：以 `chapter_audio_runs` 作为恢复接口的首要来源，`generation_progress_json` 仅作 legacy fallback
- 中期：移除 `ChapterAudio.task_id`
- 中期：移除 `ChapterAudio.generation_progress_json`
- 最终：运行态全部迁移到 `chapter_audio_runs`

这是因为：

- `ChapterAudio` 是“章节结果”
- `chapter_audio_runs` 是“某一轮生成过程”

两者职责不同，混在一个表里后续会越来越难维护。

#### 10.1.4 checkpoint_json 推荐结构

当前现状校准：

- `checkpoint_json` 已有写入
- 但当前内容主要是 `engine_task_id`、`output_path`、`tracker_detail`
- 这足以做状态挂钩，不足以支撑真正的断点续跑

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

数据库只保存相对 key，例如：

- `tmp/audiobook_runs/{run_id}/segment_000.mp3`

后续如果切换为对象存储，也只需要替换底层实现，不需要改业务模型。

推荐清理策略：

- `running`：保留
- `failed` / `paused`：保留 24-72 小时
- `completed`：在最终章节音频合成并确认落地后尽快清理
- `expired`：由后台清理任务定时删除

#### 10.1.7 恢复判定规则

当前代码还未实现下面这套完整校验，以下为修正文档后的**目标规则**：

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

- 现在只有有限的会话恢复与任务轮询
- 还没有完整的“发现可恢复 run -> 用户确认 -> 真正续跑 -> 回到统一任务状态流”的交互闭环

推荐交互如下：

1. 页面恢复时，根据本地保存的 `taskId / audiobookProjectId` 拉取服务端任务状态
2. 加载项目与章节数据时，不得覆盖已恢复的 `taskId / audiobookProjectId`
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
   - 每完成一批 segment 就写 checkpoint
3. 再补 resume 真正续跑
   - 恢复时跳过已完成片段，只补剩余片段
4. 再修前端刷新恢复链路
   - 避免 `handleSelectProject` 覆盖已恢复的 `taskId / audiobookProjectId`
   - 明确哪些 UI 状态需要持久化，哪些不需要
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
  - `activeStep`
  - `generating`
  - `ttsModel`
- 但这套恢复当前并不完全可靠，因为存在恢复顺序上的竞争窗口
- `BrowserPlayer` 当前已能恢复：
  - 当前章节
  - 播放进度
  - 音量
  - 字幕格式 / 显示状态
  - 上次是否处于播放态
- 但“自动续播”仍可能受浏览器自动播放策略影响，不能承诺绝对无感恢复
- 已进入 `localAssetVault` 的章节成品音频，在同一浏览器、同一站点存储未被清理的前提下，刷新后通常不会丢
- 但当前底层仍是 `IndexedDB blob`，如果浏览器清理站点数据、配额被回收、切换浏览器或重装环境，仍可能丢失本地副本
- 未手动收录、也未被播放器或页面缓存过的章节成品音频，刷新后仍依赖服务端下载链路
- 以下状态当前刷新后会丢，或至少不会被稳定恢复：
  - 章节勾选状态
  - 弹窗开关
  - 未保存的编辑态
  - 页面级任务恢复过程中的临时 UI 上下文

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

本轮完成的是：

- 代码
- schema
- contract
- 迁移文件

还没有在本地开发库上执行真实迁移，也还没有跑完整的手工联调回归。

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
- `localAssetVault` 已形成统一前端抽象，但当前底层仍是 `IndexedDB blob`
- Audiobook 运行态建模起步：
  - `chapter_audio_runs` 已建表
  - 章节成品音频已支持手动收录
  - 前端已有轻量会话恢复
- `BrowserPlayer` 已接入章节音频本地优先回读、字幕缓存与播放器状态持久化

### 阶段 2：建议下一步

1. 先把 `localAssetVault` 重构为 `OPFS + IndexedDB 索引 + legacy IndexedDB blob 兼容`
2. 升级 `DB_VERSION` 并做读取时的渐进迁移，而不是一次性全量搬迁
3. 接入 `navigator.storage.persist()`，补齐空间不足与写入失败提示
4. 保持 `storage_mode` 不扩枚举，把 `local_storage_driver / local_storage_path / local_persist_level` 先落到 `metadata_json`
5. 执行数据库迁移并完成联调
6. 让 `chapter_audio_runs + checkpoint_json` 成为恢复能力的主来源，`generation_progress_json` 仅保留过渡兼容
7. 打通 `resume-generation` 的真实续跑能力与恢复校验规则
8. 修复 Audiobook 页面刷新恢复链路中的状态清空竞争问题

### 阶段 3：中期增强

1. 为用户中心 / Audiobook / 资产工作台增加 `File System Access API` 资料库目录模式
2. 增加本地资产导出 / 备份提示
3. 增加本地资产缺失检测与重建策略
4. 引入 PWA 与离线增强能力

### 阶段 4：长期优化

1. 将临时资产层从“下载落临时目录”演进为真正的流式代理
2. 完善媒体清理策略与 TTL
3. 将更多长期媒体产物纳入统一本地资产生命周期管理

## 13. 一句话结论

本项目当前最优方案不是“全量改成纯云端代理模式”，而是：

**让核心业务继续服务端权威，让媒体资产转向 local-first，并把浏览器本地资产层从“IndexedDB 存 Blob”演进到“OPFS + IndexedDB 索引”，再用用户可选目录模式承接真正长期本地持有。**

修正文档后需要明确两点：

- 这套方案的**方向**仍然正确
- 但以当前实现为准，只能保证“同一站点存储未被清理时，核心业务数据与已缓存本地资产尽量不丢”，还不能保证“清站点数据后本地文件仍稳定保留”，也还不能保证“任务恢复与播放恢复完全无感”

也就是说，目标架构没有问题，当前要补的是 **Audiobook 运行态闭环** 与 **前端刷新恢复闭环**。
