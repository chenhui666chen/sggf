# 本地优先资产架构方案

日期：`2026-04-19`

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

本项目的最优方案不是“完全改成纯云端代理模式”，而是：

**核心业务服务端权威 + 媒体资产 local-first + 后端代理与临时资产层**

具体原则如下：

1. 用户、项目、章节、积分、订单、审核、RAG、Agent 编排保留服务端权威。
2. 图片、视频、音频这类大文件结果不再作为长期服务端资产保存。
3. 后端仍然负责：
   - API Key 管理
   - 第三方模型调用
   - 鉴权、限流、风控
   - 临时结果物化与对外受控暴露
4. 前端负责：
   - 将可收录资产下载到本地 IndexedDB
   - 优先展示本地副本
   - 仅将轻量元数据登记到服务端

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
- 本地资产库（IndexedDB）
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
│  IndexedDB / Local Asset Vault                      │
│  - 已收录图片                                       │
│  - 已收录视频                                       │
│  - 已收录音频                                       │
│  - 本地 object URL 预览                             │
│                                                     │
│  前端应用状态                                       │
│  - 编辑器 / 用户中心 / Asset Studio                 │
│  - 本地优先读取资产                                 │
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
- **媒体大文件**：本地优先
- **临时生成结果**：服务端短期存在，作为受控中转层
- **长期可见资产目录**：服务端只保留元数据，不保留大文件本体

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
6. 前端将 blob 存入 IndexedDB。
7. 前端调用 `/api/v1/user-assets` 仅登记元数据。

### 8.2 用户中心预览链路

1. 用户中心拉取 `user_asset_records`。
2. 前端尝试按 `asset_uuid` 从本地资产库读取 blob。
3. 若本地存在，则生成 object URL 预览。
4. 若本地不存在，则退回：
   - 受保护 DreamWeaver 文件接口
   - `preview_uri`
   - `source_uri`
   - `download_uri`

这保证了：

- 有本地副本时，优先本地展示
- 没有本地副本时，仍能从服务端链路兜底

## 9. 当前已落地内容

本轮已经完成的代码级改造如下：

### 9.1 后端

- `user_asset_records` 模型升级为新资产字段结构
- `user-assets` schema 与 API 升级为新 contract
- 新增开发期迁移：
  - 直接重建 `user_asset_records` 表
  - 不兼容旧结构
- `Asset Studio` 返回结构升级为 `assets / primary_asset`
- `Asset Studio` 对第三方远端结果先做内部物化，再对前端暴露平台内地址

### 9.2 前端

- API 类型定义切到新 contract
- 新增 `localAssetVault`，基于 IndexedDB 保存本地资产 blob
- `Asset Studio` 收录流程改为：
  - 下载 blob
  - 写本地资产库
  - 再写服务端资产元数据
- 用户中心预览改为：
  - 本地副本优先
  - 云端受控地址兜底
- DreamWeaver 资产收录 payload 已同步新字段

## 10. 当前未落地内容

以下内容尚未纳入本轮：

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

当前代码已经有一套“断点续传/缓存系统”的雏形，但还没有形成真正闭环：

- 前端已有 `localStorage` 会话恢复，只能恢复 `projectId / audiobookProjectId / taskId / activeStep / generating / ttsModel`
- 后端已有 `AudiobookTask` 持久化任务状态
- 后端已有 `ChapterAudio.generation_progress_json`
- 后端已有 `/checkpoint` 与 `/resume-generation` 接口

但目前仍存在以下问题：

1. `ChapterAudio.task_id` 只有一个值，不适合表达多次生成尝试。
2. `generation_progress_json` 放在 `ChapterAudio` 上，语义过重，容易和最终章节记录耦合。
3. `resume_from_checkpoint` 只存在于 schema，尚未真正接入执行链路。
4. TTS `enable_cache` 开关存在，但当前缓存实现实际上被禁用。
5. 前端虽然声明了 `checkpointInfo` 状态，但尚未形成完整的“查询断点 -> 用户确认 -> 恢复任务”交互。

也就是说：

- **当前已有字段和接口可以作为过渡基础**
- **但当前结构并不是最终最优结构**

#### 10.1.3 推荐数据库结构（开发阶段可直接重构）

开发阶段没有历史用户数据，建议不再把运行态字段继续堆在 `chapter_audios` 上，而是直接拆分职责：

1. **`chapter_audios` 仅保留章节最终结果与章节级内容**
   - 最终章节音频元信息
   - 剧本 `script_json`
   - 剧本评审 `script_review_json`
   - 片段评审 `segment_reviews_json`
   - 最终音频评审 `final_audio_review_json`
   - 最终时长、大小、成本、字幕等
2. **新增 `chapter_audio_runs`（推荐）**
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

- `ChapterAudio.task_id` 直接移除
- `ChapterAudio.generation_progress_json` 直接移除
- 运行态全部迁移到 `chapter_audio_runs`

这是因为：

- `ChapterAudio` 是“章节结果”
- `chapter_audio_runs` 是“某一轮生成过程”

两者职责不同，混在一个表里后续会越来越难维护。

#### 10.1.4 checkpoint_json 推荐结构

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
  "tts_model": "qwen3-tts-flash",
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

#### 10.1.5 本地数据与服务端数据的边界

Audiobook 相关数据推荐按下表处理：

| 数据类型 | 存储位置 | 说明 |
| --- | --- | --- |
| 页面恢复态 | 浏览器 `localStorage` / IndexedDB | 仅用于 UI 恢复 |
| 任务状态 | 服务端数据库 | 以 `AudiobookTask` 或 `chapter_audio_runs` 为权威 |
| 章节剧本/评审 | 服务端数据库 | 业务真相，不下放浏览器 |
| 断点元数据 | 服务端数据库 | 必须跨设备、跨刷新、跨 worker 恢复 |
| 中间片段音频 | 服务端临时对象层 | 仅用于恢复，不属于正式资产 |
| 最终章节音频 | 用户本地资产库 + 服务端短时兜底 | 进入 local-first 资产链路 |

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

推荐交互如下：

1. 页面恢复时，根据本地保存的 `taskId / audiobookProjectId` 拉取服务端任务状态
2. 若发现存在失败但可恢复的 `chapter_audio_run`，显示“继续生成”提示
3. 用户确认后调用恢复接口
4. 恢复任务启动后，继续沿用统一的任务状态轮询
5. 任务完成后，前端再按 local-first 资产链路收录最终章节音频

也就是说：

- **前端负责发现与触发恢复**
- **服务端负责判断是否真的能恢复**

#### 10.1.9 与 local-first 资产体系的衔接

Audiobook 真正接入本地优先资产抽象时，建议只把 **最终章节音频** 纳入资产收录。

推荐链路：

1. 后端完成章节音频生成
2. 前端通过受控下载接口获取最终音频 blob
3. 前端写入本地资产库（IndexedDB，后续可演进到 OPFS）
4. 前端调用 `/api/v1/user-assets` 登记轻量元数据
5. 用户中心优先显示本地副本

而以下内容 **不要进入用户资产系统**：

- 中间 segment 片段
- 恢复用 checkpoint
- 临时调试音频
- 运行态任务 detail

#### 10.1.10 推荐落地顺序

Audiobook 建议按以下顺序改造，而不是一次性大拆：

1. 先明确运行态与最终资产的边界
   - `ChapterAudio` 只保最终结果
   - 新增 `chapter_audio_runs`
2. 再补 checkpoint 实际写入
   - 每完成一批 segment 就写 checkpoint
3. 再补 resume 真正续跑
   - 恢复时跳过已完成片段，只补剩余片段
4. 最后接前端恢复交互与 local-first 收录
   - 保证用户完成后能把最终音频拿回本地

如果只做一件事，优先级最高的是：

**先把“断点真相”从 `ChapterAudio` 杂糅状态中拆出来，建立独立的运行态模型。**

### 10.2 PWA / OPFS

当前本地资产层先基于 IndexedDB。

尚未做：

- PWA 安装态
- Service Worker
- OPFS 文件级存储
- 离线包策略

### 10.3 真正的纯流式代理

本轮 `Asset Studio` 对第三方远端 URL 的处理仍然是：

- 先由后端下载到临时内部资产目录
- 再返回内部链接

这比“直接暴露第三方 URL”更安全、更稳，也更适合作为第一阶段。

但它还不是最终形态的“全程内存流式 pipe”。

### 10.4 真实环境迁移执行与联调

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

### 阶段 2：建议下一步

1. 执行数据库迁移并完成联调
2. 为 Asset Studio 增加更明确的资产生命周期管理
3. 将 Audiobook 成品音频接入同一套资产抽象

### 阶段 3：中期增强

1. 引入 PWA
2. 评估 IndexedDB -> OPFS 的演进
3. 增加本地资产导出 / 备份提示
4. 增加本地资产缺失检测与重建策略

### 阶段 4：长期优化

1. 将临时资产层从“下载落临时目录”演进为真正的流式代理
2. 完善媒体清理策略与 TTL
3. 将更多媒体产物纳入统一资产生命周期管理

## 13. 一句话结论

本项目当前最优方案不是“全量改成纯云端代理模式”，而是：

**让核心业务继续服务端权威，让媒体资产转向 local-first，并由后端承担受控代理与临时资产层。**

这套方案既符合当前平台型产品的实际结构，也能以最小风险逐步逼近“用户持有数据、平台掌控密钥、整体成本更低”的目标。
